# --- START OF FILE bot.py ---

import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
import asyncio
import logging
from pathlib import Path
# --- LAVAPLAY Import ---
try:
    import lavaplay
except ImportError:
    logging.critical("lavaplay.py is not installed! Please install it: pip install lavaplay.py")
    exit("Error: lavaplay.py dependency missing.")
# --- End LAVAPLAY Import ---
from typing import Optional

# Load environment variables
load_dotenv()

# Setup logging (same as before)
log_level_str = os.getenv('LOG_LEVEL', 'INFO').upper()
log_level = getattr(logging, log_level_str, logging.INFO)
log_file = os.getenv('LOG_FILE', 'bot.log')
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
logger = logging.getLogger(__name__)

# Bot configuration (mostly same as before)
TOKEN = os.getenv('DISCORD_TOKEN')
if not TOKEN:
    logger.critical("DISCORD_TOKEN environment variable not set!")
    exit("Error: DISCORD_TOKEN is required.")

# CLIENT_ID is NOT typically needed by lavaplay itself, but good practice to have
CLIENT_ID = os.getenv('DISCORD_CLIENT_ID')
if not CLIENT_ID:
    logger.warning("DISCORD_CLIENT_ID environment variable not set.")

DEFAULT_PREFIX = os.getenv('DEFAULT_PREFIX', '!')
DEFAULT_VOLUME = int(os.getenv('DEFAULT_VOLUME', 100)) # Keep for cog
MAX_PLAYLIST_SIZE = int(os.getenv('MAX_PLAYLIST_SIZE', 100)) # Keep for cog
MAX_QUEUE_SIZE = int(os.getenv('MAX_QUEUE_SIZE', 1000)) # Keep for cog
CACHE_DIR = Path(os.getenv('CACHE_DIR', './cache')) # Keep for potential future use
CACHE_DIR.mkdir(exist_ok=True)

# Bot setup with required intents (same as before)
intents = discord.Intents.default()
intents.voice_states = True
intents.message_content = True
intents.guilds = True
intents.members = True # If needed by other cogs/features
intents.guild_messages = True

# Use commands.Bot as before
bot = commands.Bot(command_prefix=DEFAULT_PREFIX, intents=intents)

# --- LAVAPLAY Setup ---
# Placeholder for the node instance, will be initialized in setup_hook
bot.lavalink_node: Optional[lavaplay.Node] = None
# --------------------

# --- Lavaplay Event Listeners (Attached to the Bot/Node) ---
# We define them here but attach them in setup_hook

async def on_lava_ready(event: lavaplay.ReadyEvent):
    """Called when a Lavalink node is ready."""
    logger.info(f"Lavalink Node '{event.node.identifier}' is ready!")

async def on_websocket_closed(event: lavaplay.WebSocketClosedEvent):
    """Called when the Lavalink websocket connection closes."""
    logger.error(f"Lavalink WS closed for Node '{event.node.identifier}'! "
                 f"Code: {event.code}, Reason: {event.reason}, Guild: {event.guild_id}")
    # You might want reconnection logic here, though lavaplay might handle some internally

# Track/Player specific events will be handled in the Music cog

# ----------------------------------------------------------

@bot.event
async def on_ready():
    """Called when the bot is ready (discord side)."""
    # setup_hook runs before this, so lavalink_node should exist
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    logger.info(f"Lavalink Node Status: {'Connected' if bot.lavalink_node and bot.lavalink_node.stats else 'Not Connected'}")
    logger.info("------")
    await bot.change_presence(activity=discord.Game(name="Music! /play"))


async def load_extensions():
    """Loads cogs from the 'cogs' directory."""
    logger.info("Loading extensions...")
    cogs_loaded = 0
    cogs_dir = Path('./cogs')
    if not cogs_dir.is_dir():
        logger.warning(f"Cogs directory '{cogs_dir}' not found. No extensions will be loaded.")
        return

    # Make sure lavalink_node exists before loading cogs that depend on it
    if not hasattr(bot, 'lavalink_node') or bot.lavalink_node is None:
         logger.error("Attempting to load extensions, but bot.lavalink_node is not initialized!")
         # Prevent loading cogs if Lavalink isn't ready
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
                # Log the original error from the cog setup
                logger.error(f"Failed to load extension {extension_name}: {e.original}", exc_info=True)
            except Exception as e:
                logger.error(f"An unexpected error occurred loading extension {extension_name}: {e}", exc_info=True)
    logger.info(f"Finished loading extensions. {cogs_loaded} loaded.")

# --- Setup Hook ---
@bot.setup_hook
async def setup_hook():
    """Initialize Lavalink and load extensions here."""
    logger.info("Running setup_hook...")

    if not bot.user:
        logger.error("Bot user not available during setup_hook. Cannot initialize Lavalink.")
        return

    # --- Initialize Lavalink Node ---
    logger.info("Initializing Lavalink node...")
    try:
        lava = lavaplay.Lavalink()
        # Ensure required env vars are present
        lavalink_host = os.getenv("LAVALINK_HOST", "127.0.0.1") # Default to 127.0.0.1
        lavalink_port = int(os.getenv("LAVALINK_PORT", "2333"))
        lavalink_password = os.getenv("LAVALINK_PASSWORD", "youshallnotpass")

        bot.lavalink_node = lava.create_node(
            host=lavalink_host,
            port=lavalink_port,
            password=lavalink_password,
            user_id=bot.user.id, # Essential: Use the bot's user ID
            # name="default-node" # lavaplay doesn't use name in create_node
            # region="us" # lavaplay doesn't use region here
        )
        # Set the event loop (Crucial for discord.py integration)
        bot.lavalink_node.set_event_loop(bot.loop)

        # Add global listeners defined earlier
        bot.lavalink_node.event_manager.add_listener(lavaplay.ReadyEvent, on_lava_ready)
        bot.lavalink_node.event_manager.add_listener(lavaplay.WebSocketClosedEvent, on_websocket_closed)
        # Player/Track events will be in the cog

        # Connect the node
        await bot.lavalink_node.connect()
        logger.info(f"Attempted connection to Lavalink node at {lavalink_host}:{lavalink_port}")

    except Exception as e:
        logger.critical(f"Failed to initialize or connect Lavalink node: {e}", exc_info=True)
        # Decide if the bot should exit or continue without music
        # return # Or raise, or sys.exit

    # --- Load Extensions AFTER Lavalink is set up ---
    await load_extensions()

    # --- Sync Slash Commands AFTER extensions are loaded ---
    try:
        logger.info("Syncing slash commands...")
        # Sync globally (can take time)
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} command(s) globally.")
        # Optional: Sync to a specific guild for testing
        # guild_id = YOUR_TEST_SERVER_ID
        # synced = await bot.tree.sync(guild=discord.Object(id=guild_id))
        # logger.info(f"Synced {len(synced)} command(s) to guild {guild_id}")
    except Exception as e:
        logger.error(f"Failed to sync commands: {e}")

    logger.info("setup_hook completed.")


async def main():
    async with bot: # Use async context manager
        logger.info("Starting bot...")
        await bot.start(TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except discord.errors.LoginFailure:
        logger.critical("Login Failure: Improper token passed. Make sure your DISCORD_TOKEN in .env is correct.")
    except KeyboardInterrupt:
        logger.info("Bot shutdown requested via KeyboardInterrupt.")
    except ImportError as e:
        # Catch potential import errors like lavaplay missing
        logger.critical(f"ImportError: {e}. Please ensure all dependencies are installed.")
    except Exception as e:
        logger.critical(f"Bot crashed with an unexpected error: {e}", exc_info=True)
    finally:
        logger.info("Bot process ended.")

# --- END OF FILE bot.py ---