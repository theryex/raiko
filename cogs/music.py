import discord
from discord import app_commands
from discord.ext import commands
import wavelink
import re
import math
import asyncio
import os
from typing import Optional, cast, Union

URL_REGEX = re.compile(r'https?://(?:www\.)?.+')

def format_duration(milliseconds: Optional[Union[int, float]]) -> str:
    if milliseconds is None:
        return "0:00"
    try:
        ms = int(float(milliseconds))
    except (ValueError, TypeError):
        return "Invalid"

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

class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.inactivity_timers: dict[int, asyncio.Task] = {}
        self.default_volume = int(os.getenv('DEFAULT_VOLUME', 100))
        self.max_queue_size = int(os.getenv('MAX_QUEUE_SIZE', 1000))
        self.max_playlist_size = int(os.getenv('MAX_PLAYLIST_SIZE', 100))

    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, payload: wavelink.NodeReadyEventPayload):
        pass

    @commands.Cog.listener()
    async def on_wavelink_websocket_closed(self, payload: wavelink.WebsocketClosedEventPayload):
        pass

    @commands.Cog.listener()
    async def on_wavelink_track_start(self, payload: wavelink.TrackStartEventPayload):
        player = payload.player
        track = payload.track
        if not player or not player.guild: return

        guild_id = player.guild.id

        if guild_id in self.inactivity_timers:
            self.inactivity_timers[guild_id].cancel()
            del self.inactivity_timers[guild_id]

        if hasattr(player, 'text_channel') and player.text_channel:
            channel = player.text_channel
            title = discord.utils.escape_markdown(track.title or "Unknown Title")
            uri = track.uri or "#"
            author = discord.utils.escape_markdown(track.author or "Unknown Author")
            duration_ms = track.length
            requester_mention = ""
            if track.extras and 'requester' in track.extras:
                requester_mention = f"<@{track.extras['requester']}>"

            desc = f"[{title}]({uri})\nAuthor: {author}\nDuration: {format_duration(duration_ms)}\n"
            if requester_mention:
                desc += f"Requested by: {requester_mention}"

            embed = discord.Embed(color=discord.Color.green(), title="Now Playing", description=desc)
            if track.artwork:
                embed.set_thumbnail(url=track.artwork)
            elif track.preview_url and track.source == "youtube":
                embed.set_thumbnail(url=f"https://img.youtube.com/vi/{track.identifier}/mqdefault.jpg")

            try:
                await channel.send(embed=embed)
            except discord.errors.Forbidden:
                pass
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload):
        player = payload.player
        track = payload.track
        reason = payload.reason
        if not player or not player.guild: return

        guild_id = player.guild.id

        if reason in ('FINISHED', 'LOAD_FAILED') and not player.queue.is_empty:
            if not player.playing:
                try:
                    next_track = player.queue.get()
                    await player.play(next_track)
                except wavelink.QueueEmpty:
                    pass
                except Exception:
                    pass
        elif reason == 'FINISHED' and player.queue.is_empty:
            self._schedule_inactivity_check(guild_id)
        elif reason == 'STOPPED' and player.queue.is_empty:
            self._schedule_inactivity_check(guild_id)

    @commands.Cog.listener()
    async def on_wavelink_track_exception(self, payload: wavelink.TrackExceptionEventPayload):
        player = payload.player
        track = payload.track
        exception = payload.exception
        if not player or not player.guild: return

        guild_id = player.guild.id

        if hasattr(player, 'text_channel') and player.text_channel:
            channel = player.text_channel
            track_title = getattr(track, 'title', 'the track')
            error_msg = str(exception)
            try:
                await channel.send(f"💥 Error playing `{discord.utils.escape_markdown(track_title)}`: {error_msg}")
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_wavelink_track_stuck(self, payload: wavelink.TrackStuckEventPayload):
        player = payload.player
        track = payload.track
        threshold = payload.threshold_ms
        if not player or not player.guild: return

        guild_id = player.guild.id

        if hasattr(player, 'text_channel') and player.text_channel:
            channel = player.text_channel
            track_title = getattr(track, 'title', 'the track')
            try:
                await channel.send(f"⚠️ Track `{discord.utils.escape_markdown(track_title)}` seems stuck (>{threshold}ms), skipping...")
            except discord.HTTPException:
                pass

        try:
            await player.skip(force=True)
        except Exception:
            pass

    def _schedule_inactivity_check(self, guild_id: int):
        if guild_id in self.inactivity_timers:
            self.inactivity_timers[guild_id].cancel()

        disconnect_delay = 120
        task = asyncio.create_task(self._check_inactivity(guild_id, disconnect_delay))
        self.inactivity_timers[guild_id] = task
        task.add_done_callback(lambda t: self.inactivity_timers.pop(guild_id, None))

    async def _check_inactivity(self, guild_id: int, delay: int):
        await asyncio.sleep(delay)

        guild = self.bot.get_guild(guild_id)
        if not guild:
            return

        player: Optional[wavelink.Player] = guild.voice_client

        if player and player.connected and not player.playing and player.queue.is_empty:
            if hasattr(player, 'text_channel') and player.text_channel:
                try:
                    await player.text_channel.send("Disconnected due to inactivity.")
                except discord.HTTPException:
                    pass
            await player.disconnect(force=True)
        elif player and (player.playing or not player.queue.is_empty):
            pass

    def cog_unload(self):
        for task in self.inactivity_timers.values():
            task.cancel()
        self.inactivity_timers.clear()

    async def cog_before_invoke(self, ctx: commands.Context):
        if not ctx.guild:
            raise commands.NoPrivateMessage("This command can't be used in DMs.")
        return True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            await interaction.response.send_message("This command can only be used in a server!", ephemeral=True)
            return False

        node = wavelink.Pool.get_node()
        if not node or not node.is_connected:
            await interaction.response.send_message("Music service is not available.", ephemeral=True)
            return False
        return True

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        original = getattr(error, 'original', error)
        command_name = interaction.command.name if interaction.command else 'unknown'

        error_message = f"An unexpected error occurred while running `/{command_name}`."

        if isinstance(original, app_commands.CheckFailure):
            error_message = "You don't have the necessary permissions or conditions to run this command."
        elif isinstance(original, app_commands.MissingPermissions):
            error_message = f"You lack the required permissions: {', '.join(original.missing_permissions)}"
        elif isinstance(original, app_commands.BotMissingPermissions):
            error_message = f"I lack the required permissions: {', '.join(original.missing_permissions)}"
        elif isinstance(original, wavelink.WavelinkException):
            error_message = f"Music service error: {original}"

        try:
            if interaction.response.is_done():
                await interaction.followup.send(f"❌ {error_message}", ephemeral=True)
            else:
                await interaction.response.send_message(f"❌ {error_message}", ephemeral=True)
        except discord.HTTPException:
            pass

    @app_commands.command(name="play", description="Plays or queues music (YouTube, SoundCloud, Spotify URL/Search).")
    @app_commands.describe(query='URL or search term')
    async def play(self, interaction: discord.Interaction, *, query: str):
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message("You need to be in a voice channel.", ephemeral=True)
        user_channel = interaction.user.voice.channel

        player: wavelink.Player
        if not interaction.guild.voice_client:
            try:
                player = await user_channel.connect(cls=wavelink.Player, self_deaf=True)
            except discord.ClientException:
                return await interaction.response.send_message("Already connecting to a voice channel.", ephemeral=True)
            except asyncio.TimeoutError:
                return await interaction.response.send_message("Timed out connecting to the voice channel.", ephemeral=True)
            except Exception as e:
                return await interaction.response.send_message(f"Failed to connect: {e}", ephemeral=True)
        else:
            player = cast(wavelink.Player, interaction.guild.voice_client)
            if player.channel.id != user_channel.id:
                return await interaction.response.send_message(f"You must be in the same voice channel as the bot (<#{player.channel.id}>).", ephemeral=True)

        player.text_channel = interaction.channel
        await player.set_volume(self.default_volume)

        await interaction.response.defer(thinking=True)

        try:
            search_query = query.strip('<>')
            tracks: wavelink.Search = await wavelink.Playable.search(search_query)

            if not tracks:
                return await interaction.followup.send(f"Could not find any results for `{query}`.", ephemeral=True)

        except wavelink.LavalinkLoadException as e:
            return await interaction.followup.send(f"Error loading tracks: {e}", ephemeral=True)
        except Exception:
            return await interaction.followup.send("An unexpected error occurred during search.", ephemeral=True)

        added_count = 0
        skipped_count = 0
        followup_message = ""

        if isinstance(tracks, wavelink.Playlist):
            playlist_name = tracks.name or "Unnamed Playlist"
            tracks_to_consider = tracks.tracks[:self.max_playlist_size]

            tracks_to_add = []
            for track in tracks_to_consider:
                if player.queue.count + added_count < self.max_queue_size:
                    track.extras = {'requester': interaction.user.id}
                    tracks_to_add.append(track)
                    added_count += 1
                else:
                    skipped_count += 1

            if tracks_to_add:
                player.queue.extend(tracks_to_add)

            followup_message = f"✅ Added **{added_count}** tracks from playlist **`{discord.utils.escape_markdown(playlist_name)}`**."
            if len(tracks.tracks) > self.max_playlist_size:
                followup_message += f" (Playlist capped at {self.max_playlist_size})"
            if skipped_count > 0:
                followup_message += f" (Queue full, skipped {skipped_count})"

        elif tracks:
            track = tracks[0]
            if player.queue.count < self.max_queue_size:
                track.extras = {'requester': interaction.user.id}
                await player.queue.put_wait(track)
                followup_message = f"✅ Added **`{discord.utils.escape_markdown(track.title)}`** to the queue."
                added_count = 1
            else:
                followup_message = f"❌ Queue is full (Max: {self.max_queue_size}). Could not add **`{discord.utils.escape_markdown(track.title)}`**."

        else:
            followup_message = "Received an unexpected empty result."

        await interaction.followup.send(followup_message)

        if added_count > 0 and not player.playing:
            first_track = player.queue.get()
            await player.play(first_track)

    @app_commands.command(name="disconnect", description="Disconnects the bot from the voice channel.")
    async def disconnect(self, interaction: discord.Interaction):
        player: Optional[wavelink.Player] = interaction.guild.voice_client

        if not player or not player.connected:
            return await interaction.response.send_message("Not connected to any voice channel.", ephemeral=True)

        player.queue.clear()
        await player.stop()
        await player.disconnect()

        if interaction.guild.id in self.inactivity_timers:
            self.inactivity_timers[interaction.guild.id].cancel()

        await interaction.response.send_message("Disconnected and cleared queue.")

    @app_commands.command(name="stop", description="Stops the music and clears the queue.")
    async def stop(self, interaction: discord.Interaction):
        player: Optional[wavelink.Player] = interaction.guild.voice_client

        if not player or not player.connected:
            return await interaction.response.send_message("Not connected.", ephemeral=True)

        if not player.playing and player.queue.is_empty:
            return await interaction.response.send_message("Nothing is playing and the queue is empty.", ephemeral=True)

        player.queue.clear()
        await player.stop()

        self._schedule_inactivity_check(interaction.guild.id)

        await interaction.response.send_message("⏹️ Music stopped and queue cleared.")

    @app_commands.command(name="skip", description="Skips the current song.")
    async def skip(self, interaction: discord.Interaction):
        player: Optional[wavelink.Player] = interaction.guild.voice_client

        if not player or not player.connected:
            return await interaction.response.send_message("Not connected.", ephemeral=True)

        current_track = player.current
        if not current_track:
            return await interaction.response.send_message("No song is currently playing to skip.", ephemeral=True)

        current_title = discord.utils.escape_markdown(current_track.title)

        await player.skip(force=True)

        await interaction.response.send_message(f"⏭️ Skipped **`{current_title}`**.")

    @app_commands.command(name="pause", description="Pauses the current song.")
    async def pause(self, interaction: discord.Interaction):
        player: Optional[wavelink.Player] = interaction.guild.voice_client

        if not player or not player.connected:
            return await interaction.response.send_message("Not connected.", ephemeral=True)

        if not player.playing:
            return await interaction.response.send_message("No song is currently playing.", ephemeral=True)

        if player.paused:
            return await interaction.response.send_message("Music is already paused.", ephemeral=True)

        await player.pause()
        await interaction.response.send_message("⏸️ Music paused.")

    @app_commands.command(name="resume", description="Resumes the paused song.")
    async def resume(self, interaction: discord.Interaction):
        player: Optional[wavelink.Player] = interaction.guild.voice_client

        if not player or not player.connected:
            return await interaction.response.send_message("Not connected.", ephemeral=True)

        if player.playing and not player.paused:
            return await interaction.response.send_message("Music is not paused.", ephemeral=True)

        if not player.current and player.queue.is_empty:
            return await interaction.response.send_message("Nothing is loaded to resume.", ephemeral=True)

        await player.resume()
        await interaction.response.send_message("▶️ Music resumed.")

    @app_commands.command(name="loop", description="Cycles through loop modes: OFF -> TRACK -> QUEUE -> OFF.")
    async def loop(self, interaction: discord.Interaction):
        player: Optional[wavelink.Player] = interaction.guild.voice_client

        if not player or not player.connected:
            return await interaction.response.send_message("Not connected.", ephemeral=True)

        current_mode = player.queue.mode

        if current_mode == wavelink.QueueMode.loop:
            next_mode = wavelink.QueueMode.loop_all
            mode_str = "QUEUE"
        elif current_mode == wavelink.QueueMode.loop_all:
            next_mode = wavelink.QueueMode.normal
            mode_str = "OFF"
        else:
            if not player.current and player.queue.is_empty:
                return await interaction.response.send_message("Cannot enable loop: Nothing is playing or queued.", ephemeral=True)
            next_mode = wavelink.QueueMode.loop
            mode_str = "TRACK"

        player.queue.mode = next_mode
        await interaction.response.send_message(f"🔁 Loop mode set to **{mode_str}**.")

    @app_commands.command(name="shuffle", description="Shuffles the current queue.")
    async def shuffle(self, interaction: discord.Interaction):
        player: Optional[wavelink.Player] = interaction.guild.voice_client

        if not player or not player.connected:
            return await interaction.response.send_message("Not connected.", ephemeral=True)

        if player.queue.count < 2:
            return await interaction.response.send_message("The queue needs at least 2 songs to shuffle.", ephemeral=True)

        player.queue.shuffle()

        await interaction.response.send_message(f"🔀 Queue has been shuffled.")

    @app_commands.command(name="queue", description="Displays the current song queue.")
    @app_commands.describe(page="Page number of the queue to display")
    async def queue(self, interaction: discord.Interaction, page: app_commands.Range[int, 1] = 1):
        player: Optional[wavelink.Player] = interaction.guild.voice_client

        embed = discord.Embed(title="Music Queue", color=discord.Color.blue())

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

        if not player or player.queue.is_empty:
            embed.add_field(name="Up Next", value="*The queue is empty.*", inline=False)
            embed.set_footer(text="Page 1/1 | 0 songs | Total duration: 0:00")
        else:
            items_per_page = 10
            queue_list = list(player.queue)
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

            queue_duration_ms = sum(t.length for t in queue_list if t.length is not None)
            total_duration_str = format_duration(queue_duration_ms)
            embed.set_footer(text=f"{total_items} songs in queue | Total duration: {total_duration_str} | Page {page}/{total_pages}")

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="lowpass", description="Applies a low-pass filter (bass boost effect). Strength > 0 enables.")
    @app_commands.describe(strength="Filter strength (0.0 to disable, 0.1-1.0 recommended)")
    async def lowpass(self, interaction: discord.Interaction, strength: app_commands.Range[float, 0.0, 5.0]):
        player: Optional[wavelink.Player] = interaction.guild.voice_client

        if not player or not player.connected:
            return await interaction.response.send_message("Not connected.", ephemeral=True)

        strength = max(0.0, min(5.0, strength))

        embed = discord.Embed(color=discord.Color.blurple(), title='Low Pass Filter')

        try:
            current_filters = player.filters

            if strength <= 0.0:
                new_filter = wavelink.Filter()
                await player.set_filter(new_filter, seek=False)
                embed.description = 'Disabled **Low Pass Filter** (All filters reset).'
            else:
                new_filter = wavelink.Filter(low_pass=wavelink.LowPass(smoothing=strength))
                await player.set_filter(new_filter, seek=False)
                embed.description = f'Set **Low Pass Filter** smoothing to `{strength:.2f}` (Other filters reset).'

            await interaction.response.send_message(embed=embed)

        except wavelink.WavelinkException as e:
            await interaction.response.send_message(f"An error occurred applying the filter via Wavelink: {e}", ephemeral=True)
        except Exception:
            await interaction.response.send_message(f"An unexpected error occurred while applying the filter.", ephemeral=True)

async def setup(bot: commands.Bot):
    await asyncio.sleep(2)
    node = wavelink.Pool.get_node()
    if not node:
        raise commands.ExtensionFailed("Music", NameError("Wavelink node not available during Music cog setup"))

    await bot.add_cog(Music(bot))

