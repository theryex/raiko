import discord
from discord import app_commands
from discord.ext import commands
import wavelink
import logging
import re

# Basic URL pattern
URL_REGEX = re.compile(r"https?://(?:www\.)?.+")

class Play(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="play", description="Plays a song or adds it to the queue.")
    @app_commands.describe(query='URL or search query')
    async def play(self, interaction: discord.Interaction, *, query: str):
        logger = logging.getLogger(__name__)
        logger.info(f"Received play command in '{interaction.guild.name}' with query: '{query}'")

        if not interaction.user.voice:
            await interaction.response.send_message("You need to be in a voice channel to play music.", ephemeral=True)
            return

        if not interaction.guild.voice_client:
            vc: wavelink.Player | None = await interaction.user.voice.channel.connect(cls=wavelink.Player)
            if vc is None:
                await interaction.response.send_message("Could not connect to the voice channel.", ephemeral=True)
                return
            logger.info(f"Connected to voice channel: {interaction.user.voice.channel.name}")
        else:
            vc: wavelink.Player = interaction.guild.voice_client
            if interaction.user.voice.channel != vc.channel:
                await interaction.response.send_message("You need to be in the same voice channel as the bot.", ephemeral=True)
                return

        # Check if the query is a URL or a search term
        search_query: str
        is_url = URL_REGEX.match(query)

        if is_url:
            logger.info(f"Detected URL: {query}")
            search_query = query
        else:
            logger.info(f"Detected search term: {query}")
            search_query = f"ytsearch:{query}"

        try:
            await interaction.response.defer(thinking=True)

            logger.info(f"Searching for tracks with identifier: '{search_query}' using node {vc.node.identifier}")
            logger.info(f"Node status: {vc.node.status}")

            tracks: wavelink.Search = await wavelink.Playable.search(search_query, node=vc.node)

            if not tracks:
                await interaction.followup.send(f"Could not find any tracks for: `{query}`")
                logger.warning(f"No tracks found for identifier: '{search_query}'")
                return

            if isinstance(tracks, wavelink.Playlist):
                added = await vc.queue.put_wait(tracks)
                await interaction.followup.send(f"Added playlist **`{tracks.name}`** ({added} songs) to the queue.")
                logger.info(f"Added playlist '{tracks.name}' ({added} songs) to queue.")
            else:
                track = tracks[0]
                await vc.queue.put_wait(track)
                await interaction.followup.send(f"Added **`{track.title}`** to the queue.")
                logger.info(f"Added track '{track.title}' to queue.")

            if not vc.playing and not vc.queue.is_empty:
                first_track = vc.queue.get()
                await vc.play(first_track)
                logger.info(f"Started playing: '{first_track.title}'")

        except wavelink.exceptions.LavalinkLoadException as lavalink_err:
            logger.error(f"LavalinkLoadException for identifier '{search_query}': {lavalink_err}")
            await interaction.followup.send(f"Failed to load tracks for `{query}`. Lavalink error: {lavalink_err.error}", ephemeral=True)
        except Exception as e:
            logger.exception(f"An unexpected error occurred in the play command for query '{query}': {e}")
            await interaction.followup.send(f"An unexpected error occurred: {e}", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Play(bot))
    logging.info("Play cog loaded") 