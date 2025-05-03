import discord
from discord import app_commands
from discord.ext import commands
import lavalink
from lavalink import DefaultPlayer, AudioTrack, LoadResult, LoadType
# Correctly import Event types for error handling
from lavalink import TrackStartEvent, QueueEndEvent, TrackEndEvent, TrackExceptionEvent, TrackStuckEvent, PlayerErrorEvent, NodeErrorEvent
from lavalink import LowPass # Keep filter import

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
        # Check if channel_id is None and the update is for our bot user
        if data.get('channel_id') is None and data.get('user_id') == str(self.client.user.id): # Compare IDs as strings
            guild_id_str = data.get('guild_id')
            if guild_id_str:
                try:
                    guild_id = int(guild_id_str)
                    logger.info(f"Detected bot disconnect via VOICE_STATE_UPDATE for Guild ID: {guild_id}")
                    await self._destroy_player(guild_id)
                except ValueError:
                     logger.error(f"Could not parse guild_id '{guild_id_str}' from VOICE_STATE_UPDATE")
            else:
                 logger.warning("Received disconnect VOICE_STATE_UPDATE without guild_id")


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
        player = self.lavalink.player_manager.get(self.channel.guild.id)
        guild_id = self.channel.guild.id # Store before potential cleanup

        logger.info(f"Disconnecting from voice channel: {self.channel.name if self.channel else 'Unknown'} (Guild ID: {guild_id}) Force: {force}")


        # Normally, don't force disconnect player if it's still playing
        # Check if the bot is actually connected using discord.py's state
        voice_client = self.channel.guild.voice_client if self.channel else None # Check if channel exists
        if not force and player and player.is_connected and voice_client:
            logger.warning(f"Disconnect called on Guild {guild_id} but player is connected and force=False. Not disconnecting.")
            return

        # Tell Discord to leave the channel.
        # This will trigger a VOICE_STATE_UPDATE event which Lavalink listens for.
        if voice_client: # Check if discord.py thinks we are connected
            await self.channel.guild.change_voice_state(channel=None)
            logger.info(f"Requested voice state change to disconnect from Guild {guild_id}")
            # Player cleanup should happen in on_voice_state_update now

        # Clean up the Lavalink player instance *if* discord didn't trigger the event cleanup
        # This might be redundant if on_voice_state_update works reliably, but acts as a fallback.
        # Add a small delay to allow the event handler to potentially act first
        await asyncio.sleep(0.2)
        if self.lavalink.player_manager.get(guild_id): # Check if player still exists
             logger.warning(f"Player still exists after requesting disconnect for Guild {guild_id}, attempting manual destroy.")
             await self._destroy_player(guild_id)

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
        # Event listeners are defined below with decorators

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
            if channel and isinstance(channel, discord.TextChannel): # Check if it's a text channel
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
                except discord.errors.Forbidden:
                     logger.warning(f"Missing permissions to send 'Now Playing' message in channel {channel_id} (Guild {guild_id})")
                except discord.HTTPException as e:
                    logger.warning(f"Failed to send 'Now Playing' message to channel {channel_id}: {e}")
            else:
                 logger.warning(f"Could not find text channel {channel_id} for Guild {guild_id} to send 'Now Playing' message.")
        else:
            logger.warning(f"Could not fetch channel ID or guild for Guild {guild_id} on TrackStartEvent.")

    @lavalink.listener(QueueEndEvent)
    async def on_queue_end(self, event: QueueEndEvent):
        # This event triggers when the queue becomes empty *after* a track finishes.
        # It does NOT trigger if the queue was already empty when stop/disconnect was called.
        player = event.player
        guild_id = player.guild_id
        guild = self.bot.get_guild(guild_id)
        logger.info(f"Queue ended for Guild {guild_id}. Player state: is_playing={player.is_playing}, is_connected={player.is_connected}")

        # Optional: Implement inactivity disconnect timer here
        # For now, disconnect after a short delay if nothing else starts playing
        await asyncio.sleep(10) # Wait 10 seconds

        # Check again if the player is still connected and not playing
        player = self.lavalink.player_manager.get(guild_id) # Re-fetch player state
        if player and player.is_connected and not player.is_playing:
             if guild and guild.voice_client:
                 logger.info(f"Queue ended and no new track started, disconnecting voice client for Guild {guild_id}")
                 # Use the custom disconnect which also destroys the player
                 await guild.voice_client.disconnect(force=True) # Force ensures cleanup
             elif player:
                 # If voice_client is gone but player exists, try destroying player directly
                 logger.warning(f"Queue ended for Guild {guild_id}, but no active voice client found. Attempting player destroy.")
                 await player.manager._destroy_player(guild_id) # Access protected method if needed, or use public if available
        else:
            logger.info(f"QueueEndEvent: Player on Guild {guild_id} is now playing or disconnected, not auto-disconnecting.")



    @lavalink.listener(TrackEndEvent)
    async def on_track_end(self, event: TrackEndEvent):
        # This event triggers whenever a track finishes playing for any reason (except replacement).
        # Reason can be FINISHED, LOAD_FAILED, STOPPED, REPLACED, CLEANUP.
        logger.info(f"Track ended on Guild {event.player.guild_id}. Reason: {event.reason}")
        # You could add logic here based on the reason, e.g., for queue repeat.

    @lavalink.listener(TrackExceptionEvent)
    async def on_track_exception(self, event: TrackExceptionEvent):
        logger.error(f"Track Exception on Guild {event.player.guild_id}: {event.message}", exc_info=event.exception)
        # Optionally notify the channel where the command was run
        channel_id = event.player.fetch('channel')
        guild = self.bot.get_guild(event.player.guild_id)
        if channel_id and guild:
            channel = guild.get_channel(channel_id)
            if channel and isinstance(channel, discord.TextChannel):
                try:
                    await channel.send(f"💥 Error playing track `{event.track.title}`: {event.message or event.exception}")
                except discord.HTTPException:
                    pass # Ignore if sending fails

    @lavalink.listener(TrackStuckEvent)
    async def on_track_stuck(self, event: TrackStuckEvent):
        logger.warning(f"Track Stuck on Guild {event.player.guild_id} (Threshold: {event.threshold_ms}ms): {event.track.title}")
        # Optionally skip the track or notify the channel
        channel_id = event.player.fetch('channel')
        guild = self.bot.get_guild(event.player.guild_id)
        if channel_id and guild:
            channel = guild.get_channel(channel_id)
            if channel and isinstance(channel, discord.TextChannel):
                try:
                    await channel.send(f"⚠️ Track `{event.track.title}` seems stuck, skipping...")
                except discord.HTTPException:
                     pass
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
        # Ensure bot has lavalink instance
        if not hasattr(self.bot, 'lavalink'):
            logger.error("Interaction check failed: Bot has no lavalink instance.")
            await interaction.response.send_message("Music service is not available.", ephemeral=True)
            return False
        return True

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        # Handle errors specific to slash commands within this cog
        original = getattr(error, 'original', error)
        logger.error(f"Error in slash command '{interaction.command.name if interaction.command else 'unknown'}': {original}", exc_info=original)

        error_message = f"An unexpected error occurred: {original}"
        # Check for the correct Event types now
        if isinstance(original, PlayerErrorEvent):
            error_message = f"Audio Player Error: {original.error}" # Access the error message from the event
        elif isinstance(original, NodeErrorEvent):
             error_message = f"Audio Node Error: {original.error}" # Access the error message from the event
        elif isinstance(original, app_commands.CheckFailure):
             # Check failures usually send their own messages, but maybe log here
             logger.warning(f"Check failure for command '{interaction.command.name if interaction.command else 'unknown'}': {original}")
             # If the interaction response wasn't already sent by the check
             if not interaction.response.is_done():
                  await interaction.response.send_message(str(original), ephemeral=True)
             return # Don't send another message
        # Add more specific error handling as needed

        try:
            if interaction.response.is_done():
                await interaction.followup.send(f"❌ {error_message}", ephemeral=True)
            else:
                await interaction.response.send_message(f"❌ {error_message}", ephemeral=True)
        except discord.HTTPException as e:
             logger.error(f"Failed to send error message for command '{interaction.command.name if interaction.command else 'unknown'}': {e}")

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

        # Check node availability before proceeding
        if not player and not self.lavalink.node_manager.available_nodes:
             logger.error(f"Play command failed for Guild {interaction.guild_id}: No available Lavalink nodes.")
             await interaction.response.send_message("Music service node is currently unavailable. Please try again later.", ephemeral=True)
             return
        if not player:
             player = self.lavalink.player_manager.create(interaction.guild_id)
             logger.info(f"Created Lavalink player for Guild {interaction.guild_id}")
             # Set default volume from config
             default_vol = int(os.getenv('DEFAULT_VOLUME', 100))
             await player.set_volume(default_vol)
             logger.info(f"Set default volume to {default_vol} for Guild {interaction.guild_id}")

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
            # Defer response *before* connecting or send initial message
            await interaction.response.defer(thinking=True, ephemeral=False) # Defer publicly while connecting/searching
            # await interaction.response.send_message(f"Joining {user_channel.mention}...") # Alternative initial msg
            # await asyncio.sleep(0.5) # Short delay might still be helpful
        # If already connected, check if user is in the same channel
        elif interaction.user.voice.channel.id != player.channel_id: # Check against player's stored channel ID
             await interaction.response.send_message("You need to be in the same voice channel as the bot.", ephemeral=True)
             return
        else:
             # If connected and in same channel, just acknowledge
             await interaction.response.defer(thinking=True) # Defer response while searching

        # Get tracks from Lavalink
        try:
            # Determine search type (URL or search query)
            search_query = query.strip('<>') # Remove potential embed masking <>
            load_type_log = "query" # Default log type

            if URL_REGEX.match(search_query):
                if SPOTIFY_REGEX.match(search_query):
                    logger.info(f"Spotify URL detected: {search_query}")
                    load_type_log = "Spotify URL"
                elif SOUNDCLOUD_REGEX.match(search_query):
                     logger.info(f"SoundCloud URL detected: {search_query}")
                     load_type_log = "SoundCloud URL"
                else:
                     logger.info(f"Potential YouTube/Other URL detected: {search_query}")
                     load_type_log = "Generic URL"
                     # Let Lavalink determine if it's YT or other supported HTTP
            else:
                # Default to YouTube search if not a recognizable URL
                search_query = f"ytsearch:{search_query}"
                logger.info(f"Search term detected, using YouTube search: {search_query}")
                load_type_log = "YouTube Search"


            logger.info(f"[{interaction.guild.name}] Getting tracks for: '{search_query}' ({load_type_log})")
            results: LoadResult = await player.node.get_tracks(search_query)
            logger.debug(f"LoadResult: Type={results.load_type}, Playlist={results.playlist_info}, Tracks={len(results.tracks)}")

            # Validate results
            if results.load_type == LoadType.LOAD_FAILED:
                 message = f"Failed to load tracks: {results.cause}"
                 logger.error(f"Track loading failed for query '{search_query}': {results.cause}")
                 # Use followup since we deferred
                 await interaction.followup.send(message, ephemeral=True)
                 return
            elif results.load_type == LoadType.NO_MATCHES:
                 message = f"Could not find any results for `{query}`."
                 logger.warning(f"No matches found for: {query} (Search: {search_query})")
                 await interaction.followup.send(message, ephemeral=True)
                 return
            elif not results.tracks: # Should be covered by NO_MATCHES, but safety check
                 message = f"No tracks found for `{query}`."
                 logger.warning(f"Result had no tracks despite not being NO_MATCHES for: {query}")
                 await interaction.followup.send(message, ephemeral=True)
                 return

            # Enforce Queue Size Limit before adding
            current_queue_size = len(player.queue)
            max_queue = MAX_QUEUE_SIZE # From config

            # Add tracks to queue
            added_count = 0
            skipped_count = 0
            message = ""

            if results.load_type == LoadType.PLAYLIST_LOADED:
                playlist_name = results.playlist_info.name or "Unnamed Playlist"
                max_songs_playlist = MAX_PLAYLIST_SIZE # From config
                
                tracks_to_consider = results.tracks[:max_songs_playlist]
                
                for track in tracks_to_consider:
                    if current_queue_size + added_count < max_queue:
                        player.add(requester=interaction.user.id, track=track)
                        added_count += 1
                    else:
                        skipped_count += 1
                
                message = f"✅ Added **{added_count}** tracks from playlist **`{playlist_name}`** to the queue."
                if len(results.tracks) > max_songs_playlist:
                     message += f"\n*(Playlist capped at {max_songs_playlist} tracks)*"
                if skipped_count > 0:
                     message += f"\n*(Skipped {skipped_count} tracks as queue reached max size of {max_queue})*"
                logger.info(f"Added {added_count} tracks from playlist '{playlist_name}' requested by {interaction.user} ({interaction.user.id}). Skipped {skipped_count}.")

            elif results.load_type in [LoadType.TRACK_LOADED, LoadType.SEARCH_RESULT]:
                track = results.tracks[0]
                if current_queue_size < max_queue:
                     player.add(requester=interaction.user.id, track=track)
                     added_count = 1
                     message = f"✅ Added **`{track.title}`** to the queue."
                     logger.info(f"Added track '{track.title}' requested by {interaction.user} ({interaction.user.id})")
                else:
                     message = f"❌ Could not add **`{track.title}`**, the queue is full (Max: {max_queue})."
                     logger.warning(f"Queue full. Could not add track '{track.title}' for {interaction.user} ({interaction.user.id})")


            # Send confirmation message using followup
            await interaction.followup.send(message)

            # Start playback if not already playing
            if not player.is_playing:
                logger.info(f"Player not playing, starting playback for Guild {interaction.guild_id}")
                await player.play()
            # else: Player automatically continues or starts next on track end

        # Removed specific PlayerError/NodeError catches as they are events
        except Exception as e:
            message = f"An unexpected error occurred: {e}"
            logger.exception(f"Unexpected error in play command for query '{query}': {e}") # Log full traceback
            # Use followup since we deferred
            try:
                 await interaction.followup.send(message, ephemeral=True)
            except discord.HTTPException:
                 logger.error("Failed to send followup error message for play command.")


    @app_commands.command(name="disconnect", description="Disconnects the bot from the voice channel.")
    async def disconnect(self, interaction: discord.Interaction):
        player = self.lavalink.player_manager.get(interaction.guild_id)

        if not interaction.guild.voice_client:
            return await interaction.response.send_message("Not connected to any voice channel.", ephemeral=True)

        # Permission check (optional)

        logger.info(f"Disconnect command initiated by {interaction.user} in Guild {interaction.guild_id}")
        if player:
            player.queue.clear()
            await player.stop()

        # Use the custom disconnect method from LavalinkVoiceClient
        await interaction.guild.voice_client.disconnect(force=True)
        await interaction.response.send_message("Disconnected and cleared queue.")


    @app_commands.command(name="stop", description="Stops the music and clears the queue.")
    async def stop(self, interaction: discord.Interaction):
        player = self.lavalink.player_manager.get(interaction.guild_id)

        if not player or not interaction.guild.voice_client:
            return await interaction.response.send_message("Not currently playing anything.", ephemeral=True)

        # Permission check (optional)

        if not player.is_playing and not player.queue:
             return await interaction.response.send_message("Nothing is playing and the queue is empty.", ephemeral=True)

        logger.info(f"Stop command initiated by {interaction.user} in Guild {interaction.guild_id}")
        player.queue.clear()
        await player.stop()
        # Bot remains connected
        await interaction.response.send_message("⏹️ Music stopped and queue cleared.")


    @app_commands.command(name="skip", description="Skips the current song.")
    async def skip(self, interaction: discord.Interaction):
        player = self.lavalink.player_manager.get(interaction.guild_id)

        if not player or not player.is_playing:
            return await interaction.response.send_message("No song is currently playing.", ephemeral=True)

        # Permission check (optional)

        current_title = player.current.title if player.current else "Unknown Track"
        logger.info(f"Skip command initiated by {interaction.user} for track '{current_title}' in Guild {interaction.guild_id}")
        await player.skip()
        await interaction.response.send_message(f"⏭️ Skipped **`{current_title}`**.")


    @app_commands.command(name="pause", description="Pauses the current song.")
    async def pause(self, interaction: discord.Interaction):
        player = self.lavalink.player_manager.get(interaction.guild_id)

        if not player or not player.is_playing:
            return await interaction.response.send_message("No song is currently playing.", ephemeral=True)

        if player.paused:
             return await interaction.response.send_message("Music is already paused.", ephemeral=True)

        logger.info(f"Pause command initiated by {interaction.user} in Guild {interaction.guild_id}")
        await player.set_pause(True)
        await interaction.response.send_message("⏸️ Music paused.")

    @app_commands.command(name="resume", description="Resumes the paused song.")
    async def resume(self, interaction: discord.Interaction):
        player = self.lavalink.player_manager.get(interaction.guild_id)

        if not player or not player.current:
             return await interaction.response.send_message("Nothing is paused or playing.", ephemeral=True)

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

        player.repeat = not player.repeat
        mode = "ON" if player.repeat else "OFF"
        logger.info(f"Loop command initiated by {interaction.user}. Loop set to {mode} for Guild {interaction.guild_id}")
        await interaction.response.send_message(f"🔄 Loop mode for the current track set to **{mode}**.")


    @app_commands.command(name="shuffle", description="Shuffles the current queue.")
    async def shuffle(self, interaction: discord.Interaction):
        player = self.lavalink.player_manager.get(interaction.guild_id)

        if not player or len(player.queue) < 2: # Need at least 2 songs to shuffle
            return await interaction.response.send_message("The queue needs at least 2 songs to shuffle.", ephemeral=True)

        logger.info(f"Shuffle command initiated by {interaction.user} in Guild {interaction.guild_id}")
        player.set_shuffle(True) # Enable server-side shuffling
        # Note: Lavalink shuffles *when this is set*. It doesn't re-shuffle automatically later.
        # To shuffle the current queue list in place:
        # import random
        # random.shuffle(player.queue)
        # player.set_shuffle(False) # Disable server shuffling if managing manually
        await interaction.response.send_message("🔀 Queue shuffled.")


    @app_commands.command(name="queue", description="Displays the current song queue.")
    @app_commands.describe(page="Page number of the queue to display")
    async def queue(self, interaction: discord.Interaction, page: app_commands.Range[int, 1] = 1):
        player = self.lavalink.player_manager.get(interaction.guild_id)

        if not player or (not player.current and not player.queue):
            embed = discord.Embed(title="Music Queue", description="The queue is currently empty.", color=discord.Color.blue())
            return await interaction.response.send_message(embed=embed)

        items_per_page = 10
        queue_list = list(player.queue) # Get a copy
        total_items = len(queue_list)
        total_pages = math.ceil(total_items / items_per_page) if total_items > 0 else 1

        if page < 1 or page > total_pages:
            return await interaction.response.send_message(f"Invalid page number. Please choose between 1 and {total_pages}.", ephemeral=True)

        start_index = (page - 1) * items_per_page
        end_index = start_index + items_per_page
        current_page_items = queue_list[start_index:end_index]

        queue_display = ""
        if not current_page_items and page > 1: # Show empty only if not page 1
             queue_display = "No tracks on this page."
        elif not current_page_items and page == 1 and not player.current: # Handle empty page 1 specifically
             queue_display = "The queue is empty."
        else:
            for i, track in enumerate(current_page_items, start=start_index + 1):
                if isinstance(track, AudioTrack):
                     # Escape potential markdown characters in titles
                     title = discord.utils.escape_markdown(track.title)
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
             title = discord.utils.escape_markdown(player.current.title)
             duration = format_duration(player.current.duration)
             requester = f"<@{player.current.requester}>" if player.current.requester else "Unknown"
             current_track_info = f"**`[{duration}]`** [{title}]({player.current.uri}) - {requester}"
             if player.current.artwork_url:
                 embed.set_thumbnail(url=player.current.artwork_url)

        embed.add_field(name="Currently Playing", value=current_track_info, inline=False)
        if queue_display: # Only add the queue field if there's something to display
            embed.add_field(name=f"Up Next (Page {page}/{total_pages})", value=queue_display, inline=False)
        else: # Handle edge case where queue is empty but song is playing
             if not player.queue:
                  embed.add_field(name="Up Next", value="The queue is empty.", inline=False)


        queue_duration_ms = sum(t.duration for t in queue_list if isinstance(t, AudioTrack) and t.duration is not None)
        total_duration_str = format_duration(queue_duration_ms)
        embed.set_footer(text=f"{len(queue_list)} songs in queue | Total duration: {total_duration_str} | Page {page}/{total_pages}")

        await interaction.response.send_message(embed=embed)


    @app_commands.command(name="lowpass", description="Applies a low-pass filter (bass boost effect).")
    @app_commands.describe(strength="Filter strength (0.0 to disable, recommended 1.0-20.0)")
    async def lowpass(self, interaction: discord.Interaction, strength: app_commands.Range[float, 0.0, 100.0]):
        player = self.lavalink.player_manager.get(interaction.guild_id)

        if not player:
             return await interaction.response.send_message("Bot is not connected or playing.", ephemeral=True)

        # Clamp strength (Range might handle this, but belt-and-suspenders)
        strength = max(0.0, min(100.0, strength))

        embed = discord.Embed(color=discord.Color.blurple(), title='Low Pass Filter')

        try:
            # Use player.set_filter for simplicity - it handles adding/removing/replacing
            if strength == 0.0:
                # Create a filter object *without* lowpass to remove it
                # You might need to re-apply other active filters if any exist
                # Simplest way: Create an empty LowPass to effectively nullify it
                await player.set_filter(LowPass()) # Setting default LowPass might disable it
                # Alternative: Get current filters, remove lowpass, set again (more complex)
                embed.description = 'Disabled **Low Pass Filter** (or set to default).'
            else:
                # The strength value for lavalink's LowPass is 'smoothing'
                smoothing_value = strength # Adjust this based on testing if 0-100 isn't ideal
                low_pass_filter = LowPass(smoothing=smoothing_value)
                await player.set_filter(low_pass_filter)
                embed.description = f'Set **Low Pass Filter** smoothing to `{smoothing_value:.2f}`.'

            await interaction.response.send_message(embed=embed)

        # Removed specific PlayerError catch
        except Exception as e:
              logger.exception(f"Unexpected error applying filter: {e}")
              await interaction.response.send_message(f"An unexpected error occurred while applying the filter: {e}", ephemeral=True)


async def setup(bot: commands.Bot):
    # Check if Lavalink is initialized on the bot instance before adding the cog
    if not hasattr(bot, 'lavalink') or not isinstance(bot.lavalink, lavalink.Client):
         logger.error("Lavalink client not initialized on bot before loading Music cog. Cog may fail.")
         # raise commands.ExtensionFailed("Music cog requires bot.lavalink to be initialized.")
         return # Silently fail to load

    await bot.add_cog(Music(bot))
    logger.info("Music Cog loaded.")