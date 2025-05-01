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

            # Log basic node information
            logger.info(f"Using node: {vc.node.identifier}")
            logger.info(f"Node status: {vc.node.status}")

            # Check if the query is a YouTube URL
            youtube_pattern = r'(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+'
            if re.match(youtube_pattern, query):
                logger.info(f"Detected YouTube URL: {query}")
                try:
                    # Try to extract video ID for more reliable search
                    video_id = None
                    if 'youtube.com/watch?v=' in query:
                        video_id = query.split('watch?v=')[1].split('&')[0]
                    elif 'youtu.be/' in query:
                        video_id = query.split('youtu.be/')[1].split('?')[0]
                    
                    if video_id:
                        # Try different search methods
                        search_queries = [
                            f"ytsearch:{video_id}",
                            f"ytmsearch:{video_id}",
                            f"https://www.youtube.com/watch?v={video_id}"
                        ]
                        
                        for search_query in search_queries:
                            logger.info(f"Trying search with query: {search_query}")
                            try:
                                tracks = await wavelink.Playable.search(search_query)
                                if tracks:
                                    break
                            except Exception as e:
                                logger.warning(f"Search failed with query '{search_query}': {e}")
                                continue
                    else:
                        tracks = await wavelink.Playable.search(query)
                except Exception as e:
                    logger.error(f"Error processing YouTube URL: {e}")
                    tracks = await wavelink.Playable.search(query)
            else:
                logger.info(f"Searching for tracks with query: '{query}'")
                tracks = await wavelink.Playable.search(query)

            if not tracks:
                await interaction.followup.send(f"Could not find any tracks for query: `{query}`. Please try a different search term or URL.")
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
                error_msg += "This might be due to an unsupported URL format or region restrictions. Please try a different URL or search query."
            else:
                error_msg += f"Lavalink error: {lavalink_err.error}"
            await interaction.followup.send(error_msg, ephemeral=True)
        except Exception as e:
            logger.exception(f"An unexpected error occurred in the play command for query '{query}': {e}")
            await interaction.followup.send(f"An unexpected error occurred: {e}", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Play(bot)) 