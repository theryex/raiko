import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
import asyncio
import logging
from pathlib import Path
import wavelink # Added for Lavalink

# Configuration
load_dotenv()
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] [%(name)s] - %(message)s',
    handlers=[
        logging.FileHandler('bot_debug_on_ready.log', encoding='utf-8', mode='w'), # New log file
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv('DISCORD_TOKEN')
if not TOKEN:
    logger.critical("CRITICAL: DISCORD_TOKEN is required in .env file. Exiting.")
    exit("Error: DISCORD_TOKEN is required in .env file")

DEFAULT_PREFIX = os.getenv('DEFAULT_PREFIX', '!')

class DebugBotOnReady(commands.Bot):
    def __init__(self):
        logger.info("Initializing DebugBotOnReady...")
        intents = discord.Intents.default()
        intents.message_content = True # If cogs.system uses it for prefix commands
        intents.guilds = True
        intents.voice_states = True # Required for Lavalink/voice functionality
        # intents.guild_messages = True # Covered by default intents if message_content is true

        super().__init__(command_prefix=DEFAULT_PREFIX, intents=intents)
        self.setup_called_once = False # Flag to ensure setup logic in on_ready runs once
        logger.info("DebugBotOnReady super().__init__() called.")

    async def load_extensions_debug(self):
        # Load cogs.system
        logger.info("Attempting to load 'cogs.system' extension...")
        try:
            await self.load_extension("cogs.system")
            logger.info("Successfully loaded extension: cogs.system")
        except commands.ExtensionAlreadyLoaded:
            logger.warning("ExtensionAlreadyLoaded: cogs.system is already loaded. Attempting to reload...")
            try:
                await self.reload_extension("cogs.system")
                logger.info("Successfully reloaded extension: cogs.system")
            except Exception as e_reload:
                logger.error("Failed to reload cogs.system.", exc_info=True)
        except commands.ExtensionNotFound:
            logger.error("ExtensionNotFound: cogs.system could not be found. Ensure cogs/system.py exists.", exc_info=True)
        except commands.NoEntryPointError:
            logger.error("NoEntryPointError: cogs.system (cogs/system.py) does not have a 'setup' function.", exc_info=True)
        except commands.ExtensionFailed as e:
            logger.error("ExtensionFailed: cogs.system (cogs/system.py) failed to load. Error: %s", e.original, exc_info=True)
        except Exception as e:
            logger.error("An unexpected error occurred while loading cogs.system.", exc_info=True)

        # Load cogs.music
        logger.info("Attempting to load 'cogs.music' extension...")
        try:
            await self.load_extension("cogs.music")
            logger.info("Successfully loaded extension: cogs.music")
        except commands.ExtensionAlreadyLoaded:
            logger.warning("ExtensionAlreadyLoaded: cogs.music is already loaded. Attempting to reload...")
            try:
                await self.reload_extension("cogs.music")
                logger.info("Successfully reloaded extension: cogs.music")
            except Exception as e_reload:
                logger.error("Failed to reload cogs.music.", exc_info=True)
        except commands.ExtensionNotFound:
            logger.error("ExtensionNotFound: cogs.music could not be found. Ensure cogs/music.py exists.", exc_info=True)
        except commands.NoEntryPointError:
            logger.error("NoEntryPointError: cogs.music (cogs/music.py) does not have a 'setup' function.", exc_info=True)
        except commands.ExtensionFailed as e:
            logger.error("ExtensionFailed: cogs.music (cogs/music.py) failed to load. This might be due to an error within the cog itself (e.g., Lavalink node not ready, import error). Error: %s", e.original, exc_info=True)
        except Exception as e:
            logger.error("An unexpected error occurred while loading cogs.music.", exc_info=True)
        
        logger.info(f"Current cogs after extension loading attempt: {list(self.cogs.keys())}") # More concise log of loaded cogs
        # logger.info(f"Current commands after load_extensions_debug: {[cmd.name for cmd in self.commands]}") # This logs prefixed commands, tree commands logged in on_ready

    async def sync_app_commands_debug(self):
        logger.info("Attempting to sync application commands (called from on_ready)...")
        if not self.cogs: # Check if cogs.system loaded, as it should contain app commands
            logger.warning("No cogs seem to be loaded. Application command syncing might be ineffective.")
        
        try:
            synced_commands = await self.tree.sync()
            logger.info(f"Application commands synced globally. Synced: {len(synced_commands)} commands. Details: {[c.name for c in synced_commands]}")
            for cmd in synced_commands:
                logger.debug(f"Synced command: {cmd.name}, ID: {cmd.id}, Type: {type(cmd)}")
        except discord.errors.Forbidden:
            logger.error("Forbidden: Failed to sync application commands. Check bot permissions (application.commands scope).", exc_info=True)
        except discord.app_commands.CommandSyncFailure as e:
             logger.error(f"CommandSyncFailure: {e.message}, Details: {e.failed_commands}", exc_info=True)
        except discord.errors.HTTPException as e:
            logger.error(f"HTTPException: Failed to sync application commands. {e.status} - {e.text}", exc_info=True)
        except Exception as e:
            logger.error(f"An unexpected error occurred during command syncing.", exc_info=True)

    async def setup_hook(self):
        logger.info("DebugBotOnReady setup_hook called.") # Moved to the beginning

        # Lavalink Node Setup
        lavalink_host = os.getenv('LAVALINK_HOST', '127.0.0.1')
        lavalink_port = int(os.getenv('LAVALINK_PORT', 2333)) # Ensure port is int
        lavalink_password = os.getenv('LAVALINK_PASSWORD', 'SUPERSECUREPASSWORD_A1B2C3')
        lavalink_uri = f"http://{lavalink_host}:{lavalink_port}" # Wavelink V3 uses http

        logger.info(f"Attempting to connect to Lavalink node at {lavalink_uri}...")
        node = wavelink.Node(
            uri=lavalink_uri,
            password=lavalink_password,
            client=self  # Pass the bot instance as the client
        )
        try:
            # For Wavelink 3.x, use wavelink.Pool.connect()
            # The `nodes` parameter takes a list of Node objects.
            await wavelink.Pool.connect(nodes=[node], client=self, cache_capacity=100)
            logger.info(f"Successfully initiated connection to Lavalink node: {node.identifier}")
        except Exception as e:
            # Specific critical log message for connection failure
            logger.critical(f"CRITICAL: Failed to connect to Lavalink node at {lavalink_uri}. Music functions will be unavailable. Error: {e}", exc_info=True)
            # Depending on desired behavior, you might want to exit or raise an exception to stop the bot.
            # For now, it logs and continues, but music cog might fail to load or operate.

        logger.info("Lavalink setup in setup_hook completed.")
        # Note: Actual node readiness is confirmed by on_wavelink_node_ready event.

        # It's generally better practice to load extensions in setup_hook after initial async setup like Lavalink.
        # However, the current debug flow calls it from on_ready. We will keep that for now as per instruction,
        # but acknowledge this point. If moved here, ensure on_ready doesn't also try to load them.


    async def on_ready(self):
        logger.info(f"DebugBotOnReady logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Bot is in {len(self.guilds)} guilds.")
        
        if not self.setup_called_once:
            logger.info("Running one-time setup logic in on_ready...")
            
            logger.info("Loading extensions (as per debug flow from on_ready)...")
            await self.load_extensions_debug() # Call to load extensions
            logger.info("Extension loading process completed.")
            
            logger.info("Syncing application commands (as per debug flow from on_ready)...")
            await self.sync_app_commands_debug() # Call to sync commands
            logger.info("Application command syncing process completed.")

            # Wavelink event listener setup (remains important)
            if wavelink.Pool.nodes: # Check if any nodes were added in setup_hook
                 logger.info("Wavelink nodes are available in the pool. Attaching event listeners.")
                 # Ensure these listeners are added only once if on_ready can be called multiple times.
                 # The self.setup_called_once flag helps with this.
                 self.add_listener(self.on_wavelink_node_ready, 'on_wavelink_node_ready')
                 self.add_listener(self.on_wavelink_track_end, 'on_wavelink_track_end')
                 self.add_listener(self.on_wavelink_track_start, 'on_wavelink_track_start')
                 self.add_listener(self.on_wavelink_track_exception, 'on_wavelink_track_exception')
                 self.add_listener(self.on_wavelink_track_stuck, 'on_wavelink_track_stuck')
                 logger.info("Global Wavelink event listeners attached.")
            else:
                logger.warning("No Wavelink nodes available in the pool after setup_hook. Player functionality will be impaired. Check Lavalink server and connection settings.")
            
            self.setup_called_once = True
            logger.info("One-time setup logic in on_ready marked as complete.")
        else:
            logger.info("One-time setup logic in on_ready already performed, skipping.")

        logger.info(f"Bot is ready. Cogs loaded: {list(self.cogs.keys())}")
        # To get app commands after sync, use self.tree.get_commands()
        # This might be an empty list if sync hasn't completed fully or if run too early.
        # Best to log this after sync_app_commands_debug has demonstrably finished.
        # For now, we'll log what's available in the tree at this point of on_ready.
        app_commands_list = [cmd.name for cmd in self.tree.get_commands()]
        logger.info(f"Application commands available in bot's tree: {app_commands_list}")


    # Wavelink Event Handlers (global logging)
    async def on_wavelink_node_ready(self, payload: wavelink.NodeReadyEventPayload) -> None:
        node = payload.node
        logger.info(f"Wavelink Node '{node.identifier}' is ready! Session ID: {payload.session_id}")

    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload) -> None:
        player = payload.player
        track = payload.track
        reason = payload.reason
        logger.info(f"Track '{track.title}' ended on player {player.guild.id}. Reason: {reason}")
        # Add logic here for auto-play, queue handling, etc.
        # if player:
        #    await player.handle_track_end(reason) # Example: delegate to player method

    async def on_wavelink_track_start(self, payload: wavelink.TrackStartEventPayload) -> None:
        player = payload.player
        track = payload.track
        logger.info(f"Track '{track.title}' started on player {player.guild.id}.")

    async def on_wavelink_track_exception(self, payload: wavelink.TrackExceptionEventPayload) -> None:
        player = payload.player
        track = payload.track
        error = payload.error
        logger.error(f"Track '{track.title}' on player {player.guild.id} encountered an exception: {error}", exc_info=error)

    async def on_wavelink_track_stuck(self, payload: wavelink.TrackStuckEventPayload) -> None:
        player = payload.player
        track = payload.track
        threshold = payload.threshold_ms
        logger.warning(f"Track '{track.title}' on player {player.guild.id} is stuck (threshold: {threshold}ms).")


    async def on_command_error(self, ctx, error): # For prefixed commands, if any
        logger.error(f"Error in prefixed command {ctx.command}: {error}", exc_info=True)
        if ctx.command: # Check if ctx.command is not None
            await ctx.send(f"An error occurred with command '{ctx.command.name}': {error}")
        else:
            await ctx.send(f"An error occurred: {error}")


async def main():
    logger.info("Starting DebugBotOnReady...")
    bot = DebugBotOnReady()
    try:
        await bot.start(TOKEN)
    except discord.LoginFailure:
        logger.critical("LoginFailure: Failed to log in. Check your DISCORD_TOKEN.", exc_info=True)
    except discord.HTTPException as e:
        logger.critical(f"HTTPException during bot startup: {e.status} - {e.text}", exc_info=True)
    except Exception as e:
        logger.critical(f"An unexpected error occurred during bot startup.", exc_info=True)
    finally:
        logger.info("DebugBotOnReady main() finished or encountered an error.")

if __name__ == "__main__":
    logger.info("DebugBotOnReady script execution started.")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("DebugBotOnReady shutdown requested via KeyboardInterrupt.")
    except Exception as e:
        logger.critical(f"Fatal error in asyncio.run(main()):", exc_info=True)
    finally:
        logger.info("DebugBotOnReady script execution finished.")
