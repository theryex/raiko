import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
import asyncio
import logging
from pathlib import Path
try:
    import wavelink # Use Wavelink
except ImportError:
    logging.critical("wavelink is not installed! Please install it: pip install wavelink")
    exit("Error: wavelink dependency missing.")
from typing import Optional

# --- Configuration & Logging Setup ---
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
# These env vars can be used by cogs if needed
DEFAULT_VOLUME = int(os.getenv('DEFAULT_VOLUME', 100))
MAX_PLAYLIST_SIZE = int(os.getenv('MAX_PLAYLIST_SIZE', 100))
MAX_QUEUE_SIZE = int(os.getenv('MAX_QUEUE_SIZE', 1000))
CACHE_DIR = Path(os.getenv('CACHE_DIR', './cache'))
CACHE_DIR.mkdir(exist_ok=True)
# --- End Configuration & Logging ---


# --- Bot Class Definition ---
class MusicBot(commands.Bot):
    def __init__(self):
        # Define intents
        intents = discord.Intents.default()
        intents.voice_states = True
        intents.message_content = True
        intents.guilds = True
        intents.members = False # Keep False unless specifically needed for other features
        intents.guild_messages = True

        # Initialize commands.Bot
        super().__init__(command_prefix=DEFAULT_PREFIX, intents=intents)
        # Node Pool manages nodes; no need to store individual nodes here generally

        self.wavelink_ready_event = asyncio.Event() # Signal for Wavelink node readiness

    # --- ADD THIS LISTENER ---
    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, payload: wavelink.NodeReadyEventPayload):
        """Event fired when a node establishes a connection."""
        node = payload.node
        logger.info(f"Wavelink Node '{node.identifier}' is ready! Session ID: {payload.session_id}")
        self.wavelink_ready_event.set() # Signal that the node is ready

    async def load_extensions(self):
        """Loads cogs from the 'cogs' directory."""
        logger.info("Loading extensions...")
        cogs_loaded = 0
        cogs_dir = Path('./cogs')
        if not cogs_dir.is_dir():
            logger.warning(f"Cogs directory '{cogs_dir}' not found. No extensions will be loaded.")
            return

        # Let cogs load, they should check for node readiness in their setup/checks
        for filename in os.listdir(cogs_dir):
            if filename.endswith('.py') and not filename.startswith('_'):
                extension_name = f'cogs.{filename[:-3]}'
                try:
                    # Pass config values when loading the cog
                    await self.load_extension(extension_name)
                    # OR if setup function takes args (less common for cogs):
                    # await self.load_extension(extension_name, package=None, volume=DEFAULT_VOLUME)
                    logger.info(f"Successfully loaded extension: {extension_name}")
                except commands.ExtensionNotFound:
                    logger.error(f"Extension not found: {extension_name}")
                except commands.ExtensionAlreadyLoaded:
                    logger.warning(f"Extension already loaded: {extension_name}")
                except commands.NoEntryPointError:
                     logger.error(f"Extension '{extension_name}' has no setup() function.")
                except commands.ExtensionFailed as e:
                    # Log the original exception for better debugging
                    logger.error(f"Failed to load extension {extension_name}: {e.original}", exc_info=True)
                except Exception as e:
                    logger.error(f"An unexpected error occurred loading extension {extension_name}: {e}", exc_info=True)
        logger.info(f"Finished loading extensions. {cogs_loaded} loaded.")

    async def setup_hook(self):
        
        # --- Connect to Lavalink ---
        logger.info("Initializing Wavelink node connection...")
        try:
            lavalink_host = os.getenv("LAVALINK_HOST", "127.0.0.1")
            lavalink_port = int(os.getenv("LAVALINK_PORT", "2333"))
            lavalink_password = os.getenv("LAVALINK_PASSWORD", "youshallnotpass")

            node_uri = f"http://{lavalink_host}:{lavalink_port}"
            logger.debug(f"Attempting to connect to Lavalink at {node_uri}")

            # Initiate the connection
            await wavelink.Pool.connect(
                nodes=[
                    wavelink.Node(
                        uri=node_uri,
                        password=lavalink_password
                    )
                ],
                client=self
            )
            logger.info("Wavelink connection process initiated.")

        except Exception as e:
            logger.critical(f"Failed to initiate Wavelink connection: {e}", exc_info=True)
            exit("Lavalink connection failed during initiation.")

        # --- Wait for Node to be Ready ---
        logger.info("Waiting for Wavelink node to become ready...")
        try:
            # Wait for the on_wavelink_node_ready event to fire, with a timeout
            timeout = int(os.getenv("WAVELINK_TIMEOUT", 30))  # Default timeout is 30 seconds
            max_retries = 3
            retry_delay = 10  # seconds
            
            for attempt in range(max_retries):
                try:
                    await asyncio.wait_for(self.wavelink_ready_event.wait(), timeout=timeout)
                    logger.info("Wavelink node is ready!")
                    break
                except asyncio.TimeoutError:
                    logger.warning(f"Attempt {attempt + 1} of {max_retries} timed out. Retrying in {retry_delay} seconds...")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                    else:
                        logger.critical("Exceeded maximum retries waiting for Wavelink node to become ready.")
                        raise RuntimeError("Lavalink node connection failed after multiple retries.")
            
        except asyncio.TimeoutError:
            logger.critical("Timed out waiting for Wavelink node to become ready. Check Lavalink connection & logs.")
            raise RuntimeError("Lavalink node connection timed out.")

        # --- Load Extensions AFTER Wavelink is Ready ---
        logger.debug("Wavelink node ready, loading extensions...")
        await self.load_extensions()

        # --- Sync Slash Commands AFTER extensions are loaded ---
        try:
            logger.info("Syncing slash commands...")
            synced = await self.tree.sync()
            logger.info(f"Synced {len(synced)} command(s) globally.")
        except Exception as e:
            logger.error(f"Failed to sync commands: {e}")

        logger.info("setup_hook completed.")

    async def on_ready(self):
        """Called when the bot is ready (discord side)."""
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        # Don't log node status here, rely on the on_wavelink_node_ready event listener
        logger.info("Bot is ready. Waiting for Wavelink node connection events...")
        logger.info("------")
        await self.change_presence(activity=discord.Game(name="Music! /player, Users! /users, GPU info! /gpuinfo"))

# --- Main Execution ---
async def main():
    bot = MusicBot()
    try:
        logger.info("Starting bot...")
        await bot.start(TOKEN)
    except RuntimeError as e:  # Handle custom exceptions for graceful shutdown
        logger.critical(f"RuntimeError: {e}")
    except SystemExit as e:  # Catch the explicit exit() call
        logger.info(f"Bot process terminated: {e}")
    except Exception as e:
        logger.critical(f"Unexpected error during bot execution: {e}", exc_info=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except discord.errors.LoginFailure:
        logger.critical("Login Failure: Improper token passed. Make sure DISCORD_TOKEN is correct.")
    except KeyboardInterrupt:
        logger.info("Bot shutdown requested via KeyboardInterrupt.")
    except ImportError as e:
        logger.critical(f"ImportError: {e}. Please ensure all dependencies are installed.")
    except SystemExit as e: # Catch the explicit exit() call
         logger.info(f"Bot process terminated: {e}")
    except Exception as e:
        logger.critical(f"Bot crashed with an unexpected error: {e}", exc_info=True)
    finally:
        # Ensure logs indicate the process truly finished
        logging.info("Bot process ended.")
        logging.shutdown() # Explicitly shut down logging


