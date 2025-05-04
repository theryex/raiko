import discord
from discord import app_commands
from discord.ext import commands
import wavelink # Use Wavelink
import logging
import re
import math
import asyncio
import os # For environment variables
from typing import Optional, cast, Union

# Ensure DEFAULT_VOLUME is imported from bot.py
from bot import DEFAULT_VOLUME

# Basic URL pattern (can be refined)
URL_REGEX = re.compile(r'https?://(?:www\.)?.+')

logger = logging.getLogger(__name__)

# --- Helper Functions ---
def format_duration(milliseconds: Optional[Union[int, float]]) -> str:
    """Formats milliseconds into HH:MM:SS or MM:SS."""
    if milliseconds is None:
        return "0:00" # Return 0:00 instead of N/A for None
    try:
        ms = int(float(milliseconds))
    except (ValueError, TypeError):
        return "Invalid" # Or some other indicator

    if ms <= 0:
        return "0:00"

    seconds_total = math.floor(ms / 1000)
    hours = math.floor(seconds_total / 3600)
    minutes = math.floor((seconds_total % 3600) / 60)
    seconds = seconds_total % 60

    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    else:
        return f"{minutes}:{seconds:02d}"

# --- Music Cog ---
class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.inactivity_timers: dict[int, asyncio.Task] = {}
        # Fetch queue/playlist limits from env vars once during init
        self.max_queue_size = int(os.getenv('MAX_QUEUE_SIZE', 1000))
        self.max_playlist_size = int(os.getenv('MAX_PLAYLIST_SIZE', 100))

    # --- Wavelink Event Listeners ---

    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, payload: wavelink.NodeReadyEventPayload):
        """Called when a node has established connection."""
        logger.info(f"Wavelink Node '{payload.node.identifier}' is ready.")

    @commands.Cog.listener()
    async def on_wavelink_websocket_closed(self, payload: wavelink.WebsocketClosedEventPayload):
        """Called when the node websocket connection is closed."""
        logger.error(f"Wavelink WS closed for Node '{payload.node.identifier}'! "
                     f"Code: {payload.code}, Reason: {payload.reason}, By Remote: {payload.remote}")
        # Optionally try to reconnect or alert admins

    @commands.Cog.listener()
    async def on_wavelink_track_start(self, payload: wavelink.TrackStartEventPayload):
        """Called when a track starts playing."""
        player = payload.player
        track = payload.track
        if not player or not player.guild: return

        guild_id = player.guild.id
        logger.info(f"Track started on Guild {guild_id}: {track.title}")

        # Cancel inactivity timer if player starts playing
        if guild_id in self.inactivity_timers:
            self.inactivity_timers[guild_id].cancel()
            del self.inactivity_timers[guild_id]
            # logger.debug(f"Cancelled inactivity timer for Guild {guild_id} due to track start.")

        # Send "Now Playing" message to the stored text channel
        # Assumes text_channel was stored on the player during the 'play' command
        if hasattr(player, 'text_channel') and player.text_channel:
            channel = player.text_channel
            # Use Wavelink track attributes
            title = discord.utils.escape_markdown(track.title or "Unknown Title")
            uri = track.uri or "#"
            author = discord.utils.escape_markdown(track.author or "Unknown Author")
            duration_ms = track.length
            requester_mention = ""
            if track.extras and 'requester' in track.extras:
                 requester_mention = f"<@{track.extras['requester']}>"

            desc = f"[{title}]({uri})\n"
            desc += f"Author: {author}\n"
            desc += f"Duration: {format_duration(duration_ms)}\n"
            if requester_mention:
                desc += f"Requested by: {requester_mention}"

            embed = discord.Embed(
                color=discord.Color.green(),
                title="Now Playing",
                description=desc
            )
            if track.artwork:
                embed.set_thumbnail(url=track.artwork)
            elif track.preview_url and track.source == "youtube": # Basic YT thumb fallback
                embed.set_thumbnail(url=f"https://img.youtube.com/vi/{track.identifier}/mqdefault.jpg")


            try:
                await channel.send(embed=embed)
            except discord.errors.Forbidden:
                 logger.warning(f"Missing permissions to send 'Now Playing' message in channel {channel.id} (Guild {guild_id})")
            except discord.HTTPException as e:
                logger.warning(f"Failed to send 'Now Playing' message to channel {channel.id}: {e}")
        else:
            logger.debug(f"Could not find text channel on player for Guild {guild_id} on TrackStartEvent.")

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload):
        """Called when a track finishes or is stopped."""
        player = payload.player
        track = payload.track
        reason = payload.reason
        if not player or not player.guild: return

        guild_id = player.guild.id
        logger.info(f"Track ended on Guild {guild_id}. Reason: {reason}. Queue size: {player.queue.count}")

        # Auto-play next song if queue is not empty and reason is FINISHED/LOAD_FAILED
        if reason in ('FINISHED', 'LOAD_FAILED') and not player.queue.is_empty:
             # Check if already playing (might happen with quick track ends/starts)
             if not player.playing:
                 try:
                     next_track = player.queue.get()
                     await player.play(next_track)
                 except wavelink.QueueEmpty:
                      logger.debug(f"Queue became empty unexpectedly after track end for Guild {guild_id}")
                 except Exception as e:
                      logger.error(f"Error starting next track for Guild {guild_id}: {e}")

        # Schedule inactivity check if queue is empty and player finished naturally
        elif reason == 'FINISHED' and player.queue.is_empty:
             self._schedule_inactivity_check(guild_id)
        # Schedule inactivity if stopped manually and queue is empty
        elif reason == 'STOPPED' and player.queue.is_empty:
             self._schedule_inactivity_check(guild_id)
        # Handle cases like 'REPLACED' or 'CLEANUP' if needed


    @commands.Cog.listener()
    async def on_wavelink_track_exception(self, payload: wavelink.TrackExceptionEventPayload):
        """Called when a track encounters an error during playback."""
        player = payload.player
        track = payload.track
        exception = payload.exception
        if not player or not player.guild: return

        guild_id = player.guild.id
        logger.error(f"Track Exception on Guild {guild_id}: {exception}", exc_info=False)

        # Send error message to the stored text channel
        if hasattr(player, 'text_channel') and player.text_channel:
            channel = player.text_channel
            track_title = getattr(track, 'title', 'the track')
            # Wavelink exception might have more details, adapt formatting as needed
            error_msg = str(exception) # Simple string representation
            try:
                await channel.send(f"💥 Error playing `{discord.utils.escape_markdown(track_title)}`: {error_msg}")
            except discord.HTTPException:
                pass # Avoid error loops

        # Optionally skip to the next track automatically on exceptions
        # if not player.queue.is_empty:
        #     try:
        #         await player.skip()
        #     except Exception as e:
        #         logger.error(f"Error skipping after track exception on Guild {guild_id}: {e}")


    @commands.Cog.listener()
    async def on_wavelink_track_stuck(self, payload: wavelink.TrackStuckEventPayload):
        """Called when a track appears to be stuck."""
        player = payload.player
        track = payload.track
        threshold = payload.threshold_ms
        if not player or not player.guild: return

        guild_id = player.guild.id
        logger.warning(f"Track Stuck on Guild {guild_id} (Threshold: {threshold}ms): {getattr(track, 'title', 'Unknown Title')}")

        # Send message to the stored text channel
        if hasattr(player, 'text_channel') and player.text_channel:
            channel = player.text_channel
            track_title = getattr(track, 'title', 'the track')
            try:
                await channel.send(f"⚠️ Track `{discord.utils.escape_markdown(track_title)}` seems stuck (>{threshold}ms), skipping...")
            except discord.HTTPException:
                 pass

        # Skip the stuck track
        try:
            await player.skip(force=True) # force=True might be needed for stuck tracks
        except Exception as e:
            logger.error(f"Error skipping stuck track on Guild {guild_id}: {e}")


    # --- Inactivity Handling ---

    def _schedule_inactivity_check(self, guild_id: int):
        """Schedules the inactivity check task."""
        # Cancel existing timer for the guild
        if guild_id in self.inactivity_timers:
            self.inactivity_timers[guild_id].cancel()

        disconnect_delay = 120 # Seconds (e.g., 2 minutes)
        logger.info(f"Queue ended or player stopped, starting {disconnect_delay}s disconnect timer for Guild {guild_id}")
        # Create task and store it
        task = asyncio.create_task(self._check_inactivity(guild_id, disconnect_delay))
        self.inactivity_timers[guild_id] = task
        # Remove task from dict when it's done (either cancelled or completed)
        task.add_done_callback(lambda t: self.inactivity_timers.pop(guild_id, None))

    async def _check_inactivity(self, guild_id: int, delay: int):
        """Checks if the player is inactive after a delay and disconnects."""
        await asyncio.sleep(delay)

        guild = self.bot.get_guild(guild_id)
        if not guild:
            logger.debug(f"Inactivity check: Guild {guild_id} not found.")
            return

        # Wavelink player is attached to guild.voice_client after connection
        player: Optional[wavelink.Player] = guild.voice_client
        # Alternatively, use NodePool if player might detach from voice_client somehow
        # player = wavelink.NodePool.get_node().get_player(guild)

        if player and player.connected and not player.playing and player.queue.is_empty:
             logger.info(f"Disconnect timer finished, disconnecting inactive player for Guild {guild_id}")
             # Optionally notify the channel
             if hasattr(player, 'text_channel') and player.text_channel:
                 try:
                      await player.text_channel.send("Disconnected due to inactivity.")
                 except discord.HTTPException:
                      pass
             await player.disconnect(force=True) # Disconnect the Wavelink player
        elif player and (player.playing or not player.queue.is_empty):
             logger.info(f"Inactivity check for Guild {guild_id}: Player is active, cancelling auto-disconnect.")
        else:
             # Player might already be disconnected or in an unexpected state
             logger.debug(f"Inactivity check for Guild {guild_id}: Player not found, not connected, or state prevents disconnect.")

    # --- Cog Unload ---
    def cog_unload(self):
        """Cog cleanup."""
        # Cancel any running inactivity timers
        for task in self.inactivity_timers.values():
            task.cancel()
        self.inactivity_timers.clear()
        # Wavelink listeners are usually managed globally or via NodePool,
        # specific cleanup might not be needed here unless listeners were added manually.
        logger.info("Music Cog unloaded, inactivity timers cancelled.")

    # --- Cog Checks ---
    async def cog_before_invoke(self, ctx: commands.Context):
        """Check executed before any command in this cog."""
        if not ctx.guild:
            raise commands.NoPrivateMessage("This command can't be used in DMs.")
        # You could add cooldowns or other checks here
        return True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Check executed before any slash command interaction in this cog."""
        if not interaction.guild:
            await interaction.response.send_message("This command can only be used in a server!", ephemeral=True)
            return False

        # Check if Wavelink node is available and connected
        node = wavelink.NodePool.get_node()
        if not node or not node.is_connected:
            logger.error("Interaction check failed: Wavelink node is not available or not connected.")
            await interaction.response.send_message("Music service is not available.", ephemeral=True)
            return False
        return True

    # --- App Command Error Handler ---
    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Handles errors specifically from this cog's slash commands."""
        original = getattr(error, 'original', error)
        command_name = interaction.command.name if interaction.command else 'unknown'

        # Log the error with traceback for debugging
        logger.error(f"Error in slash command '{command_name}': {original.__class__.__name__}: {original}", exc_info=original)

        error_message = f"An unexpected error occurred while running `/{command_name}`."

        # Handle specific errors
        if isinstance(original, app_commands.CheckFailure):
             error_message = "You don't have the necessary permissions or conditions to run this command."
        elif isinstance(original, app_commands.MissingPermissions):
             error_message = f"You lack the required permissions: {', '.join(original.missing_permissions)}"
        elif isinstance(original, app_commands.BotMissingPermissions):
             error_message = f"I lack the required permissions: {', '.join(original.missing_permissions)}"
        elif isinstance(original, wavelink.WavelinkException):
             # More specific Wavelink errors can be caught if needed
             error_message = f"Music service error: {original}"
        # Add more specific error handling as needed

        try:
            # Use followup if already responded (e.g., deferred)
            if interaction.response.is_done():
                await interaction.followup.send(f"❌ {error_message}", ephemeral=True)
            else:
                await interaction.response.send_message(f"❌ {error_message}", ephemeral=True)
        except discord.HTTPException as e:
             logger.error(f"Failed to send error message for command '{command_name}': {e}")


    # --- Slash Commands ---

    @app_commands.command(name="play", description="Plays or queues music (YouTube, SoundCloud, Spotify URL/Search).")
    @app_commands.describe(query='URL or search term')
    async def play(self, interaction: discord.Interaction, *, query: str):
        """Plays or adds a song/playlist to the queue."""

        # 1. Check user's voice state
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message("You need to be in a voice channel.", ephemeral=True)
        user_channel = interaction.user.voice.channel

        # 2. Get or Connect Player
        player: wavelink.Player
        if not interaction.guild.voice_client:
            # Connect bot to user's channel if not already connected
            try:
                # cls=wavelink.Player ensures the voice client is a Wavelink player
                player = await user_channel.connect(cls=wavelink.Player, self_deaf=True)
                logger.info(f"Connected to voice channel {user_channel.name} in Guild {interaction.guild.id}")
            except discord.ClientException:
                 return await interaction.response.send_message("Already connecting to a voice channel.", ephemeral=True)
            except asyncio.TimeoutError:
                return await interaction.response.send_message("Timed out connecting to the voice channel.", ephemeral=True)
            except Exception as e:
                 logger.error(f"Failed to connect to voice channel {user_channel.id}: {e}", exc_info=True)
                 return await interaction.response.send_message(f"Failed to connect: {e}", ephemeral=True)
        else:
            # Bot is already connected, get the player
            player = cast(wavelink.Player, interaction.guild.voice_client)
            # Check if user is in the same channel as the bot
            if player.channel.id != user_channel.id:
                return await interaction.response.send_message(f"You must be in the same voice channel as the bot (<#{player.channel.id}>).", ephemeral=True)

        # Store the text channel on the player for later messages
        player.text_channel = interaction.channel
        # Set default volume (optional, can be a command)
        await player.set_volume(DEFAULT_VOLUME) # Using volume from .env

        # 3. Defer response while searching
        await interaction.response.defer(thinking=True)

        # 4. Search for tracks
        try:
            search_query = query.strip('<>')
            logger.info(f"[{interaction.guild.name}] Searching for: '{search_query}'")
            # Wavelink v3 uses Playable.search() - simplifies source handling
            tracks: wavelink.Search = await wavelink.Playable.search(search_query)

            if not tracks:
                return await interaction.followup.send(f"Could not find any results for `{query}`.", ephemeral=True)

        except wavelink.LavalinkLoadException as e: # More specific error for load failures
            logger.error(f"LavalinkLoadException in play: {e}", exc_info=True)
            return await interaction.followup.send(f"Error loading tracks: {e}", ephemeral=True)
        except Exception as e:
            logger.exception(f"Unexpected error during search in play command: {e}")
            return await interaction.followup.send("An unexpected error occurred during search.", ephemeral=True)

        # 5. Process search results and add to queue
        added_count = 0
        skipped_count = 0
        followup_message = ""

        # --- Playlist Handling ---
        if isinstance(tracks, wavelink.Playlist):
            playlist_name = tracks.name or "Unnamed Playlist"
            tracks_to_consider = tracks.tracks[:self.max_playlist_size] # Apply playlist limit

            # Filter out tracks exceeding max queue size
            tracks_to_add = []
            for track in tracks_to_consider:
                if player.queue.count + added_count < self.max_queue_size:
                    track.extras = {'requester': interaction.user.id} # Store requester
                    tracks_to_add.append(track)
                    added_count += 1
                else:
                    skipped_count += 1

            if tracks_to_add:
                player.queue.extend(tracks_to_add) # Add multiple tracks efficiently
                logger.info(f"Added {added_count}/{len(tracks_to_consider)} tracks from playlist '{playlist_name}'.")

            # Build followup message for playlist
            followup_message = f"✅ Added **{added_count}** tracks from playlist **`{discord.utils.escape_markdown(playlist_name)}`**."
            if len(tracks.tracks) > self.max_playlist_size:
                followup_message += f" (Playlist capped at {self.max_playlist_size})"
            if skipped_count > 0:
                followup_message += f" (Queue full, skipped {skipped_count})"

        # --- Single Track/Search Result Handling ---
        elif tracks: # tracks is a list of Playable
             # Add the first result from the search list
             track = tracks[0]
             if player.queue.count < self.max_queue_size:
                 track.extras = {'requester': interaction.user.id} # Store requester
                 await player.queue.put_wait(track) # put_wait is awaitable
                 followup_message = f"✅ Added **`{discord.utils.escape_markdown(track.title)}`** to the queue."
                 added_count = 1
                 logger.info(f"Added track '{track.title}'.")
             else:
                 followup_message = f"❌ Queue is full (Max: {self.max_queue_size}). Could not add **`{discord.utils.escape_markdown(track.title)}`**."
                 logger.warning(f"Queue full. Skipped track '{track.title}'.")

        else: # Should not happen if tracks is not None and not Playlist/list
             logger.error("Unexpected empty result from Wavelink search.")
             followup_message = "Received an unexpected empty result."

        # Send confirmation message
        await interaction.followup.send(followup_message)

        # 6. Start playback if not already playing and tracks were added
        if added_count > 0 and not player.playing:
            first_track = player.queue.get()
            await player.play(first_track)
            logger.info(f"Player not playing, starting playback for Guild {interaction.guild.id}")


    @app_commands.command(name="disconnect", description="Disconnects the bot from the voice channel.")
    async def disconnect(self, interaction: discord.Interaction):
        """Disconnects the bot and clears the queue."""
        player: Optional[wavelink.Player] = interaction.guild.voice_client

        if not player or not player.connected:
            return await interaction.response.send_message("Not connected to any voice channel.", ephemeral=True)

        logger.info(f"Disconnect command initiated by {interaction.user} in Guild {interaction.guild.id}")

        # Stop player and clear queue BEFORE disconnecting
        player.queue.clear()
        await player.stop()
        await player.disconnect() # Use Wavelink's disconnect

        # Cancel inactivity timer if running
        if interaction.guild.id in self.inactivity_timers:
            self.inactivity_timers[interaction.guild.id].cancel()

        await interaction.response.send_message("Disconnected and cleared queue.")


    @app_commands.command(name="stop", description="Stops the music and clears the queue.")
    async def stop(self, interaction: discord.Interaction):
        """Stops playback and clears the queue."""
        player: Optional[wavelink.Player] = interaction.guild.voice_client

        if not player or not player.connected:
            return await interaction.response.send_message("Not connected.", ephemeral=True)

        if not player.playing and player.queue.is_empty:
             return await interaction.response.send_message("Nothing is playing and the queue is empty.", ephemeral=True)

        logger.info(f"Stop command initiated by {interaction.user} in Guild {interaction.guild.id}")
        player.queue.clear()
        await player.stop() # Stops current track and clears filters

        # Schedule inactivity check *after* stopping
        self._schedule_inactivity_check(interaction.guild.id)

        await interaction.response.send_message("⏹️ Music stopped and queue cleared.")


    @app_commands.command(name="skip", description="Skips the current song.")
    async def skip(self, interaction: discord.Interaction):
        """Skips the currently playing track."""
        player: Optional[wavelink.Player] = interaction.guild.voice_client

        if not player or not player.connected:
            return await interaction.response.send_message("Not connected.", ephemeral=True)

        current_track = player.current
        if not current_track:
            return await interaction.response.send_message("No song is currently playing to skip.", ephemeral=True)

        current_title = discord.utils.escape_markdown(current_track.title)
        logger.info(f"Skip command initiated by {interaction.user} for track '{current_title}' in Guild {interaction.guild.id}")

        # Wavelink's skip handles playing the next track if available
        await player.skip(force=True) # force=True ensures skip even if loop is on

        # Send confirmation
        await interaction.response.send_message(f"⏭️ Skipped **`{current_title}`**.")


    @app_commands.command(name="pause", description="Pauses the current song.")
    async def pause(self, interaction: discord.Interaction):
        """Pauses playback."""
        player: Optional[wavelink.Player] = interaction.guild.voice_client

        if not player or not player.connected:
            return await interaction.response.send_message("Not connected.", ephemeral=True)

        if not player.playing:
            return await interaction.response.send_message("No song is currently playing.", ephemeral=True)

        if player.paused:
             return await interaction.response.send_message("Music is already paused.", ephemeral=True)

        logger.info(f"Pause command initiated by {interaction.user} in Guild {interaction.guild.id}")
        await player.pause() # Wavelink v3: pause() toggles or use set_pause(True)
        await interaction.response.send_message("⏸️ Music paused.")


    @app_commands.command(name="resume", description="Resumes the paused song.")
    async def resume(self, interaction: discord.Interaction):
        """Resumes playback."""
        player: Optional[wavelink.Player] = interaction.guild.voice_client

        if not player or not player.connected:
            return await interaction.response.send_message("Not connected.", ephemeral=True)

        if player.playing and not player.paused:
             return await interaction.response.send_message("Music is not paused.", ephemeral=True)

        if not player.current and player.queue.is_empty:
             return await interaction.response.send_message("Nothing is loaded to resume.", ephemeral=True)

        logger.info(f"Resume command initiated by {interaction.user} in Guild {interaction.guild.id}")
        await player.resume() # Wavelink v3: resume() or use set_pause(False)
        await interaction.response.send_message("▶️ Music resumed.")


    @app_commands.command(name="loop", description="Cycles through loop modes: OFF -> TRACK -> QUEUE -> OFF.")
    async def loop(self, interaction: discord.Interaction):
        """Sets the loop mode for the queue."""
        player: Optional[wavelink.Player] = interaction.guild.voice_client

        if not player or not player.connected:
            return await interaction.response.send_message("Not connected.", ephemeral=True)

        current_mode = player.queue.mode

        if current_mode == wavelink.QueueMode.loop: # TRACK
            next_mode = wavelink.QueueMode.loop_all
            mode_str = "QUEUE"
        elif current_mode == wavelink.QueueMode.loop_all: # QUEUE
            next_mode = wavelink.QueueMode.normal
            mode_str = "OFF"
        else: # OFF (normal)
            # Can only loop if there's a current track or items in queue
            if not player.current and player.queue.is_empty:
                 return await interaction.response.send_message("Cannot enable loop: Nothing is playing or queued.", ephemeral=True)
            next_mode = wavelink.QueueMode.loop
            mode_str = "TRACK"

        player.queue.mode = next_mode
        logger.info(f"Loop command initiated by {interaction.user}. Loop set to {mode_str} for Guild {interaction.guild.id}")
        await interaction.response.send_message(f"🔁 Loop mode set to **{mode_str}**.")


    @app_commands.command(name="shuffle", description="Shuffles the current queue.")
    async def shuffle(self, interaction: discord.Interaction):
        """Shuffles the tracks currently in the queue."""
        player: Optional[wavelink.Player] = interaction.guild.voice_client

        if not player or not player.connected:
            return await interaction.response.send_message("Not connected.", ephemeral=True)

        if player.queue.count < 2:
            return await interaction.response.send_message("The queue needs at least 2 songs to shuffle.", ephemeral=True)

        player.queue.shuffle()
        logger.info(f"Shuffle command initiated by {interaction.user} in Guild {interaction.guild.id}. Queue reshuffled.")

        await interaction.response.send_message(f"🔀 Queue has been shuffled.")


    @app_commands.command(name="queue", description="Displays the current song queue.")
    @app_commands.describe(page="Page number of the queue to display")
    async def queue(self, interaction: discord.Interaction, page: app_commands.Range[int, 1] = 1):
        """Shows the current queue page."""
        player: Optional[wavelink.Player] = interaction.guild.voice_client

        embed = discord.Embed(title="Music Queue", color=discord.Color.blue())

        # --- Current Track ---
        current_track_info = "*Nothing currently playing.*"
        if player and player.current:
             track = player.current
             title = discord.utils.escape_markdown(track.title or "Unknown Title")
             duration = format_duration(track.length)
             uri = track.uri or "#"
             requester = ""
             if track.extras and 'requester' in track.extras:
                 requester = f" - <@{track.extras['requester']}>"
             current_track_info = f"**`[{duration}]`** [{title}]({uri}){requester}"
             if track.artwork:
                  embed.set_thumbnail(url=track.artwork)

        embed.add_field(name="Currently Playing", value=current_track_info, inline=False)

        # --- Queue ---
        if not player or player.queue.is_empty:
            embed.add_field(name="Up Next", value="*The queue is empty.*", inline=False)
            embed.set_footer(text="Page 1/1 | 0 songs | Total duration: 0:00")
        else:
            items_per_page = 10
            queue_list = list(player.queue) # Get a copy
            total_items = len(queue_list)
            total_pages = math.ceil(total_items / items_per_page)

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
                     duration = format_duration(track.length)
                     uri = track.uri or "#"
                     requester = ""
                     if track.extras and 'requester' in track.extras:
                         requester = f" - <@{track.extras['requester']}>"
                     queue_display += f"**{i}.** `[{duration}]` [{title}]({uri}){requester}\n"

            embed.add_field(name=f"Up Next (Page {page}/{total_pages})", value=queue_display, inline=False)

            # Calculate total queue duration
            queue_duration_ms = sum(t.length for t in queue_list if t.length is not None)
            total_duration_str = format_duration(queue_duration_ms)
            embed.set_footer(text=f"{total_items} songs in queue | Total duration: {total_duration_str} | Page {page}/{total_pages}")

        await interaction.response.send_message(embed=embed)


    @app_commands.command(name="lowpass", description="Applies a low-pass filter (bass boost effect). Strength > 0 enables.")
    @app_commands.describe(strength="Filter strength (0.0 to disable, 0.1-1.0 recommended)")
    async def lowpass(self, interaction: discord.Interaction, strength: app_commands.Range[float, 0.0, 5.0]): # Adjusted range for sensibility
        """Applies or disables a low-pass filter."""
        player: Optional[wavelink.Player] = interaction.guild.voice_client

        if not player or not player.connected:
             return await interaction.response.send_message("Not connected.", ephemeral=True)

        strength = max(0.0, min(5.0, strength)) # Ensure bounds

        embed = discord.Embed(color=discord.Color.blurple(), title='Low Pass Filter')

        try:
            # Create a filter object - start with current filters if modifying, or new if replacing
            # For simplicity, this example replaces all filters when setting lowpass
            current_filters = player.filters # Get current filters applied (Wavelink v3+)

            if strength <= 0.0:
                # Disable lowpass by removing it or resetting all filters
                # Option 1: Reset all filters
                new_filter = wavelink.Filter()
                await player.set_filter(new_filter, seek=False) # Apply empty filter
                embed.description = 'Disabled **Low Pass Filter** (All filters reset).'
                logger.info(f"Resetting filters for Guild {interaction.guild.id}")
                 # Option 2 (If modifying): Remove just lowpass if possible (API might vary)
                 # if hasattr(current_filters, 'low_pass'): del current_filters.low_pass
                 # await player.set_filter(current_filters, seek=False)
            else:
                # Enable lowpass - Add it to a new filter object
                # Note: Creating a new wavelink.Filter() will reset other filters
                new_filter = wavelink.Filter(low_pass=wavelink.LowPass(smoothing=strength))
                # If you want to KEEP existing filters, you need to build upon current_filters:
                # current_filters.low_pass = wavelink.LowPass(smoothing=strength)
                # await player.set_filter(current_filters, seek=False)

                # Applying the new filter (replace existing)
                await player.set_filter(new_filter, seek=False) # seek=False avoids track restart
                embed.description = f'Set **Low Pass Filter** smoothing to `{strength:.2f}` (Other filters reset).'
                logger.info(f"Set LowPass filter (strength {strength:.2f}) for Guild {interaction.guild.id}")

            await interaction.response.send_message(embed=embed)

        except wavelink.WavelinkException as e:
              logger.exception(f"Wavelink error applying filter: {e}")
              await interaction.response.send_message(f"An error occurred applying the filter via Wavelink: {e}", ephemeral=True)
        except Exception as e:
              logger.exception(f"Unexpected error applying filter: {e}")
              await interaction.response.send_message(f"An unexpected error occurred while applying the filter.", ephemeral=True)


# --- Cog Setup Function ---
async def setup(bot: commands.Bot):
    # Check if Wavelink NodePool is ready before adding cog
    # Add a slightly longer delay to ensure node connection attempt has occurred
    await asyncio.sleep(2)
    node = wavelink.NodePool.get_node()
    if not node or not node.is_connected:
        logger.error("Music cog setup: Wavelink node is not available or not connected after delay. Cannot load Music cog.")
        raise commands.ExtensionFailed("Music", NameError("Wavelink node not available during Music cog setup"))

    await bot.add_cog(Music(bot))
    logger.info("Music Cog (using wavelink) loaded.")

