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
LAVALINK_VERSION = "3.7.11"
PLUGIN_VERSION = "1.13.0"
PLUGIN_NAME = "youtube-plugin"
PLUGIN_JAR_NAME = f"{PLUGIN_NAME}-{PLUGIN_VERSION}.jar"
PLUGIN_URL = f"https://github.com/lavalink-devs/youtube-source/releases/download/{PLUGIN_VERSION}/{PLUGIN_JAR_NAME}"

SPOTIFY_PLUGIN_NAME = "lavasrc-plugin"
SPOTIFY_PLUGIN_VERSION = "4.0.0"
SPOTIFY_PLUGIN_JAR_NAME = f"LavaSrc-{SPOTIFY_PLUGIN_VERSION}.jar"
SPOTIFY_PLUGIN_URL = f"https://github.com/topi314/LavaSrc/releases/download/{SPOTIFY_PLUGIN_VERSION}/LavaSrc-{SPOTIFY_PLUGIN_VERSION}.jar"

LAVALINK_DIR = "lavalink"
JAR_NAME = "Lavalink.jar"
CONFIG_NAME = "application.yml"
EXAMPLE_CONFIG_NAME = "application.yml.example"
PLUGINS_DIR = os.path.join(LAVALINK_DIR, "plugins")

JAR_PATH = os.path.join(LAVALINK_DIR, JAR_NAME)
CONFIG_PATH = os.path.join(LAVALINK_DIR, CONFIG_NAME)
PLUGIN_JAR_PATH = os.path.join(PLUGINS_DIR, PLUGIN_JAR_NAME)
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

        youtube_plugin_present = os.path.exists(PLUGIN_JAR_PATH)
        if youtube_plugin_present:
            built_in_yt_nested_enabled = re.search(r"lavalink:\s*\n.*?\s+server:\s*\n.*?\s+sources:\s*\n.*?\s+youtube:\s*true", content, re.DOTALL | re.IGNORECASE)
            if built_in_yt_nested_enabled:
                print("Error: Built-in YouTube source must be disabled when using the YouTube plugin.")
                config_ok = False

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

    if not os.path.exists(PLUGIN_JAR_PATH):
        download_file(PLUGIN_URL, PLUGIN_JAR_PATH, "YouTube Plugin")

    if not os.path.exists(SPOTIFY_PLUGIN_JAR_PATH):
        download_file(SPOTIFY_PLUGIN_URL, SPOTIFY_PLUGIN_JAR_PATH, "Spotify Plugin")

    return True

def start_lavalink():
    if not setup_lavalink():
        sys.exit("Setup failed. Please check your internet connection and try again.")

    if os.path.exists(CONFIG_PATH) and not check_plugin_config(CONFIG_PATH):
         sys.exit("Please fix the configuration issues and try again.")

    dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
    load_dotenv(dotenv_path=dotenv_path, override=True)

    if os.path.exists(SPOTIFY_PLUGIN_JAR_PATH):
        if not os.getenv("SPOTIFY_CLIENT_ID") or not os.getenv("SPOTIFY_CLIENT_SECRET"):
            print("Warning: Missing Spotify credentials in .env file")

    # Platform-independent Java executable
    java_executable = "java"
    if platform.system() == "Windows":
        java_executable = "java.exe"

    java_command = [
        java_executable,
        "-Djava.net.preferIPv4Stack=true",
        "-Dlogging.level.root=INFO",
        "-jar",
        JAR_PATH
    ]

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