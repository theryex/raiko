#!/bin/bash

# Update package list
echo "Updating package list..."
sudo apt update

# Install Python and pip if not already installed
if ! command -v python3 &> /dev/null; then
    echo "Installing Python3..."
    sudo apt install -y python3 python3-pip
fi

# Install Java if not already installed
if ! command -v java &> /dev/null; then
    echo "Installing Java..."
    sudo apt install -y openjdk-17-jre
fi

# Install Python dependencies
echo "Installing Python dependencies..."
pip3 install -r requirements.txt

# Make scripts executable
echo "Making scripts executable..."
chmod +x start_bot.sh

echo "Installation complete! You can now run the bot using ./start_bot.sh" 