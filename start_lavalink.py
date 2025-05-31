print("DEBUG: TOP OF start_lavalink.py IN PROJECT ROOT IS RUNNING")
import os
import sys
import subprocess
import urllib.request
import urllib.error
import platform
import re
import shutil
import textwrap
from dotenv import load_dotenv

# Configuration
LAVALINK_VERSION = "4.0.8" # Updated to Lavalink v4.x

# Old YouTube plugin (youtube-plugin) variables removed as Lavalink v4 has built-in YouTube support.
# However, per new instructions, we are adding a Lavalink v4 compatible YouTube plugin.
V4_YOUTUBE_PLUGIN_NAME = "youtube-source" 
V4_YOUTUBE_PLUGIN_VERSION = "1.5.3" # Placeholder - use actual latest compatible version
V4_YOUTUBE_PLUGIN_JAR_NAME = f"{V4_YOUTUBE_PLUGIN_NAME}-{V4_YOUTUBE_PLUGIN_VERSION}.jar" 
V4_YOUTUBE_PLUGIN_URL = f"https://github.com/lavalink-devs/youtube-source/releases/download/{V4_YOUTUBE_PLUGIN_VERSION}/{V4_YOUTUBE_PLUGIN_JAR_NAME}"


SPOTIFY_PLUGIN_NAME = "lavasrc-plugin" # LavaSrc plugin for Spotify, Apple Music, etc.
SPOTIFY_PLUGIN_VERSION = "4.0.0" # Ensure this is compatible with Lavalink v4.0.8
SPOTIFY_PLUGIN_JAR_NAME = f"LavaSrc-{SPOTIFY_PLUGIN_VERSION}.jar"
SPOTIFY_PLUGIN_URL = f"https://github.com/topi314/LavaSrc/releases/download/{SPOTIFY_PLUGIN_VERSION}/LavaSrc-{SPOTIFY_PLUGIN_VERSION}.jar"

LAVALINK_DIR = "lavalink"
JAR_NAME = "Lavalink.jar"
CONFIG_NAME = "application.yml"
EXAMPLE_CONFIG_NAME = "application.yml.example" # Lavalink v4 still uses application.yml.example
PLUGINS_DIR = os.path.join(LAVALINK_DIR, "plugins")

JAR_PATH = os.path.join(LAVALINK_DIR, JAR_NAME)
CONFIG_PATH = os.path.join(LAVALINK_DIR, CONFIG_NAME)
V4_YOUTUBE_PLUGIN_JAR_PATH = os.path.join(PLUGINS_DIR, V4_YOUTUBE_PLUGIN_JAR_NAME) # Path for the new YouTube plugin
SPOTIFY_PLUGIN_JAR_PATH = os.path.join(PLUGINS_DIR, SPOTIFY_PLUGIN_JAR_NAME)

def get_lavalink_urls(version):
    base_url = f"https://github.com/lavalink-devs/Lavalink/releases/download/{version}/"
    jar_url = base_url + JAR_NAME
    config_url = f"https://raw.githubusercontent.com/lavalink-devs/Lavalink/{version}/LavalinkServer/{EXAMPLE_CONFIG_NAME}"
    return jar_url, config_url

def download_file(url, destination_path, description):
    try:
        os.makedirs(os.path.dirname(destination_path), exist_ok=True)
        headers = {'User-Agent': 'Lavalink-Setup-Script/1.0'}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as response, open(destination_path, 'wb') as out_file:
            if response.status == 200:
                shutil.copyfileobj(response, out_file)
                return True
            return False
    except Exception as e:
        if os.path.exists(destination_path): 
            os.remove(destination_path)
        return False

def check_plugin_config(config_file_path):
    if not os.path.exists(config_file_path):
        return True

    config_ok = True
    try:
        with open(config_file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Old YouTube plugin check removed.
        # For Lavalink v4, 'youtube: true' in sources is standard for built-in support.
        # If a user *were* to add a different YouTube plugin for v4, they'd need to manage source settings.

        spotify_plugin_present = os.path.exists(SPOTIFY_PLUGIN_JAR_PATH)
        if spotify_plugin_present:
            lavasrc_block_exists = re.search(r"^\s*lavasrc:", content, re.MULTILINE | re.IGNORECASE)
            if lavasrc_block_exists and ("${SPOTIFY_CLIENT_ID}" not in content or "${SPOTIFY_CLIENT_SECRET}" not in content):
                print("Note: It should be able to use spotify.")

        return config_ok
    except Exception:
        return False

def setup_lavalink():
    os.makedirs(LAVALINK_DIR, exist_ok=True)
    os.makedirs(PLUGINS_DIR, exist_ok=True)
    jar_url, config_url = get_lavalink_urls(LAVALINK_VERSION)
    config_example_path = os.path.join(LAVALINK_DIR, EXAMPLE_CONFIG_NAME)

    if not os.path.exists(JAR_PATH):
        if not download_file(jar_url, JAR_PATH, f"Lavalink v{LAVALINK_VERSION}"): 
            return False

    if not os.path.exists(CONFIG_PATH):
        if not download_file(config_url, config_example_path, "configuration"): 
            return False
        try:
            shutil.move(config_example_path, CONFIG_PATH)
        except OSError:
            return False

    # Old YouTube plugin download logic removed.

    if not os.path.exists(SPOTIFY_PLUGIN_JAR_PATH):
        download_file(SPOTIFY_PLUGIN_URL, SPOTIFY_PLUGIN_JAR_PATH, f"{SPOTIFY_PLUGIN_NAME} v{SPOTIFY_PLUGIN_VERSION}") # More descriptive name

    # Download new V4 YouTube Plugin
    if not os.path.exists(V4_YOUTUBE_PLUGIN_JAR_PATH):
        print(f"{V4_YOUTUBE_PLUGIN_NAME} v{V4_YOUTUBE_PLUGIN_VERSION} not found. Downloading...")
        download_file(V4_YOUTUBE_PLUGIN_URL, V4_YOUTUBE_PLUGIN_JAR_PATH, f"{V4_YOUTUBE_PLUGIN_NAME} v{V4_YOUTUBE_PLUGIN_VERSION}")

    return True

# Removed redundant start_lavalink definition

def start_lavalink():
    print("DEBUG: Entered start_lavalink function (adapted from launch_lavalink_process)") # ADD THIS LINE
    if not setup_lavalink():
        print("DEBUG: setup_lavalink failed (adapted from setup_lavalink_environment)") # ADD THIS LINE
        sys.exit("Setup failed. Please check your internet connection and try again.")

    if os.path.exists(CONFIG_PATH) and not check_plugin_config(CONFIG_PATH):
         sys.exit("Please fix the configuration issues and try again.")

    print(f"DEBUG: CONFIG_PATH is {CONFIG_PATH}") # ADD THIS LINE
    abs_config_path = os.path.abspath(CONFIG_PATH)
    print(f"DEBUG: abs_config_path is {abs_config_path}") # UPDATED THIS LINE

    dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
    load_dotenv(dotenv_path=dotenv_path, override=True)

    if os.path.exists(SPOTIFY_PLUGIN_JAR_PATH):
        if not os.getenv("SPOTIFY_CLIENT_ID") or not os.getenv("SPOTIFY_CLIENT_SECRET"):
            print("Warning: Missing Spotify credentials in .env file")

    # Platform-independent Java executable
    java_executable = "java"
    if platform.system() == "Windows":
        java_executable = "java.exe"

    print(f"DEBUG: java_executable is {java_executable}") # ADD THIS LINE

    java_command = [
        java_executable,
        f"-Dspring.config.location={abs_config_path}", # THIS IS THE CRITICAL FIX
        "-Dserver.port=2333",  # Explicitly set port
        "-Djava.net.preferIPv4Stack=true",
        # Removed -Dlogging.level.root=INFO as it should be controlled by application.yml
        # Add other system properties here if needed, e.g., memory limits like "-Xmx1G"
        "-jar",
        JAR_PATH
    ]

    print(f"DEBUG: Attempting to run Java command: {' '.join(java_command)}") # ENSURE THIS LINE IS PRESENT OR ADDED

    process = None
    try:
        process = subprocess.Popen(
            java_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1,
            encoding='utf-8',
            errors='replace'
        )
        
        if process.stdout:
            for line in iter(process.stdout.readline, ''):
                if line: print(line, end='', flush=True)
        process.wait()

    except KeyboardInterrupt:
        if process and process.poll() is None:
             process.terminate()
             process.wait(timeout=5)
    except FileNotFoundError:
         sys.exit("Failed to start: Java not found. Please install Java 17 or newer.")
    except Exception as e:
        sys.exit(f"Failed to start: {str(e)}")

if __name__ == "__main__":
    start_lavalink()

# --- END OF FILE start_lavalink.py ---