import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
import asyncio
import logging
from pathlib import Path
import wavelink
from typing import Optional

# Configuration
load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

TOKEN = os.getenv('DISCORD_TOKEN')
if not TOKEN:
    exit("Error: DISCORD_TOKEN is required in .env file")

DEFAULT_PREFIX = os.getenv('DEFAULT_PREFIX', '!')
DEFAULT_VOLUME = int(os.getenv('DEFAULT_VOLUME', 100))
MAX_PLAYLIST_SIZE = int(os.getenv('MAX_PLAYLIST_SIZE', 100))
MAX_QUEUE_SIZE = int(os.getenv('MAX_QUEUE_SIZE', 1000))
CACHE_DIR = Path(os.getenv('CACHE_DIR', './cache'))
CACHE_DIR.mkdir(exist_ok=True)

class MusicBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.voice_states = True        intents.message_content = True
        intents.guilds = True
        intents.guild_messages = True

        super().__init__(command_prefix=DEFAULT_PREFIX, intents=intents)
        self.wavelink_ready_event = asyncio.Event()

    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, payload: wavelink.NodeReadyEventPayload):
        self.wavelink_ready_event.set()
        
    async def load_extensions(self):
        try:
            await self.load_extension("cogs.music_slash")
            print(f"Loaded {len(self.commands)} commands.")
        except Exception as e:
            print(f"Failed to load music extension: {str(e)}")

    async def setup_hook(self):
        try:
            # Connect to Lavalink
            await wavelink.Pool.connect(
                nodes=[
                    wavelink.Node(
                        uri=f"http://{os.getenv('LAVALINK_HOST', '127.0.0.1')}:{int(os.getenv('LAVALINK_PORT', '2333'))}",
                        password=os.getenv('LAVALINK_PASSWORD', 'youshallnotpass')
                    )
                ],
                client=self
            )

            # Wait for node to be ready
            try:
                await asyncio.wait_for(self.wavelink_ready_event.wait(), timeout=30)
            except asyncio.TimeoutError:
                raise RuntimeError("Failed to connect to Lavalink server. Please ensure it's running.")            # Load extensions and sync commands
            await self.load_extensions()            await self.tree.sync()

        except Exception as e:
            exit(f"Setup failed: {str(e)}")

    async def on_ready(self):
        print(f"Logged in as {self.user}")
        await self.change_presence(activity=discord.Activity(
            type=discord.ActivityType.watching, name="paint dry."))

async def main():
    bot = MusicBot()
    try:
        await bot.start(TOKEN)
    except Exception as e:
        exit(f"Bot error: {str(e)}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot shutdown requested.")
    except Exception as e:
        print(f"Fatal error: {str(e)}")



