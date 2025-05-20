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

class Music(commands.Cog):
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

        if not interaction.user.voice:
            await interaction.response.send_message("You must be in a voice channel to use this command.", ephemeral=True)
            return None

        player = interaction.guild.voice_client

        if not player:
            try:
                player = await interaction.user.voice.channel.connect(cls=wavelink.Player)
                player.text_channel = interaction.channel
                player.volume = self.default_volume
            except Exception as e:
                await interaction.response.send_message("Failed to join voice channel.", ephemeral=True)
                return None
        
        return player

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload):
        player = payload.player
        if not player or not player.guild:
            return

        if payload.reason in ('FINISHED', 'LOAD_FAILED') and not player.queue.is_empty:
            try:
                next_track = player.queue.get()
                await player.play(next_track)
            except Exception:
                pass
        elif payload.reason in ('FINISHED', 'STOPPED') and player.queue.is_empty:
            self._schedule_inactivity_check(player.guild.id)

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
            if not search_result:
                await interaction.followup.send("No results found.", ephemeral=True)
                return

            requester_id = interaction.user.id # Store requester ID once

            if isinstance(search_result, wavelink.Playlist):
                playlist = search_result
                tracks_from_playlist = playlist.tracks[:self.max_playlist_size] # Initial slice respecting max_playlist_size
                
                if not tracks_from_playlist:
                    await interaction.followup.send(f"Playlist **{playlist.name}** is empty or no tracks could be loaded.", ephemeral=True)
                    return
                
                tracks_actually_queued = []
                played_from_playlist = None
                queue_full_message = ""

                # Try to play the first track if player is idle and playlist is not empty
                if not player.playing and not player.paused: 
                    if tracks_from_playlist: # Ensure there's a track to pop
                        played_from_playlist = tracks_from_playlist.pop(0) # Take from the list to avoid queuing it again
                        played_from_playlist.extras = {'requester': requester_id}
                        await player.play(played_from_playlist)
                        # Primary response will be about this track playing. Other messages use interaction.channel.
                
                # Queue remaining tracks from the (potentially modified) tracks_from_playlist list
                for track_to_queue in tracks_from_playlist:
                    if player.queue.count >= self.max_queue_size:
                        if playlist.tracks_count > len(tracks_actually_queued) + (1 if played_from_playlist else 0) :
                             queue_full_message = f"Queue is full. Not all songs from **{playlist.name}** were added."
                        break 
                    track_to_queue.extras = {'requester': requester_id}
                    player.queue.put(track_to_queue)
                    tracks_actually_queued.append(track_to_queue)

                # Send feedback messages
                if played_from_playlist:
                    await interaction.followup.send(f"Playing: **{played_from_playlist.title}** (from playlist **{playlist.name}**)")
                    if tracks_actually_queued:
                        await interaction.channel.send(f"Queued an additional {len(tracks_actually_queued)} songs from **{playlist.name}**.")
                    if queue_full_message:
                        await interaction.channel.send(queue_full_message, ephemeral=True)
                    # Optional: message if playlist was truncated by max_playlist_size but queue wasn't full
                    elif len(playlist.tracks) > self.max_playlist_size and not queue_full_message:
                        await interaction.channel.send(f"Playlist was truncated to the first {self.max_playlist_size} songs.",ephemeral=True)
                
                elif tracks_actually_queued: # Nothing played from playlist (player was busy), but songs were queued
                    await interaction.followup.send(f"Queued {len(tracks_actually_queued)} songs from playlist **{playlist.name}**.")
                    if queue_full_message:
                        await interaction.channel.send(queue_full_message, ephemeral=True)
                    elif len(playlist.tracks) > self.max_playlist_size and not queue_full_message:
                         await interaction.channel.send(f"Playlist was truncated to the first {self.max_playlist_size} songs.",ephemeral=True)

                else: # No track played from playlist, no tracks queued
                    final_message = f"No songs added from **{playlist.name}**."
                    if queue_full_message: 
                        final_message = queue_full_message
                    elif not playlist.tracks : # check original playlist attribute if available, otherwise assume initial check was enough
                         final_message = f"Playlist **{playlist.name}** is empty." # Should have been caught earlier
                    else: # e.g. queue was full initially, or playlist had 1 song which couldn't be played (player busy)
                         final_message = f"Could not add songs from **{playlist.name}**. The queue might have been full or the player busy."
                    await interaction.followup.send(final_message, ephemeral=True)

            else: # Single track or search result (list of Playable)
                single_track = search_result[0]
                single_track.extras = {'requester': requester_id}

                if player.playing or player.paused: # player.paused implies something is loaded
                    if player.queue.count >= self.max_queue_size:
                        await interaction.followup.send("Queue is full.", ephemeral=True)
                        return
                    player.queue.put(single_track)
                    await interaction.followup.send(f"Queued: **{single_track.title}**")
                else:
                    await player.play(single_track)
                    await interaction.followup.send(f"Playing: **{single_track.title}**")

        except Exception as e:
            # Log the error for debugging
            # logging.error(f"Error in /play command: {e}", exc_info=True) 
            await interaction.followup.send(f"Failed to process request. Details: {str(e)}", ephemeral=True)

    @app_commands.command(name="disconnect", description="Disconnects the bot")
    async def disconnect(self, interaction: discord.Interaction):
        player = interaction.guild.voice_client
        if not player:
            await interaction.response.send_message("Not connected.", ephemeral=True)
            return

        await player.disconnect()
        await interaction.response.send_message("Disconnected.")

    @app_commands.command(name="skip", description="Skips the current song")
    async def skip(self, interaction: discord.Interaction):
        player = interaction.guild.voice_client
        if not player or not player.playing:
            await interaction.response.send_message("Nothing to skip.", ephemeral=True)
            return

        await player.skip()
        await interaction.response.send_message("⏭️ Skipped.")

    @app_commands.command(name="queue", description="Shows the current queue")
    async def queue(self, interaction: discord.Interaction):
        player = interaction.guild.voice_client
        if not player:
            await interaction.response.send_message("Not playing anything.", ephemeral=True)
            return

        embed = discord.Embed(title="Queue", color=discord.Color.blue())
        
        if player.current:
            embed.add_field(
                name="Now Playing",
                value=f"**{player.current.title}**\nRequested by: <@{player.current.extras.get('requester')}>",
                inline=False
            )

        queue_list = []
        for i, track in enumerate(player.queue, start=1):
            queue_list.append(f"{i}. **{track.title}**")
        
        if queue_list:
            embed.add_field(name="Up Next", value="\n".join(queue_list[:10]), inline=False)
            if len(queue_list) > 10:
                embed.set_footer(text=f"And {len(queue_list) - 10} more...")
        else:
            embed.add_field(name="Up Next", value="Nothing in queue", inline=False)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="pause", description="Pauses the currently playing track.")
    async def pause(self, interaction: discord.Interaction):
        player = await self.ensure_voice_client(interaction)
        if not player:
            return

        await interaction.response.defer()

        if not player.playing:
            await interaction.followup.send("Nothing is currently playing.", ephemeral=True)
            return

        if player.paused:
            await interaction.followup.send("Playback is already paused.", ephemeral=True)
            return

        await player.pause()
        await interaction.followup.send("Playback paused.")

    @app_commands.command(name="resume", description="Resumes the currently paused track.")
    async def resume(self, interaction: discord.Interaction):
        player = await self.ensure_voice_client(interaction)
        if not player:
            return

        await interaction.response.defer()

        # Check if there's something to resume (player might exist but not be playing anything)
        if not player.current and not player.paused:
             await interaction.followup.send("Nothing is currently playing or paused to resume.", ephemeral=True)
             return
        
        if not player.paused:
            await interaction.followup.send("Playback is not paused.", ephemeral=True)
            return

        await player.resume()
        await interaction.followup.send("Playback resumed.")

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

        embed = discord.Embed(title="Now Playing", color=discord.Color.blue())
        embed.add_field(name="Title", value=current_track.title or "Unknown Title", inline=False)
        embed.add_field(name="Author", value=current_track.author or "Unknown Author", inline=False)
        embed.add_field(name="Duration", value=format_duration(current_track.duration), inline=True)
        embed.add_field(name="Source", value=current_track.source or "Unknown Source", inline=True)
        if current_track.uri:
            embed.add_field(name="URL", value=current_track.uri, inline=False)
        
        requester_id = current_track.extras.get('requester')
        if requester_id:
            # Try to get user object, otherwise show ID
            requester_user = self.bot.get_user(int(requester_id))
            requester_display = requester_user.mention if requester_user else f"<@{requester_id}>"
            embed.add_field(name="Requested by", value=requester_display, inline=True)
        
        # Add thumbnail
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
        await interaction.followup.send(f"Volume set to {level}%.")

async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))

