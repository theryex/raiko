import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
import wavelink
import asyncio
import logging
from pathlib import Path

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    level=getattr(logging, os.getenv('LOG_LEVEL', 'INFO')),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.getenv('LOG_FILE', 'bot.log')),
        logging.StreamHandler()
    ]
)

# Bot configuration
TOKEN = os.getenv('DISCORD_TOKEN')
CLIENT_ID = os.getenv('DISCORD_CLIENT_ID')
DEFAULT_PREFIX = os.getenv('DEFAULT_PREFIX', '!')
DEFAULT_VOLUME = int(os.getenv('DEFAULT_VOLUME', 100))
MAX_PLAYLIST_SIZE = int(os.getenv('MAX_PLAYLIST_SIZE', 100))
MAX_QUEUE_SIZE = int(os.getenv('MAX_QUEUE_SIZE', 1000))

# Create cache directory if it doesn't exist
cache_dir = Path(os.getenv('CACHE_DIR', './cache'))
cache_dir.mkdir(exist_ok=True)

# Bot setup with required intents
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix=DEFAULT_PREFIX, intents=intents)

# Load cogs
async def load_extensions():
    for filename in os.listdir('./cogs'):
        if filename.endswith('.py'):
            await bot.load_extension(f'cogs.{filename[:-3]}')

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')
    try:
        await bot.tree.sync()
        print("Command tree synced.")
    except Exception as e:
        print(f"Error syncing command tree: {e}")

    # Setup wavelink
    lavalink_host = os.getenv("LAVALINK_HOST", "127.0.0.1")
    lavalink_port = os.getenv("LAVALINK_PORT", "2333")
    lavalink_password = os.getenv('LAVALINK_PASSWORD', 'youshallnotpass')
    node_uri = f'http://{lavalink_host}:{lavalink_port}'

    print(f"Attempting to connect to Lavalink node: {node_uri}")
    print(f"Using Lavalink password: '{lavalink_password}'")

    node = wavelink.Node(
        uri=node_uri,
        password=lavalink_password
    )
    try:
        await wavelink.Pool.connect(client=bot, nodes=[node])
        print("Wavelink Pool connection initiated.")
        # You might need to wait for the node to be ready using an event listener
    except Exception as e:
        print(f"Error connecting to Lavalink node: {e}")
        logging.exception("Wavelink connection failed")

@bot.event
async def on_wavelink_node_ready(payload: wavelink.NodeReadyEventPayload):
    print(f"Wavelink Node '{payload.node.identifier}' is ready!")

@bot.event
async def on_wavelink_websocket_closed(payload: wavelink.WebsocketClosedEventPayload):
    print(f"Wavelink websocket closed: Reason: {payload.reason}, Code: {payload.code}")
    # Implement reconnection logic here if needed

async def main():
    async with bot:
        await load_extensions()
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main()) 