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
intents.voice_states = True  # Required for voice channel state tracking
intents.message_content = True  # Required for message content
intents.guilds = True  # Required for guild data
intents.members = True  # Required for member data
intents.voice_states = True  # Required for voice state updates
intents.guild_messages = True  # Required for message events

bot = commands.Bot(command_prefix=DEFAULT_PREFIX, intents=intents)

# Initialize Lavalink client
bot.lavalink = None

# --- Lavalink Setup ---
# Lavalink client will be initialized in on_ready after bot user ID is available

@bot.event
async def on_ready():
    """Called when the bot is ready"""
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    logger.info("------")

    # Initialize Lavalink client
    bot.lavalink = lavalink.Client(bot.user.id)
    
    # Add Lavalink nodes from environment variables
    lavalink_nodes = [
        {
            "host": os.getenv("LAVALINK_HOST", "localhost"),
            "port": int(os.getenv("LAVALINK_PORT", "2333")),
            "password": os.getenv("LAVALINK_PASSWORD", "youshallnotpass"),
            "region": os.getenv("LAVALINK_REGION", "us"),
            "name": "default-node"
        }
    ]
    
    for node in lavalink_nodes:
        try:
            bot.lavalink.add_node(**node)
            logger.info(f"Added Lavalink node: {node['host']}:{node['port']}")
        except Exception as e:
            logger.error(f"Failed to add Lavalink node: {e}")

    # Sync slash commands
    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} command(s)")
    except Exception as e:
        logger.error(f"Failed to sync commands: {e}")

    logger.info("Bot is ready and Lavalink connection prepared.")
    await bot.change_presence(activity=discord.Game(name="Music! /play"))

    # Load extensions after Lavalink is initialized
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
    # Start the bot
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