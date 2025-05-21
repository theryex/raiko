import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
import asyncio
import logging
from pathlib import Path

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
        # We are moving the core logic to on_ready for this debug version.
        logger.info("DebugBotOnReady setup_hook called (minimal, logic moved to on_ready).")
        # If cogs.system had some setup_hook dependent logic that wasn't command registration,
        # it might be an issue, but typically commands are the focus.

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
            
            self.setup_called_once = True
            logger.info("Setup logic in on_ready marked as complete.")
        else:
            logger.info("Setup logic in on_ready already performed, skipping.")

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
