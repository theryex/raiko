# --- START OF FILE cogs/music.py ---
import discord
from discord import app_commands
from discord.ext import commands
import lavalink
from lavalink import DefaultPlayer, AudioTrack, LoadResult, LoadType
# Import available event types
from lavalink import TrackStartEvent, QueueEndEvent, TrackEndEvent, TrackExceptionEvent, TrackStuckEvent, PlayerErrorEvent # REMOVED NodeErrorEvent
from lavalink import LowPass # Keep filter import
import os # Ensure OS is imported

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
def format_duration(milliseconds: Optional[int]) -> str: # Added Optional typing
    """Formats milliseconds into HH:MM:SS or MM:SS."""
    if milliseconds is None:
        return "N/A"
    try:
        milliseconds = int(milliseconds) # Ensure it's an integer
    except (ValueError, TypeError):
        return "N/A"

    if milliseconds <= 0: # Handle zero or negative duration
        return "00:00"

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
        super().__init__(client, channel) # Call super init
        self.client = client
        self.channel = channel
        # Ensure the Lavalink client instance exists
        if not hasattr(self.client, 'lavalink'):
            logger.critical("Lavalink client not found on bot when creating VoiceClient!")
            # This voice client might not function correctly.
            self.lavalink = None # Indicate lavalink is missing
        else:
             self.lavalink: lavalink.Client = self.client.lavalink


    async def on_voice_server_update(self, data):
        """Handles the VOICE_SERVER_UPDATE event from Discord."""
        if not self.lavalink: return # Don't proceed if lavalink wasn't initialized
        lavalink_data = {
            't': 'VOICE_SERVER_UPDATE',
            'd': data
        }
        # logger.debug(f"VOICE_SERVER_UPDATE: {data}")
        await self.lavalink.voice_update_handler(lavalink_data)

    async def on_voice_state_update(self, data):
        """Handles the VOICE_STATE_UPDATE event from Discord."""
        if not self.lavalink: return # Don't proceed if lavalink wasn't initialized
        lavalink_data = {
            't': 'VOICE_STATE_UPDATE',
            'd': data
        }
        # logger.debug(f"VOICE_STATE_UPDATE: {data}")

        # Check if 'guild_id' exists before processing further
        guild_id_str = data.get('guild_id')
        if not guild_id_str:
             # This can happen on user updates outside guilds? Log if needed.
             # logger.warning("Received VOICE_STATE_UPDATE without guild_id")
             return # Cannot process player state without guild ID

        try:
             current_guild_id = int(guild_id_str)
        except ValueError:
             logger.error(f"Could not parse guild_id '{guild_id_str}' from VOICE_STATE_UPDATE")
             return

        await self.lavalink.voice_update_handler(lavalink_data)

        # Handle disconnects initiated from Discord (e.g., user moves bot)
        # Check if channel_id is None and the update is for our bot user
        if data.get('channel_id') is None and data.get('user_id') == str(self.client.user.id): # Compare IDs as strings
            logger.info(f"Detected bot disconnect via VOICE_STATE_UPDATE for Guild ID: {current_guild_id}")
            # Schedule the player destruction after a short delay to ensure events settle
            self.client.loop.create_task(self._delayed_destroy_player(current_guild_id))

    async def _delayed_destroy_player(self, guild_id: int, delay: float = 0.5):
        """ Waits a short delay then destroys the player if it exists. """
        await asyncio.sleep(delay)
        await self._destroy_player(guild_id)

    async def connect(self, *, timeout: float, reconnect: bool, self_deaf: bool = False, self_mute: bool = False) -> None:
        """ Connects to the voice channel and creates a Lavalink player. """
        if not self.lavalink:
             logger.error(f"Cannot connect: Lavalink not initialized on bot.")
             raise RuntimeError("Lavalink client is not available.")

        logger.info(f"Connecting to voice channel: {self.channel.name} (ID: {self.channel.id})")
        # Ensure a player instance exists for this guild in the Lavalink client
        # Use get_or_create for robustness
        self.lavalink.player_manager.create(guild_id=self.channel.guild.id)
        # Use discord.py's state change mechanism to connect
        await self.channel.guild.change_voice_state(channel=self.channel, self_mute=self_mute, self_deaf=self_deaf)
        logger.info(f"Successfully requested connection to {self.channel.name}")


    async def disconnect(self, *, force: bool = False) -> None:
        """ Disconnects from the voice channel and destroys the Lavalink player. """
        if not self.channel: # Safety check if channel is somehow None
            logger.warning("Attempted disconnect but VoiceClient channel is None.")
            self.cleanup()
            return

        guild_id = self.channel.guild.id # Store before potential cleanup

        if not self.lavalink:
            logger.warning(f"Cannot disconnect cleanly for Guild {guild_id}: Lavalink not initialized on bot.")
            # Attempt basic discord.py disconnect if possible
            if self.channel.guild.voice_client:
                 await self.channel.guild.change_voice_state(channel=None)
            self.cleanup()
            return

        # Proceed with Lavalink disconnect logic
        player = self.lavalink.player_manager.get(guild_id)

        logger.info(f"Disconnecting from voice channel: {self.channel.name} (Guild ID: {guild_id}) Force: {force}")

        # Check if the bot is actually connected using discord.py's state
        voice_client = self.channel.guild.voice_client

        # Simplified logic: Always try to tell Discord to disconnect if we think we should be
        # Player cleanup is primarily handled by the VOICE_STATE_UPDATE event now.
        if voice_client: # Check if discord.py thinks we are connected
            logger.info(f"Requesting voice state change to disconnect from Guild {guild_id}")
            await self.channel.guild.change_voice_state(channel=None)
            # Player cleanup should happen in on_voice_state_update -> _delayed_destroy_player

        # Minimal fallback cleanup
        await asyncio.sleep(0.2) # Give event handler a moment
        if player and self.lavalink.player_manager.get(guild_id): # Check if player still exists
             logger.warning(f"Player still exists after requesting disconnect for Guild {guild_id}, attempting manual destroy (might be redundant).")
             await self._destroy_player(guild_id) # This might be called twice if event worked, but safe

        self.cleanup() # discord.py internal cleanup


    async def _destroy_player(self, guild_id: int):
        """ Safely destroys the player and cleans up resources. """
        if not self.lavalink: return # Can't destroy if lavalink doesn't exist

        # Ensure the player actually exists before trying to destroy
        if self.lavalink.player_manager.get(guild_id):
            logger.info(f"Attempting to destroy player for Guild ID: {guild_id}")
            try:
                await self.lavalink.player_manager.destroy(guild_id)
                logger.info(f"Lavalink player destroyed for Guild ID: {guild_id}")
            except Exception as e:
                logger.error(f"Error destroying Lavalink player for Guild ID {guild_id}: {e}", exc_info=True)
        else:
            logger.info(f"Lavalink player already destroyed or not found for Guild ID: {guild_id} upon _destroy_player call.")

# --- Music Cog ---
class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Ensure Lavalink client is ready (it should be from bot.py)
        if not hasattr(bot, 'lavalink'):
            logger.critical("Lavalink client not found on bot instance in Music Cog init!")
            # This cog might not function correctly. Consider raising an error or preventing load.
            raise commands.ExtensionFailed("Music Cog", NameError("Lavalink client not found on bot instance"))


        self.lavalink: lavalink.Client = self.bot.lavalink
        self.inactivity_timers: dict[int, asyncio.Task] = {} # Store inactivity tasks per guild

    def cog_unload(self):
        """ Cog cleanup """
        # Cancel any running inactivity timers
        for task in self.inactivity_timers.values():
            task.cancel()
        self.inactivity_timers.clear()
        logger.info("Music Cog unloaded, inactivity timers cancelled.")


    # Use decorators for event listeners - simpler and cleaner
    @lavalink.listener(TrackStartEvent)
    async def on_track_start(self, event: TrackStartEvent):
        player = event.player
        guild_id = player.guild_id

        # Cancel existing inactivity timer for this guild if one exists
        if guild_id in self.inactivity_timers:
            self.inactivity_timers[guild_id].cancel()
            del self.inactivity_timers[guild_id]
            logger.info(f"Cancelled inactivity timer for Guild {guild_id} due to track start.")

        guild = self.bot.get_guild(guild_id)
        logger.info(f"Track started on Guild {guild_id}: {event.track.title}")

        # Fetch the channel ID we stored earlier
        channel_id = player.fetch('channel')
        if channel_id and guild:
            channel = guild.get_channel(channel_id)
            if channel and isinstance(channel, discord.TextChannel): # Check if it's a text channel
                # Make sure track properties are available
                title = getattr(event.track, 'title', 'Unknown Title')
                uri = getattr(event.track, 'uri', '#')
                author = getattr(event.track, 'author', 'Unknown Author')
                duration_ms = getattr(event.track, 'duration', None)
                requester = getattr(event.track, 'requester', None)
                artwork_url = getattr(event.track, 'artwork_url', None)

                desc = f"[{discord.utils.escape_markdown(title)}]({uri})\n"
                desc += f"Author: {discord.utils.escape_markdown(author)}\n"
                desc += f"Duration: {format_duration(duration_ms)}\n"
                if requester:
                    desc += f"Requested by: <@{requester}>"

                embed = discord.Embed(
                    color=discord.Color.green(),
                    title="Now Playing",
                    description=desc
                )
                if artwork_url:
                    embed.set_thumbnail(url=artwork_url)
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
        player = event.player
        guild_id = player.guild_id
        logger.info(f"Queue ended for Guild {guild_id}. Player state: is_playing={player.is_playing}, is_connected={player.is_connected}")

        # Start the inactivity disconnect timer
        self._schedule_inactivity_check(guild_id)

    def _schedule_inactivity_check(self, guild_id: int):
        """Schedules the inactivity check task."""
        # Cancel any previous timer for this guild
        if guild_id in self.inactivity_timers:
            self.inactivity_timers[guild_id].cancel()

        disconnect_delay = 60 # Seconds to wait before disconnecting
        logger.info(f"Queue ended or player stopped, starting {disconnect_delay}s disconnect timer for Guild {guild_id}")
        # Schedule the check
        task = asyncio.create_task(self._check_inactivity(guild_id, disconnect_delay))
        self.inactivity_timers[guild_id] = task
        # Remove task from dict when done (handles completion and cancellation)
        task.add_done_callback(lambda t: self.inactivity_timers.pop(guild_id, None))


    async def _check_inactivity(self, guild_id: int, delay: int):
        """Checks if the player is inactive after a delay and disconnects."""
        await asyncio.sleep(delay)

        player = self.lavalink.player_manager.get(guild_id)
        guild = self.bot.get_guild(guild_id)

        # Check again if the player is still connected and not playing after the delay
        if player and player.is_connected and not player.is_playing and not player.queue: # Also check queue is empty
             if guild and guild.voice_client:
                 logger.info(f"Disconnect timer finished, disconnecting inactive voice client for Guild {guild_id}")
                 await guild.voice_client.disconnect(force=True) # force=True may not be needed if handled by event
                 # Player destruction should be handled by the on_voice_state_update event
             elif player:
                 logger.warning(f"Disconnect timer finished for Guild {guild_id}, but no active discord.py voice client found. Attempting manual player destroy.")
                 await self._safe_destroy_player(guild_id) # Use helper
        else:
            status = "playing" if player and player.is_playing else "queue has items" if player and player.queue else "already disconnected" if not player else "unknown state"
            logger.info(f"Inactivity check for Guild {guild_id}: Player is {status}, cancelling auto-disconnect.")


    # Helper to destroy player safely, used by event handlers & inactivity check
    async def _safe_destroy_player(self, guild_id: int):
         # Ensure player exists before trying
         player = self.lavalink.player_manager.get(guild_id)
         if player:
             try:
                 await self.lavalink.player_manager.destroy(guild_id)
                 logger.info(f"Helper destroyed player for Guild ID: {guild_id}")
             except Exception as e:
                 logger.error(f"Error in _safe_destroy_player for Guild ID {guild_id}: {e}", exc_info=True)
         else:
             logger.info(f"_safe_destroy_player called for Guild ID {guild_id}, but player was already gone.")


    @lavalink.listener(TrackEndEvent)
    async def on_track_end(self, event: TrackEndEvent):
        logger.info(f"Track ended on Guild {event.player.guild_id}. Reason: {event.reason}")
        # If the track finished normally (not replaced/stopped) and queue is empty, start inactivity timer
        if event.reason == 'FINISHED' and not event.player.queue:
             self._schedule_inactivity_check(event.player.guild_id)
        # Add specific logic if needed, e.g., REPLACED doesn't mean playback stopped.


    @lavalink.listener(TrackExceptionEvent)
    async def on_track_exception(self, event: TrackExceptionEvent):
        logger.error(f"Track Exception on Guild {event.player.guild_id}: {event.message}", exc_info=event.exception)
        channel_id = event.player.fetch('channel')
        guild = self.bot.get_guild(event.player.guild_id)
        if channel_id and guild:
            channel = guild.get_channel(channel_id)
            if channel and isinstance(channel, discord.TextChannel):
                track_title = getattr(event.track, 'title', 'the track') # Safely get title
                error_msg = event.message or str(event.exception)
                try:
                    await channel.send(f"💥 Error playing `{discord.utils.escape_markdown(track_title)}`: {error_msg}")
                except discord.HTTPException:
                    pass
        # Optionally skip to the next track here if desired on exceptions


    @lavalink.listener(TrackStuckEvent)
    async def on_track_stuck(self, event: TrackStuckEvent):
        logger.warning(f"Track Stuck on Guild {event.player.guild_id} (Threshold: {event.threshold_ms}ms): {getattr(event.track, 'title', 'Unknown Title')}")
        channel_id = event.player.fetch('channel')
        guild = self.bot.get_guild(event.player.guild_id)
        if channel_id and guild:
            channel = guild.get_channel(channel_id)
            if channel and isinstance(channel, discord.TextChannel):
                track_title = getattr(event.track, 'title', 'the track') # Safely get title
                try:
                    await channel.send(f"⚠️ Track `{discord.utils.escape_markdown(track_title)}` seems stuck, skipping...")
                except discord.HTTPException:
                     pass
        # Skip the stuck track
        await event.player.skip()

    # Listener for Player Errors (like decoding issues, etc.)
    @lavalink.listener(PlayerErrorEvent)
    async def on_player_error(self, event: PlayerErrorEvent):
         logger.error(f"Player Error on Guild {event.player.guild_id}: {event.error}")
         channel_id = event.player.fetch('channel')
         guild = self.bot.get_guild(event.player.guild_id)
         if channel_id and guild:
             channel = guild.get_channel(channel_id)
             if channel and isinstance(channel, discord.TextChannel):
                 try:
                     await channel.send(f"❌ A player error occurred: {event.error}")
                 except discord.HTTPException:
                     pass
         # Depending on the error, you might want to destroy the player or skip


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
        # Ensure bot has lavalink instance (redundant due to cog init check, but safe)
        if not hasattr(self.bot, 'lavalink') or not self.lavalink:
            logger.error("Interaction check failed: Bot has no lavalink instance.")
            await interaction.response.send_message("Music service is not available.", ephemeral=True)
            return False
        return True

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        original = getattr(error, 'original', error)
        command_name = interaction.command.name if interaction.command else 'unknown'
        logger.error(f"Error in slash command '{command_name}': {original.__class__.__name__}: {original}", exc_info=original)

        error_message = f"An unexpected error occurred while running `/{command_name}`."

        # Handle specific, known error types first
        if isinstance(original, app_commands.CheckFailure):
             # Specific check failures might have custom messages
             error_message = str(original)
             logger.warning(f"Check failure for command '{command_name}': {original}")
        elif isinstance(original, app_commands.CommandNotFound): # Should not happen with slash usually
             error_message = f"Command `/{command_name}` not found."
             logger.warning(f"CommandNotFound error for slash command: {command_name}")
        elif isinstance(original, app_commands.MissingPermissions):
             error_message = f"You lack the required permissions: {', '.join(original.missing_permissions)}"
             logger.warning(f"Missing Permissions for {command_name}: {original.missing_permissions}")
        elif isinstance(original, app_commands.BotMissingPermissions):
             error_message = f"I lack the required permissions: {', '.join(original.missing_permissions)}"
             logger.warning(f"Bot Missing Permissions for {command_name}: {original.missing_permissions}")
        elif isinstance(original, lavalink.errors.AuthenticationError):
             error_message = "Lavalink authentication failed. Please check the server configuration."
        elif isinstance(original, lavalink.errors.RequestError):
             error_message = f"Error communicating with the music service node: {original}"
        # Handle the original NameError from previous debugging if it somehow reappears
        elif isinstance(original, NameError) and 'os' in str(original):
            error_message = "Internal bot configuration error (missing import)."
            logger.error("Critical NameError related to 'os' caught - ensure 'import os' is present in music.py")
        # Add more specific error handlers here as needed

        # Fallback for generic errors logged above
        # else: error_message = f"An unexpected error occurred: {original.__class__.__name__}"

        # Try sending the error message
        try:
            if interaction.response.is_done():
                await interaction.followup.send(f"❌ {error_message}", ephemeral=True)
            else:
                await interaction.response.send_message(f"❌ {error_message}", ephemeral=True)
        except discord.HTTPException as e:
             logger.error(f"Failed to send error message for command '{command_name}': {e}")

    # --- Slash Commands ---

    @app_commands.command(name="play", description="Plays a song/playlist or adds it to the queue (YouTube, SoundCloud, Spotify).")
    @app_commands.describe(query='URL (YouTube, SoundCloud, Spotify) or search term (defaults to YouTube search)')
    async def play(self, interaction: discord.Interaction, *, query: str):

        # Ensure user is in a voice channel
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message("You need to be in a voice channel to play music.", ephemeral=True)
        user_channel = interaction.user.voice.channel

        # Use get_or_create for robustness
        player: DefaultPlayer = self.lavalink.player_manager.create(interaction.guild_id)

        # Check node availability AFTER ensuring a player object exists conceptually
        if not self.lavalink.node_manager.available_nodes:
             logger.error(f"Play command failed for Guild {interaction.guild_id}: No available Lavalink nodes.")
             # We created a player object, but can't connect, destroy it.
             await self._safe_destroy_player(interaction.guild_id)
             return await interaction.response.send_message("Music service node is currently unavailable. Please try again later.", ephemeral=True)

        # Set default volume if player was just created (or ensure it's set)
        # This check might be better placed after connection? But safe here too.
        if not player.volume == int(os.getenv('DEFAULT_VOLUME', 100)): # Only set if not default
             try:
                 default_vol = int(os.getenv('DEFAULT_VOLUME', 100))
                 await player.set_volume(default_vol)
                 logger.info(f"Set volume to {default_vol} for Guild {interaction.guild_id}")
             except ValueError:
                 logger.error(f"Invalid DEFAULT_VOLUME in config: {os.getenv('DEFAULT_VOLUME')}")
             except Exception as e:
                 logger.error(f"Error setting volume for Guild {interaction.guild_id}: {e}", exc_info=True)

        # Connect or check channel consistency
        vc = interaction.guild.voice_client
        should_connect = False
        if not vc:
            should_connect = True
        elif vc.channel.id != user_channel.id:
            # If connected to a different channel, move or inform user
             logger.info(f"Bot is in channel {vc.channel.name}, user is in {user_channel.name}. Moving bot.")
             # TODO: Decide if you want to allow moving or require user to join bot's channel
             # Option 1: Move the bot
             # permissions = user_channel.permissions_for(interaction.guild.me)
             # if not permissions.connect or not permissions.speak:
             #     return await interaction.response.send_message("I need permissions to `Connect` and `Speak` in your target voice channel.", ephemeral=True)
             # await vc.move_to(user_channel)
             # player.store('channel', interaction.channel.id) # Update text channel link
             # await interaction.response.defer(thinking=True)

             # Option 2: Tell user to join bot
             return await interaction.response.send_message(f"You need to be in the same voice channel as the bot (<#{vc.channel.id}>).", ephemeral=True)

        # If not connected, attempt connection
        if should_connect:
             permissions = user_channel.permissions_for(interaction.guild.me)
             if not permissions.connect or not permissions.speak:
                 await self._safe_destroy_player(interaction.guild_id) # Clean up player if cannot connect
                 return await interaction.response.send_message("I need permissions to `Connect` and `Speak` in your voice channel.", ephemeral=True)

             logger.info(f"Connecting to voice channel {user_channel.name} in Guild {interaction.guild_id}")
             player.store('channel', interaction.channel.id) # Store text channel ID for messages
             try:
                 await user_channel.connect(cls=LavalinkVoiceClient, self_deaf=True) # Connect and self-deafen
                 await interaction.response.defer(thinking=True, ephemeral=False) # Defer publicly after successful connection request
             except Exception as e:
                 logger.error(f"Failed to connect to voice channel {user_channel.id}: {e}", exc_info=True)
                 await self._safe_destroy_player(interaction.guild_id) # Clean up player on connection failure
                 await interaction.response.send_message(f"Failed to connect to the voice channel: {e}", ephemeral=True)
                 return
        else:
             # Already connected and in the same channel
             await interaction.response.defer(thinking=True) # Defer privately


        # Get tracks from Lavalink
        try:
            search_query = query.strip('<>')
            load_type_log = "query"

            # --- Determine search type ---
            if URL_REGEX.match(search_query):
                if SPOTIFY_REGEX.match(search_query): load_type_log = "Spotify URL"
                elif SOUNDCLOUD_REGEX.match(search_query): load_type_log = "SoundCloud URL"
                else: load_type_log = "Generic URL"
                # No prefix needed for URLs
            else:
                search_query = f"ytsearch:{search_query}" # Default to YouTube search
                load_type_log = "YouTube Search"

            logger.info(f"[{interaction.guild.name}] Getting tracks for: '{search_query}' ({load_type_log})")
            results: LoadResult = await player.node.get_tracks(search_query)
            logger.debug(f"LoadResult: Type={results.load_type}, Playlist={results.playlist_info}, Tracks={len(results.tracks)}")

            # --- Validate results using correct enum names (VERIFIED CORRECT) ---
            if results.load_type == LoadType.ERROR:
                 error_cause = getattr(results, 'cause', "Unknown Lavalink error") # Safely get cause
                 # More user-friendly message for common errors if possible
                 if "Unknown file format" in error_cause:
                      error_message = "Failed to load track (Unknown Format). This might be a temporary YouTube issue."
                 elif "Something went wrong" in error_cause:
                      error_message = "Something went wrong while looking up the track. Try again later."
                 else:
                      error_message = f"Failed to load tracks: {error_cause}"
                 logger.warning(f"{error_message} (Query: {search_query})")
                 # Use followup since we deferred
                 await interaction.followup.send(f"❌ {error_message}", ephemeral=True)
                 return
            elif results.load_type == LoadType.EMPTY or not results.tracks:
                 message = f"Could not find any results for `{query}`."
                 logger.warning(f"{message} (Query: {search_query}, LoadType: {results.load_type})")
                 await interaction.followup.send(message, ephemeral=True)
                 return

            # Enforce Queue Size Limit
            current_queue_size = len(player.queue)
            max_queue = int(os.getenv('MAX_QUEUE_SIZE', 1000)) # Read from env

            added_count = 0
            skipped_count = 0
            tracks_to_add = []
            followup_message = ""

            # --- Process results using correct enum names (VERIFIED CORRECT) ---
            if results.load_type == LoadType.PLAYLIST:
                playlist_name = getattr(results.playlist_info, 'name', "Unnamed Playlist") or "Unnamed Playlist" # Safer access
                max_playlist = int(os.getenv('MAX_PLAYLIST_SIZE', 100)) # Read from env

                tracks_to_consider = results.tracks[:max_playlist] # Apply playlist limit first

                for track in tracks_to_consider:
                    if current_queue_size + added_count < max_queue:
                        tracks_to_add.append(track)
                        added_count += 1
                    else: skipped_count += 1

                followup_message = f"✅ Added **{added_count}** tracks from playlist **`{discord.utils.escape_markdown(playlist_name)}`**."
                if len(results.tracks) > max_playlist: followup_message += f" (Playlist capped at {max_playlist})"
                if skipped_count > 0: followup_message += f" (Queue full, skipped {skipped_count})"
                logger.info(f"Adding {added_count}/{len(tracks_to_consider)} tracks from playlist '{playlist_name}' for {interaction.user}. Skipped {skipped_count}.")

            elif results.load_type in [LoadType.TRACK, LoadType.SEARCH]:
                track = results.tracks[0]
                if current_queue_size < max_queue:
                     tracks_to_add.append(track)
                     followup_message = f"✅ Added **`{discord.utils.escape_markdown(track.title)}`** to the queue."
                     logger.info(f"Adding track '{track.title}' for {interaction.user} (LoadType: {results.load_type})")
                else:
                     followup_message = f"❌ Queue is full (Max: {max_queue}). Could not add **`{discord.utils.escape_markdown(track.title)}`**."
                     logger.warning(f"Queue full. Skipped track '{track.title}' for {interaction.user}")

            else:
                # Fallback for any unexpected load types
                logger.warning(f"Unhandled LoadType '{results.load_type}' for query '{search_query}'")
                await interaction.followup.send(f"Received an unexpected result type ({results.load_type}). Cannot process.", ephemeral=True)
                return # Stop processing if type is unknown


            # Add tracks to the queue
            for track in tracks_to_add:
                 player.add(requester=interaction.user.id, track=track)

            # Send confirmation using followup
            await interaction.followup.send(followup_message)

            # Start playback if not already playing
            if not player.is_playing:
                logger.info(f"Player not playing, starting playback for Guild {interaction.guild_id}")
                await player.play()

        # Catch potential operational errors during get_tracks or play
        except lavalink.errors.RequestError as e:
             logger.error(f"Lavalink RequestError in play command: {e}", exc_info=True)
             try: await interaction.followup.send(f"Error communicating with Lavalink node: {e}", ephemeral=True)
             except discord.NotFound: pass # Interaction might be gone
        except Exception as e:
            message = f"An unexpected error occurred processing your request." # Don't expose raw error
            logger.exception(f"Unexpected error in play command for query '{query}': {e}")
            try: await interaction.followup.send(f"❌ {message}", ephemeral=True)
            except discord.NotFound: pass # Interaction might be gone


    @app_commands.command(name="disconnect", description="Disconnects the bot from the voice channel.")
    async def disconnect(self, interaction: discord.Interaction):
        player = self.lavalink.player_manager.get(interaction.guild_id)
        vc = interaction.guild.voice_client

        if not vc:
            return await interaction.response.send_message("Not connected to any voice channel.", ephemeral=True)

        logger.info(f"Disconnect command initiated by {interaction.user} in Guild {interaction.guild_id}")
        # Stop player and clear queue BEFORE disconnecting voice client
        if player:
            player.queue.clear()
            await player.stop()
            # Cancel inactivity timer if running
            if interaction.guild_id in self.inactivity_timers:
                self.inactivity_timers[interaction.guild_id].cancel()

        await vc.disconnect(force=False) # Let events handle player destruction
        await interaction.response.send_message("Disconnected and cleared queue.")


    @app_commands.command(name="stop", description="Stops the music and clears the queue.")
    async def stop(self, interaction: discord.Interaction):
        player = self.lavalink.player_manager.get(interaction.guild_id)

        if not player or not interaction.guild.voice_client:
            return await interaction.response.send_message("Not currently playing anything.", ephemeral=True)

        # Check if playing or queue has items
        if not player.is_playing and not player.queue:
             return await interaction.response.send_message("Nothing is playing and the queue is empty.", ephemeral=True)

        logger.info(f"Stop command initiated by {interaction.user} in Guild {interaction.guild_id}")
        player.queue.clear()
        await player.stop() # This should trigger track end/queue end events

        # Schedule inactivity check after stopping
        self._schedule_inactivity_check(interaction.guild_id)

        await interaction.response.send_message("⏹️ Music stopped and queue cleared.")


    @app_commands.command(name="skip", description="Skips the current song.")
    async def skip(self, interaction: discord.Interaction):
        player = self.lavalink.player_manager.get(interaction.guild_id)

        if not player or not player.current: # Check if there's actually a current track
            return await interaction.response.send_message("No song is currently playing to skip.", ephemeral=True)

        current_title = player.current.title if player.current else "Unknown Track"
        logger.info(f"Skip command initiated by {interaction.user} for track '{current_title}' in Guild {interaction.guild_id}")

        await player.skip()
        # Skip message will be sent immediately. TrackEnd/TrackStart events handle state changes.
        skipped_msg = f"⏭️ Skipped **`{discord.utils.escape_markdown(current_title)}`**."

        # Check if queue is empty *after* skip (small delay might be needed, but usually event handles this)
        # await asyncio.sleep(0.1) # Optional small delay
        # player = self.lavalink.player_manager.get(interaction.guild_id) # Re-fetch? Maybe not needed.
        # if not player or (not player.is_playing and not player.queue):
        #      skipped_msg += "\nQueue is now empty."

        await interaction.response.send_message(skipped_msg)


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

        # Check if player exists and is paused
        if not player or not player.paused:
            # Also check if a song is loaded, otherwise resume does nothing
            if not player or not player.current:
                 return await interaction.response.send_message("Nothing is loaded to resume.", ephemeral=True)
            else: # Player exists, has track, but isn't paused
                 return await interaction.response.send_message("Music is not paused.", ephemeral=True)


        logger.info(f"Resume command initiated by {interaction.user} in Guild {interaction.guild_id}")
        await player.set_pause(False)
        await interaction.response.send_message("▶️ Music resumed.")

    @app_commands.command(name="loop", description="Toggles looping for the current track.")
    async def loop(self, interaction: discord.Interaction):
        player = self.lavalink.player_manager.get(interaction.guild_id)

        if not player or not player.current:
            return await interaction.response.send_message("No song is currently playing to loop.", ephemeral=True)

        # Lavalink library uses 'repeat' property (bool) for single track loop
        player.repeat = not player.repeat # Toggles boolean value
        mode = "ON" if player.repeat else "OFF"
        logger.info(f"Loop command initiated by {interaction.user}. Loop set to {mode} for Guild {interaction.guild_id}")
        await interaction.response.send_message(f"🔂 Loop mode for the current track set to **{mode}**.")
        # Note: Queue looping usually requires custom logic beyond player.repeat


    @app_commands.command(name="shuffle", description="Shuffles the current queue.")
    async def shuffle(self, interaction: discord.Interaction):
        player = self.lavalink.player_manager.get(interaction.guild_id)

        if not player or len(player.queue) < 2:
            return await interaction.response.send_message("The queue needs at least 2 songs to shuffle.", ephemeral=True)

        logger.info(f"Shuffle command initiated by {interaction.user} in Guild {interaction.guild_id}")
        player.set_shuffle(not player.shuffle) # Toggle shuffle state
        shuffle_state = "enabled" if player.shuffle else "disabled"
        await interaction.response.send_message(f"🔀 Queue shuffle {shuffle_state}.")


    @app_commands.command(name="queue", description="Displays the current song queue.")
    @app_commands.describe(page="Page number of the queue to display")
    async def queue(self, interaction: discord.Interaction, page: app_commands.Range[int, 1] = 1):
        player = self.lavalink.player_manager.get(interaction.guild_id)

        embed = discord.Embed(title="Music Queue", color=discord.Color.blue())

        current_track_info = "*Nothing currently playing.*"
        if player and player.current and isinstance(player.current, AudioTrack):
             title = discord.utils.escape_markdown(player.current.title)
             duration = format_duration(player.current.duration)
             uri = player.current.uri
             requester = f"<@{player.current.requester}>" if player.current.requester else "Unknown"
             current_track_info = f"**`[{duration}]`** [{title}]({uri}) - {requester}"
             if player.current.artwork_url:
                 embed.set_thumbnail(url=player.current.artwork_url)

        embed.add_field(name="Currently Playing", value=current_track_info, inline=False)


        if not player or not player.queue:
            embed.add_field(name="Up Next", value="*The queue is empty.*", inline=False)
            embed.set_footer(text="0 songs in queue | Page 1/1")
        else:
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
            if not current_page_items:
                 queue_display = "*No tracks on this page.*"
            else:
                for i, track in enumerate(current_page_items, start=start_index + 1):
                    if isinstance(track, AudioTrack):
                         title = discord.utils.escape_markdown(track.title)
                         duration = format_duration(track.duration)
                         uri = track.uri
                         requester = f"<@{track.requester}>" if track.requester else "Unknown"
                         queue_display += f"**{i}.** `[{duration}]` [{title}]({uri}) - {requester}\n"
                    else:
                         logger.warning(f"Item in queue {i} is not an AudioTrack instance: {track}")
                         queue_display += f"**{i}.** *Invalid track data*\n"

            embed.add_field(name=f"Up Next (Page {page}/{total_pages})", value=queue_display, inline=False)

            queue_duration_ms = sum(t.duration for t in queue_list if isinstance(t, AudioTrack) and t.duration is not None)
            total_duration_str = format_duration(queue_duration_ms)
            embed.set_footer(text=f"{total_items} songs in queue | Total duration: {total_duration_str} | Page {page}/{total_pages}")

        await interaction.response.send_message(embed=embed)


    @app_commands.command(name="lowpass", description="Applies a low-pass filter (bass boost effect).")
    @app_commands.describe(strength="Filter strength (0.0 to disable, recommended 1.0-20.0)")
    async def lowpass(self, interaction: discord.Interaction, strength: app_commands.Range[float, 0.0, 100.0]):
        player = self.lavalink.player_manager.get(interaction.guild_id)

        if not player:
             return await interaction.response.send_message("Bot is not connected or playing.", ephemeral=True)

        # Ensure strength is within reasonable bounds, although Range does this
        strength = max(0.0, min(100.0, strength))

        embed = discord.Embed(color=discord.Color.blurple(), title='Low Pass Filter')

        try:
            # Use the Filter factory to create/modify filters
            # To reset, apply a new default Filter() object
            # To disable just lowpass but keep others, fetch existing, modify, set
            # For simplicity, this example sets *only* lowpass or resets all filters.
            if strength <= 0.0: # Use <= 0.0 for disabling
                # Reset all filters by applying an empty Filter object
                await player.set_filters(lavalink.Filter())
                embed.description = 'Disabled **Low Pass Filter** (All filters reset).'
                logger.info(f"Resetting filters for Guild {interaction.guild_id}")
            else:
                # Create a new filter object specifically for LowPass
                # Note: This will overwrite any other filters currently applied.
                # If you need to combine filters, fetch existing filters, modify, and set.
                low_pass_filter = lavalink.Filter(low_pass=lavalink.LowPass(smoothing=strength))
                await player.set_filters(low_pass_filter)
                embed.description = f'Set **Low Pass Filter** smoothing to `{strength:.2f}` (Other filters may be overwritten).'
                logger.info(f"Set LowPass filter (strength {strength:.2f}) for Guild {interaction.guild_id}")

            await interaction.response.send_message(embed=embed)

        except Exception as e:
              logger.exception(f"Unexpected error applying filter: {e}")
              await interaction.response.send_message(f"An unexpected error occurred while applying the filter: {e}", ephemeral=True)


async def setup(bot: commands.Bot):
    # Wait for Lavalink to be initialized (ensure this runs *after* bot.lavalink is set in on_ready)
    # This check might be less critical if load_extensions is always called after bot.lavalink exists
    max_attempts = 10
    attempt = 0
    while not hasattr(bot, 'lavalink') or not isinstance(bot.lavalink, lavalink.Client):
        if attempt >= max_attempts:
            logger.error("Music cog setup: Lavalink client not initialized after maximum attempts. Cog may fail.")
            # Raise an error to prevent loading if Lavalink isn't ready
            raise commands.ExtensionFailed("Music", NameError("Lavalink client not available during setup"))
        logger.info(f"Music cog setup: Waiting for Lavalink initialization... (Attempt {attempt + 1}/{max_attempts})")
        await asyncio.sleep(1)
        attempt += 1

    # Lavalink seems ready, add the cog
    await bot.add_cog(Music(bot))
    logger.info("Music Cog loaded.")
# --- END OF FILE cogs/music.py ---