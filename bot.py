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
        intents.voice_states = True
        intents.message_content = True
        intents.guilds = True
        intents.guild_messages = True

        super().__init__(command_prefix=DEFAULT_PREFIX, intents=intents)
        self.wavelink_ready_event = asyncio.Event()

    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, payload: wavelink.NodeReadyEventPayload):
        self.wavelink_ready_event.set()

    async def load_extensions(self):
        extensions = [
            "cogs.lavalink",
            "cogs.system"
        ]
        for extension in extensions:
            try:
                await self.load_extension(extension)
                logging.info(f"Successfully loaded extension: {extension}")
            except Exception as e:
                logging.error(f"Failed to load extension {extension}.", exc_info=True)
        logging.info(f"Finished loading extensions. Total commands loaded: {len(self.commands)}")

    async def setup_hook(self):
        # Lavalink connection setup
        try:
            logging.info("Attempting to connect to Lavalink server...")
            await wavelink.Pool.connect(
                nodes=[
                    wavelink.Node(
                        uri=f"http://{os.getenv('LAVALINK_HOST', '127.0.0.1')}:{int(os.getenv('LAVALINK_PORT', '2333'))}",
                        password=os.getenv('LAVALINK_PASSWORD', 'youshallnotpass')
                    )
                ],
                client=self
            )
            logging.info("Waiting for Lavalink node to be ready...")
            try:
                await asyncio.wait_for(self.wavelink_ready_event.wait(), timeout=30)
                logging.info("Lavalink node is ready.")
            except asyncio.TimeoutError:
                logging.error("Lavalink node connection timed out after 30 seconds. This is a fatal error.")
                # This specific error should still cause an exit, as it's critical for music functionality.
                exit("Error: Failed to connect to Lavalink server (timeout). Please ensure it's running and accessible.")
        except Exception as e:
            logging.error(f"Failed to connect to Lavalink or Lavalink node not ready. Error: {e}", exc_info=True)
            # This is a critical failure.
            exit(f"Setup failed due to Lavalink connection error: {str(e)}")

        # Load extensions
        logging.info("Starting to load extensions...")
        await self.load_extensions()
        logging.info("Extension loading process completed.")

        # Sync commands
        logging.info("Attempting to sync application commands...")
        try:
            await self.tree.sync()
            logging.info("Application commands synced successfully.")
        except Exception as e:
            logging.error("Failed to sync application commands.", exc_info=True)
            # Bot can continue running if command sync fails, but commands might not be available.
            # No exit here, just log the error.

    async def on_ready(self):
        logging.info(f"Logged in as {self.user} (ID: {self.user.id})")
        await self.change_presence(activity=discord.Activity(
            type=discord.ActivityType.streaming, name="All your data to the NSA"))

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



