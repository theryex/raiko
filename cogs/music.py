import discord
from discord import app_commands
from discord.ext import commands
import wavelink
import logging
import re
from typing import Optional
import lavalink
from lavalink.events import TrackStartEvent, QueueEndEvent
from lavalink.errors import ClientError
from lavalink.filters import LowPass

# Basic URL pattern
URL_REGEX = re.compile(r"https?://(?:www\.)?.+")

class LavalinkVoiceClient(discord.VoiceProtocol):
    """
    Custom VoiceProtocol to handle Lavalink voice connections.
    """
    def __init__(self, client: discord.Client, channel: discord.abc.Connectable):
        self.client = client
        self.channel = channel
        self.guild_id = channel.guild.id
        self._destroyed = False

        if not hasattr(self.client, 'lavalink'):
            self.client.lavalink = lavalink.Client(client.user.id)
            self.client.lavalink.add_node(host='localhost', port=2333, password='youshallnotpass',
                                          region='us', name='default-node')

        self.lavalink = self.client.lavalink

    async def on_voice_server_update(self, data):
        lavalink_data = {'t': 'VOICE_SERVER_UPDATE', 'd': data}
        await self.lavalink.voice_update_handler(lavalink_data)

    async def on_voice_state_update(self, data):
        channel_id = data['channel_id']

        if not channel_id:
            await self._destroy()
            return

        self.channel = self.client.get_channel(int(channel_id))
        lavalink_data = {'t': 'VOICE_STATE_UPDATE', 'd': data}
        await self.lavalink.voice_update_handler(lavalink_data)

    async def connect(self, *, timeout: float, reconnect: bool, self_deaf: bool = False, self_mute: bool = False) -> None:
        self.lavalink.player_manager.create(guild_id=self.channel.guild.id)
        await self.channel.guild.change_voice_state(channel=self.channel, self_mute=self_mute, self_deaf=self_deaf)

    async def disconnect(self, *, force: bool = False) -> None:
        player = self.lavalink.player_manager.get(self.channel.guild.id)

        if not force and not player.is_connected:
            return

        await self.channel.guild.change_voice_state(channel=None)
        player.channel_id = None
        await self._destroy()

    async def _destroy(self):
        self.cleanup()

        if self._destroyed:
            return

        self._destroyed = True

        try:
            await self.lavalink.player_manager.destroy(self.guild_id)
        except ClientError:
            pass

class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_before_invoke(self, ctx):
        """Check if the command is being used in a guild."""
        if not ctx.guild:
            await ctx.send("This command can only be used in a server!")
            return False
        return True

    def cog_unload(self):
        """
        Remove event hooks when the cog is unloaded.
        """
        self.bot.lavalink._event_hooks.clear()

    async def cog_command_error(self, ctx, error):
        if isinstance(error, commands.CommandInvokeError):
            await ctx.send(error.original)

    @lavalink.listener(TrackStartEvent)
    async def on_track_start(self, event: TrackStartEvent):
        guild_id = event.player.guild_id
        channel_id = event.player.fetch('channel')
        guild = self.bot.get_guild(guild_id)

        if not guild:
            return await self.bot.lavalink.player_manager.destroy(guild_id)

        channel = guild.get_channel(channel_id)

        if channel:
            await channel.send(f'Now playing: {event.track.title} by {event.track.author}')

    @lavalink.listener(QueueEndEvent)
    async def on_queue_end(self, event: QueueEndEvent):
        guild_id = event.player.guild_id
        guild = self.bot.get_guild(guild_id)

        if guild is not None:
            await guild.voice_client.disconnect(force=True)

    @app_commands.command(name="play", description="Plays a song or adds it to the queue.")
    @app_commands.describe(query='URL or search query')
    async def play(self, interaction: discord.Interaction, *, query: str):
        if not interaction.guild:
            return await interaction.response.send_message("This command can only be used in a server!", ephemeral=True)

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

        try:
            await interaction.response.defer(thinking=True)

            # Check if the query is a YouTube URL
            youtube_pattern = r'(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+'
            if re.match(youtube_pattern, query):
                logger.info(f"Detected YouTube URL: {query}")
                # Try to extract video ID for more reliable search
                video_id = None
                if 'youtube.com/watch?v=' in query:
                    video_id = query.split('watch?v=')[1].split('&')[0]
                elif 'youtu.be/' in query:
                    video_id = query.split('youtu.be/')[1].split('?')[0]
                
                if video_id:
                    # Try searching with the video ID first
                    search_query = f"ytsearch:{video_id}"
                else:
                    search_query = query
            else:
                logger.info(f"Detected search term: {query}")
                search_query = f"ytsearch:{query}"

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
            error_msg = f"Failed to load tracks for `{query}`. "
            if "Unknown file format" in str(lavalink_err):
                error_msg += "This might be due to an unsupported URL format or region restrictions. Please try a different URL or search query."
            else:
                error_msg += f"Lavalink error: {lavalink_err.error}"
            await interaction.followup.send(error_msg, ephemeral=True)
        except Exception as e:
            logger.exception(f"An unexpected error occurred in the play command for query '{query}': {e}")
            await interaction.followup.send(f"An unexpected error occurred: {e}", ephemeral=True)

    @app_commands.command(name="shuffle", description="Shuffles the queue")
    async def shuffle(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("This command can only be used in a server!", ephemeral=True)

        if not interaction.guild.voice_client:
            return await interaction.response.send_message("I'm not connected to a voice channel!", ephemeral=True)

        vc: wavelink.Player = interaction.guild.voice_client
        if not vc.queue:
            return await interaction.response.send_message("There are no songs in the queue!", ephemeral=True)

        vc.queue.shuffle()
        await interaction.response.send_message(f"The queue of {len(vc.queue)} songs has been shuffled.")

    @app_commands.command(name="skip", description="Skips the current song")
    async def skip(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("This command can only be used in a server!", ephemeral=True)

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
        if not interaction.guild:
            return await interaction.response.send_message("This command can only be used in a server!", ephemeral=True)

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
        if not interaction.guild:
            return await interaction.response.send_message("This command can only be used in a server!", ephemeral=True)

        if not interaction.guild.voice_client:
            return await interaction.response.send_message("I'm not connected to a voice channel!", ephemeral=True)

        vc: wavelink.Player = interaction.guild.voice_client
        if not vc.current:
            return await interaction.response.send_message("There is no song currently playing!", ephemeral=True)

        await vc.pause()
        await interaction.response.send_message("Music paused ⏸️")

    @app_commands.command(name="resume", description="Resumes the current song")
    async def resume(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("This command can only be used in a server!", ephemeral=True)

        if not interaction.guild.voice_client:
            return await interaction.response.send_message("I'm not connected to a voice channel!", ephemeral=True)

        vc: wavelink.Player = interaction.guild.voice_client
        if not vc.current:
            return await interaction.response.send_message("There is no song currently playing!", ephemeral=True)

        await vc.resume()
        await interaction.response.send_message("Music resumed ▶️")

    @app_commands.command(name="stop", description="Stops the music and clears the queue")
    async def stop(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("This command can only be used in a server!", ephemeral=True)

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
        if not interaction.guild:
            return await interaction.response.send_message("This command can only be used in a server!", ephemeral=True)

        if not interaction.guild.voice_client:
            return await interaction.response.send_message("I'm not connected to a voice channel!", ephemeral=True)

        vc: wavelink.Player = interaction.guild.voice_client
        if not vc.current:
            return await interaction.response.send_message("There is no song currently playing!", ephemeral=True)

        vc.loop = not vc.loop
        await interaction.response.send_message(f"Loop mode {'enabled' if vc.loop else 'disabled'} 🔄")

    @commands.command(aliases=['lp'])
    async def lowpass(self, ctx, strength: float):
        """ Sets the strength of the low pass filter. """
        player = self.bot.lavalink.player_manager.get(ctx.guild.id)

        strength = max(0.0, min(100.0, strength))

        embed = discord.Embed(color=discord.Color.blurple(), title='Low Pass Filter')

        if strength == 0.0:
            await player.remove_filter('lowpass')
            embed.description = 'Disabled **Low Pass Filter**'
            return await ctx.send(embed=embed)

        low_pass = LowPass()
        low_pass.update(smoothing=strength)
        await player.set_filter(low_pass)

        embed.description = f'Set **Low Pass Filter** strength to {strength}.'
        await ctx.send(embed=embed)

    @commands.command(aliases=['dc'])
    async def disconnect(self, ctx):
        """ Disconnects the player from the voice channel and clears its queue. """
        player = self.bot.lavalink.player_manager.get(ctx.guild.id)
        player.queue.clear()
        await player.stop()
        await ctx.voice_client.disconnect(force=True)
        await ctx.send('✳ | Disconnected.')

async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))