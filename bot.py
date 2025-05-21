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
    level=logging.DEBUG,  # More verbose logging for debugging
    format='%(asctime)s [%(levelname)s] [%(name)s] - %(message)s',
    handlers=[
        logging.FileHandler('bot_debug.log', encoding='utf-8', mode='w'), # Use a separate debug log
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv('DISCORD_TOKEN')
if not TOKEN:
    logger.critical("CRITICAL: DISCORD_TOKEN is required in .env file. Exiting.")
    exit("Error: DISCORD_TOKEN is required in .env file")

DEFAULT_PREFIX = os.getenv('DEFAULT_PREFIX', '!')

class MinimalBot(commands.Bot):
    def __init__(self):
        logger.info("Initializing MinimalBot...")
        intents = discord.Intents.default()
        # Remove voice_states if not strictly needed by cogs.system
        # intents.voice_states = True 
        intents.message_content = True # If cogs.system uses it
        intents.guilds = True
        intents.guild_messages = True

        super().__init__(command_prefix=DEFAULT_PREFIX, intents=intents)
        logger.info("MinimalBot super().__init__() called.")

    async def load_extensions_debug(self):
        logger.info("Attempting to load 'cogs.system' extension...")
        try:
            await self.load_extension("cogs.system")
            logger.info("Successfully loaded extension: cogs.system")
        except commands.ExtensionNotFound:
            logger.error("ExtensionNotFound: cogs.system could not be found.", exc_info=True)
        except commands.ExtensionAlreadyLoaded:
            logger.warning("ExtensionAlreadyLoaded: cogs.system is already loaded.", exc_info=True)
        except commands.NoEntryPointError:
            logger.error("NoEntryPointError: cogs.system does not have a 'setup' function.", exc_info=True)
        except commands.ExtensionFailed as e:
            logger.error(f"ExtensionFailed: cogs.system failed to load. Error: {e.original}", exc_info=True)
        except Exception as e:
            logger.error(f"An unexpected error occurred while loading cogs.system.", exc_info=True)
        
        logger.info(f"Current cogs: {self.cogs}")
        logger.info(f"Current commands: {[cmd.name for cmd in self.commands]}")


    async def setup_hook(self):
        logger.info("MinimalBot setup_hook started.")
        
        logger.info("Loading extensions (debug mode)...")
        await self.load_extensions_debug()
        logger.info("Extension loading process completed.")

        if not self.cogs:
            logger.warning("No cogs were loaded. Application command syncing will likely fail or be empty.")
        
        logger.info("Attempting to sync application commands...")
        try:
            # Sync globally if no guild IDs are specified
            # synced_commands = await self.tree.sync()
            # logger.info(f"Application commands synced globally. Synced: {len(synced_commands)} commands.")
            
            # Example: Sync to a specific guild for faster testing (replace with your guild ID)
            # test_guild_id = os.getenv('TEST_GUILD_ID')
            # if test_guild_id:
            #     guild_obj = discord.Object(id=int(test_guild_id))
            #     logger.info(f"Attempting to sync commands to guild: {test_guild_id}")
            #     synced_commands = await self.tree.sync(guild=guild_obj)
            #     logger.info(f"Application commands synced to guild {test_guild_id}. Synced: {len(synced_commands)} commands: {[c.name for c in synced_commands]}")
            # else:
            #     logger.info("No TEST_GUILD_ID found in .env, syncing globally.")
            synced_commands = await self.tree.sync()
            logger.info(f"Application commands synced globally. Synced: {len(synced_commands)} commands. Details: {[c.name for c in synced_commands]}")

        except discord.errors.Forbidden:
            logger.error("Forbidden: Failed to sync application commands. Check bot permissions (application.commands scope).", exc_info=True)
        except discord.errors.HTTPException as e:
            logger.error(f"HTTPException: Failed to sync application commands. {e.status} - {e.text}", exc_info=True)
        except Exception as e:
            logger.error(f"An unexpected error occurred during command syncing.", exc_info=True)
        
        logger.info("MinimalBot setup_hook finished.")

    async def on_ready(self):
        logger.info(f"MinimalBot logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Bot is in {len(self.guilds)} guilds.")
        # No presence change for simplicity

    async def on_command_error(self, ctx, error):
        logger.error(f"Error in command {ctx.command}: {error}", exc_info=True)
        await ctx.send(f"An error occurred: {error}")

async def main():
    logger.info("Starting MinimalBot...")
    bot = MinimalBot()
    try:
        await bot.start(TOKEN)
    except discord.LoginFailure:
        logger.critical("LoginFailure: Failed to log in. Check your DISCORD_TOKEN.", exc_info=True)
    except discord.HTTPException as e:
        logger.critical(f"HTTPException during bot startup: {e.status} - {e.text}", exc_info=True)
    except Exception as e:
        logger.critical(f"An unexpected error occurred during bot startup.", exc_info=True)
    finally:
        logger.info("MinimalBot main() finished or encountered an error.")

if __name__ == "__main__":
    logger.info("MinimalBot script execution started.")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("MinimalBot shutdown requested via KeyboardInterrupt.")
    except Exception as e:
        logger.critical(f"Fatal error in asyncio.run(main()):", exc_info=True)
    finally:
        logger.info("MinimalBot script execution finished.")
