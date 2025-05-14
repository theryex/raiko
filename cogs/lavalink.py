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

    @app_commands.command(name="stream", description="Plays music from Streaming, SoundCloud, or Spotify")
    @app_commands.describe(query='URL or search term')
    async def play(self, interaction: discord.Interaction, *, query: str):
        player = await self.ensure_voice_client(interaction)
        if not player:
            return
            
        await interaction.response.defer()

        try:
            tracks = await wavelink.Playable.search(query)
            if not tracks:
                await interaction.followup.send("No results found.", ephemeral=True)
                return

            track = tracks[0]
            track.extras = {'requester': interaction.user.id}

            if player.playing:
                if player.queue.count >= self.max_queue_size:
                    await interaction.followup.send("Queue is full.", ephemeral=True)
                    return
                player.queue.put(track)
                await interaction.followup.send(f"Queued: **{track.title}**")
            else:
                await player.play(track)
                await interaction.followup.send(f"Playing: **{track.title}**")

        except Exception as e:
            await interaction.followup.send("Failed to play track.", ephemeral=True)

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

async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))

