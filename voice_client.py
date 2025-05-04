# --- START OF FILE voice_client.py ---

import discord
# Make sure wavelink is installed: pip install wavelink
try:
    import wavelink
except ImportError:
    raise ImportError("wavelink is not installed. Please install it using: pip install wavelink")


class LavalinkVoiceClient(discord.VoiceClient):
    """
    A voice client for Wavelink.
    Connects discord.py voice logic to Wavelink node/player methods.
    """
    def __init__(self, client: discord.Client, channel: discord.abc.Connectable):
        super().__init__(client, channel) # Call super init first
        self.client = client
        self.channel = channel

    async def connect(self, *, timeout: float, reconnect: bool, self_deaf: bool = False, self_mute: bool = False) -> None:
        """ Connects to the voice channel and ensures a Wavelink player exists. """
        # Tell discord.py to change the voice state
        await self.channel.guild.change_voice_state(channel=self.channel, self_mute=self_mute, self_deaf=self_deaf)
        print(f"Requested connection to {self.channel.name} (Guild: {self.channel.guild.id})")

    async def disconnect(self, *, force: bool = False) -> None:
        """ Disconnects from the voice channel. """
        if not self.channel:
            print("Attempted disconnect but VoiceClient channel is None.")
            self.cleanup() # discord.py internal cleanup
            return

        print(f"Disconnecting from voice channel: {self.channel.name} (Guild ID: {self.channel.guild.id}) Force: {force}")

        # Tell discord.py to change the voice state to None (disconnect)
        if self.channel.guild.voice_client: # Check if discord.py thinks we are connected
            print(f"Requesting voice state change to disconnect from Guild {self.channel.guild.id}")
            await self.channel.guild.change_voice_state(channel=None)

        # Perform discord.py internal cleanup LAST
        self.cleanup()
        print(f"Finished disconnect process for Guild {self.channel.guild.id}")


# --- END OF FILE voice_client.py ---