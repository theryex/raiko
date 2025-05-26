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
        logger.info("Attempting to load 'cogs.system' extension (called from on_ready)...")
        try:
            await self.load_extension("cogs.system")
            logger.info("Successfully loaded extension: cogs.system")
        except commands.ExtensionAlreadyLoaded:
            logger.warning("ExtensionAlreadyLoaded: cogs.system is already loaded. Attempting to reload...")
            try:
                await self.reload_extension("cogs.system")
                logger.info("Successfully reloaded extension: cogs.system")
            except Exception as e_reload:
                logger.error(f"Failed to reload cogs.system.", exc_info=True)
        except commands.ExtensionNotFound:
            logger.error("ExtensionNotFound: cogs.system could not be found.", exc_info=True)
        except commands.NoEntryPointError:
            logger.error("NoEntryPointError: cogs.system does not have a 'setup' function.", exc_info=True)
        except commands.ExtensionFailed as e:
            logger.error(f"ExtensionFailed: cogs.system failed to load. Error: {e.original}", exc_info=True)
        except Exception as e:
            logger.error(f"An unexpected error occurred while loading cogs.system.", exc_info=True)

        logger.info("Attempting to load 'cogs.music' extension (called from on_ready)...") # Updated here
        try:
            await self.load_extension("cogs.music") # Updated here
            logger.info("Successfully loaded extension: cogs.music") # Updated here
        except commands.ExtensionAlreadyLoaded:
            logger.warning("ExtensionAlreadyLoaded: cogs.music is already loaded. Attempting to reload...") # Updated here
            try:
                await self.reload_extension("cogs.music") # Updated here
                logger.info("Successfully reloaded extension: cogs.music") # Updated here
            except Exception as e_reload:
                logger.error(f"Failed to reload cogs.music.", exc_info=True) # Updated here
        except commands.ExtensionNotFound:
            logger.error("ExtensionNotFound: cogs.music could not be found.", exc_info=True) # Updated here
        except commands.NoEntryPointError:
            logger.error("NoEntryPointError: cogs.music does not have a 'setup' function.", exc_info=True) # Updated here
        except commands.ExtensionFailed as e:
            logger.error(f"ExtensionFailed: cogs.music failed to load. Error: {e.original}", exc_info=True) # Updated here
        except Exception as e:
            logger.error(f"An unexpected error occurred while loading cogs.music.", exc_info=True) # Updated here
        
        logger.info(f"Current cogs after load_extensions_debug: {self.cogs}")
        logger.info(f"Current commands after load_extensions_debug: {[cmd.name for cmd in self.commands]}") # This will show prefixed commands

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
        # setup_hook is called before login.
        logger.info("DebugBotOnReady setup_hook called.")

        # Lavalink Node Setup
        lavalink_host = os.getenv('LAVALINK_HOST', '127.0.0.1')
        lavalink_port = int(os.getenv('LAVALINK_PORT', 2333))
        lavalink_password = os.getenv('LAVALINK_PASSWORD', 'SUPERSECUREPASSWORD_A1B2C3') # Default to the one we set
        lavalink_uri = f"http://{lavalink_host}:{lavalink_port}"

        logger.info(f"Attempting to connect to Lavalink node at {lavalink_uri}")
        node = wavelink.Node(
            uri=lavalink_uri,
            password=lavalink_password,
            client=self 
        )
        try:
            await wavelink.Pool.connect(nodes=[node], client=self, cache_capacity=100)
            logger.info("Successfully connected to Lavalink node.")
        except Exception as e:
            logger.error(f"Failed to connect to Lavalink node: {e}", exc_info=True)
            # Depending on the desired behavior, you might want to exit or handle this differently.
            # For now, it will log the error and the bot will continue to run without Lavalink.

        # The rest of the setup logic (extension loading, command syncing)
        # will be triggered by on_ready for this debug version.
        # However, for production, it's better to load extensions here too.
        # For now, keeping the debug flow where on_ready triggers them.
        logger.info("DebugBotOnReady setup_hook finished initial Lavalink setup.")


    async def on_ready(self):
        logger.info(f"DebugBotOnReady logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Bot is in {len(self.guilds)} guilds.")
        
        if not self.setup_called_once:
            logger.info("Running setup logic in on_ready for the first time...")
            
            logger.info("Loading extensions (debug mode from on_ready)...")
            await self.load_extensions_debug()
            logger.info("Extension loading process (from on_ready) completed.")
            
            logger.info("Syncing application commands (debug mode from on_ready)...")
            await self.sync_app_commands_debug()
            logger.info("Application command syncing (from on_ready) completed.")

            # Wavelink event listener (example)
            if wavelink.Pool.nodes:
                 logger.info("Wavelink nodes are available. Attaching on_node_ready listener.")
                 # Access the first node for simplicity, or iterate if multiple
                 # node = wavelink.Pool.get_node() # Gets the default node
                 # if node:
                 #    node.set_hook(self.on_wavelink_node_ready) # Not a direct method, need to use event
                 # For Wavelink 3.x, events are handled via bot.add_listener
                 self.add_listener(self.on_wavelink_node_ready, 'on_wavelink_node_ready')
                 self.add_listener(self.on_wavelink_track_end, 'on_wavelink_track_end')
                 self.add_listener(self.on_wavelink_track_start, 'on_wavelink_track_start')
                 self.add_listener(self.on_wavelink_track_exception, 'on_wavelink_track_exception')
                 self.add_listener(self.on_wavelink_track_stuck, 'on_wavelink_track_stuck')
                 logger.info("Added Wavelink event listeners.")
            else:
                logger.warning("No Wavelink nodes available after setup_hook. Player functionality will be impaired.")
            
            self.setup_called_once = True
            logger.info("Setup logic in on_ready marked as complete.")
        else:
            logger.info("Setup logic in on_ready already performed, skipping.")

    # Wavelink Event Handlers (examples, can be moved to a cog)
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
