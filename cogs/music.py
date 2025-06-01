import discord
from discord import app_commands
from discord.ext import commands
import wavelink
import re
import math
import asyncio
import os
import subprocess # Added
from typing import Optional, Union
import logging # Added for logger

logger = logging.getLogger(__name__) # Added for logger

URL_REGEX = re.compile(r'https?://(?:www\.)?.+')
MUSIC_CACHE_DIR = "./music_cache"
YOUTUBE_VIDEO_ID_REGEX = re.compile(r'(?:youtube\.com\/(?:[^\/]+\/.+\/|(?:v|e(?:mbed)?)\/|.*[?&]v=)|youtu\.be\/|music\.youtube\.com\/watch\?v=|youtube\.com\/shorts\/)([^"&?/\s]{11})')

def get_youtube_video_id(url: str) -> Optional[str]:
    match = YOUTUBE_VIDEO_ID_REGEX.search(url)
    if match:
        return match.group(1)
    return None

def format_duration(milliseconds: Optional[Union[int, float]]) -> str:
    if milliseconds is None:
        return "0:00"
    try:
        ms = int(float(milliseconds))
    except (ValueError, TypeError):
        return "Invalid"

    seconds_total = math.floor(ms / 1000)
    hours = math.floor(seconds_total / 3600)
    minutes = math.floor((seconds_total % 3600) / 60)
    seconds = seconds_total % 60

    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours > 0 else f"{minutes}:{seconds:02d}"

class MusicCog(commands.Cog): # Renamed class
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.inactivity_timers = {}
        self.default_volume = int(os.getenv('DEFAULT_VOLUME', 100))
        self.max_queue_size = int(os.getenv('MAX_QUEUE_SIZE', 1000))
        self.max_playlist_size = int(os.getenv('MAX_PLAYLIST_SIZE', 100))
        os.makedirs(MUSIC_CACHE_DIR, exist_ok=True)

    async def ensure_voice_client(self, interaction: discord.Interaction) -> Optional[wavelink.Player]:
        if not interaction.guild: 
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return None

        user_voice = interaction.user.voice
        if not user_voice or not user_voice.channel:
            await interaction.response.send_message("You must be in a voice channel to use this command.", ephemeral=True)
            return None

        player: wavelink.Player = interaction.guild.voice_client

        if not player: 
            try:
                player = await user_voice.channel.connect(cls=wavelink.Player, self_deaf=True)
            except discord.errors.ClientException: 
                await interaction.response.send_message("Already trying to connect to a voice channel. Please wait.", ephemeral=True)
                return None
            except Exception as e:
                await interaction.response.send_message(f"Failed to join your voice channel: {str(e)}", ephemeral=True)
                return None
        
        elif player.channel != user_voice.channel:
            await interaction.response.send_message(f"You must be in the same voice channel as the bot ({player.channel.mention}).", ephemeral=True)
            return None

        # Ensure text_channel is set or updated
        if not hasattr(player, 'text_channel') or (interaction.channel and player.text_channel != interaction.channel) :
            if interaction.channel: 
                 player.text_channel = interaction.channel
            # else: # Fallback if interaction.channel is None, though less likely for slash commands
                 # player.text_channel = self.bot.get_channel(interaction.channel_id)


        # Set default volume only once when player is first established
        if not hasattr(player, '_volume_set_once'): # Use a private-like attribute
            await player.set_volume(self.default_volume)
            player._volume_set_once = True 

        return player

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload):
        player = payload.player
        if not player or not player.guild or not player.connected: # Added player.connected check
            return
        
        reason = payload.reason
        # If a track ended because it was stopped by /stop or /disconnect, player might be disconnected.
        # The player.stop() or player.disconnect() in those commands should handle cleanup.

        if payload.reason == 'finished':
            if not player.queue.is_empty:
                try:
                    next_track = player.queue.get()
                    await player.play(next_track)
                    if hasattr(player, 'text_channel') and player.text_channel and hasattr(next_track, 'title'):
                        requester_mention = next_track.extras.get('requester_mention', "Unknown User")
                        await player.text_channel.send(f"🎶 Now playing: **{next_track.title}** (Requested by: {requester_mention})")
                except Exception as e:
                    if hasattr(player, 'text_channel') and player.text_channel:
                        await player.text_channel.send(f"Error playing next track: {str(e)}. Please check logs.")
            else: # Queue is empty
                if hasattr(player, 'text_channel') and player.text_channel:
                     await player.text_channel.send("Queue finished. Bot will disconnect if inactive.")
                self._schedule_inactivity_check(player.guild.id)
        
        elif payload.reason == 'load_failed':
            if hasattr(player, 'text_channel') and player.text_channel:
                await player.text_channel.send(f"Failed to load track: **{payload.track.title if payload.track else 'Unknown Track'}**. Skipping to next if available.")
            if not player.queue.is_empty:
                try:
                    next_track = player.queue.get()
                    await player.play(next_track)
                    if hasattr(player, 'text_channel') and player.text_channel and hasattr(next_track, 'title'):
                       requester_mention = next_track.extras.get('requester_mention', "Unknown User")
                       await player.text_channel.send(f"🎶 Now playing: **{next_track.title}** (Requested by: {requester_mention})")
                except Exception as e:
                    if hasattr(player, 'text_channel') and player.text_channel:
                        await player.text_channel.send(f"Error playing next track after load failure: {str(e)}. Please check logs.")
            else: # Queue is empty after load failure
                 if hasattr(player, 'text_channel') and player.text_channel:
                    await player.text_channel.send("Queue finished after track load failure. Bot will disconnect if inactive.")
                 self._schedule_inactivity_check(player.guild.id)

        elif payload.reason == 'stopped':
            logger.debug(f"[TRACK_END_STOPPED] Guild: {player.guild.id} - Queue empty: {player.queue.is_empty}, Queue size: {len(list(player.queue))}") # Use len(list(player.queue)) for accurate size at this moment
            if not player.queue.is_empty:
                # Add another log to see what's at the front of the queue
                logger.debug(f"[TRACK_END_STOPPED] Guild: {player.guild.id} - About to get track from queue. Current front title: '{getattr(player.queue[0].extras, 'display_title', player.queue[0].title if player.queue and hasattr(player.queue[0], 'title') else 'N/A')}'")
                try:
                    next_track = player.queue.get()
                    # ADD THIS LINE:
                    logger.debug(f"[TRACK_END_STOPPED] Guild: {player.guild.id} - Got next_track. Title: '{getattr(next_track.extras, 'display_title', next_track.title if next_track and hasattr(next_track, 'title') else 'N/A')}', URI: '{getattr(next_track, 'uri', 'N/A')}'")
                    await player.play(next_track)
                    # Optional: Send "Now playing" message, consistent with 'finished' reason.
                    # Consider if this is desirable after a /skip or /stop that results in immediate next play.
                    # For now, let's keep it consistent with 'finished'.
                    if hasattr(player, 'text_channel') and player.text_channel and hasattr(next_track, 'title'): # Check if next_track is Playable
                        display_title = getattr(next_track.extras, 'display_title', next_track.title or "Unknown Title")
                        requester_mention = getattr(next_track.extras, 'requester_mention', "Unknown User")
                        await player.text_channel.send(f"🎶 Now playing: **{display_title}** (Requested by: {requester_mention})")
                except Exception as e:
                    logger.error(f"[TRACK_END_STOPPED] Guild: {player.guild.id} - Error playing next track: {e}", exc_info=True)
                    if hasattr(player, 'text_channel') and player.text_channel:
                        await player.text_channel.send(f"Error playing next track: {str(e)}. Please check logs.")
            else:
                logger.debug(f"[TRACK_END_STOPPED] Guild: {player.guild.id} - Queue is empty, scheduling inactivity check.")
                if hasattr(player, 'text_channel') and player.text_channel:
                     await player.text_channel.send("Playback stopped and queue is empty. Bot will disconnect if inactive.")
                 self._schedule_inactivity_check(player.guild.id)
            # If /stop was used, player will likely be disconnected by the command itself.
            # If /skip was used and queue is not empty, track_end for skip should trigger next play (already handled by this block).

        # REPLACED and CLEANUP reasons usually don't need specific "next song" logic here
        # as they are handled by Wavelink or other commands.

    def _schedule_inactivity_check(self, guild_id: int):
        if guild_id in self.inactivity_timers:
            self.inactivity_timers[guild_id].cancel()
        task = asyncio.create_task(self._check_inactivity(guild_id, 120))
        self.inactivity_timers[guild_id] = task
        task.add_done_callback(lambda t: self.inactivity_timers.pop(guild_id, None))

    async def _check_inactivity(self, guild_id: int, delay: int):
        await asyncio.sleep(delay)
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return

        player = guild.voice_client
        if player and player.connected and not player.playing and player.queue.is_empty:
            await player.disconnect()
        
    def cog_unload(self):
        for task in self.inactivity_timers.values():
            task.cancel()
        self.inactivity_timers.clear()

    @app_commands.command(name="play", description="Plays music or adds a playlist from YouTube, Spotify, or SoundCloud.")
    @app_commands.describe(query='URL or search term')
    async def play(self, interaction: discord.Interaction, *, query: str):
        player = await self.ensure_voice_client(interaction)
        if not player:
            return
            
        await interaction.response.defer()

        video_id = get_youtube_video_id(query)

        if video_id:
            # This is a YouTube URL, implement downloading & local play logic here
            # For now, just send a message indicating it's a YT video
            # We will fill in the download and play logic in subsequent steps.
            
            # Construct expected filepath
            # yt-dlp with --audio-format opus and -o "./music_cache/%(id)s.%(ext)s"
            # will likely produce a .opus file.
            expected_filename = f"{video_id}.opus"
            cached_filepath = os.path.join(MUSIC_CACHE_DIR, expected_filename)
            abs_cached_filepath = os.path.abspath(cached_filepath)

            if os.path.exists(abs_cached_filepath):
                await interaction.followup.send(f"Found '{expected_filename}' in cache. Attempting to play...")
            else:
                await interaction.followup.send(f"Downloading '{query}'. This may take a moment...")
                cmd = [
                    "yt-dlp",
                    "-x",  # Short for --extract-audio
                    "--audio-format", "opus",
                    "--audio-quality", "0", # Add this for best VBR Opus
                    "-o", os.path.join(MUSIC_CACHE_DIR, f"{video_id}.opus"),
                    query
                ]
                try:
                    loop = asyncio.get_event_loop()
                    process_result = await loop.run_in_executor(None, lambda: subprocess.run(cmd, check=True, capture_output=True, text=True))
                    logger.info(f"yt-dlp download successful for {video_id}:\n{process_result.stdout}")
                    # If subprocess.run didn't raise an exception, we assume the file was created as specified.
                    # The check for abs_cached_filepath existence will happen before wavelink.Pool.fetch_tracks
                except subprocess.CalledProcessError as e:
                    logger.error(f"yt-dlp download failed for {video_id}. Return code: {e.returncode}\nStderr: {e.stderr}\nStdout: {e.stdout}")
                    await interaction.channel.send(f"Failed to download YouTube video: `{e.stderr[:1800]}`")
                    return
                except Exception as e_exec:
                    logger.error(f"Error executing yt-dlp for {video_id}: {e_exec}", exc_info=True)
                    await interaction.channel.send(f"An error occurred while trying to download the video: {str(e_exec)[:1000]}.")
                    return

            # Play Local File via Lavalink (after cache check or download)
            # Simplified check: if the file isn't at the exact path after supposed success, then error.
            if not os.path.exists(abs_cached_filepath):
                logger.error(f"yt-dlp claimed success, but output file {abs_cached_filepath} is missing.")
                await interaction.channel.send(f"Download seemed to complete, but the output audio file could not be found.")
                return

            # Fetch YouTube Title
            fetched_title = video_id # Default to video_id if title fetch fails
            try:
                title_cmd = [
                    "yt-dlp", "--print", "title", "-s", # -s to skip download, --print title to output only title
                    query # The original YouTube URL
                ]
                loop = asyncio.get_event_loop()
                title_process_result = await loop.run_in_executor(None, lambda: subprocess.run(title_cmd, check=True, capture_output=True, text=True, encoding='utf-8'))
                fetched_title = title_process_result.stdout.strip()
                logger.info(f"Fetched title for {video_id}: {fetched_title}")
            except subprocess.CalledProcessError as e_title:
                logger.error(f"yt-dlp title fetch failed for {video_id}: {e_title.stderr}")
                # Keep fetched_title as video_id (already defaulted)
            except Exception as e_title_exec:
                logger.error(f"Error executing yt-dlp for title fetch {video_id}: {e_title_exec}", exc_info=True)
                # Keep fetched_title as video_id

            try:
                tracks = await wavelink.Pool.fetch_tracks(f'{abs_cached_filepath}')
                if not tracks:
                    await interaction.channel.send("Could not load the downloaded local file via Lavalink. The file might be corrupted or an unsupported format for Lavalink's local source.")
                    return

                track_to_play = tracks[0] if isinstance(tracks, list) else tracks
                track_to_play.extras = {
                    'requester_id': interaction.user.id,
                    'requester_mention': interaction.user.mention,
                    'display_title': fetched_title # Use the fetched title here
                }

                if player.playing or player.paused:
                    if player.queue.count >= self.max_queue_size:
                        await interaction.channel.send("Queue is full. Cannot add local track.", ephemeral=True)
                        return
                    player.queue.put(track_to_play)
                    await interaction.channel.send(f"➕ Queued (local): **{getattr(track_to_play.extras, 'display_title', video_id)}** (Requested by: {interaction.user.mention})")
                else:
                    await player.play(track_to_play)
                    await interaction.channel.send(f"🎶 Playing (local): **{getattr(track_to_play.extras, 'display_title', video_id)}** (Requested by: {interaction.user.mention})")

            except Exception as e:
                logger.error(f"Error playing local file {abs_cached_filepath} with Lavalink: {e}", exc_info=True)
                await interaction.channel.send(f"Error playing local file via Lavalink: {str(e)[:1000]}")
            return # Ensure we return after handling a YouTube video

        else: # Not a YouTube video URL, proceed with existing Lavalink search logic
            try:
                search_result = await wavelink.Playable.search(query)

                # Primary check for Wavelink v3, which returns None or empty list if no tracks are found.
                if not search_result:
                    await interaction.followup.send("No results found for your query.", ephemeral=True)
                    return

                # Ensure player.text_channel is set for later messages by on_wavelink_track_end
                if not hasattr(player, 'text_channel') or not player.text_channel:
                    if interaction.channel: # Check if interaction.channel exists
                        player.text_channel = interaction.channel
                    # else: Fallback not strictly needed here as command context should have channel

                requester_id = interaction.user.id
                requester_mention = interaction.user.mention

                if isinstance(search_result, wavelink.Playlist):
                    playlist = search_result
                    # Limit how many tracks we take from the playlist initially
                    tracks_to_process = playlist.tracks[:self.max_playlist_size]

                    if not tracks_to_process:
                        await interaction.followup.send(f"Playlist **{playlist.name}** is empty or no usable tracks found (check Lavalink logs for details).", ephemeral=True)
                        return

                    added_count = 0
                    first_track_played_info = None

                    # If nothing is playing, play the first track immediately
                    if not player.playing and not player.paused:
                        if tracks_to_process:
                            first_track = tracks_to_process.pop(0) # Remove from list to process
                            first_track.extras = {'requester_id': requester_id, 'requester_mention': requester_mention}
                            await player.play(first_track)
                            first_track_played_info = f"🎶 Playing: **{first_track.title}** (from playlist **{playlist.name}** requested by {requester_mention})"

                    # Add remaining tracks to the queue
                    for track in tracks_to_process:
                        if player.queue.count >= self.max_queue_size:
                            if player.text_channel:
                                await player.text_channel.send(f"Queue is full ({self.max_queue_size} tracks). Not all songs from **{playlist.name}** were added.", ephemeral=True)
                            break
                        track.extras = {'requester_id': requester_id, 'requester_mention': requester_mention}
                        player.queue.put(track)
                        added_count += 1

                    response_message = ""
                    if first_track_played_info:
                        response_message = first_track_played_info
                        if added_count > 0:
                            response_message += f"\n➕ Queued an additional {added_count} song(s) from the playlist."
                    elif added_count > 0:
                        response_message = f"➕ Queued {added_count} song(s) from playlist **{playlist.name}** (Requested by: {requester_mention})."
                    else: # No track played, no tracks queued
                        response_message = f"Could not add songs from **{playlist.name}**. Player might be busy and queue full, or playlist limit reached/empty."

                    await interaction.followup.send(response_message)

                    # Notify if playlist was truncated due to bot's own MAX_PLAYLIST_SIZE limit
                    if len(playlist.tracks) > self.max_playlist_size and added_count == (self.max_playlist_size - (1 if first_track_played_info else 0)) :
                         if player.text_channel:
                            await player.text_channel.send(f"ℹ️ Note: Playlist **{playlist.name}** was truncated to the first {self.max_playlist_size} songs due to bot configuration.", ephemeral=True)


                else: # Single track or search result (list of Playable)
                    # If search_result is a list, take the first item. Otherwise, it's a single Playable.
                    single_track = search_result[0] if isinstance(search_result, list) else search_result

                    # This check might be redundant if wavelink.Playable.search always returns Playable or list of Playable
                    # but kept for safety.
                    if not isinstance(single_track, wavelink.Playable):
                        await interaction.followup.send("Could not process the search result into a playable track.", ephemeral=True)
                        return

                    single_track.extras = {'requester_id': requester_id, 'requester_mention': requester_mention}

                    if player.playing or player.paused:
                        if player.queue.count >= self.max_queue_size:
                            await interaction.followup.send("Queue is full. Cannot add track.", ephemeral=True)
                            return
                        player.queue.put(single_track)
                        await interaction.followup.send(f"➕ Queued: **{single_track.title}** (Requested by: {requester_mention})")
                    else:
                        await player.play(single_track)
                        await interaction.followup.send(f"🎶 Playing: **{single_track.title}** (Requested by: {requester_mention})")

            # Removed specific NoTracksError as it's handled by `if not search_result:`
            except wavelink.exceptions.LavalinkLoadException as e:
                # Log the error for server-side diagnosis
                # Assuming logger is defined at the top of the file:
                # import logging
                # logger = logging.getLogger(__name__)
                # If not, you'd need to add it or use print for temporary debugging.
                # For now, let's assume a logger object `logger` exists as per previous context.
                logger.error(f"LavalinkLoadException in /play (non-YouTube). Error string: {e}", exc_info=True) # Differentiate log
                user_friendly_error = getattr(e, 'error', str(e)) # Use e.error if available, else str(e)
                await interaction.followup.send(f"Lavalink error: {user_friendly_error}. This might be due to restrictions on the track/playlist or a Lavalink server issue. Please check the track if it's valid and playable.", ephemeral=True)
            except Exception as e:
                # Log the error for server-side diagnosis
                # logger.exception(f"Unexpected error in /play command: {e}")
                logger.error(f"Unexpected error in /play (non-YouTube): {e}", exc_info=True) # Differentiate log
                await interaction.followup.send(f"An unexpected error occurred: {str(e)}", ephemeral=True)

    @app_commands.command(name="disconnect", description="Disconnects the bot from the voice channel.")
    async def disconnect(self, interaction: discord.Interaction):
        player = interaction.guild.voice_client if interaction.guild else None
        if not player or not player.connected: # Check connected status
            await interaction.response.send_message("Not connected to a voice channel.", ephemeral=True)
            return
        
        # Optional: Check if user is in the bot's channel
        # if interaction.user.voice and interaction.user.voice.channel == player.channel:
        await player.disconnect() 
        await interaction.response.send_message("Disconnected from the voice channel. Queue cleared.")
        # else:
        #     await interaction.response.send_message("You must be in the bot's voice channel to disconnect it.", ephemeral=True)


    @app_commands.command(name="skip", description="Skips the current song.")
    async def skip(self, interaction: discord.Interaction):
        player = await self.ensure_voice_client(interaction)
        if not player: # ensure_voice_client sends its own message
            return
        
        if not player.playing and not player.paused : # Nothing loaded/playing
            await interaction.response.send_message("Nothing is currently playing to skip.", ephemeral=True)
            return
        
        current_track_title = player.current.title if player.current else "The current track"
        # Wavelink's skip() should trigger on_wavelink_track_end, which handles playing next.
        await player.skip(force=True) # force=True ensures it skips even if it was only paused.
        await interaction.response.send_message(f"⏭️ Skipped **{current_track_title}**.")
        # No need to manually play next here, on_wavelink_track_end handles it.

    @app_commands.command(name="queue", description="Shows the current music queue.")
    async def queue(self, interaction: discord.Interaction):
        player = await self.ensure_voice_client(interaction)
        if not player:
            # ensure_voice_client sends its own message, but a fallback here is fine.
            # await interaction.response.send_message("Not connected or not in a valid voice channel.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=False) # Defer as fetching user info might take time

        embed = discord.Embed(title="🎵 Music Queue 🎵", color=discord.Color.og_blurple()) # Changed color
        
        if player.current:
            requester_mention = getattr(player.current.extras, 'requester_mention', "N/A")
            current_title = getattr(player.current.extras, 'display_title', player.current.title or 'Unknown Title')
            embed.add_field(
                name="▶️ Now Playing",
                value=f"**[{current_title}]({player.current.uri or 'URL not available'})** ({format_duration(player.current.length)})\nRequested by: {requester_mention}",
                inline=False
            )
        else:
            embed.add_field(name="▶️ Now Playing", value="Nothing is currently playing.", inline=False)


        if player.queue.is_empty:
            embed.add_field(name="📜 Up Next", value="The queue is empty. Use `/play` to add songs!", inline=False)
        else:
            queue_display_limit = 10 # Show up to 10 tracks
            queue_text_list = []
            # Iterate through a copy for safety if queue can be modified elsewhere concurrently
            for i, track in enumerate(list(player.queue)[:queue_display_limit], start=1):
                track_requester_mention = getattr(track.extras, 'requester_mention', "N/A")
                title_to_display = getattr(track.extras, 'display_title', track.title or 'Unknown Title')
                duration = format_duration(track.length)
                queue_text_list.append(f"`{i}.` **[{title_to_display}]({track.uri or 'URL not available'})** ({duration}) - Req: {track_requester_mention}")
            
            # Use description for a cleaner list if it's long
            embed.description = "\n".join(queue_text_list) if queue_text_list else "The queue is empty."


            if len(player.queue) > queue_display_limit:
                embed.set_footer(text=f"And {len(player.queue) - queue_display_limit} more track(s)...")
        
        # Add queue mode status
        if player.queue.mode == wavelink.QueueMode.loop:
            embed.add_field(name="🔁 Loop Mode", value="Looping (Track)", inline=True)
        elif player.queue.mode == wavelink.QueueMode.loop_all:
            embed.add_field(name="🔁 Loop Mode", value="Looping (Queue)", inline=True)
        # else wavelink.QueueMode.normal (no loop)

        embed.add_field(name="🔢 Queue Length", value=str(player.queue.count), inline=True)


        await interaction.followup.send(embed=embed)

    @app_commands.command(name="pause", description="Pauses the currently playing track.")
    async def pause(self, interaction: discord.Interaction):
        player = await self.ensure_voice_client(interaction)
        if not player:
            return

        await interaction.response.defer()

        if not player.playing: # Check if actually playing
            await interaction.followup.send("Nothing is currently playing to pause.", ephemeral=True)
            return

        if player.paused:
            await interaction.followup.send("Playback is already paused.", ephemeral=True)
            return

        await player.pause(True)
        await interaction.followup.send("⏸️ Playback paused.")

    @app_commands.command(name="resume", description="Resumes the currently paused track.")
    async def resume(self, interaction: discord.Interaction):
        player = await self.ensure_voice_client(interaction)
        if not player:
            return

        await interaction.response.defer()
        
        if not player.paused: # Check if actually paused
            await interaction.followup.send("Playback is not paused, or nothing to resume.", ephemeral=True)
            return

        await player.pause(False)
        await interaction.followup.send("▶️ Playback resumed.")

    @app_commands.command(name="info", description="Shows information about the currently playing song.")
    async def info(self, interaction: discord.Interaction):
        player = await self.ensure_voice_client(interaction)
        if not player:
            return

        await interaction.response.defer()

        current_track = player.current
        if not current_track:
            await interaction.followup.send("Nothing is currently playing.", ephemeral=True)
            return

        embed = discord.Embed(title="💿 Song Information", color=discord.Color.green())
        
        title_to_display = getattr(current_track.extras, 'display_title', current_track.title or "Unknown Title")
        embed.description=f"**[{title_to_display}]({current_track.uri or 'URL not available'})**"

        thumbnail_url = None
        if hasattr(current_track, 'artwork') and current_track.artwork:
            thumbnail_url = current_track.artwork
        elif hasattr(current_track, 'thumb') and current_track.thumb: # youtube_dl often provides 'thumb' for Playable objects from search
            thumbnail_url = current_track.thumb

        if thumbnail_url:
            embed.set_thumbnail(url=thumbnail_url)

        embed.add_field(name="👤 Artist/Author", value=current_track.author or "Unknown Artist", inline=True)
        embed.add_field(name="⏱️ Duration", value=format_duration(current_track.length), inline=True) # Verified .length
        
        requester_mention = getattr(current_track.extras, 'requester_mention', "Unknown User") # Verified getattr
        embed.add_field(name="🙋 Requested by", value=requester_mention, inline=True)

        embed.add_field(name="🎵 Source", value=current_track.source.replace('_', ' ').title() if current_track.source else "Unknown Source", inline=True)

        # Loop status
        if player.queue.mode == wavelink.QueueMode.loop: # Track loop
            embed.add_field(name="🔁 Looping", value="Current Track", inline=True)
        elif player.queue.mode == wavelink.QueueMode.loop_all: # Queue loop
            embed.add_field(name="🔁 Looping", value="Entire Queue", inline=True)
        else: # wavelink.QueueMode.normal
            embed.add_field(name="🔁 Looping", value="Disabled", inline=True)

        embed.add_field(name="🔊 Volume", value=f"{player.volume}%", inline=True)
        
        if player.queue and player.current:
            embed.add_field(name="📊 Queue Position", value=f"Currently Playing", inline=True)
        
        embed.add_field(name="ℹ️ Track ID (Debug)", value=f"`{current_track.identifier}`", inline=False)

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="shuffle", description="Shuffles the current queue.")
    async def shuffle(self, interaction: discord.Interaction):
        player = await self.ensure_voice_client(interaction)
        if not player:
            return

        await interaction.response.defer()

        if player.queue.is_empty:
            await interaction.followup.send("The queue is empty, nothing to shuffle.", ephemeral=True)
            return

        player.queue.shuffle()
        await interaction.followup.send("Queue shuffled.")

    @app_commands.command(name="loop", description="Toggles looping for the current track or the entire queue.")
    @app_commands.describe(mode="Choose loop mode")
    async def loop(self, interaction: discord.Interaction, mode: wavelink.QueueMode):
        player = await self.ensure_voice_client(interaction)
        if not player:
            return

        await interaction.response.defer()
        
        player.queue.mode = mode # mode is already a wavelink.QueueMode enum instance due to type hint
        
        if mode == wavelink.QueueMode.loop: # Single track loop
            await interaction.followup.send("Looping current track activated.")
        elif mode == wavelink.QueueMode.loop_all: # Entire queue loop
            await interaction.followup.send("Looping entire queue activated.")
        elif mode == wavelink.QueueMode.normal: # No loop
            await interaction.followup.send("Looping disabled.")
        else:
            # This case should ideally not be reached if mode is correctly typed to the enum
            await interaction.followup.send("Invalid loop mode specified.", ephemeral=True)

    @app_commands.command(name="skipto", description="Skips to a specific track in the queue.")
    @app_commands.describe(track_number="The track number to skip to (starts at 1)")
    async def skipto(self, interaction: discord.Interaction, track_number: app_commands.Range[int, 1]):
        player = await self.ensure_voice_client(interaction)
        if not player:
            return

        await interaction.response.defer()

        if player.queue.is_empty:
            await interaction.followup.send("The queue is empty.", ephemeral=True)
            return

        # track_number is 1-indexed. Convert to 0-indexed for list slicing.
        target_zero_indexed = track_number - 1

        # Use list(player.queue) to get a copy for consistent length checking
        current_queue_list = list(player.queue)
        if not (0 <= target_zero_indexed < len(current_queue_list)):
            await interaction.followup.send(f"Invalid track number. Must be between 1 and {len(current_queue_list)}.", ephemeral=True)
            return

        # Get all current queue items
        # current_queue_items = list(player.queue) # Already got current_queue_list

        # Clear the live queue
        player.queue.clear()

        # Add back the tracks from the target track to the end
        for i in range(target_zero_indexed, len(current_queue_list)):
            player.queue.put(current_queue_list[i])
        
        # If something is playing or paused, skip to initiate playing the new first track from the modified queue.
        # If nothing was playing, and the queue is now not empty, start playback.
        if player.playing or player.paused:
            await player.skip(force=True)
            # on_wavelink_track_end should handle playing the new first item if queue not empty
        elif not player.queue.is_empty:
            # This case handles if the player was stopped but queue was not empty and skipto is used.
            # Or if skipto is used on an empty playing queue (after current song finished)
            try:
                first_track = player.queue.get() # Get the track we want to start
                await player.play(first_track)
                # No need to send "Now playing" here, as on_wavelink_track_start should handle it globally if implemented
                # or the individual play command for local files already sent a message.
            except Exception as e:
                logger.error(f"Error trying to play after skipto on idle player: {e}", exc_info=True)
                await interaction.followup.send("Skipped, but could not automatically start the track.", ephemeral=True)
        # If player was not playing and queue is now empty (e.g. skipped to end of a 1-item queue), do nothing more.

        await interaction.followup.send(f"Skipped to track {track_number}.")


    @app_commands.command(name="volume", description="Sets the player volume (0-1000).")
    @app_commands.describe(level="The volume level (e.g., 100 for default)")
    async def volume(self, interaction: discord.Interaction, level: app_commands.Range[int, 0, 1000]):
        player = await self.ensure_voice_client(interaction)
        if not player:
            return

        await interaction.response.defer()
        
        await player.set_volume(level)
        # Store volume on player instance if you want it to persist for this session's client
        # player.volume = level 
        await interaction.followup.send(f"🔊 Volume set to {level}%.")

    @app_commands.command(name="stop", description="Stops the music, clears the queue, and disconnects the bot.")
    async def stop(self, interaction: discord.Interaction):
        player = interaction.guild.voice_client if interaction.guild else None

        if player and player.connected:
            # Optional: Check if user is in the same channel
            # if not interaction.user.voice or interaction.user.voice.channel != player.channel:
            #    await interaction.response.send_message(f"You must be in the bot's voice channel ({player.channel.mention}) to stop it.", ephemeral=True)
            #    return

            await interaction.response.defer() 
            
            player.queue.clear() 
            await player.stop() # Stop current track. This should trigger TrackEndEvent.
            await player.disconnect() 
            
            await interaction.followup.send("⏹️ Music stopped, queue cleared, and disconnected.")
        else:
            await interaction.response.send_message("Not connected to any voice channel or no player available.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(MusicCog(bot)) # Ensure class name is updated here too

