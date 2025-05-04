import discord
from discord import app_commands
from discord.ext import commands
import subprocess
import platform
import logging

logger = logging.getLogger(__name__)

def get_gpu_info():
    if platform.system() == "Windows":
        try:
            result = subprocess.run(['nvidia-smi'], capture_output=True, text=True, check=True)
            return result.stdout
        except FileNotFoundError:
            return "NVIDIA GPU information is not available (nvidia-smi not found)"
        except subprocess.CalledProcessError:
            return "Failed to retrieve GPU information"
    else:
        return "GPU information is only available on Windows systems"

def get_ssh_clients():
    if platform.system() != "Linux":
        return "SSH client information is only available on Linux systems"
        
    try:
        who_result = subprocess.run(['who'], capture_output=True, text=True, check=True)
        who_clients = [line for line in who_result.stdout.splitlines() if 'pts/' in line]
        
        w_result = subprocess.run(['w'], capture_output=True, text=True, check=True)
        w_clients = [line for line in w_result.stdout.splitlines() if 'ssh' in line]
        
        all_clients = list(set(who_clients + w_clients))
        return "\n".join(all_clients) if all_clients else "No users connected via SSH."
    except subprocess.CalledProcessError:
        return "Failed to retrieve SSH client information"

def split_message(message, max_length=2000):
    """Splits a long message into chunks that are within Discord's message length limit."""
    max_length -= 8  # Account for code block syntax
    return [message[i:i+max_length] for i in range(0, len(message), max_length)]

class System(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="gpuinfo", description="Shows NVIDIA GPU information (Windows only)")
    async def gpuinfo(self, interaction: discord.Interaction):
        await interaction.response.defer()
        gpu_info = get_gpu_info()
        for chunk in split_message(gpu_info):
            await interaction.followup.send(f"```{chunk}```")

    @app_commands.command(name="users", description="Shows connected SSH users (Linux only)")
    async def users(self, interaction: discord.Interaction):
        await interaction.response.defer()
        ssh_clients_info = get_ssh_clients()
        for chunk in split_message(ssh_clients_info):
            await interaction.followup.send(f"```{chunk}```")

async def setup(bot: commands.Bot):
    await bot.add_cog(System(bot))
    logger.info("System Cog loaded.")