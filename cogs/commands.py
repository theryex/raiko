import discord
from discord import app_commands
from discord.ext import commands
import wavelink
import re
import math
import asyncio
import os
from typing import Optional, cast, Union
import subprocess

URL_REGEX = re.compile(r'https?://(?:www\.)?.+')

def format_duration(milliseconds: Optional[Union[int, float]]) -> str:
    if milliseconds is None: return "0:00"
    try: ms = int(float(milliseconds))
    except (ValueError, TypeError): return "Invalid"
    if ms <= 0: return "0:00"
    seconds_total = math.floor(ms / 1000)
    hours = math.floor(seconds_total / 3600)
    minutes = math.floor((seconds_total % 3600) / 60)
    seconds = seconds_total % 60
    if hours > 0: return f"{hours}:{minutes:02d}:{seconds:02d}"
    else: return f"{minutes}:{seconds:02d}"

def get_gpu_info():
    try:
        result = subprocess.run(['nvidia-smi'], capture_output=True, text=True, check=True, timeout=5)
        return result.stdout
    except FileNotFoundError: return "Error: 'nvidia-smi' command not found."
    except subprocess.TimeoutExpired: return "Error: 'nvidia-smi' command timed out."
    except subprocess.CalledProcessError as e: return f"Error running nvidia-smi: {e.stderr}"
    except Exception as e: return f"An unexpected error occurred retrieving GPU info: {e}"

def get_ssh_clients():
    try:
        who_result = subprocess.run(['who'], capture_output=True, text=True, check=True, timeout=5)
        who_clients = [line for line in who_result.stdout.splitlines() if '(' in line or 'pts/' in line]
        w_result = subprocess.run(['w', '-h'], capture_output=True, text=True, check=True, timeout=5)
        w_clients = [line for line in w_result.stdout.splitlines() if 'ssh' in line.lower() or '@' in line.split()[2] or ':' in line.split()[2]]
        client_details = set()
        processed_clients = []
        for line in who_clients + w_clients:
            parts = line.split(); user = parts[0]; tty = parts[1]; source = "Unknown"
            if len(parts) > 2:
                if '(' in parts[-1] and ')' in parts[-1]: source = parts[-1].strip('()')
                elif '@' in parts[2] or ':' in parts[2]: source = parts[2]
            detail_key = f"{user}@{source} ({tty})"
            if detail_key not in client_details:
                client_details.add(detail_key); processed_clients.append(line.strip())
        return "\n".join(processed_clients) if processed_clients else "No active remote/terminal sessions detected."
    except FileNotFoundError: return "Error: Command 'who' or 'w' not found."
    except subprocess.TimeoutExpired: return "Error: User info command timed out."
    except subprocess.CalledProcessError as e: return f"Error retrieving user info: {e.stderr}"
    except Exception as e: return f"An unexpected error occurred retrieving user info: {e}"

def split_message(message, max_length=1990): # Reduced max_length for safety ```
    if len(message) <= max_length: return [message]
    return [message[i:i+max_length] for i in range(0, len(message), max_length)]

class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.inactivity_timers: dict[int, asyncio.Task] = {}
        self.default_volume = int(os.getenv('DEFAULT_VOLUME', 100))
        self.max_queue_size = int(os.getenv('MAX_QUEUE_SIZE', 1000))
        self.max_playlist_size = int(os.getenv('MAX_PLAYLIST_SIZE', 100))

    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, payload: wavelink.NodeReadyEventPayload): pass

    @commands.Cog.listener()
    async def on_wavelink_websocket_closed(self, payload: wavelink.WebsocketClosedEventPayload): pass

    @commands.Cog.listener()
    async def on_wavelink_track_start(self, payload: wavelink.TrackStartEventPayload):
        player = payload.player; track = payload.track
        if not player or not player.guild: return
        guild_id = player.guild.id
        if guild_id in self.inactivity_timers:
            self.inactivity_timers[guild_id].cancel(); del self.inactivity_timers[guild_id]
        if hasattr(player, 'text_channel') and player.text_channel:
            channel = player.text_channel
            title = discord.utils.escape_markdown(track.title or "Unknown Title"); uri = track.uri or "#"
            author = discord.utils.escape_markdown(track.author or "Unknown Author")
            requester_mention = f"<@{track.extras['requester']}>" if track.extras and 'requester' in track.extras else ""
            desc = f"[{title}]({uri})\nAuthor: {author}\nDuration: {format_duration(track.length)}\n"
            if requester_mention: desc += f"Requested by: {requester_mention}"
            embed = discord.Embed(color=discord.Color.green(), title="💿 Now Playing", description=desc)
            artwork = track.artwork or track.preview_url
            if artwork: embed.set_thumbnail(url=artwork)
            elif track.source == "youtube" and track.identifier: embed.set_thumbnail(url=f"https://img.youtube.com/vi/{track.identifier}/mqdefault.jpg")
            try: await channel.send(embed=embed)
            except (discord.HTTPException, discord.errors.Forbidden): pass

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload):
        player = payload.player; track = payload.track; reason = payload.reason
        if not player or not player.guild: return
        guild_id = player.guild.id
        if reason in ('FINISHED', 'LOAD_FAILED'):
            if player.queue.mode == wavelink.QueueMode.loop and track: await player.queue.put_wait(track)
            if not player.playing and not player.queue.is_empty:
                if player.queue.mode == wavelink.QueueMode.loop_all and track:
                    track.extras = getattr(track, 'extras', {}); await player.queue.put_wait(track)
                try:
                    next_track = player.queue.get(); await player.play(next_track, volume=player.volume)
                except wavelink.QueueEmpty: self._schedule_inactivity_check(guild_id)
                except Exception: self._schedule_inactivity_check(guild_id)
            elif player.queue.is_empty: self._schedule_inactivity_check(guild_id)
        elif reason == 'STOPPED' and player.queue.is_empty: self._schedule_inactivity_check(guild_id)

    @commands.Cog.listener()
    async def on_wavelink_track_exception(self, payload: wavelink.TrackExceptionEventPayload):
        player = payload.player; track = payload.track; exception = payload.exception
        if not player or not player.guild: return
        if hasattr(player, 'text_channel') and player.text_channel:
            channel = player.text_channel; track_title = getattr(track, 'title', 'the track')
            try: await channel.send(f"💥 Error playing `{discord.utils.escape_markdown(track_title)}`: {exception}", delete_after=30)
            except discord.HTTPException: pass

    @commands.Cog.listener()
    async def on_wavelink_track_stuck(self, payload: wavelink.TrackStuckEventPayload):
        player = payload.player; track = payload.track; threshold = payload.threshold_ms
        if not player or not player.guild: return
        if hasattr(player, 'text_channel') and player.text_channel:
            channel = player.text_channel; track_title = getattr(track, 'title', 'the track')
            try: await channel.send(f"⚠️ Track `{discord.utils.escape_markdown(track_title)}` stuck (>{threshold/1000:.1f}s), skipping...", delete_after=30)
            except discord.HTTPException: pass
        try: await player.skip(force=True)
        except Exception: pass

    def _schedule_inactivity_check(self, guild_id: int):
        if guild_id in self.inactivity_timers: self.inactivity_timers[guild_id].cancel()
        task = asyncio.create_task(self._check_inactivity(guild_id, 120))
        self.inactivity_timers[guild_id] = task
        task.add_done_callback(lambda t: self.inactivity_timers.pop(guild_id, None))

    async def _check_inactivity(self, guild_id: int, delay: int):
        await asyncio.sleep(delay)
        guild = self.bot.get_guild(guild_id)
        if not guild: return
        player: Optional[wavelink.Player] = guild.voice_client
        is_active = False
        if player and player.connected:
            if player.playing or not player.queue.is_empty: is_active = True
            elif player.channel and len([m for m in player.channel.members if not m.bot]) > 0: is_active = True
        if player and player.connected and not is_active:
            if hasattr(player, 'text_channel') and player.text_channel:
                try: await player.text_channel.send("👋 Disconnected due to inactivity.", delete_after=60)
                except discord.HTTPException: pass
            await player.disconnect(force=True)

    def cog_unload(self):
        for task in self.inactivity_timers.values(): task.cancel()
        self.inactivity_timers.clear()

    async def cog_before_invoke(self, ctx: commands.Context):
        if not ctx.guild: raise commands.NoPrivateMessage("This command can't be used in DMs.")
        return True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            await interaction.response.send_message("❌ This command can only be used in a server!", ephemeral=True)
            return False
        node = wavelink.Pool.get_node()
        if not node or node.status != wavelink.NodeStatus.CONNECTED:
            await interaction.response.send_message("❌ Music service is currently unavailable.", ephemeral=True)
            return False
        commands_require_vc = ["play", "disconnect", "stop", "skip", "pause", "resume", "loop", "shuffle", "lowpass"]
        if interaction.command and interaction.command.name in commands_require_vc:
             if not interaction.user.voice or not interaction.user.voice.channel:
                 await interaction.response.send_message("❌ You need to be in a voice channel.", ephemeral=True)
                 return False
             player: Optional[wavelink.Player] = interaction.guild.voice_client
             if player and player.connected and player.channel.id != interaction.user.voice.channel.id:
                  await interaction.response.send_message(f"❌ You must be in <#{player.channel.id}>.", ephemeral=True)
                  return False
        return True

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        original = getattr(error, 'original', error)
        command_name = interaction.command.name if interaction.command else 'command'
        error_message = f"Unexpected error running `/{command_name}`."
        if isinstance(original, app_commands.CheckFailure): error_message = "You don't meet the requirements to run this command."
        elif isinstance(original, app_commands.CommandNotFound): error_message = f"Command `/{command_name}` not found."
        elif isinstance(original, app_commands.MissingPermissions): error_message = f"You lack permissions: {', '.join(original.missing_permissions)}"
        elif isinstance(original, app_commands.BotMissingPermissions): error_message = f"I lack permissions: {', '.join(original.missing_permissions)}"
        elif isinstance(original, app_commands.CommandOnCooldown): error_message = f"Cooldown! Try again in {original.retry_after:.2f}s."
        elif isinstance(original, app_commands.TransformerError): error_message = f"Invalid value provided for `{original.parameter.name}`."
        elif isinstance(original, wavelink.ZeroConnectedNodes): error_message = "Music service connection lost."
        elif isinstance(original, wavelink.LavalinkLoadException): error_message = f"Error loading track: {original}"
        elif isinstance(original, wavelink.WavelinkException): error_message = f"Music service error: {original}"
        elif isinstance(original, asyncio.TimeoutError): error_message = "Operation timed out."
        elif isinstance(original, discord.errors.NotFound): error_message = "Requested item not found."
        try:
            send_method = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
            await send_method(f"⚠️ {error_message}", ephemeral=True)
        except discord.HTTPException: pass
        except Exception: pass # Ignore errors in error handler


    @app_commands.command(name="play", description="Plays or queues music (URL/Search).")
    @app_commands.describe(query='URL or search term')
    async def play(self, interaction: discord.Interaction, *, query: str):
        user_channel = interaction.user.voice.channel
        player: wavelink.Player
        if not interaction.guild.voice_client:
            try: player = await user_channel.connect(cls=wavelink.Player, self_deaf=True)
            except Exception as e: return await interaction.response.send_message(f"⚠️ Failed to connect: {e}", ephemeral=True)
        else: player = cast(wavelink.Player, interaction.guild.voice_client)
        player.text_channel = interaction.channel
        await player.set_volume(self.default_volume)
        await interaction.response.defer(thinking=True)
        try:
            tracks: wavelink.Search = await wavelink.Playable.search(query.strip('<>'))
            if not tracks: return await interaction.followup.send(f"❌ No results for `{discord.utils.escape_markdown(query)}`.", ephemeral=True)
        except Exception as e: return await interaction.followup.send(f"⚠️ Search/Load error: {e}", ephemeral=True)

        added_count, skipped_limit, skipped_full = 0, 0, 0
        followup_message = ""; requester_id = interaction.user.id

        if isinstance(tracks, wavelink.Playlist):
            pl_name = tracks.name or "Playlist"; pl_name_safe = discord.utils.escape_markdown(pl_name)
            tracks_to_consider = tracks.tracks[:self.max_playlist_size]
            if len(tracks.tracks) > self.max_playlist_size: skipped_limit = len(tracks.tracks) - self.max_playlist_size
            tracks_to_add = []
            for track in tracks_to_consider:
                if player.queue.count + added_count < self.max_queue_size:
                    track.extras = {'requester': requester_id}; tracks_to_add.append(track); added_count += 1
                else: skipped_full += 1
            if tracks_to_add: player.queue.extend(tracks_to_add)
            followup_message = f"✅ Added **{added_count}** tracks from **`{pl_name_safe}`**."
            if skipped_limit > 0: followup_message += f" (Limit {self.max_playlist_size}, skipped {skipped_limit})"
            if skipped_full > 0: followup_message += f" (Queue full, skipped {skipped_full})"
        elif tracks:
            track = tracks[0]; title_safe = discord.utils.escape_markdown(track.title or "Track")
            if player.queue.count < self.max_queue_size:
                track.extras = {'requester': requester_id}; await player.queue.put_wait(track)
                followup_message = f"✅ Added **`{title_safe}`**." ; added_count = 1
            else: followup_message = f"❌ Queue full. Could not add **`{title_safe}`**."
        else: followup_message = "⚠️ Unexpected empty search result."

        await interaction.followup.send(followup_message)
        if added_count > 0 and not player.playing:
            try: first_track = player.queue.get(); await player.play(first_track)
            except Exception: pass # Handle potential error starting playback

    @app_commands.command(name="disconnect", description="Disconnects the bot and clears queue.")
    async def disconnect(self, interaction: discord.Interaction):
        player: Optional[wavelink.Player] = interaction.guild.voice_client
        if not player or not player.connected: return await interaction.response.send_message("❌ Not connected.", ephemeral=True)
        guild_id = interaction.guild.id
        if guild_id in self.inactivity_timers: self.inactivity_timers[guild_id].cancel()
        await player.disconnect(force=True)
        await interaction.response.send_message("👋 Disconnected.")

    @app_commands.command(name="stop", description="Stops music and clears queue.")
    async def stop(self, interaction: discord.Interaction):
        player: Optional[wavelink.Player] = interaction.guild.voice_client
        if not player or not player.connected: return await interaction.response.send_message("❌ Not connected.", ephemeral=True)
        if not player.playing and player.queue.is_empty: return await interaction.response.send_message("ℹ️ Nothing playing.", ephemeral=True)
        player.queue.clear(); await player.stop()
        self._schedule_inactivity_check(interaction.guild.id)
        await interaction.response.send_message("⏹️ Stopped & cleared queue.")

    @app_commands.command(name="skip", description="Skips the current song.")
    async def skip(self, interaction: discord.Interaction):
        player: Optional[wavelink.Player] = interaction.guild.voice_client
        if not player or not player.connected: return await interaction.response.send_message("❌ Not connected.", ephemeral=True)
        current_track = player.current
        if not current_track: return await interaction.response.send_message("ℹ️ Nothing playing.", ephemeral=True)
        title_safe = discord.utils.escape_markdown(current_track.title or "Track")
        await player.skip(force=True)
        await interaction.response.send_message(f"⏭️ Skipped **`{title_safe}`**.")

    @app_commands.command(name="pause", description="Pauses the current song.")
    async def pause(self, interaction: discord.Interaction):
        player: Optional[wavelink.Player] = interaction.guild.voice_client
        if not player or not player.connected: return await interaction.response.send_message("❌ Not connected.", ephemeral=True)
        if not player.playing: return await interaction.response.send_message("ℹ️ Not playing." if not player.paused else "⏸️ Already paused.", ephemeral=True)
        await player.pause(True); await interaction.response.send_message("⏸️ Paused.")
        self._schedule_inactivity_check(interaction.guild.id)

    @app_commands.command(name="resume", description="Resumes the paused song.")
    async def resume(self, interaction: discord.Interaction):
        player: Optional[wavelink.Player] = interaction.guild.voice_client
        if not player or not player.connected: return await interaction.response.send_message("❌ Not connected.", ephemeral=True)
        if not player.paused: return await interaction.response.send_message("▶️ Already playing." if player.playing else "ℹ️ Nothing to resume.", ephemeral=True)
        await player.pause(False); await interaction.response.send_message("▶️ Resumed.")
        guild_id = interaction.guild.id
        if guild_id in self.inactivity_timers: self.inactivity_timers[guild_id].cancel()

    @app_commands.command(name="loop", description="Cycles loop modes: OFF -> TRACK -> QUEUE.")
    async def loop(self, interaction: discord.Interaction):
        player: Optional[wavelink.Player] = interaction.guild.voice_client
        if not player or not player.connected: return await interaction.response.send_message("❌ Not connected.", ephemeral=True)
        current_mode = player.queue.mode; next_mode: wavelink.QueueMode; mode_str: str
        if current_mode == wavelink.QueueMode.normal:
            if not player.current and player.queue.is_empty: return await interaction.response.send_message("ℹ️ Nothing to loop.", ephemeral=True)
            next_mode = wavelink.QueueMode.loop; mode_str = "TRACK"
        elif current_mode == wavelink.QueueMode.loop: next_mode = wavelink.QueueMode.loop_all; mode_str = "QUEUE"
        else: next_mode = wavelink.QueueMode.normal; mode_str = "OFF"
        player.queue.mode = next_mode
        await interaction.response.send_message(f"🔁 Loop: **{mode_str}**.")

    @app_commands.command(name="shuffle", description="Shuffles the queue.")
    async def shuffle(self, interaction: discord.Interaction):
        player: Optional[wavelink.Player] = interaction.guild.voice_client
        if not player or not player.connected: return await interaction.response.send_message("❌ Not connected.", ephemeral=True)
        if player.queue.count < 2: return await interaction.response.send_message("ℹ️ Need >1 song to shuffle.", ephemeral=True)
        player.queue.shuffle()
        await interaction.response.send_message(f"🔀 Queue shuffled ({player.queue.count} songs).")

    @app_commands.command(name="queue", description="Displays the current queue.")
    @app_commands.describe(page="Page number")
    async def queue(self, interaction: discord.Interaction, page: app_commands.Range[int, 1] = 1):
        player: Optional[wavelink.Player] = interaction.guild.voice_client
        embed = discord.Embed(title="🎶 Music Queue", color=discord.Color.blue())
        current_track_info = "*Nothing playing.*"; queue_duration_ms = 0; thumbnail_url = None
        if player and player.current:
            track = player.current; title = discord.utils.escape_markdown(track.title or "Track"); uri = track.uri or "#"
            dur = format_duration(track.length); pos = format_duration(player.position)
            req = f" - <@{track.extras['requester']}>" if track.extras and 'requester' in track.extras else ""
            current_track_info = f"**`[{dur}]`** [{title}]({uri}){req}\n> `⏳ {pos} / {dur}`"
            artwork = track.artwork or track.preview_url
            if artwork: thumbnail_url = artwork
            elif track.source == "youtube" and track.identifier: thumbnail_url = f"https://img.youtube.com/vi/{track.identifier}/mqdefault.jpg"
        embed.add_field(name="Currently Playing", value=current_track_info, inline=False)
        if thumbnail_url: embed.set_thumbnail(url=thumbnail_url)

        if not player or player.queue.is_empty:
            embed.add_field(name="Up Next", value="*Queue is empty.*", inline=False)
            footer_text = "Page 1/1 | 0 songs | Duration: 0:00"
        else:
            items_per_page = 10; queue_list = list(player.queue); total_items = len(queue_list)
            total_pages = math.ceil(total_items / items_per_page) or 1; page = max(1, min(page, total_pages))
            start_index = (page - 1) * items_per_page; end_index = start_index + items_per_page
            current_page_items = queue_list[start_index:end_index]
            queue_display = ""
            for i, track in enumerate(current_page_items, start=start_index + 1):
                title = discord.utils.escape_markdown(track.title or "Track"); dur = format_duration(track.length); uri = track.uri or "#"
                req = f" - <@{track.extras['requester']}>" if track.extras and 'requester' in track.extras else ""
                queue_display += f"**{i}.** `[{dur}]` [{title}]({uri}){req}\n"
                if track.length: queue_duration_ms += track.length
            embed.add_field(name=f"Up Next ({total_items} songs)", value=queue_display.strip() or "*Empty queue.*", inline=False)
            loop_str = ""; mode = player.queue.mode
            if mode == wavelink.QueueMode.loop: loop_str = " | Loop: Track 🔁"
            elif mode == wavelink.QueueMode.loop_all: loop_str = " | Loop: Queue 🔁"
            footer_text = f"Page {page}/{total_pages} | {total_items} songs | Duration: {format_duration(queue_duration_ms)}{loop_str}"

        embed.set_footer(text=footer_text)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="lowpass", description="Applies low-pass filter (bass boost).")
    @app_commands.describe(strength="Strength (0=disable, 0.05-0.5 recommend)")
    async def lowpass(self, interaction: discord.Interaction, strength: app_commands.Range[float, 0.0, 5.0]):
        player: Optional[wavelink.Player] = interaction.guild.voice_client
        if not player or not player.connected: return await interaction.response.send_message("❌ Not connected.", ephemeral=True)
        embed = discord.Embed(color=discord.Color.blurple(), title='🔊 Low Pass Filter')
        try:
            filters = player.filters or wavelink.Filter()
            if strength <= 0.01:
                if filters.low_pass: filters.low_pass = None; await player.set_filter(filters, seek=player.playing); embed.description = 'Disabled Low Pass Filter.'
                else: embed.description = 'Low Pass already disabled.'
            else:
                filters.low_pass = wavelink.LowPass(smoothing=strength); await player.set_filter(filters, seek=player.playing)
                embed.description = f'Set Low Pass smoothing to `{strength:.2f}`.'
            await interaction.response.send_message(embed=embed)
        except Exception as e: await interaction.response.send_message(f"⚠️ Filter error: {e}", ephemeral=True)


class System(commands.Cog):
    def __init__(self, bot: commands.Bot): self.bot = bot

    @app_commands.command(name="gpuinfo", description="Shows GPU info (nvidia-smi)")
    async def gpuinfo(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        try:
            gpu_info = get_gpu_info(); chunks = split_message(gpu_info); first = True
            for chunk in chunks:
                content = f"```\n{chunk}\n```"
                send_method = interaction.followup.send if first else interaction.channel.send
                await send_method(content); first = False
        except Exception as e: await interaction.followup.send(f"⚠️ Error processing GPU info: {e}", ephemeral=True)

    @app_commands.command(name="users", description="Shows connected remote/terminal users")
    async def users(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        try:
            clients_info = get_ssh_clients(); chunks = split_message(clients_info); first = True
            for chunk in chunks:
                content = f"```\n{chunk}\n```"
                send_method = interaction.followup.send if first else interaction.channel.send
                await send_method(content); first = False
        except Exception as e: await interaction.followup.send(f"⚠️ Error processing user info: {e}", ephemeral=True)


async def setup(bot: commands.Bot):
    node = wavelink.Pool.get_node()
    if not node or node.status != wavelink.NodeStatus.CONNECTED:
         print("WARNING: Wavelink node not ready during combined setup.") # Keep one critical warning
         # Consider await asyncio.sleep(5) or raising error if node is absolutely mandatory at load time
    try: await bot.add_cog(Music(bot))
    except Exception as e: print(f"Failed to load Music Cog: {e}") # Keep load failure messages
    try: await bot.add_cog(System(bot))
    except Exception as e: print(f"Failed to load System Cog: {e}")