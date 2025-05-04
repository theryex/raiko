# --- START OF FILE bot.py ---

import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
import asyncio
import logging
from pathlib import Path
try:
    import wavelink
except ImportError:
    logging.critical("wavelink is not installed! Please install it: pip install wavelink")
    exit("Error: wavelink dependency missing.")
from typing import Optional

# --- Configuration & Logging Setup (Keep as is) ---
load_dotenv()
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
TOKEN = os.getenv('DISCORD_TOKEN')
if not TOKEN:
    logger.critical("DISCORD_TOKEN environment variable not set!")
    exit("Error: DISCORD_TOKEN is required.")
CLIENT_ID = os.getenv('DISCORD_CLIENT_ID')
DEFAULT_PREFIX = os.getenv('DEFAULT_PREFIX', '!')
DEFAULT_VOLUME = int(os.getenv('DEFAULT_VOLUME', 100))
MAX_PLAYLIST_SIZE = int(os.getenv('MAX_PLAYLIST_SIZE', 100))
MAX_QUEUE_SIZE = int(os.getenv('MAX_QUEUE_SIZE', 1000))
CACHE_DIR = Path(os.getenv('CACHE_DIR', './cache'))
CACHE_DIR.mkdir(exist_ok=True)
# --- End Configuration & Logging ---


# --- Global Wavelink Event Listeners ---
# These need access to the node, which will be on the bot instance.
# We can define them here and attach them in setup_hook using the bot instance.

async def on_lava_ready(event: wavelink.ReadyEvent):
    """Called when a Wavelink node is ready."""
    # We assume 'bot' is the global instance later, or pass node if needed.
    logger.info(f"Wavelink Node '{event.node.identifier}' is ready!")

async def on_websocket_closed(event: wavelink.WebSocketClosedEvent):
    """Called when the Wavelink websocket connection closes."""
    logger.error(f"Wavelink WS closed for Node '{event.node.identifier}'! "
                 f"Code: {event.code}, Reason: {event.reason}, Guild: {event.guild_id}")
# --------------------------------------


# --- Bot Class Definition ---
class MusicBot(commands.Bot):
    def __init__(self):
        # Define intents
        intents = discord.Intents.default()
        intents.voice_states = True
        intents.message_content = True
        intents.guilds = True
        intents.members = True # If needed by other cogs/features
        intents.guild_messages = True

        # Initialize commands.Bot
        super().__init__(command_prefix=DEFAULT_PREFIX, intents=intents)

        # Initialize Wavelink node placeholder
        self.wavelink_node: Optional[wavelink.Node] = None

    async def load_extensions(self):
        """Loads cogs from the 'cogs' directory."""
        # Now uses self.load_extension
        logger.info("Loading extensions...")
        cogs_loaded = 0
        cogs_dir = Path('./cogs')
        if not cogs_dir.is_dir():
            logger.warning(f"Cogs directory '{cogs_dir}' not found. No extensions will be loaded.")
            return

        if not self.wavelink_node: # Check self.wavelink_node
             logger.error("Attempting to load extensions, but self.wavelink_node is not initialized!")
             return

        for filename in os.listdir(cogs_dir):
            if filename.endswith('.py') and not filename.startswith('_'):
                extension_name = f'cogs.{filename[:-3]}'
                try:
                    await self.load_extension(extension_name) # Use self.load_extension
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

    async def setup_hook(self):
        """Initialize Wavelink and load extensions here."""
        logger.info("Running setup_hook...")

        if not self.user:
            # This check might run before the user is fully available,
            # but user ID should be ready shortly after login.
            # Wait a brief moment if needed, though usually setup_hook runs late enough.
            await asyncio.sleep(0.1)
            if not self.user:
                logger.error("Bot user not available during setup_hook. Cannot initialize Wavelink.")
                return

        # --- Initialize Wavelink Node ---
        logger.info("Initializing Wavelink node...")
        try:
            lavalink_host = os.getenv("LAVALINK_HOST", "127.0.0.1")
            lavalink_port = int(os.getenv("LAVALINK_PORT", "2333"))
            lavalink_password = os.getenv("LAVALINK_PASSWORD", "youshallnotpass")

            self.wavelink_node = wavelink.Node(uri=f"http://{lavalink_host}:{lavalink_port}", password=lavalink_password)
            await wavelink.NodePool.connect(client=self, nodes=[self.wavelink_node])

            logger.info(f"Successfully connected to Wavelink node at {lavalink_host}:{lavalink_port}")
        except Exception as e:
            logger.critical(f"Failed to initialize or connect Wavelink node: {e}", exc_info=True)
            exit("Wavelink connection failed during setup.")

        # --- Load Extensions AFTER Wavelink is set up ---
        # This part only runs if all the above succeeds without exiting
        await self.load_extensions()

        # --- Sync Slash Commands AFTER extensions are loaded ---
        try:
            logger.info("Syncing slash commands...")
            # Use self.tree
            synced = await self.tree.sync()
            logger.info(f"Synced {len(synced)} command(s) globally.")
            # Optional guild sync:
            # guild_id = YOUR_TEST_SERVER_ID
            # synced = await self.tree.sync(guild=discord.Object(id=guild_id))
            # logger.info(f"Synced {len(synced)} command(s) to guild {guild_id}")
        except Exception as e:
            logger.error(f"Failed to sync commands: {e}")

        logger.info("setup_hook completed.")

    async def on_ready(self):
        """Called when the bot is ready (discord side)."""
        # setup_hook runs before this
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        node_status = "Not Initialized"
        if self.wavelink_node:
            node_status = "Connected" if self.wavelink_node.is_connected else "Connecting/Failed"
        logger.info(f"Wavelink Node Status: {node_status}")
        logger.info("------")
        await self.change_presence(activity=discord.Game(name="Music! /play"))

# --- Main Execution ---
async def main():
    # Instantiate the bot class
    bot = MusicBot()
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
        logger.critical(f"ImportError: {e}. Please ensure all dependencies are installed.")
    except Exception as e:
        logger.critical(f"Bot crashed with an unexpected error: {e}", exc_info=True)
    finally:
        logger.info("Bot process ended.")

# --- END OF FILE bot.py ---