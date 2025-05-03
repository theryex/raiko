import discord
from discord import app_commands
from discord.ext import commands
import lavalink
from lavalink import DefaultPlayer, AudioTrack, LoadResult, LoadType
from lavalink import TrackStartEvent, QueueEndEvent, TrackEndEvent, TrackExceptionEvent, TrackStuckEvent
from lavalink import PlayerErrorEvent, NodeErrorEvent
from lavalink import LowPass  # Keep filter import

import logging
import re
import math # For formatting time
import asyncio
from typing import Optional, cast

# Basic URL pattern (improved slightly)
URL_REGEX = re.compile(r'https?://(?:www\.)?.+')
SOUNDCLOUD_REGEX = re.compile(r'https?://(?:www\.)?soundcloud\.com/')
SPOTIFY_REGEX = re.compile(r'https?://(?:open|play)\.spotify\.com/')

logger = logging.getLogger(__name__) # Use logger


# --- Helper Functions ---
def format_duration(milliseconds: int) -> str:
    """Formats milliseconds into HH:MM:SS or MM:SS."""
    if milliseconds is None:
        return "N/A"
    seconds = math.floor(milliseconds / 1000)
    minutes = math.floor(seconds / 60)
    hours = math.floor(minutes / 60)

    if hours > 0:
        return f"{hours:02d}:{minutes % 60:02d}:{seconds % 60:02d}"
    else:
        return f"{minutes:02d}:{seconds % 60:02d}"

# --- Custom Voice Client for Lavalink Integration ---
# This class IS required when using the standalone discord-lavalink library
class LavalinkVoiceClient(discord.VoiceProtocol):
    """
    This is the preferred way to handle external voice sending
    This client handles the discord voice packets needed by Lavalink.
    Based on the official discord.py example.
    """
    def __init__(self, client: discord.Client, channel: discord.abc.Connectable):
        self.client = client
        self.channel = channel
        # Ensure the Lavalink client instance exists
        if not hasattr(self.client, 'lavalink'):
            # Attempt to initialize here as a fallback, though it should be done in bot.py
            logger.warning("Lavalink client not found on bot, attempting fallback initialization in VoiceClient.")
            self.client.lavalink = lavalink.Client(str(client.user.id))
            # Note: Node connection should ideally happen in bot.py on_ready

        self.lavalink: lavalink.Client = self.client.lavalink


    async def on_voice_server_update(self, data):
        """Handles the VOICE_SERVER_UPDATE event from Discord."""
        lavalink_data = {
            't': 'VOICE_SERVER_UPDATE',
            'd': data
        }
        # logger.debug(f"VOICE_SERVER_UPDATE: {data}")
        await self.lavalink.voice_update_handler(lavalink_data)

    async def on_voice_state_update(self, data):
        """Handles the VOICE_STATE_UPDATE event from Discord."""
        lavalink_data = {
            't': 'VOICE_STATE_UPDATE',
            'd': data
        }
        # logger.debug(f"VOICE_STATE_UPDATE: {data}")
        # Cache the channel_id? Might not be necessary as Lavalink handles internal state.
        await self.lavalink.voice_update_handler(lavalink_data)
        # Handle disconnects initiated from Discord (e.g., user moves bot)
        if data['channel_id'] is None and int(data['user_id']) == self.client.user.id:
            guild_id = int(data['guild_id'])
            await self._destroy_player(guild_id)


    async def connect(self, *, timeout: float, reconnect: bool, self_deaf: bool = False, self_mute: bool = False) -> None:
        """ Connects to the voice channel and creates a Lavalink player. """
        logger.info(f"Connecting to voice channel: {self.channel.name} (ID: {self.channel.id})")
        # Ensure a player instance exists for this guild in the Lavalink client
        self.lavalink.player_manager.create(guild_id=self.channel.guild.id)
        # Use discord.py's state change mechanism to connect
        await self.channel.guild.change_voice_state(channel=self.channel, self_mute=self_mute, self_deaf=self_deaf)
        logger.info(f"Successfully requested connection to {self.channel.name}")


    async def disconnect(self, *, force: bool = False) -> None:
        """ Disconnects from the voice channel and destroys the Lavalink player. """
        logger.info(f"Disconnecting from voice channel: {self.channel.name if self.channel else 'Unknown'} (Guild ID: {self.channel.guild.id}) Force: {force}")

        player = self.lavalink.player_manager.get(self.channel.guild.id)

        # Normally, don't force disconnect player if it's still playing
        # Check if the bot is actually connected using discord.py's state
        voice_client = self.channel.guild.voice_client
        if not force and player and player.is_connected and voice_client:
            logger.warning("Disconnect called but player is connected and force=False. Not disconnecting.")
            return

        # Tell Discord to leave the channel.
        # This will trigger a VOICE_STATE_UPDATE event which Lavalink listens for.
        if voice_client: # Check if discord.py thinks we are connected
            await self.channel.guild.change_voice_state(channel=None)
            logger.info(f"Requested voice state change to disconnect from Guild {self.channel.guild.id}")

        # Clean up the Lavalink player instance.
        if player:
             await self._destroy_player(self.channel.guild.id)

        self.cleanup() # discord.py internal cleanup


    async def _destroy_player(self, guild_id: int):
        """ Safely destroys the player and cleans up resources. """
        logger.info(f"Attempting to destroy player for Guild ID: {guild_id}")
        try:
            # Check again if player exists before destroying
            if self.lavalink.player_manager.get(guild_id):
                await self.lavalink.player_manager.destroy(guild_id)
                logger.info(f"Lavalink player destroyed for Guild ID: {guild_id}")
            else:
                logger.info(f"Lavalink player already destroyed or not found for Guild ID: {guild_id}")
        except Exception as e:
            logger.error(f"Error destroying Lavalink player for Guild ID {guild_id}: {e}", exc_info=True)

# --- Music Cog ---
class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Ensure Lavalink client is ready (it should be from bot.py)
        if not hasattr(bot, 'lavalink'):
            logger.critical("Lavalink client not found on bot instance in Music Cog init!")
            # This cog might not function correctly.
            return

        self.lavalink: lavalink.Client = self.bot.lavalink
        # Add event listeners for Lavalink events
        # Note: Using bot.add_listener in cog's __init__ might register multiple times on reload
        # It's generally better to use the @lavalink.listener decorator if the cog structure allows it,
        # or manage listeners carefully during cog load/unload.
        # For simplicity here, we assume it's okay or handled by cog reload mechanics.
        # Alternatively, define listeners directly in the cog with the decorator.

    # Use decorators for event listeners - simpler and cleaner
    @lavalink.listener(TrackStartEvent)
    async def on_track_start(self, event: TrackStartEvent):
        player = event.player
        guild_id = player.guild_id
        guild = self.bot.get_guild(guild_id)
        logger.info(f"Track started on Guild {guild_id}: {event.track.title}")

        # Fetch the channel ID we stored earlier
        channel_id = player.fetch('channel')
        if channel_id and guild:
            channel = guild.get_channel(channel_id)
            if channel:
                embed = discord.Embed(
                    color=discord.Color.green(),
                    title="Now Playing",
                    description=f"[{event.track.title}]({event.track.uri})\n"
                                f"Author: {event.track.author}\n"
                                f"Duration: {format_duration(event.track.duration)}\n"
                                f"Requested by: <@{event.track.requester}>"
                )
                if event.track.artwork_url:
                    embed.set_thumbnail(url=event.track.artwork_url)
                try:
                    await channel.send(embed=embed)
                except discord.HTTPException as e:
                    logger.warning(f"Failed to send 'Now Playing' message to channel {channel_id}: {e}")
            else:
                 logger.warning(f"Could not find channel {channel_id} for Guild {guild_id} to send 'Now Playing' message.")
        else:
            logger.warning(f"Could not fetch channel ID or guild for Guild {guild_id} on TrackStartEvent.")

    @lavalink.listener(QueueEndEvent)
    async def on_queue_end(self, event: QueueEndEvent):
        # This event triggers when the queue becomes empty *after* a track finishes.
        # It does NOT trigger if the queue was already empty when stop/disconnect was called.
        player = event.player
        guild_id = player.guild_id
        guild = self.bot.get_guild(guild_id)
        logger.info(f"Queue ended for Guild {guild_id}. Player state: {player.is_playing=}, {player.is_connected=}")

        # Optional: Implement inactivity disconnect timer here
        # We'll just disconnect directly for now.
        if guild and guild.voice_client:
            logger.info(f"Queue ended, disconnecting voice client for Guild {guild_id}")
            # Use the custom disconnect which also destroys the player
            await guild.voice_client.disconnect(force=True) # Force ensures cleanup even if technically still "connected" briefly
        elif player:
            # If voice_client is gone but player exists, try destroying player directly
            logger.warning(f"Queue ended for Guild {guild_id}, but no active voice client found. Attempting player destroy.")
            try:
                await self.lavalink.player_manager.destroy(guild_id)
            except Exception as e:
                logger.error(f"Error destroying player on queue end (no voice client): {e}")


    @lavalink.listener(TrackEndEvent)
    async def on_track_end(self, event: TrackEndEvent):
        # This event triggers whenever a track finishes playing for any reason (except replacement).
        # Reason can be FINISHED, LOAD_FAILED, STOPPED, REPLACED, CLEANUP.
        logger.info(f"Track ended on Guild {event.player.guild_id}. Reason: {event.reason}")
        # You could add logic here based on the reason, e.g., for queue repeat.

    @lavalink.listener(TrackExceptionEvent)
    async def on_track_exception(self, event: TrackExceptionEvent):
        logger.error(f"Track Exception on Guild {event.player.guild_id}: {event.exception}", exc_info=event.exception)
        # Optionally notify the channel where the command was run
        channel_id = event.player.fetch('channel')
        guild = self.bot.get_guild(event.player.guild_id)
        if channel_id and guild:
            channel = guild.get_channel(channel_id)
            if channel:
                await channel.send(f"💥 Error playing track `{event.track.title}`: {event.exception}")

    @lavalink.listener(TrackStuckEvent)
    async def on_track_stuck(self, event: TrackStuckEvent):
        logger.warning(f"Track Stuck on Guild {event.player.guild_id} (Threshold: {event.threshold_ms}ms): {event.track.title}")
        # Optionally skip the track or notify the channel
        channel_id = event.player.fetch('channel')
        guild = self.bot.get_guild(event.player.guild_id)
        if channel_id and guild:
            channel = guild.get_channel(channel_id)
            if channel:
                await channel.send(f"⚠️ Track `{event.track.title}` seems stuck, skipping...")
        await event.player.skip()


    # --- Cog Checks ---
    async def cog_before_invoke(self, ctx: commands.Context):
        # This check applies to prefix commands if you add any later
        if not ctx.guild:
            raise commands.NoPrivateMessage("This command can't be used in DMs.")
        return True

    # Check for slash commands
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            await interaction.response.send_message("This command can only be used in a server!", ephemeral=True)
            return False
        return True

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        # Handle errors specific to slash commands within this cog
        original = getattr(error, 'original', error)
        logger.error(f"Error in slash command '{interaction.command.name if interaction.command else 'unknown'}': {original}", exc_info=original)

        error_message = f"An unexpected error occurred: {original}"
        if isinstance(original, PlayerErrorEvent):
            error_message = f"Audio Player Error: {original}"
        elif isinstance(original, NodeErrorEvent):
             error_message = f"Audio Node Error: {original}"
        elif isinstance(original, app_commands.CheckFailure):
             # Check failures usually send their own messages, but maybe log here
             logger.warning(f"Check failure for command '{interaction.command.name}': {original}")
             return # Don't send another message if check failed likely already did
        # Add more specific error handling as needed

        if interaction.response.is_done():
            await interaction.followup.send(f"❌ {error_message}", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ {error_message}", ephemeral=True)

    # --- Slash Commands ---

    @app_commands.command(name="play", description="Plays a song/playlist or adds it to the queue (YouTube, SoundCloud, Spotify).")
    @app_commands.describe(query='URL (YouTube, SoundCloud, Spotify) or search term (defaults to YouTube search)')
    async def play(self, interaction: discord.Interaction, *, query: str):
        # interaction_check runs automatically for slash commands in cogs

        # Ensure user is in a voice channel
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("You need to be in a voice channel to play music.", ephemeral=True)
            return
        user_channel = interaction.user.voice.channel

        # Get or create the Lavalink player for this guild
        # Using guild_id directly is safe as interaction_check ensures it's in a guild
        player: DefaultPlayer = self.lavalink.player_manager.get(interaction.guild_id)
        if not player:
             player = self.lavalink.player_manager.create(interaction.guild_id)
             logger.info(f"Created Lavalink player for Guild {interaction.guild_id}")

        # Connect if not already connected
        if not interaction.guild.voice_client or not player.is_connected:
             # Check permissions before attempting connection
            permissions = user_channel.permissions_for(interaction.guild.me)
            if not permissions.connect or not permissions.speak:
                await interaction.response.send_message("I need permissions to `Connect` and `Speak` in your voice channel.", ephemeral=True)
                # Clean up player if we created it but can't connect
                if self.lavalink.player_manager.get(interaction.guild_id):
                     await self.lavalink.player_manager.destroy(interaction.guild_id)
                return

            logger.info(f"Connecting to voice channel {user_channel.name} in Guild {interaction.guild_id}")
            # Store the text channel ID where the command was invoked for sending messages later
            player.store('channel', interaction.channel.id)
            await user_channel.connect(cls=LavalinkVoiceClient) # Use our custom voice client
            await interaction.response.send_message(f"Joined {user_channel.mention}!")
            await asyncio.sleep(0.5) # Short delay to ensure connection is fully established
        # If already connected, check if user is in the same channel
        elif interaction.user.voice.channel != interaction.guild.voice_client.channel:
             await interaction.response.send_message("You need to be in the same voice channel as the bot.", ephemeral=True)
             return
        else:
             # If connected and in same channel, just acknowledge
             await interaction.response.defer(thinking=True) # Defer response while searching

        # Get tracks from Lavalink
        try:
            # Determine search type (URL or search query)
            search_query = query.strip('<>') # Remove potential embed masking <>
            search_type = "query"
            load_type_log = "query"

            if URL_REGEX.match(search_query):
                search_type = "URL"
                if SPOTIFY_REGEX.match(search_query):
                    logger.info(f"Spotify URL detected: {search_query}")
                    load_type_log = "Spotify URL"
                    # Lavasrc handles Spotify URLs directly
                elif SOUNDCLOUD_REGEX.match(search_query):
                     logger.info(f"SoundCloud URL detected: {search_query}")
                     load_type_log = "SoundCloud URL"
                     # Lavalink handles SoundCloud URLs directly (if source enabled)
                else:
                     logger.info(f"Generic URL detected: {search_query}")
                     load_type_log = "Generic URL"
                     # Lavalink handles YouTube and some others directly
            else:
                # Default to YouTube search if not a recognizable URL
                search_query = f"ytsearch:{search_query}"
                logger.info(f"Search term detected, using YouTube search: {search_query}")
                load_type_log = "YouTube Search"


            logger.info(f"[{interaction.guild.name}] Getting tracks for: {search_query} ({load_type_log})")
            results: LoadResult = await player.node.get_tracks(search_query)
            logger.debug(f"LoadResult: Type={results.load_type}, Playlist={results.playlist_info}, Tracks={len(results.tracks)}")

            # Validate results
            if results.load_type == LoadType.LOAD_FAILED:
                 message = f"Failed to load tracks: {results.cause}"
                 logger.error(f"Track loading failed: {results.cause}")
                 if interaction.response.is_done(): await interaction.followup.send(message, ephemeral=True)
                 else: await interaction.response.send_message(message, ephemeral=True)
                 return
            elif results.load_type == LoadType.NO_MATCHES:
                 message = f"Could not find any results for `{query}`."
                 logger.warning(f"No matches found for: {query} (Search: {search_query})")
                 if interaction.response.is_done(): await interaction.followup.send(message, ephemeral=True)
                 else: await interaction.response.send_message(message, ephemeral=True)
                 return
            elif not results.tracks: # Should be covered by NO_MATCHES, but safety check
                 message = f"No tracks found for `{query}`."
                 logger.warning(f"Result had no tracks despite not being NO_MATCHES for: {query}")
                 if interaction.response.is_done(): await interaction.followup.send(message, ephemeral=True)
                 else: await interaction.response.send_message(message, ephemeral=True)
                 return

            # Add tracks to queue
            added_count = 0
            if results.load_type == LoadType.PLAYLIST_LOADED:
                playlist_name = results.playlist_info.name or "Unnamed Playlist"
                max_songs = MAX_PLAYLIST_SIZE # Get from config
                tracks_to_add = results.tracks[:max_songs]
                added_count = len(tracks_to_add)

                for track in tracks_to_add:
                    # Create an AudioTrack instance if needed (depends on library version)
                    # Usually, results.tracks contains AudioTrack instances directly
                    player.add(requester=interaction.user.id, track=track)

                message = f"✅ Added **{added_count}** tracks from playlist **`{playlist_name}`** to the queue."
                if len(results.tracks) > max_songs:
                     message += f"\n*(Playlist was capped at {max_songs} tracks)*"
                logger.info(f"Added {added_count} tracks from playlist '{playlist_name}' requested by {interaction.user} ({interaction.user.id})")

            elif results.load_type in [LoadType.TRACK_LOADED, LoadType.SEARCH_RESULT]:
                # Add the first track found (for search) or the single loaded track
                track = results.tracks[0]
                player.add(requester=interaction.user.id, track=track)
                added_count = 1
                message = f"✅ Added **`{track.title}`** to the queue."
                logger.info(f"Added track '{track.title}' requested by {interaction.user} ({interaction.user.id})")

            # Send confirmation message
            if interaction.response.is_done():
                 await interaction.followup.send(message)
            else:
                 # This case shouldn't happen if we deferred correctly
                 await interaction.response.send_message(message)

            # Start playback if not already playing
            if not player.is_playing:
                logger.info(f"Player not playing, starting playback for Guild {interaction.guild_id}")
                await player.play()
            else:
                 logger.info(f"Player already playing, track(s) added to queue for Guild {interaction.guild_id}")

        except NodeErrorEvent as e:
             message = f"Lavalink node connection error: {e}. Please try again later or contact the admin."
             logger.error(f"NodeError during play command: {e}", exc_info=True)
             if interaction.response.is_done(): await interaction.followup.send(message, ephemeral=True)
             else: await interaction.response.send_message(message, ephemeral=True)
        except PlayerErrorEvent as e:
             message = f"Audio player error: {e}. Please try again."
             logger.error(f"PlayerError during play command: {e}", exc_info=True)
             if interaction.response.is_done(): await interaction.followup.send(message, ephemeral=True)
             else: await interaction.response.send_message(message, ephemeral=True)
        except Exception as e:
            message = f"An unexpected error occurred: {e}"
            logger.exception(f"Unexpected error in play command for query '{query}': {e}") # Log full traceback
            if interaction.response.is_done(): await interaction.followup.send(message, ephemeral=True)
            else: await interaction.response.send_message(message, ephemeral=True)


    @app_commands.command(name="disconnect", description="Disconnects the bot from the voice channel.")
    async def disconnect(self, interaction: discord.Interaction):
        player = self.lavalink.player_manager.get(interaction.guild_id)

        if not interaction.guild.voice_client:
            return await interaction.response.send_message("Not connected to any voice channel.", ephemeral=True)

        # Check if user is in the same channel or has permissions (optional)
        # if interaction.user.voice is None or interaction.user.voice.channel != interaction.guild.voice_client.channel:
        #     # Add role/permission check here if needed
        #     return await interaction.response.send_message("You must be in the bot's voice channel to disconnect it.", ephemeral=True)


        logger.info(f"Disconnect command initiated by {interaction.user} in Guild {interaction.guild_id}")
        if player:
            player.queue.clear()
            await player.stop()
            # Store channel maybe? No, disconnect handles player destroy via VoiceClient.disconnect

        # Use the custom disconnect method from LavalinkVoiceClient
        await interaction.guild.voice_client.disconnect(force=True)
        await interaction.response.send_message("Disconnected and cleared queue.")


    @app_commands.command(name="stop", description="Stops the music and clears the queue.")
    async def stop(self, interaction: discord.Interaction):
        player = self.lavalink.player_manager.get(interaction.guild_id)

        if not player or not interaction.guild.voice_client:
            return await interaction.response.send_message("Not currently playing anything.", ephemeral=True)

        # Permission check (optional) - e.g., check if user is in channel or has role
        # if interaction.user.voice is None or interaction.user.voice.channel != interaction.guild.voice_client.channel:
        #      return await interaction.response.send_message("You must be in the bot's voice channel to stop it.", ephemeral=True)

        if not player.is_playing and not player.queue:
             return await interaction.response.send_message("Nothing is playing and the queue is empty.", ephemeral=True)

        logger.info(f"Stop command initiated by {interaction.user} in Guild {interaction.guild_id}")
        player.queue.clear()
        await player.stop()
        # Keep the bot connected, just stop playing
        # If you want stop to also disconnect, call the disconnect command's logic:
        # await interaction.guild.voice_client.disconnect(force=True)
        await interaction.response.send_message("⏹️ Music stopped and queue cleared.")


    @app_commands.command(name="skip", description="Skips the current song.")
    async def skip(self, interaction: discord.Interaction):
        player = self.lavalink.player_manager.get(interaction.guild_id)

        if not player or not player.is_playing:
            return await interaction.response.send_message("No song is currently playing.", ephemeral=True)

        # Permission check (optional)
        # if interaction.user.voice is None or interaction.user.voice.channel != interaction.guild.voice_client.channel:
        #      return await interaction.response.send_message("You must be in the bot's voice channel to skip.", ephemeral=True)

        current_title = player.current.title if player.current else "Unknown Track"
        logger.info(f"Skip command initiated by {interaction.user} for track '{current_title}' in Guild {interaction.guild_id}")
        await player.skip()
        await interaction.response.send_message(f"⏭️ Skipped **`{current_title}`**.")
        # Player will automatically start next song if available due to TrackEndEvent handling

    @app_commands.command(name="pause", description="Pauses the current song.")
    async def pause(self, interaction: discord.Interaction):
        player = self.lavalink.player_manager.get(interaction.guild_id)

        if not player or not player.is_playing:
            return await interaction.response.send_message("No song is currently playing.", ephemeral=True)

        # Permission check (optional)

        if player.paused:
             return await interaction.response.send_message("Music is already paused.", ephemeral=True)

        logger.info(f"Pause command initiated by {interaction.user} in Guild {interaction.guild_id}")
        await player.set_pause(True)
        await interaction.response.send_message("⏸️ Music paused.")

    @app_commands.command(name="resume", description="Resumes the paused song.")
    async def resume(self, interaction: discord.Interaction):
        player = self.lavalink.player_manager.get(interaction.guild_id)

        if not player or not player.current: # Check if there's something to resume
             return await interaction.response.send_message("Nothing is paused or playing.", ephemeral=True)

        # Permission check (optional)

        if not player.paused:
            return await interaction.response.send_message("Music is not paused.", ephemeral=True)

        logger.info(f"Resume command initiated by {interaction.user} in Guild {interaction.guild_id}")
        await player.set_pause(False)
        await interaction.response.send_message("▶️ Music resumed.")

    @app_commands.command(name="loop", description="Toggles looping for the current track.")
    async def loop(self, interaction: discord.Interaction):
        player = self.lavalink.player_manager.get(interaction.guild_id)

        if not player or not player.current:
            return await interaction.response.send_message("No song is currently playing to loop.", ephemeral=True)

        # Permission check (optional)

        # discord-lavalink uses 'repeat' boolean for single track loop
        player.repeat = not player.repeat
        mode = "ON" if player.repeat else "OFF"
        logger.info(f"Loop command initiated by {interaction.user}. Loop set to {mode} for Guild {interaction.guild_id}")
        await interaction.response.send_message(f"🔄 Loop mode for the current track set to **{mode}**.")
        # Note: Queue looping is not built-in, requires manual implementation (e.g., re-adding track in TrackEndEvent if queue loop enabled)

    @app_commands.command(name="shuffle", description="Shuffles the current queue.")
    async def shuffle(self, interaction: discord.Interaction):
        player = self.lavalink.player_manager.get(interaction.guild_id)

        if not player or not player.queue:
            return await interaction.response.send_message("The queue is empty, nothing to shuffle.", ephemeral=True)

        # Permission check (optional)

        logger.info(f"Shuffle command initiated by {interaction.user} in Guild {interaction.guild_id}")
        player.shuffle = True # Enable shuffling mode (Lavalink server handles it)
        # Note: This might only shuffle *once* when enabled. Continuous shuffling isn't standard.
        # Alternatively, shuffle the player.queue list directly:
        # import random
        # random.shuffle(player.queue)
        # player.shuffle = False # Ensure server doesn't also try shuffling
        await interaction.response.send_message("🔀 Queue shuffled.")

    @app_commands.command(name="queue", description="Displays the current song queue.")
    @app_commands.describe(page="Page number of the queue to display")
    async def queue(self, interaction: discord.Interaction, page: app_commands.Range[int, 1] = 1):
        player = self.lavalink.player_manager.get(interaction.guild_id)

        if not player or (not player.current and not player.queue):
            return await interaction.response.send_message("The queue is currently empty.", ephemeral=True)

        items_per_page = 10
        queue_list = list(player.queue) # Get a copy of the queue
        total_items = len(queue_list)
        total_pages = math.ceil(total_items / items_per_page) if total_items > 0 else 1

        if page < 1 or page > total_pages:
            return await interaction.response.send_message(f"Invalid page number. Please choose between 1 and {total_pages}.", ephemeral=True)

        start_index = (page - 1) * items_per_page
        end_index = start_index + items_per_page
        current_page_items = queue_list[start_index:end_index]

        queue_display = ""
        if not current_page_items and page == 1: # Only show "empty" if it's page 1 and list is empty
             queue_display = "The queue is empty."
        else:
            for i, track in enumerate(current_page_items, start=start_index + 1):
                # Ensure track is AudioTrack instance
                if isinstance(track, AudioTrack):
                     title = track.title.replace('`', '\\`') # Escape backticks
                     duration = format_duration(track.duration)
                     requester = f"<@{track.requester}>" if track.requester else "Unknown"
                     queue_display += f"**{i}.** `[{duration}]` [{title}]({track.uri}) - {requester}\n"
                else:
                     logger.warning(f"Item in queue is not an AudioTrack instance: {track}")
                     queue_display += f"**{i}.** Invalid track data\n"


        embed = discord.Embed(
            title="Music Queue",
            color=discord.Color.blue()
        )

        current_track_info = "Nothing currently playing."
        if player.current and isinstance(player.current, AudioTrack):
             title = player.current.title.replace('`', '\\`')
             duration = format_duration(player.current.duration)
             requester = f"<@{player.current.requester}>" if player.current.requester else "Unknown"
             current_track_info = f"**`[{duration}]`** [{title}]({player.current.uri}) - {requester}"
             if player.current.artwork_url:
                 embed.set_thumbnail(url=player.current.artwork_url)

        embed.add_field(name="Currently Playing", value=current_track_info, inline=False)
        embed.add_field(name=f"Up Next (Page {page}/{total_pages})", value=queue_display if queue_display else "No tracks on this page.", inline=False)

        queue_duration_ms = sum(t.duration for t in queue_list if isinstance(t, AudioTrack))
        total_duration_str = format_duration(queue_duration_ms)
        embed.set_footer(text=f"{len(queue_list)} songs in queue | Total duration: {total_duration_str}")

        await interaction.response.send_message(embed=embed)


    @app_commands.command(name="lowpass", description="Applies a low-pass filter (bass boost effect).")
    @app_commands.describe(strength="Filter strength (0.0 to disable, higher = more bassy, max ~2.0 sensible)")
    async def lowpass(self, interaction: discord.Interaction, strength: app_commands.Range[float, 0.0, 100.0]): # Range limits input
        player = self.lavalink.player_manager.get(interaction.guild_id)

        if not player:
             return await interaction.response.send_message("Bot is not connected or playing.", ephemeral=True)

        # Clamp strength just in case Range doesn't fully prevent edge cases
        strength = max(0.0, min(100.0, strength)) # Keep range 0-100 for user input simplicity

        embed = discord.Embed(color=discord.Color.blurple(), title='Low Pass Filter')

        try:
            if strength == 0.0:
                # To remove a specific filter, update the filter object without it
                # Get current filters, remove lowpass, apply the rest
                current_filters = player.filters
                if isinstance(current_filters, dict) and 'lowpass' in current_filters:
                     del current_filters['lowpass'] # Remove the key
                     await player.set_filters(current_filters) # Apply the modified dict
                     embed.description = 'Disabled **Low Pass Filter**'
                elif hasattr(current_filters, 'low_pass') and isinstance(current_filters.low_pass, LowPass):
                     current_filters.low_pass = None # Reset the attribute if using Filter object
                     await player.set_filters(current_filters)
                     embed.description = 'Disabled **Low Pass Filter**'
                else:
                    embed.description = '**Low Pass Filter** was not active.'


            else:
                # Apply the filter
                # The strength value for lavalink's LowPass is 'smoothing'
                # Map the 0-100 input to a reasonable smoothing range (e.g., 1.0 to 20.0?)
                # Let's try a direct mapping for simplicity first, maybe 0-20?
                smoothing_value = strength # Adjust this multiplier based on testing
                low_pass_filter = LowPass(smoothing=smoothing_value)
                await player.set_filter(low_pass_filter) # set_filter adds/replaces

                embed.description = f'Set **Low Pass Filter** smoothing to `{smoothing_value:.2f}`.'

            await interaction.response.send_message(embed=embed)

        except PlayerErrorEvent as e:
             logger.error(f"Error applying filter: {e}")
             await interaction.response.send_message(f"Error applying filter: {e}", ephemeral=True)
        except Exception as e:
              logger.exception(f"Unexpected error applying filter: {e}")
              await interaction.response.send_message("An unexpected error occurred while applying the filter.", ephemeral=True)


async def setup(bot: commands.Bot):
    # Check if Lavalink is initialized on the bot instance before adding the cog
    if not hasattr(bot, 'lavalink') or not isinstance(bot.lavalink, lavalink.Client):
         logger.error("Lavalink client not initialized on bot before loading Music cog. Cog may fail.")
         # Optionally raise an error or prevent loading
         # raise commands.ExtensionFailed("Music cog requires bot.lavalink to be initialized.")
         return # Or silently fail to load

    await bot.add_cog(Music(bot))
    logger.info("Music Cog loaded.")