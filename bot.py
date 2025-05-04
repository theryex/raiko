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

        # --- Initialize and Connect Wavelink Node using pool.connect ---
        logger.info("Initializing Wavelink node ")
        try:
            lavalink_host = os.getenv("LAVALINK_HOST", "127.0.0.1")
            lavalink_port = int(os.getenv("LAVALINK_PORT", "2333"))
            lavalink_password = os.getenv("LAVALINK_PASSWORD", "youshallnotpass")
            node_id = os.getenv("LAVALINK_IDENTIFIER", "DEFAULT_NODE")

            node_uri = f"http://{lavalink_host}:{lavalink_port}"
            logger.debug(f"Preparing node '{node_id}' for URI {node_uri}")

            # 1. Create the Node instance WITHOUT the client here
            node = wavelink.Node(
                identifier=node_id,
                uri=node_uri,
                password=lavalink_password
            )

            # 2. Connect using Pool.connect, passing the client and list of nodes
            # Add a timeout to prevent indefinite hanging
            logger.debug("Starting Pool.connect task...")
            connect_task = asyncio.create_task(wavelink.Pool.connect(nodes=[node], client=self))
            await asyncio.wait_for(connect_task, timeout=30)  # Timeout after 30 seconds

            logger.info(f"Wavelink Pool.connect called for node '{node_id}'. Waiting for node ready event...")

        # Catch specific Wavelink exceptions if possible, otherwise general Exception
        except asyncio.TimeoutError:
            logger.critical("Wavelink connection timed out. Please check your Lavalink server.")
            exit("Wavelink connection timed out during setup.")
        except wavelink.InvalidClientException as e:
            logger.critical(f"Wavelink connection failed: Invalid client provided. Error: {e}", exc_info=True)
            exit("Wavelink connection failed during setup (Invalid Client).")
        except wavelink.AuthorizationFailedException as e:
            logger.critical(f"Wavelink connection failed: Authorization failed (check password?). Error: {e}", exc_info=True)
            exit("Wavelink connection failed during setup (Authorization Failed).")
        except wavelink.NodeException as e:
            logger.critical(f"Wavelink connection failed: Node connection error (check URI/Lavalink server?). Error: {e}", exc_info=True)
            exit("Wavelink connection failed during setup (Node Error).")
        except Exception as e:
            logger.critical(f"Failed during Wavelink Pool.connect setup: {e}", exc_info=True)
            exit("Wavelink connection failed during setup.")

        # Add debug log to check node status after connection
        try:
            node = wavelink.NPool.get_node()
            logger.info(f"Node '{node.identifier}' status: {node.status}")
        except Exception as e:
            logger.error(f"Failed to retrieve node status: {e}")

        # Add timeout handling for node readiness
        try:
            await asyncio.wait_for(self.wait_until_ready(), timeout=30)
            logger.info("Bot is ready and node connection is complete.")
        except asyncio.TimeoutError:
            logger.critical("Timeout waiting for Lavalink node to be ready. Exiting...")
            exit("Timeout waiting for Lavalink node to be ready.")

        # --- Load Extensions AFTER Wavelink setup attempt ---
        # Extensions should ideally wait for on_wavelink_node_ready if they need immediate node access
        logger.debug("Loading extensions after Wavelink setup...")
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
        await self.change_presence(activity=discord.Game(name="Music! /play"))

        # Add debug log to confirm node readiness
        @self.event
        async def on_wavelink_node_ready(node):
            logger.info(f"Wavelink node '{node.identifier}' is ready and connected.")

        # Add debug log to confirm node disconnection
        @self.event
        async def on_wavelink_node_disconnect(node):
            logger.warning(f"Wavelink node '{node.identifier}' has disconnected.")

        # Add debug log to confirm node connection failure
        @self.event
        async def on_wavelink_node_connection_failed(node, error):
            logger.error(f"Wavelink node '{node.identifier}' connection failed: {error}")

# --- Main Execution ---
async def main():
    bot = MusicBot()
    async with bot: # Use async context manager for cleaner shutdown
        logger.info("Starting bot...")
        await bot.start(TOKEN)

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


