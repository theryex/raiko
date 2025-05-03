#!/bin/bash

# Check if Java is installed
if ! command -v java &> /dev/null; then
    echo "Java is not installed. Please install Java 17 or higher."
    exit 1
fi

# Check Java version
JAVA_VERSION=$(java -version 2>&1 | awk -F '"' '/version/ {print $2}' | awk -F. '{print $1}')
if [ "$JAVA_VERSION" -lt 17 ]; then
    echo "Java version $JAVA_VERSION is too old. Please install Java 17 or higher."
    exit 1
fi

# Start Lavalink server in the background
echo "Starting Lavalink server..."
python3 start_lavalink.py &
LAVALINK_PID=$!

# Wait for Lavalink to start
echo "Waiting for Lavalink server to initialize..."
sleep 10

# Check if Lavalink is running
if ! ps -p $LAVALINK_PID > /dev/null; then
    echo "Lavalink server failed to start. Please check the logs."
    exit 1
fi

# Start the bot
echo "Starting Discord bot..."
python3 bot.py

# Cleanup on exit
trap "kill $LAVALINK_PID 2>/dev/null" EXIT 