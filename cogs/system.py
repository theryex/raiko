import discord
from discord import app_commands
from discord.ext import commands
import subprocess
import platform
import logging

logger = logging.getLogger(__name__)

def get_nvidia_smi_info():
    """Attempts to run the 'nvidia-smi' command and return its output."""
    try:
        # Attempt to run nvidia-smi
        result = subprocess.run(['nvidia-smi'], capture_output=True, text=True, check=True, encoding='utf-8')
        return result.stdout
    except FileNotFoundError:
        logger.warning("nvidia-smi command not found. It might not be installed or not in PATH.")
        return "NVIDIA GPU information is not available (nvidia-smi command not found)."
    except subprocess.CalledProcessError as e:
        logger.error(f"nvidia-smi command failed with error code {e.returncode}: {e.stderr}")
        return f"Failed to retrieve GPU information. nvidia-smi exited with error: {e.stderr}"
    except Exception as e:
        logger.exception("An unexpected error occurred while trying to execute nvidia-smi.")
        return f"An unexpected error occurred while fetching GPU info: {str(e)}"

def get_active_users_info(): # Renamed from get_ssh_clients
    """Gets active user information using the 'who' command."""
    try:
        # The 'who' command is standard on POSIX-compliant systems (Linux, macOS, etc.)
        result = subprocess.run(['who'], capture_output=True, text=True, check=True, encoding='utf-8')
        output = result.stdout.strip()
        return output if output else "No users currently logged in (according to 'who' command)."
    except FileNotFoundError:
        logger.warning("'who' command not found.")
        return "'who' command not found. This command may not be available on your system."
    except subprocess.CalledProcessError as e:
        logger.error(f"'who' command failed: {e.stderr}")
        return f"Failed to retrieve active user information. Error: {e.stderr}"
    except Exception as e:
        logger.exception("An unexpected error occurred while fetching active user info.")
        return f"An unexpected error occurred: {str(e)}"

def split_message(message: str, max_length: int = 2000) -> list[str]:
    """Splits a long message into chunks for Discord, accounting for code block syntax."""
    # Reserve 6 characters for "```" at the beginning and end of the chunk.
    # Max content length per chunk is max_length - 6.
    # If using language identifier like ```py, reserve more.
    chunk_content_max_len = max_length - 6 
    
    if chunk_content_max_len <= 0:
        # This case should not happen with default max_length=2000
        raise ValueError("max_length is too small to include code block ticks.")

    lines = message.splitlines(keepends=True)
    chunks = []
    current_chunk = ""

    for line in lines:
        if len(current_chunk) + len(line) > chunk_content_max_len:
            if current_chunk: # Avoid adding empty chunks
                chunks.append(current_chunk)
            current_chunk = line
            # Handle cases where a single line itself is too long
            while len(current_chunk) > chunk_content_max_len:
                chunks.append(current_chunk[:chunk_content_max_len])
                current_chunk = current_chunk[chunk_content_max_len:]
        else:
            current_chunk += line
    
    if current_chunk: # Add the last remaining chunk
        chunks.append(current_chunk)
        
    return chunks

class System(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="nvidia_smi", description="Shows NVIDIA GPU utilization (from 'nvidia-smi' command).")
    async def nvidia_smi_command(self, interaction: discord.Interaction): # Method name updated for clarity
        await interaction.response.defer()
        logger.info(f"/nvidia_smi command invoked by {interaction.user}")
        gpu_info = get_nvidia_smi_info()
        
        if not gpu_info.strip(): # Handle cases where gpu_info might be empty or just whitespace
            await interaction.followup.send("No information returned from nvidia-smi command.")
            return

        message_chunks = split_message(gpu_info)
        for i, chunk in enumerate(message_chunks):
            if i == 0: # First chunk as followup
                await interaction.followup.send(f"```{chunk}```")
            else: # Subsequent chunks as new messages
                await interaction.channel.send(f"```{chunk}```")

    @app_commands.command(name="who", description="Shows currently active users (from 'who' command).")
    async def who_command(self, interaction: discord.Interaction): # Method name updated for clarity
        await interaction.response.defer()
        logger.info(f"/who command invoked by {interaction.user}")
        active_users_info = get_active_users_info()

        if not active_users_info.strip():
            await interaction.followup.send("No information returned from 'who' command or no users active.")
            return

        message_chunks = split_message(active_users_info)
        for i, chunk in enumerate(message_chunks):
            if i == 0:
                await interaction.followup.send(f"```{chunk}```")
            else:
                await interaction.channel.send(f"```{chunk}```")

async def setup(bot: commands.Bot):
    await bot.add_cog(System(bot))
    logger.info("System Cog loaded successfully.") # Added "successfully" for confirmation