import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
import asyncio
import logging
from pathlib import Path
import lavalink # Import the lavalink library

# Load environment variables
load_dotenv()

# Setup logging
log_level_str = os.getenv('LOG_LEVEL', 'INFO').upper()
log_level = getattr(logging, log_level_str, logging.INFO)
log_file = os.getenv('LOG_FILE', 'bot.log')

# Ensure logs directory exists if LOG_FILE includes a path
log_path = Path(log_file)
log_path.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=log_level,
    format='%(asctime)s - %(name)s [%(levelname)s] - %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__) # Use a logger instance

# Bot configuration
TOKEN = os.getenv('DISCORD_TOKEN')
if not TOKEN:
    logger.critical("DISCORD_TOKEN environment variable not set!")
    exit("Error: DISCORD_TOKEN is required.")

CLIENT_ID = os.getenv('DISCORD_CLIENT_ID') # Needed for Lavalink client
if not CLIENT_ID:
    logger.warning("DISCORD_CLIENT_ID environment variable not set. Using bot's user ID instead.")
    # Will fetch ID later in on_ready

DEFAULT_PREFIX = os.getenv('DEFAULT_PREFIX', '!') # Keep for potential future prefix commands
DEFAULT_VOLUME = int(os.getenv('DEFAULT_VOLUME', 100))
MAX_PLAYLIST_SIZE = int(os.getenv('MAX_PLAYLIST_SIZE', 100)) # You'll need to enforce this in the cog
MAX_QUEUE_SIZE = int(os.getenv('MAX_QUEUE_SIZE', 1000)) # You'll need to enforce this in the cog

# Create cache directory if it doesn't exist (might not be needed by lavalink lib itself)
cache_dir = Path(os.getenv('CACHE_DIR', './cache'))
cache_dir.mkdir(exist_ok=True)

# Bot setup with required intents
intents = discord.Intents.default()
intents.message_content = True # Needed for potential prefix commands/debugging
intents.voice_states = True  # Crucial for voice channel updates
intents.guilds = True        # Standard guild events
intents.members = True       # Useful for getting member objects

bot = commands.Bot(command_prefix=DEFAULT_PREFIX, intents=intents) # Keep prefix for now

# --- Lavalink Setup ---
# Lavalink client will be initialized in on_ready after bot user ID is available

@bot.event
async def on_ready():
    """ Executes when the bot is ready and connected to Discord. """
    logger.info(f'Logged in as {bot.user.name} (ID: {bot.user.id})')
    logger.info(f'discord.py version: {discord.__version__}')
    logger.info(f'lavalink version: {lavalink.__version__}')

    # Use Client ID from env or fallback to bot's ID
    lavalink_client_id = CLIENT_ID or str(bot.user.id)

    # Initialize Lavalink client here
    if not hasattr(bot, 'lavalink'): # Initialize only once
        logger.info("Initializing Lavalink Client...")
        bot.lavalink = lavalink.Client(lavalink_client_id)

        # Add Lavalink nodes from environment variables
        lavalink_host = os.getenv("LAVALINK_HOST", "127.0.0.1")
        lavalink_port = int(os.getenv("LAVALINK_PORT", 2333))
        lavalink_password = os.getenv('LAVALINK_PASSWORD', 'youshallnotpass')
        lavalink_region = os.getenv('LAVALINK_REGION', 'us') # Optional, but good practice

        logger.info(f"Adding Lavalink node: Host={lavalink_host}, Port={lavalink_port}, Region={lavalink_region}, SSL=False")
        bot.lavalink.add_node(
            host=lavalink_host,
            port=lavalink_port,
            password=lavalink_password,
            region=lavalink_region,
            name='default-node' # Identifier for this node
        )
        # You can add more nodes here if needed

        # IMPORTANT: Hook Lavalink into discord.py's voice event handling
        bot.add_listener(bot.lavalink.voice_update_handler, 'on_socket_response')
        logger.info("Lavalink voice update handler registered.")

    try:
        logger.info("Attempting to sync application commands...")
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} application commands.")
    except Exception as e:
        logger.error(f"Error syncing application commands: {e}", exc_info=True)

    logger.info("Bot is ready and Lavalink connection prepared.")
    await bot.change_presence(activity=discord.Game(name="Music! /play"))

    # Load cogs after Lavalink is initialized
    await load_extensions()

# Load cogs
async def load_extensions():
    logger.info("Loading extensions...")
    cogs_loaded = 0
    cogs_dir = Path('./cogs')
    if not cogs_dir.is_dir():
        logger.warning(f"Cogs directory '{cogs_dir}' not found. No extensions will be loaded.")
        return

    for filename in os.listdir(cogs_dir):
        if filename.endswith('.py') and not filename.startswith('_'):
            extension_name = f'cogs.{filename[:-3]}'
            try:
                await bot.load_extension(extension_name)
                logger.info(f"Successfully loaded extension: {extension_name}")
                cogs_loaded += 1
            except commands.ExtensionNotFound:
                logger.error(f"Extension not found: {extension_name}")
            except commands.ExtensionAlreadyLoaded:
                logger.warning(f"Extension already loaded: {extension_name}")
            except commands.NoEntryPointError:
                 logger.error(f"Extension '{extension_name}' has no setup() function.")
            except commands.ExtensionFailed as e:
                logger.error(f"Failed to load extension {extension_name}: {e.original}", exc_info=True)
            except Exception as e:
                logger.error(f"An unexpected error occurred loading extension {extension_name}: {e}", exc_info=True)
    logger.info(f"Finished loading extensions. {cogs_loaded} loaded.")

async def main():
    async with bot:
        await load_extensions()
        logger.info("Starting bot...")
        await bot.start(TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except discord.errors.LoginFailure:
        logger.critical("Login Failure: Improper token passed. Make sure your DISCORD_TOKEN in .env is correct.")
    except KeyboardInterrupt:
        logger.info("Bot shutdown requested via KeyboardInterrupt.")
    except Exception as e:
        logger.critical(f"Bot crashed with an unexpected error: {e}", exc_info=True)
    finally:
        logger.info("Bot process ended.")