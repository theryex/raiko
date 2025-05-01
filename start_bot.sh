#!/bin/bash

# Check if Java is installed
if ! command -v java &> /dev/null; then
    echo "Java is not installed. Please install Java 11 or higher."
    exit 1
fi

# Start Lavalink server in the background
echo "Starting Lavalink server..."
python3 start_lavalink.py &
LAVALINK_PID=$!

# Wait for Lavalink to start
echo "Waiting for Lavalink server to initialize..."
sleep 5

# Start the bot
echo "Starting Discord bot..."
python3 bot.py

# Cleanup on exit
trap "kill $LAVALINK_PID" EXIT 