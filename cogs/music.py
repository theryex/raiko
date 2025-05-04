# --- START OF FILE cogs/music.py ---
import discord
from discord import app_commands
from discord.ext import commands
# --- LAVAPLAY Imports ---
try:
    import lavaplay
    # Import specific types needed
    from lavaplay import player, Track, PlayList, TrackLoadFailed, Filters
    from lavaplay.events import ReadyEvent, TrackStartEvent, TrackEndEvent, TrackExceptionEvent, TrackStuckEvent, WebSocketClosedEvent
except ImportError:
    # This allows loading other cogs even if lavaplay isn't installed,
    # but this cog itself will fail to load properly later in setup.
    raise ImportError("import error")
# --- End LAVAPLAY Imports ---

# --- Voice Client Import ---
# Assumes voice_client.py is in the root directory relative to where bot.py runs
try:
    from voice_client import LavalinkVoiceClient
except ImportError:
    # Handle case where voice_client.py might be missing or not in path
    raise ImportError("Could not import LavalinkVoiceClient from voice_client.py. Ensure the file exists in the root directory.")
# --- End Voice Client Import ---

import logging
import re
import math
import asyncio
from typing import Optional, cast, Union # Union for track types

# Basic URL pattern (same as before)
URL_REGEX = re.compile(r'https?://(?:www\.)?.+')
SOUNDCLOUD_REGEX = re.compile(r'https?://(?:www\.)?soundcloud\.com/')
SPOTIFY_REGEX = re.compile(r'https?://(?:open|play)\.spotify\.com/')

logger = logging.getLogger(__name__) # Use logger

# --- Helper Functions ---
def format_duration(milliseconds: Optional[Union[int, float]]) -> str: # Allow float too
    """Formats milliseconds into HH:MM:SS or MM:SS."""
    if milliseconds is None:
        return "N/A"
    try:
        # lavaplay duration can be float
        ms = int(float(milliseconds))
    except (ValueError, TypeError):
        return "N/A"

    if ms <= 0:
        return "00:00"

    seconds = math.floor(ms / 1000)
    minutes = math.floor(seconds / 60)
    hours = math.floor(minutes / 60)

    if hours > 0:
        return f"{hours:02d}:{minutes % 60:02d}:{seconds % 60:02d}"
    else:
        return f"{minutes:02d}:{seconds % 60:02d}"

# --- Music Cog ---
class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Ensure Lavalink node is ready (it should be from bot.py's setup_hook)
        if not hasattr(bot, 'lavalink_node') or bot.lavalink_node is None:
            logger.critical("Lavalink node ('lavalink_node') not found on bot instance in Music Cog init!")
            raise commands.ExtensionFailed("Music Cog", NameError("Lavalink node not found on bot instance"))

        self.lavalink_node: lavaplay.Node = self.bot.lavalink_node
        self.inactivity_timers: dict[int, asyncio.Task] = {} # Store inactivity tasks per guild

        # --- Register Lavaplay Listeners for this Cog ---
        # Using the node instance directly as a decorator source
        self.lavalink_node.event_manager.add_listener(TrackStartEvent, self.on_track_start)
        self.lavalink_node.event_manager.add_listener(TrackEndEvent, self.on_track_end)
        self.lavalink_node.event_manager.add_listener(TrackExceptionEvent, self.on_track_exception)
        self.lavalink_node.event_manager.add_listener(TrackStuckEvent, self.on_track_stuck)
        # Note: PlayerErrorEvent doesn't seem to exist in lavaplay. TrackException covers most cases.
        # Note: WebSocketClosedEvent is handled globally in bot.py

    def cog_unload(self):
        """ Cog cleanup """
        # Cancel any running inactivity timers
        for task in self.inactivity_timers.values():
            task.cancel()
        self.inactivity_timers.clear()
        # Remove listeners specific to this cog instance
        # This requires storing the listener refs or iterating if using decorators isn't feasible
        # For simplicity with add_listener, we might skip removal or handle it more robustly if needed.
        # Example (if listeners were stored):
        # self.lavalink_node.event_manager.remove_listener(TrackStartEvent, self.on_track_start)
        # ... and so on for others added in __init__
        logger.info("Music Cog unloaded, inactivity timers cancelled.")


    # --- Event Handlers ---

    async def on_track_start(self, event: TrackStartEvent):
        player = event.player
        guild_id = event.guild_id # Use guild_id from event

        # Cancel existing inactivity timer
        if guild_id in self.inactivity_timers:
            self.inactivity_timers[guild_id].cancel()
            del self.inactivity_timers[guild_id]
            logger.info(f"Cancelled inactivity timer for Guild {guild_id} due to track start.")

        guild = self.bot.get_guild(guild_id)
        track_title = getattr(event.track, 'title', 'Unknown Title')
        logger.info(f"Track started on Guild {guild_id}: {track_title}")

        # Fetch the channel ID stored on the player (if we stored it)
        channel_id = player.fetch('channel_id') # Use fetch method if you store custom data
        if channel_id and guild:
            channel = guild.get_channel(channel_id)
            if channel and isinstance(channel, discord.TextChannel):
                # Create and send 'Now Playing' embed
                track = event.track
                title = discord.utils.escape_markdown(track.title or "Unknown Title")
                uri = track.uri or "#"
                author = discord.utils.escape_markdown(track.author or "Unknown Author")
                duration_ms = track.length # lavaplay uses 'length'
                requester_id = track.requester # lavaplay stores requester ID directly

                desc = f"[{title}]({uri})\n"
                desc += f"Author: {author}\n"
                desc += f"Duration: {format_duration(duration_ms)}\n"
                if requester_id:
                    desc += f"Requested by: <@{requester_id}>"

                embed = discord.Embed(
                    color=discord.Color.green(),
                    title="Now Playing",
                    description=desc
                )
                # lavaplay doesn't directly expose artwork_url in Track? Check if available via source specifics if needed
                # Example: if track.source == "youtube" and hasattr(track, 'identifier'):
                #    embed.set_thumbnail(url=f"https://img.youtube.com/vi/{track.identifier}/mqdefault.jpg")
                # Need to investigate best way to get thumbnails with lavaplay + plugins

                try:
                    await channel.send(embed=embed)
                except discord.errors.Forbidden:
                     logger.warning(f"Missing permissions to send 'Now Playing' message in channel {channel_id} (Guild {guild_id})")
                except discord.HTTPException as e:
                    logger.warning(f"Failed to send 'Now Playing' message to channel {channel_id}: {e}")
            else:
                 logger.warning(f"Could not find text channel {channel_id} for Guild {guild_id} to send 'Now Playing' message.")
        else:
            logger.debug(f"Could not fetch text channel ID or guild for Guild {guild_id} on TrackStartEvent.")



    def _schedule_inactivity_check(self, guild_id: int):
        """Schedules the inactivity check task."""
        if guild_id in self.inactivity_timers:
            self.inactivity_timers[guild_id].cancel()

        disconnect_delay = 60 # Seconds
        logger.info(f"Queue ended or player stopped, starting {disconnect_delay}s disconnect timer for Guild {guild_id}")
        task = asyncio.create_task(self._check_inactivity(guild_id, disconnect_delay))
        self.inactivity_timers[guild_id] = task
        task.add_done_callback(lambda t: self.inactivity_timers.pop(guild_id, None))

    async def _check_inactivity(self, guild_id: int, delay: int):
        """Checks if the player is inactive after a delay and disconnects."""
        await asyncio.sleep(delay)

        player = self.lavalink_node.get_player(guild_id)
        guild = self.bot.get_guild(guild_id)

        # Check again if player exists, is connected, not playing, and queue is empty
        # lavaplay player state checks: player.is_playing, player.is_paused, player.is_connected, player.queue
        if player and player.is_connected and not player.is_playing and not player.queue:
             if guild and guild.voice_client:
                 logger.info(f"Disconnect timer finished, disconnecting inactive voice client for Guild {guild_id}")
                 await guild.voice_client.disconnect(force=True) # force=True helps ensure cleanup
                 # Player destruction should be handled by the disconnect method of our voice client
             elif player:
                  logger.warning(f"Disconnect timer finished for Guild {guild_id}, but no active discord.py voice client found. Attempting manual player destroy.")
                  await player.destroy() # Manually destroy if voice client is gone somehow
        else:
            status = "playing" if player and player.is_playing else \
                     "paused" if player and player.is_paused else \
                     "queue has items" if player and player.queue else \
                     "already disconnected" if not player or not player.is_connected else \
                     "unknown state"
            logger.info(f"Inactivity check for Guild {guild_id}: Player is {status}, cancelling auto-disconnect.")


    async def on_track_end(self, event: TrackEndEvent):
        player = event.player
        guild_id = event.guild_id
        reason = event.reason
        logger.info(f"Track ended on Guild {guild_id}. Reason: {reason}. Current queue size: {len(player.queue)}")

        # Only schedule inactivity if the queue ended naturally and the queue is now empty
        # lavaplay reasons: 'FINISHED', 'LOAD_FAILED', 'STOPPED', 'REPLACED', 'CLEANUP'
        if reason == 'FINISHED' and not player.queue:
             self._schedule_inactivity_check(guild_id)
        # Handle other reasons if needed (e.g., announce load failures)


    async def on_track_exception(self, event: TrackExceptionEvent):
        player = event.player
        guild_id = event.guild_id
        exception_details = event.exception # Contains message, severity, cause
        logger.error(f"Track Exception on Guild {guild_id}: {exception_details}", exc_info=False) # Don't need full traceback usually

        channel_id = player.fetch('channel_id') # Get stored text channel
        guild = self.bot.get_guild(guild_id)
        if channel_id and guild:
            channel = guild.get_channel(channel_id)
            if channel and isinstance(channel, discord.TextChannel):
                track_title = getattr(event.track, 'title', 'the track')
                error_msg = exception_details.get('message', 'Unknown playback error')
                severity = exception_details.get('severity', 'UNKNOWN')
                try:
                    await channel.send(f"💥 Error playing `{discord.utils.escape_markdown(track_title)}` (Severity: {severity}): {error_msg}")
                except discord.HTTPException:
                    pass
        # Optionally skip to the next track automatically on exceptions
        # await player.skip()


    async def on_track_stuck(self, event: TrackStuckEvent):
        player = event.player
        guild_id = event.guild_id
        threshold = event.threshold_ms
        logger.warning(f"Track Stuck on Guild {guild_id} (Threshold: {threshold}ms): {getattr(event.track, 'title', 'Unknown Title')}")

        channel_id = player.fetch('channel_id')
        guild = self.bot.get_guild(guild_id)
        if channel_id and guild:
            channel = guild.get_channel(channel_id)
            if channel and isinstance(channel, discord.TextChannel):
                track_title = getattr(event.track, 'title', 'the track')
                try:
                    await channel.send(f"⚠️ Track `{discord.utils.escape_markdown(track_title)}` seems stuck (>{threshold}ms), skipping...")
                except discord.HTTPException:
                     pass
        # Skip the stuck track
        await player.skip()


    # --- Cog Checks (same as before) ---
    async def cog_before_invoke(self, ctx: commands.Context):
        if not ctx.guild:
            raise commands.NoPrivateMessage("This command can't be used in DMs.")
        return True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            await interaction.response.send_message("This command can only be used in a server!", ephemeral=True)
            return False
        # Check if lavalink node is available
        if not hasattr(self.bot, 'lavalink_node') or not self.lavalink_node or not self.lavalink_node.stats:
            logger.error("Interaction check failed: Bot has no lavalink node or node is not connected.")
            await interaction.response.send_message("Music service is not available or not connected.", ephemeral=True)
            return False
        return True

    # --- App Command Error Handler (Mostly same, adjust specific errors if needed) ---
    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        original = getattr(error, 'original', error)
        command_name = interaction.command.name if interaction.command else 'unknown'
        logger.error(f"Error in slash command '{command_name}': {original.__class__.__name__}: {original}", exc_info=original)

        error_message = f"An unexpected error occurred while running `/{command_name}`."

        # Handle specific discord.py errors
        if isinstance(original, app_commands.CheckFailure):
             error_message = str(original)
        elif isinstance(original, app_commands.MissingPermissions):
             error_message = f"You lack the required permissions: {', '.join(original.missing_permissions)}"
        elif isinstance(original, app_commands.BotMissingPermissions):
             error_message = f"I lack the required permissions: {', '.join(original.missing_permissions)}"
        # Handle potential lavaplay errors (though TrackLoadFailed is handled in play)
        # Example: Catching a generic lavaplay error if one were to bubble up
        elif isinstance(original, lavaplay.LavalinkException):
             error_message = f"Music service error: {original}"
        elif isinstance(original, NameError) and 'LavalinkVoiceClient' in str(original):
             error_message = "Internal setup error: Could not find the voice client."
             logger.critical("NameError finding LavalinkVoiceClient - check import in music.py")
        elif isinstance(original, AttributeError) and 'lavalink_node' in str(original):
             error_message = "Internal setup error: Music service node not found on bot."
             logger.critical("AttributeError: lavalink_node not found - check bot.py setup_hook")


        try:
            if interaction.response.is_done():
                await interaction.followup.send(f"❌ {error_message}", ephemeral=True)
            else:
                await interaction.response.send_message(f"❌ {error_message}", ephemeral=True)
        except discord.HTTPException as e:
             logger.error(f"Failed to send error message for command '{command_name}': {e}")


    # --- Slash Commands ---

    @app_commands.command(name="play", description="Plays a song/playlist or adds it to the queue (YT, SC, Spotify supported by Lavalink).")
    @app_commands.describe(query='URL (YouTube, SoundCloud, Spotify...) or search term')
    async def play(self, interaction: discord.Interaction, *, query: str):
        # 1. Ensure user is in VC
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message("You need to be in a voice channel to play music.", ephemeral=True)
        user_channel = interaction.user.voice.channel

        # 2. Get or create Lavalink player
        player = self.lavalink_node.get_player(interaction.guild_id)
        if not player:
            player = self.lavalink_node.create_player(interaction.guild_id)
            logger.info(f"Created lavaplay player for Guild {interaction.guild_id}")

        # 3. Check node availability (redundant due to interaction_check, but safe)
        if not self.lavalink_node.stats:
             logger.error(f"Play command failed for Guild {interaction.guild_id}: No available Lavalink nodes.")
             return await interaction.response.send_message("Music service node is currently unavailable.", ephemeral=True)

        # 4. Connect or Ensure Correct Channel
        vc = interaction.guild.voice_client
        if not vc:
            # Not connected, connect now
            permissions = user_channel.permissions_for(interaction.guild.me)
            if not permissions.connect or not permissions.speak:
                await player.destroy() # Clean up player if cannot connect
                return await interaction.response.send_message("I need permissions to `Connect` and `Speak` in your voice channel.", ephemeral=True)

            logger.info(f"Connecting to voice channel {user_channel.name} in Guild {interaction.guild_id}")
            player.store('channel_id', interaction.channel.id) # Store text channel ID for messages
            try:
                # Use the custom LavalinkVoiceClient for connection
                await user_channel.connect(cls=LavalinkVoiceClient, self_deaf=True, timeout=60.0)
                await interaction.response.defer(thinking=True, ephemeral=False) # Defer publicly after connection starts
            except asyncio.TimeoutError:
                logger.error(f"Timeout connecting to voice channel {user_channel.id}")
                await player.destroy()
                await interaction.response.send_message("Timed out connecting to the voice channel.", ephemeral=True)
                return
            except Exception as e:
                logger.error(f"Failed to connect to voice channel {user_channel.id}: {e}", exc_info=True)
                await player.destroy()
                # Try to send message even if deferred
                followup = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
                await followup(f"Failed to connect to the voice channel: {e}", ephemeral=True)
                return
        elif vc.channel.id != user_channel.id:
            # Connected to a different channel
             return await interaction.response.send_message(f"You need to be in the same voice channel as the bot (<#{vc.channel.id}>).", ephemeral=True)
        else:
            # Already connected to the right channel
            await interaction.response.defer(thinking=True) # Defer privately

        # 5. Search for Tracks using lavaplay
        try:
            search_query = query.strip('<>')
            logger.info(f"[{interaction.guild.name}] Getting tracks for: '{search_query}'")

            # Use auto_search_tracks - it handles URLs and searches (ytsearch:, scsearch:)
            results = await self.lavalink_node.auto_search_tracks(search_query)
            # Optional: Log result type for debugging
            # logger.debug(f"LoadResult Type: {type(results)}")

            # --- Validate results ---
            if isinstance(results, TrackLoadFailed):
                 error_message = f"Failed to load track/playlist: {results.message}"
                 logger.warning(f"{error_message} (Query: {search_query}, Severity: {results.severity})")
                 await interaction.followup.send(f"❌ {error_message}", ephemeral=True)
                 return
            elif not results or (isinstance(results, list) and not results): # Handle empty list or None
                 message = f"Could not find any results for `{query}`."
                 logger.warning(f"{message} (Query: {search_query})")
                 await interaction.followup.send(message, ephemeral=True)
                 return

            # --- Enforce Queue Limits ---
            current_queue_size = len(player.queue)
            max_queue = int(os.getenv('MAX_QUEUE_SIZE', 1000))
            max_playlist = int(os.getenv('MAX_PLAYLIST_SIZE', 100))

            added_count = 0
            skipped_count = 0
            followup_message = ""
            track_to_play_now = None

            # --- Process results ---
            if isinstance(results, PlayList):
                playlist_name = results.name or "Unnamed Playlist"
                tracks_to_consider = results.tracks[:max_playlist] # Apply playlist limit

                tracks_to_add_to_queue = []
                for track in tracks_to_consider:
                    if current_queue_size + added_count < max_queue:
                        tracks_to_add_to_queue.append(track)
                        added_count += 1
                    else:
                        skipped_count += 1

                if tracks_to_add_to_queue:
                     # Add tracks to lavaplay queue
                     player.add_to_queue(tracks_to_add_to_queue, requester=interaction.user.id)
                     if not player.is_playing:
                          # If not playing, the first track added will be played automatically by play_playlist
                          # We don't need to manually set track_to_play_now here if using play_playlist
                          pass

                followup_message = f"✅ Added **{added_count}** tracks from playlist **`{discord.utils.escape_markdown(playlist_name)}`**."
                if len(results.tracks) > max_playlist: followup_message += f" (Playlist capped at {max_playlist})"
                if skipped_count > 0: followup_message += f" (Queue full, skipped {skipped_count})"
                logger.info(f"Adding {added_count}/{len(tracks_to_consider)} tracks from playlist '{playlist_name}' for {interaction.user}. Skipped {skipped_count}.")

                # Start playback if not playing and tracks were added
                if not player.is_playing and added_count > 0:
                    # Use play_playlist if you want Lavalink to manage the playlist context
                    # await player.play_playlist(results) # This might replay the whole list? Check docs
                    # OR just play the first track normally if add_to_queue handles the rest
                    await player.play() # Should play the first track added
                    logger.info(f"Player not playing, starting playback from playlist for Guild {interaction.guild_id}")


            elif isinstance(results, list): # Should be list[Track] from search
                track = results[0] # Get the first track from search
                if current_queue_size < max_queue:
                     player.add_to_queue([track], requester=interaction.user.id) # Add takes a list
                     followup_message = f"✅ Added **`{discord.utils.escape_markdown(track.title)}`** to the queue."
                     logger.info(f"Adding track '{track.title}' for {interaction.user}")
                     if not player.is_playing:
                         track_to_play_now = track # Set this track to start playback
                else:
                     followup_message = f"❌ Queue is full (Max: {max_queue}). Could not add **`{discord.utils.escape_markdown(track.title)}`**."
                     logger.warning(f"Queue full. Skipped track '{track.title}' for {interaction.user}")

            else:
                # Should not happen with auto_search_tracks returning list, Playlist, or TrackLoadFailed
                logger.error(f"Unexpected result type from auto_search_tracks: {type(results)}")
                await interaction.followup.send("Received an unexpected result type. Cannot process.", ephemeral=True)
                return

            # Send confirmation message
            await interaction.followup.send(followup_message)

            # Start playback if a single track was added and player wasn't playing
            if track_to_play_now and not player.is_playing:
                logger.info(f"Player not playing, starting playback for single track for Guild {interaction.guild_id}")
                await player.play() # Play the track that was just added

        # Catch potential lavaplay errors during search/play
        except lavaplay.LavalinkException as e:
             logger.error(f"Lavalink Exception in play command: {e}", exc_info=True)
             try: await interaction.followup.send(f"Error interacting with music service: {e}", ephemeral=True)
             except discord.NotFound: pass
        except Exception as e:
            message = f"An unexpected error occurred processing your request."
            logger.exception(f"Unexpected error in play command for query '{query}': {e}")
            try: await interaction.followup.send(f"❌ {message}", ephemeral=True)
            except discord.NotFound: pass


    @app_commands.command(name="disconnect", description="Disconnects the bot from the voice channel.")
    async def disconnect(self, interaction: discord.Interaction):
        player = self.lavalink_node.get_player(interaction.guild_id)
        vc = interaction.guild.voice_client # Get discord.py voice client

        if not vc:
            return await interaction.response.send_message("Not connected to any voice channel.", ephemeral=True)

        logger.info(f"Disconnect command initiated by {interaction.user} in Guild {interaction.guild_id}")

        # Stop player and clear queue BEFORE telling discord.py to disconnect
        if player:
            player.queue.clear() # Clear lavaplay queue
            await player.stop() # Stop playback
            # Player destruction is handled by LavalinkVoiceClient.disconnect

        # Cancel inactivity timer if running
        if interaction.guild_id in self.inactivity_timers:
            self.inactivity_timers[interaction.guild_id].cancel()

        # Tell discord.py's voice client to disconnect
        # This will trigger the on_voice_state_update and LavalinkVoiceClient.disconnect logic
        await vc.disconnect() # Use force=False or omit, let the voice client handle it

        await interaction.response.send_message("Disconnected and cleared queue.")


    @app_commands.command(name="stop", description="Stops the music and clears the queue.")
    async def stop(self, interaction: discord.Interaction):
        player = self.lavalink_node.get_player(interaction.guild_id)

        if not player or not interaction.guild.voice_client:
            return await interaction.response.send_message("Not currently playing anything or not connected.", ephemeral=True)

        # Check if playing or queue has items
        if not player.is_playing and not player.queue:
             return await interaction.response.send_message("Nothing is playing and the queue is empty.", ephemeral=True)

        logger.info(f"Stop command initiated by {interaction.user} in Guild {interaction.guild_id}")
        player.queue.clear()
        await player.stop() # This stops current track and prevents next one

        # Schedule inactivity check *after* stopping
        self._schedule_inactivity_check(interaction.guild_id)

        await interaction.response.send_message("⏹️ Music stopped and queue cleared.")


    @app_commands.command(name="skip", description="Skips the current song.")
    async def skip(self, interaction: discord.Interaction):
        player = self.lavalink_node.get_player(interaction.guild_id)

        # lavaplay player.current might be None briefly between tracks
        current_track = player.current # Get current track object from lavaplay player
        if not player or not current_track:
            return await interaction.response.send_message("No song is currently playing to skip.", ephemeral=True)

        current_title = current_track.title if current_track else "Unknown Track"
        logger.info(f"Skip command initiated by {interaction.user} for track '{current_title}' in Guild {interaction.guild_id}")

        await player.skip()
        # Skip message
        skipped_msg = f"⏭️ Skipped **`{discord.utils.escape_markdown(current_title)}`**."

        # Check queue *after* skip. lavaplay should handle this transition quickly.
        # player = self.lavalink_node.get_player(interaction.guild_id) # Re-fetch might be needed if state changes drastically
        # if not player.queue and not player.is_playing: # Check if queue is empty AND not immediately playing next
        #     skipped_msg += "\nQueue is now empty."

        await interaction.response.send_message(skipped_msg)


    @app_commands.command(name="pause", description="Pauses the current song.")
    async def pause(self, interaction: discord.Interaction):
        player = self.lavalink_node.get_player(interaction.guild_id)

        if not player or not player.is_playing:
            return await interaction.response.send_message("No song is currently playing.", ephemeral=True)

        if player.is_paused:
             return await interaction.response.send_message("Music is already paused.", ephemeral=True)

        logger.info(f"Pause command initiated by {interaction.user} in Guild {interaction.guild_id}")
        await player.pause(True) # Pass True to pause
        await interaction.response.send_message("⏸️ Music paused.")


    @app_commands.command(name="resume", description="Resumes the paused song.")
    async def resume(self, interaction: discord.Interaction):
        player = self.lavalink_node.get_player(interaction.guild_id)

        if not player or not player.is_paused:
            # Check if a song is loaded, otherwise resume does nothing
            if not player or not player.current:
                 return await interaction.response.send_message("Nothing is loaded to resume.", ephemeral=True)
            else: # Player exists, has track, but isn't paused
                 return await interaction.response.send_message("Music is not paused.", ephemeral=True)

        logger.info(f"Resume command initiated by {interaction.user} in Guild {interaction.guild_id}")
        await player.pause(False) # Pass False to resume
        await interaction.response.send_message("▶️ Music resumed.")


    @app_commands.command(name="loop", description="Cycles through loop modes: OFF -> TRACK -> QUEUE -> OFF.")
    async def loop(self, interaction: discord.Interaction):
        player = self.lavalink_node.get_player(interaction.guild_id)

        if not player:
            return await interaction.response.send_message("Not connected or playing.", ephemeral=True)

        # lavaplay loop states: 0 = OFF, 1 = TRACK, 2 = QUEUE
        current_loop = player.loop # Gets current state (0, 1, or 2)

        next_loop = (current_loop + 1) % 3

        # Apply the next loop state using lavaplay methods
        if next_loop == 0: # OFF
            await player.repeat(False)
            await player.queue_repeat(False)
            mode = "OFF"
        elif next_loop == 1: # TRACK
            await player.repeat(True)
            await player.queue_repeat(False) # Ensure queue repeat is off
            mode = "TRACK"
        else: # QUEUE (next_loop == 2)
            await player.repeat(False) # Ensure track repeat is off
            await player.queue_repeat(True)
            mode = "QUEUE"

        logger.info(f"Loop command initiated by {interaction.user}. Loop set to {mode} for Guild {interaction.guild_id}")
        await interaction.response.send_message(f"🔁 Loop mode set to **{mode}**.")


    @app_commands.command(name="shuffle", description="Toggles shuffling of the queue.")
    async def shuffle(self, interaction: discord.Interaction):
        player = self.lavalink_node.get_player(interaction.guild_id)

        if not player or len(player.queue) < 2:
            return await interaction.response.send_message("The queue needs at least 2 songs to shuffle.", ephemeral=True)

        # lavaplay doesn't have a toggle method, just enable/disable
        # We need to track the state ourselves or just call shuffle() to reshuffle
        # Let's just reshuffle the existing queue when command is called
        player.shuffle() # Re-shuffles the queue in place
        logger.info(f"Shuffle command initiated by {interaction.user} in Guild {interaction.guild_id}. Queue reshuffled.")

        await interaction.response.send_message(f"🔀 Queue has been shuffled.")
        # Note: This doesn't provide an "unshuffle" back to original order.


    @app_commands.command(name="queue", description="Displays the current song queue.")
    @app_commands.describe(page="Page number of the queue to display")
    async def queue(self, interaction: discord.Interaction, page: app_commands.Range[int, 1] = 1):
        player = self.lavalink_node.get_player(interaction.guild_id)

        embed = discord.Embed(title="Music Queue", color=discord.Color.blue())

        # --- Current Track ---
        current_track_info = "*Nothing currently playing.*"
        if player and player.current:
             track = player.current
             title = discord.utils.escape_markdown(track.title or "Unknown Title")
             duration = format_duration(track.length) # Use length
             uri = track.uri or "#"
             requester = f"<@{track.requester}>" if track.requester else "Unknown"
             current_track_info = f"**`[{duration}]`** [{title}]({uri}) - {requester}"
             # Thumbnail logic needs check - see on_track_start
             # if track.artwork_url: embed.set_thumbnail(url=track.artwork_url)

        embed.add_field(name="Currently Playing", value=current_track_info, inline=False)

        # --- Queue ---
        if not player or not player.queue:
            embed.add_field(name="Up Next", value="*The queue is empty.*", inline=False)
            embed.set_footer(text="0 songs in queue | Page 1/1")
        else:
            items_per_page = 10
            queue_list = list(player.queue) # Get a copy of lavaplay queue
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
                     title = discord.utils.escape_markdown(track.title or "Unknown Title")
                     duration = format_duration(track.length) # Use length
                     uri = track.uri or "#"
                     requester = f"<@{track.requester}>" if track.requester else "Unknown"
                     queue_display += f"**{i}.** `[{duration}]` [{title}]({uri}) - {requester}\n"

            embed.add_field(name=f"Up Next (Page {page}/{total_pages})", value=queue_display, inline=False)

            # Calculate total queue duration
            queue_duration_ms = sum(t.length for t in queue_list if t.length is not None)
            total_duration_str = format_duration(queue_duration_ms)
            embed.set_footer(text=f"{total_items} songs in queue | Total duration: {total_duration_str} | Page {page}/{total_pages}")

        await interaction.response.send_message(embed=embed)


    @app_commands.command(name="lowpass", description="Applies a low-pass filter (bass boost effect). Strength > 0 enables.")
    @app_commands.describe(strength="Filter strength (0.0 to disable, 1.0-20.0 recommended)")
    async def lowpass(self, interaction: discord.Interaction, strength: app_commands.Range[float, 0.0, 100.0]):
        player = self.lavalink_node.get_player(interaction.guild_id)

        if not player:
             return await interaction.response.send_message("Bot is not connected or playing.", ephemeral=True)

        strength = max(0.0, min(100.0, strength)) # Ensure bounds, though Range helps

        embed = discord.Embed(color=discord.Color.blurple(), title='Low Pass Filter')

        try:
            # Create a new Filters object
            filters = Filters()
            # IMPORTANT: Applying a new Filters object resets ALL filters.
            # To modify existing filters, you'd need to fetch the current state,
            # update it, then apply. lavaplay doesn't seem to have a simple way
            # to get the current filter state easily from the player.
            # This command will just set LowPass and clear others.

            if strength <= 0.0:
                # Apply default (empty) filters to disable
                await player.filters(filters) # Sending default Filters() resets
                embed.description = 'Disabled **Low Pass Filter** (All filters reset).'
                logger.info(f"Resetting filters for Guild {interaction.guild_id}")
            else:
                # Add the lowpass filter to the Filters object
                filters.low_pass(strength) # Pass smoothing strength
                # Apply the filter set
                await player.filters(filters)
                embed.description = f'Set **Low Pass Filter** smoothing to `{strength:.2f}` (Other filters reset).'
                logger.info(f"Set LowPass filter (strength {strength:.2f}) for Guild {interaction.guild_id}")

            await interaction.response.send_message(embed=embed)

        except lavaplay.LavalinkException as e:
              logger.exception(f"Lavalink error applying filter: {e}")
              await interaction.response.send_message(f"An error occurred applying the filter via Lavalink: {e}", ephemeral=True)
        except Exception as e:
              logger.exception(f"Unexpected error applying filter: {e}")
              await interaction.response.send_message(f"An unexpected error occurred while applying the filter: {e}", ephemeral=True)


# --- Cog Setup Function ---
async def setup(bot: commands.Bot):
    # Check if lavalink_node was initialized successfully in bot.py
    if not hasattr(bot, 'lavalink_node') or bot.lavalink_node is None:
        logger.error("Music cog setup: Lavalink node ('lavalink_node') not found on bot. Cannot load Music cog.")
        # Prevent the cog from loading if Lavalink isn't ready
        raise commands.ExtensionFailed("Music", NameError("Lavalink node not available during Music cog setup"))

    # Check if node is connected (optional, but good indicator)
    # Adding a short wait might be needed if setup_hook connection is slow
    await asyncio.sleep(1) # Small delay to allow connection attempt
    if not bot.lavalink_node.stats:
         logger.warning("Music cog setup: Lavalink node found but not connected/no stats yet. Cog might face issues initially.")
         # Allow loading, but warn the user.

    await bot.add_cog(Music(bot))
    logger.info("Music Cog (using lavaplay) loaded.")

# --- END OF FILE cogs/music.py ---