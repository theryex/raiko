
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

        self.wavelink_node: Optional[wavelink.Node] = None # Store the node reference if needed, though NodePool is often used

    async def load_extensions(self):
        """Loads cogs from the 'cogs' directory."""
        logger.info("Loading extensions...")
        cogs_loaded = 0
        cogs_dir = Path('./cogs')
        if not cogs_dir.is_dir():
            logger.warning(f"Cogs directory '{cogs_dir}' not found. No extensions will be loaded.")
            return

        # Check if NodePool is ready before loading cogs that depend on it
        if not wavelink.NodePool.nodes:
             logger.error("Attempting to load extensions, but Wavelink NodePool is not ready!")
             # Decide if you want to prevent loading or just warn
             # return # Option: Stop loading if NodePool isn't ready

        for filename in os.listdir(cogs_dir):
            if filename.endswith('.py') and not filename.startswith('_'):
                extension_name = f'cogs.{filename[:-3]}'
                try:
                    await self.load_extension(extension_name)
                    logger.info(f"Successfully loaded extension: {extension_name}")
                    cogs_loaded += 1
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
        """Initialize Wavelink and load extensions here."""
        logger.info("Running setup_hook...")

        if not self.user:
            await asyncio.sleep(0.1) # Brief wait for user object availability
            if not self.user:
                logger.error("Bot user not available during setup_hook. Cannot initialize Wavelink.")
                return

        # --- Initialize Wavelink Node ---
        logger.info("Initializing Wavelink node...")
        try:
            lavalink_host = os.getenv("LAVALINK_HOST", "127.0.0.1")
            lavalink_port = int(os.getenv("LAVALINK_PORT", "2333"))
            lavalink_password = os.getenv("LAVALINK_PASSWORD", "youshallnotpass")
            node_id = os.getenv("LAVALINK_IDENTIFIER", "DEFAULT_NODE") # Optional identifier

            # Construct the URI carefully
            # Assuming http for standard Lavalink setup. Adjust if using ws/wss.
            node_uri = f"http://{lavalink_host}:{lavalink_port}"
            logger.debug(f"Attempting to connect Wavelink node '{node_id}' to {node_uri}")

            # Create the node instance
            node = wavelink.Node(
                identifier=node_id,
                uri=node_uri,
                password=lavalink_password
            )
            self.wavelink_node = node # Store reference if needed

            # Connect the node using NodePool
            # Wavelink v3+ uses connect on NodePool
            await wavelink.NodePool.connect(client=self, nodes=[node])
            # Note: Node connection status is handled via events (on_wavelink_node_ready)

        except Exception as e:
            logger.critical(f"Failed to initialize or connect Wavelink node: {e}", exc_info=True)
            # Consider if exiting is the right approach or if the bot can run without music
            exit("Wavelink connection failed during setup.")

        # --- Load Extensions AFTER Wavelink setup attempt ---
        await self.load_extensions()

        # --- Sync Slash Commands AFTER extensions are loaded ---
        try:
            logger.info("Syncing slash commands...")
            synced = await self.tree.sync()
            logger.info(f"Synced {len(synced)} command(s) globally.")
            # Optional guild sync (uncomment and replace ID if needed):
            # guild_id = 123456789012345678 # Replace with your test server ID
            # synced = await self.tree.sync(guild=discord.Object(id=guild_id))
            # logger.info(f"Synced {len(synced)} command(s) to guild {guild_id}")
        except Exception as e:
            logger.error(f"Failed to sync commands: {e}")

        logger.info("setup_hook completed.")

    async def on_ready(self):
        """Called when the bot is ready (discord side)."""
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        # Check node status via NodePool or stored reference
        node_status = "Not Initialized"
        node = wavelink.NodePool.get_node() # Get default node
        if node:
            node_status = "Connected" if node.is_connected else "Connecting/Failed"
            logger.info(f"Wavelink Node '{node.identifier}' Status: {node_status}")
        else:
             logger.warning("Wavelink NodePool has no nodes available.")

        logger.info("------")
        await self.change_presence(activity=discord.Game(name="Music! /play"))

    # Optional: Add listener for Wavelink websocket close here if not handled in Cog
    # @commands.Cog.listener() # This would need to be in a Cog or handled differently if defined here
    # async def on_wavelink_websocket_closed(self, payload: wavelink.WebsocketClosedEventPayload):
    #    logger.error(f"Wavelink WS closed for Node '{payload.node.identifier}'! "
    #                 f"Code: {payload.code}, Reason: {payload.reason}, By Remote: {payload.remote}")


# --- Main Execution ---
async def main():
    bot = MusicBot()
    async with bot:
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
