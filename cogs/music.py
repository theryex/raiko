import discord
from discord import app_commands
from discord.ext import commands
import wavelink
import logging
from typing import Optional

class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="shuffle", description="Shuffles the queue")
    async def shuffle(self, interaction: discord.Interaction):
        if not interaction.guild.voice_client:
            return await interaction.response.send_message("I'm not connected to a voice channel!", ephemeral=True)

        vc: wavelink.Player = interaction.guild.voice_client
        if not vc.queue:
            return await interaction.response.send_message("There are no songs in the queue!", ephemeral=True)

        vc.queue.shuffle()
        await interaction.response.send_message(f"The queue of {len(vc.queue)} songs has been shuffled.")

    @app_commands.command(name="skip", description="Skips the current song")
    async def skip(self, interaction: discord.Interaction):
        if not interaction.guild.voice_client:
            return await interaction.response.send_message("I'm not connected to a voice channel!", ephemeral=True)

        vc: wavelink.Player = interaction.guild.voice_client
        if not vc.current:
            return await interaction.response.send_message("There is no song currently playing!", ephemeral=True)

        current_song = vc.current
        await vc.stop()
        await interaction.response.send_message(f"**{current_song.title}** has been skipped.")

    @app_commands.command(name="queue", description="Displays the current song queue")
    @app_commands.describe(page="Page number of the queue")
    async def queue(self, interaction: discord.Interaction, page: Optional[int] = 1):
        if not interaction.guild.voice_client:
            return await interaction.response.send_message("I'm not connected to a voice channel!", ephemeral=True)

        vc: wavelink.Player = interaction.guild.voice_client
        if not vc.queue:
            return await interaction.response.send_message("There are no songs in the queue!", ephemeral=True)

        items_per_page = 10
        pages = []
        queue = list(vc.queue)

        for i in range(0, len(queue), items_per_page):
            page_songs = queue[i:i + items_per_page]
            page_text = ""
            for j, song in enumerate(page_songs, start=i+1):
                page_text += f"**{j}.** `[{song.duration}]` {song.title} -- <@{song.requester.id}>\n"
            pages.append(page_text)

        if page < 1 or page > len(pages):
            return await interaction.response.send_message(f"Invalid page number. There are {len(pages)} pages available.", ephemeral=True)

        current_song = vc.current
        embed = discord.Embed(
            title="Music Queue",
            description=f"**Currently Playing**\n`[{current_song.duration}]` {current_song.title} -- <@{current_song.requester.id}>\n\n**Queue**\n{pages[page-1]}",
            color=discord.Color.blue()
        )
        embed.set_footer(text=f"Page {page} of {len(pages)}")
        if current_song.artwork:
            embed.set_thumbnail(url=current_song.artwork)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="pause", description="Pauses the current song")
    async def pause(self, interaction: discord.Interaction):
        if not interaction.guild.voice_client:
            return await interaction.response.send_message("I'm not connected to a voice channel!", ephemeral=True)

        vc: wavelink.Player = interaction.guild.voice_client
        if not vc.current:
            return await interaction.response.send_message("There is no song currently playing!", ephemeral=True)

        await vc.pause()
        await interaction.response.send_message("Music paused ⏸️")

    @app_commands.command(name="resume", description="Resumes the current song")
    async def resume(self, interaction: discord.Interaction):
        if not interaction.guild.voice_client:
            return await interaction.response.send_message("I'm not connected to a voice channel!", ephemeral=True)

        vc: wavelink.Player = interaction.guild.voice_client
        if not vc.current:
            return await interaction.response.send_message("There is no song currently playing!", ephemeral=True)

        await vc.resume()
        await interaction.response.send_message("Music resumed ▶️")

    @app_commands.command(name="stop", description="Stops the music and clears the queue")
    async def stop(self, interaction: discord.Interaction):
        if not interaction.guild.voice_client:
            return await interaction.response.send_message("I'm not connected to a voice channel!", ephemeral=True)

        vc: wavelink.Player = interaction.guild.voice_client
        if not vc.current:
            return await interaction.response.send_message("There is no song currently playing!", ephemeral=True)

        vc.queue.clear()
        await vc.stop()
        await interaction.response.send_message("Music stopped and queue cleared ⏹️")

    @app_commands.command(name="loop", description="Toggles loop mode for the current song")
    async def loop(self, interaction: discord.Interaction):
        if not interaction.guild.voice_client:
            return await interaction.response.send_message("I'm not connected to a voice channel!", ephemeral=True)

        vc: wavelink.Player = interaction.guild.voice_client
        if not vc.current:
            return await interaction.response.send_message("There is no song currently playing!", ephemeral=True)

        vc.loop = not vc.loop
        await interaction.response.send_message(f"Loop mode {'enabled' if vc.loop else 'disabled'} 🔄")

async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot)) 