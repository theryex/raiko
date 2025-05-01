import discord
from discord import app_commands
from discord.ext import commands
import wavelink
import asyncio
import logging
import re

class Play(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="play", description="Plays a song or adds it to the queue.")
    @app_commands.describe(query='URL or search query')
    async def play(self, interaction: discord.Interaction, *, query: str):
        if not interaction.user.voice:
            return await interaction.response.send_message("You need to be in a voice channel to use this command!", ephemeral=True)

        logger = logging.getLogger(__name__)
        logger.info(f"Received play command in '{interaction.guild.name}' with query: '{query}'")

        if not interaction.guild.voice_client:
            vc: wavelink.Player | None = await interaction.user.voice.channel.connect(cls=wavelink.Player)
            if vc is None:
                await interaction.response.send_message("Could not connect to the voice channel.", ephemeral=True)
                return
        else:
            vc: wavelink.Player = interaction.guild.voice_client

        try:
            await interaction.response.defer(ephemeral=True, thinking=True)

            # Check if the query is a YouTube URL
            youtube_pattern = r'(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+'
            if re.match(youtube_pattern, query):
                logger.info(f"Detected YouTube URL, attempting direct load: {query}")
                try:
                    tracks = await wavelink.Playable.search(query, source=wavelink.TrackSource.YouTube)
                except wavelink.exceptions.LavalinkLoadException:
                    # If direct load fails, try searching with the URL as a query
                    logger.info("Direct load failed, falling back to search")
                    tracks = await wavelink.Playable.search(query)
            else:
                logger.info(f"Searching for tracks with query: '{query}' using node {vc.node.identifier}")
                tracks = await wavelink.Playable.search(query)

            if not tracks:
                await interaction.followup.send(f"Could not find any tracks for query: `{query}`")
                return

            if isinstance(tracks, wavelink.Playlist):
                added = await vc.queue.put_wait(tracks)
                await interaction.followup.send(f"Added playlist **`{tracks.name}`** ({added} songs) to the queue.")
            else:
                track = tracks[0]
                await vc.queue.put_wait(track)
                await interaction.followup.send(f"Added **`{track.title}`** to the queue.")

            if not vc.playing:
                await vc.play(vc.queue.get())

        except wavelink.exceptions.LavalinkLoadException as lavalink_err:
            logger.error(f"LavalinkLoadException for query '{query}': {lavalink_err}")
            error_msg = f"Failed to load tracks for `{query}`. "
            if "Unknown file format" in str(lavalink_err):
                error_msg += "This might be due to an unsupported URL format or region restrictions."
            else:
                error_msg += f"Lavalink error: {lavalink_err.error}"
            await interaction.followup.send(error_msg, ephemeral=True)
        except Exception as e:
            logger.exception(f"An unexpected error occurred in the play command for query '{query}': {e}")
            await interaction.followup.send(f"An unexpected error occurred: {e}", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Play(bot)) 