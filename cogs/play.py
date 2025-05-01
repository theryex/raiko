import discord
from discord import app_commands
from discord.ext import commands
import wavelink
import asyncio

class Play(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="play", description="Play a song")
    async def play(self, interaction: discord.Interaction, query: str):
        if not interaction.user.voice:
            return await interaction.response.send_message("You need to be in a voice channel to use this command!", ephemeral=True)

        await interaction.response.defer()

        # Get the voice channel
        voice_channel = interaction.user.voice.channel

        # Connect to voice channel if not already connected
        if not interaction.guild.voice_client:
            await voice_channel.connect(cls=wavelink.Player)

        # Get the player
        player: wavelink.Player = interaction.guild.voice_client

        # Search for the track
        tracks = await wavelink.Playable.search(query)
        if not tracks:
            return await interaction.followup.send("No tracks found!", ephemeral=True)

        track = tracks[0]

        # Play the track
        await player.play(track)

        # Create and send embed
        embed = discord.Embed(
            title="Now Playing",
            description=f"[{track.title}]({track.uri})",
            color=discord.Color.blue()
        )
        embed.add_field(name="Duration", value=str(track.duration))
        embed.add_field(name="Requested by", value=interaction.user.mention)
        
        await interaction.followup.send(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(Play(bot)) 