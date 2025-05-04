# --- START OF FILE voice_client.py ---

import discord
# Make sure lavaplay is installed: pip install lavaplay.py
try:
    import lavaplay
except ImportError:
    raise ImportError("lavaplay.py is not installed. Please install it using: pip install lavaplay.py")


class LavalinkVoiceClient(discord.VoiceClient):
    """
    A voice client for Lavalink using lavaplay.py.
    Connects discord.py voice logic to lavaplay node/player methods.
    Based on the official lavaplay.py example.
    https://discordpy.readthedocs.io/en/latest/api.html#voiceprotocol
    """
    def __init__(self, client: discord.Client, channel: discord.abc.Connectable):
        super().__init__(client, channel) # Call super init first
        self.client = client
        self.channel = channel
        # Ensure the Lavalink node instance exists on the bot client
        if not hasattr(self.client, 'lavalink_node'):
            # This should ideally not happen if setup_hook runs correctly
            raise AttributeError("Lavalink node ('lavalink_node') not found on bot client when creating VoiceClient!")
        self.lavalink: lavaplay.Node = self.client.lavalink_node # Use the node instance from the bot

    async def on_voice_server_update(self, data):
        """Handles the VOICE_SERVER_UPDATE event from Discord."""
        if not self.lavalink: return
        player = self.lavalink.get_player(self.channel.guild.id)
        # Player might not exist if connection is just starting,
        # but lavaplay handles this internally.
        await player.raw_voice_server_update(data.get('endpoint'), data.get('token'))


    async def on_voice_state_update(self, data):
        """Handles the VOICE_STATE_UPDATE event from Discord."""
        if not self.lavalink: return

        # Extract data safely
        guild_id = data.get('guild_id')
        user_id_str = data.get('user_id')
        channel_id_str = data.get('channel_id') # Note: Can be None if user disconnected
        session_id = data.get('session_id')

        # Basic validation
        if not guild_id or not user_id_str or not session_id:
            # Log if needed, but often these are partial updates we don't need
            # print(f"Partial VOICE_STATE_UPDATE ignored: {data}")
            return

        try:
            user_id = int(user_id_str)
            # channel_id can be None, handle that case
            channel_id = int(channel_id_str) if channel_id_str else None
        except (ValueError, TypeError):
            print(f"Error parsing IDs in VOICE_STATE_UPDATE: {data}")
            return

        # Get the player *after* validation
        player = self.lavalink.get_player(int(guild_id))

        # If the update is for our bot and the channel_id is None, it means the bot was disconnected
        if user_id == self.client.user.id and channel_id is None:
            print(f"Bot disconnected via VOICE_STATE_UPDATE for Guild ID: {guild_id}")
            # Lavaplay's disconnect logic might handle player destruction,
            # but we can ensure it here if needed. Consider adding player.destroy() if issues arise.
            # await player.destroy() # Potentially redundant, test without first
            pass # Usually handled by disconnect method call or event

        # Forward the raw update to lavaplay player
        # lavaplay needs user_id (int), session_id (str), and channel_id (int or None)
        await player.raw_voice_state_update(user_id, session_id, channel_id)


    async def connect(self, *, timeout: float, reconnect: bool, self_deaf: bool = False, self_mute: bool = False) -> None:
        """ Connects to the voice channel and ensures a Lavalink player exists. """
        if not self.lavalink:
             raise RuntimeError("Lavalink node is not available for connection.")

        # Ensure player exists for this guild *before* changing state
        # Use get_player first, then create if needed
        player = self.lavalink.get_player(self.channel.guild.id)
        if not player:
             self.lavalink.create_player(self.channel.guild.id)
             print(f"Created lavaplay player for Guild {self.channel.guild.id}")

        # Tell discord.py to change the voice state
        await self.channel.guild.change_voice_state(channel=self.channel, self_mute=self_mute, self_deaf=self_deaf)
        print(f"Requested connection to {self.channel.name} (Guild: {self.channel.guild.id})")
        # Note: Actual confirmation often comes via voice state/server updates


    async def disconnect(self, *, force: bool = False) -> None:
        """ Disconnects from the voice channel and destroys the Lavalink player. """
        if not self.channel:
            print("Attempted disconnect but VoiceClient channel is None.")
            self.cleanup() # discord.py internal cleanup
            return

        guild_id = self.channel.guild.id
        player = self.lavalink.get_player(guild_id)

        print(f"Disconnecting from voice channel: {self.channel.name} (Guild ID: {guild_id}) Force: {force}")

        # Always destroy the lavaplay player for this guild upon disconnect
        if player:
            try:
                await player.destroy()
                print(f"Destroyed lavaplay player for Guild {guild_id}")
            except Exception as e:
                print(f"Error destroying lavaplay player for Guild {guild_id}: {e}")

        # Tell discord.py to change the voice state to None (disconnect)
        if self.channel.guild.voice_client: # Check if discord.py thinks we are connected
            print(f"Requesting voice state change to disconnect from Guild {guild_id}")
            await self.channel.guild.change_voice_state(channel=None)

        # Perform discord.py internal cleanup LAST
        self.cleanup()
        print(f"Finished disconnect process for Guild {guild_id}")


# --- END OF FILE voice_client.py ---