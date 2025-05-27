import discord
from discord import app_commands
from discord.ext import commands
import wavelink
import re
import math
import asyncio
import os
from typing import Optional, Union

URL_REGEX = re.compile(r'https?://(?:www\.)?.+')

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

        if reason == wavelink.TrackEndReason.FINISHED:
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
        
        elif reason == wavelink.TrackEndReason.LOAD_FAILED:
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

        elif reason == wavelink.TrackEndReason.STOPPED: # Track was stopped by a command like /stop or /skip
            if player.queue.is_empty and player.connected: # If /skip made queue empty
                 if hasattr(player, 'text_channel') and player.text_channel:
                    await player.text_channel.send("Queue finished. Bot will disconnect if inactive.")
                 self._schedule_inactivity_check(player.guild.id)
            # If /stop was used, player will likely be disconnected by the command itself.
            # If /skip was used and queue is not empty, track_end for skip should trigger next play.

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
            logger.error(f"LavalinkLoadException in /play. Error: {e.error}, Data: {e.data}", exc_info=False)
            error_message = e.data.get('message', 'No specific message from Lavalink.')
            await interaction.followup.send(f"Lavalink error: {e.error}. Details: {error_message}. This might be due to restrictions on the track/playlist or a Lavalink server issue.", ephemeral=True)
        except Exception as e:
            # Log the error for server-side diagnosis
            # logger.exception(f"Unexpected error in /play command: {e}")
            await interaction.followup.send(f"An unexpected error occurred while processing your request. Please try again later. Details: {str(e)}", ephemeral=True)

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
            requester_mention = player.current.extras.get('requester_mention', "N/A")
            embed.add_field(
                name="▶️ Now Playing",
                value=f"**[{player.current.title}]({player.current.uri or 'URL not available'})** ({format_duration(player.current.duration)})\nRequested by: {requester_mention}",
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
                track_requester_mention = track.extras.get('requester_mention', "N/A")
                duration = format_duration(track.duration)
                queue_text_list.append(f"`{i}.` **[{track.title}]({track.uri or 'URL not available'})** ({duration}) - Req: {track_requester_mention}")
            
            # Use description for a cleaner list if it's long
            embed.description = "\n".join(queue_text_list) if queue_text_list else "The queue is empty."


            if len(player.queue) > queue_display_limit:
                embed.set_footer(text=f"And {len(player.queue) - queue_display_limit} more track(s)...")
        
        # Add queue mode status
        if player.queue.mode != wavelink.QueueMode.normal:
             embed.add_field(name="🔁 Loop Mode", value=f"Current mode: **{player.queue.mode.name.replace('_', ' ').title()}**", inline=True)
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

        await player.pause()
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

        await player.resume()
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

        embed = discord.Embed(title="💿 Song Information", color=discord.Color.green()) # Changed color
        
        # Main track details
        embed.description=f"**[{current_track.title}]({current_track.uri or 'URL not available'})**"
        # Thumbnail
        if current_track.artwork_url: # Wavelink 3+ uses artwork_url
            embed.set_thumbnail(url=current_track.artwork_url)
        elif hasattr(current_track, 'thumb') and current_track.thumb: # Fallback for older or other attributes
            embed.set_thumbnail(url=current_track.thumb)

        embed.add_field(name="👤 Artist/Author", value=current_track.author or "Unknown Artist", inline=True)
        embed.add_field(name="⏱️ Duration", value=format_duration(current_track.duration), inline=True)
        
        requester_mention = current_track.extras.get('requester_mention', "Unknown User")
        embed.add_field(name="🙋 Requested by", value=requester_mention, inline=True)

        embed.add_field(name="🎵 Source", value=current_track.source.replace('_', ' ').title() if current_track.source else "Unknown Source", inline=True)
        # Check current track loop status specifically if QueueMode.loop is active for the current track
        is_track_looping = "Yes" if player.queue.mode == wavelink.QueueMode.loop and player.current == current_track else "No"
        embed.add_field(name="🔁 Looping (Track)", value=is_track_looping, inline=True)
        embed.add_field(name="🔊 Volume", value=f"{player.volume}%", inline=True)
        
        # Queue specific info if available
        if player.queue and player.current: # Redundant check for player.current, but safe
            # For current track, its "position" is that it's playing.
            embed.add_field(name="📊 Queue Position", value=f"Currently Playing", inline=True)
        
        # Add a field for overall queue loop status if it's loop_all
        if player.queue.mode == wavelink.QueueMode.loop_all:
            embed.add_field(name="🔁 Looping (Queue)", value="Yes (Loop All)", inline=True)

        embed.add_field(name="ℹ️ Track ID (Debug)", value=f"`{current_track.identifier}`", inline=False)
        
        thumbnail_url = None
        if hasattr(current_track, 'artwork_url') and current_track.artwork_url: # For new wavelink
             thumbnail_url = current_track.artwork_url
        elif hasattr(current_track, 'artwork') and current_track.artwork: # older wavelink or other attribute
             thumbnail_url = current_track.artwork
        elif hasattr(current_track, 'thumb') and current_track.thumb: # some sources use thumb
            thumbnail_url = current_track.thumb
        
        if thumbnail_url:
            embed.set_thumbnail(url=thumbnail_url)

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
        
        player.queue.mode = mode
        
        if mode == wavelink.QueueMode.loop:
            await interaction.followup.send("Looping current track.")
        elif mode == wavelink.QueueMode.loop_all:
            await interaction.followup.send("Looping entire queue.")
        elif mode == wavelink.QueueMode.normal:
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

        if not (1 <= track_number <= len(player.queue)):
            await interaction.followup.send(f"Invalid track number. Must be between 1 and {len(player.queue)}.", ephemeral=True)
            return
        
        target_track_index = track_number - 1
        player.queue.skip_to_index(target_track_index)
        
        # player.skip() will stop the current track and Lavalink will send an event.
        # The on_wavelink_track_end event will then play the next track in queue,
        # which is now the track we skipped to.
        # If nothing is playing, skip won't trigger track_end, so we also need to ensure play if stopped.
        if player.playing or player.paused:
            await player.skip(force=True) # force=True to ensure it skips even if paused.
        else: # If player was stopped but queue was not empty
            next_track = player.queue.get()
            if next_track:
                await player.play(next_track)

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

