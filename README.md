# Discord Music Bot

A Python-based Discord music bot with built-in Lavalink server support.

## Prerequisites

- Python 3.8 or higher
- Java 11 or higher
- Discord Bot Token

## Setup

1. Clone this repository
2. Install dependencies:
   - **Windows**: Install Python and Java manually
   - **Linux/Ubuntu**: Run the installation script:
     ```bash
     chmod +x install_dependencies.sh
     ./install_dependencies.sh
     ```
3. Configure the `.env` file with your settings:
   ```env
   # Required Settings
   DISCORD_TOKEN=your_discord_bot_token_here
   DISCORD_CLIENT_ID=your_discord_client_id_here

   # Optional Settings (with defaults)
   LAVALINK_HOST=127.0.0.1
   LAVALINK_PORT=2333
   LAVALINK_PASSWORD=youshallnotpass
   DEFAULT_VOLUME=100
   MAX_PLAYLIST_SIZE=100
   MAX_QUEUE_SIZE=1000
   DEFAULT_PREFIX=!
   LOG_LEVEL=INFO
   LOG_FILE=bot.log
   CACHE_DIR=./cache
   MAX_CACHE_SIZE=1000

   # Optional API Keys (for enhanced functionality)
   YOUTUBE_API_KEY=your_youtube_api_key_here
   SPOTIFY_CLIENT_ID=your_spotify_client_id_here
   SPOTIFY_CLIENT_SECRET=your_spotify_client_secret_here
   SOUNDCLOUD_CLIENT_ID=your_soundcloud_client_id_here
   ```

## Running the Bot

### Windows
Simply double-click `start_bot.bat` or run it from the command line:
```bash
start_bot.bat
```

### Linux/Ubuntu
1. Make the start script executable:
   ```bash
   chmod +x start_bot.sh
   ```
2. Run the bot:
   ```bash
   ./start_bot.sh
   ```

### Manual Start (Both Platforms)
1. Start the Lavalink server:
   ```bash
   python start_lavalink.py
   ```
2. In a new terminal, start the bot:
   ```bash
   python bot.py
   ```

## Features
- Play music from various sources (YouTube, SoundCloud, etc.)
- Queue management
- Volume control
- Playlist support
- And more!

## Notes
- The Lavalink server will be automatically downloaded on first run
- Make sure Java 11 or higher is installed and in your PATH
- The bot uses slash commands, so you'll need to wait for them to sync when the bot starts
- Optional API keys can be obtained from:
  - YouTube: https://console.cloud.google.com/
  - Spotify: https://developer.spotify.com/dashboard
  - SoundCloud: https://developers.soundcloud.com/

# Raiko Horikawa
A Discord music bot by MoonShinkiro  


![follow1852Arisu](https://user-images.githubusercontent.com/107448523/235394870-00964e3d-374c-44e6-9548-d1942fd9446f.png)
Commissioned artwork by 1852Arisu on Twitter, please follow them! https://twitter.com/1852Arisu

## Running
1. Acquire and copy your own bot token from https://discord.com/developers/applications/ and check the boxes ```bot``` and ```applications.commands``` from OAuth2 section. Make sure to add your bot to your server as well.
2. Open/edit the .env file and paste your bot token to ```TOKEN=```
3. In the folder where /raiko is located, run a terminal line with: ```node index.js load```
4. To load the commands into the bot, follow this step with: ```node index.js``` To activate the bot.

## Commands
- ```/help``` Lists all commands and contact information for support.
- ```/play song``` Queues a single song from a specific given link from Youtube/Spotify/Soundcloud.
- ```/play search``` Searches for a song from youtube and adds to queue.
- ```/play playlist``` Queues all songs from a playlist link from Youtube/Spotify/Soundcloud.
- ```/skip``` Skips the currently playing song.
- ```/skipto``` Skips to a certain song given from the queue's numbered list.
- ```/pause``` To halt the music.
- ```/resume``` To continue the music.
- ```/queue``` Lists out all songs queued from a playlist, can check multiple pages.
- ```/info``` Gives information on the currently playing song.
- ```/shuffle``` Mixes up the order of the current queue.
- ```/loop``` Set to [*on*] or [*off*] to allow the current song to continue looping over again.
- ```/quit``` Raiko quits the queue and leaves the VC.
