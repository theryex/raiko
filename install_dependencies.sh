#!/bin/bash

# Update package list
echo "Updating package list..."
sudo apt update

# Install Python and pip if not already installed
if ! command -v python3 &> /dev/null; then
    echo "Installing Python3..."
    sudo apt install -y python3 python3-pip
fi

# Install Java 17 (LTS version)
echo "Installing Java 17..."
sudo apt install -y openjdk-17-jre

# Verify Java version
java_version=$(java -version 2>&1 | awk -F '"' '/version/ {print $2}' | awk -F. '{print $1}')
if [ "$java_version" -lt 11 ]; then
    echo "Error: Java version $java_version is too old. Please install Java 11 or higher."
    exit 1
fi

# Install Python dependencies
echo "Installing Python dependencies..."
pip3 install -r requirements.txt

# Make scripts executable
echo "Making scripts executable..."
chmod +x start_bot.sh

echo "Installation complete! You can now run the bot using ./start_bot.sh" 