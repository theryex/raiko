# --- START OF FILE start_lavalink.py ---

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

# --- Configuration ---
LAVALINK_VERSION = "3.7.11"
# YouTube Plugin
PLUGIN_VERSION = "1.13.0"
PLUGIN_NAME = "youtube-plugin"
PLUGIN_JAR_NAME = f"{PLUGIN_NAME}-{PLUGIN_VERSION}.jar"
PLUGIN_URL = f"https://github.com/lavalink-devs/youtube-source/releases/download/{PLUGIN_VERSION}/{PLUGIN_JAR_NAME}"
# Spotify Plugin (Lavasrc)
SPOTIFY_PLUGIN_NAME = "lavasrc-plugin"
SPOTIFY_PLUGIN_VERSION = "4.0.0"
SPOTIFY_PLUGIN_JAR_NAME = f"LavaSrc-{SPOTIFY_PLUGIN_VERSION}.jar"
SPOTIFY_PLUGIN_URL = f"https://github.com/topi314/LavaSrc/releases/download/{SPOTIFY_PLUGIN_VERSION}/LavaSrc-{SPOTIFY_PLUGIN_VERSION}.jar"
# --- End Configuration ---

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
    """Gets the download URLs for the JAR and example config."""
    base_url = f"https://github.com/lavalink-devs/Lavalink/releases/download/{version}/"
    jar_url = base_url + JAR_NAME
    config_url = f"https://raw.githubusercontent.com/lavalink-devs/Lavalink/{version}/LavalinkServer/{EXAMPLE_CONFIG_NAME}"
    return jar_url, config_url

def download_file(url, destination_path, description):
    """Downloads a file from a URL to a destination path."""
    print(f"Downloading {description} from {url}...")
    try:
        os.makedirs(os.path.dirname(destination_path), exist_ok=True)
        headers = {'User-Agent': 'Lavalink-Setup-Script/1.0'}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as response, open(destination_path, 'wb') as out_file:
            if response.status == 200:
                shutil.copyfileobj(response, out_file)
                print(f"{description} download complete!")
                return True
            else:
                 print(f"Error downloading {description}: HTTP Status {response.status} {response.reason}")
                 return False
    except urllib.error.HTTPError as e:
        print(f"Error downloading {description}: HTTP Error {e.code}: {e.reason} ({url})")
        if os.path.exists(destination_path): os.remove(destination_path)
        return False
    except urllib.error.URLError as e:
        print(f"Error downloading {description}: {e.reason} ({url})")
        if os.path.exists(destination_path): os.remove(destination_path)
        return False
    except Exception as e:
        print(f"An unexpected error occurred during download: {e}")
        if os.path.exists(destination_path): os.remove(destination_path)
        return False

def check_plugin_config(config_file_path):
    """Checks application.yml for common critical plugin configuration issues."""
    if not os.path.exists(config_file_path):
        return True # Cannot check, assume ok

    print(f"Checking '{config_file_path}' for critical plugin configuration issues...")
    config_ok = True
    warnings = []
    try:
        with open(config_file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        youtube_plugin_present = os.path.exists(PLUGIN_JAR_PATH)
        if youtube_plugin_present:
            # Critical Check: built-in YT source MUST be disabled if plugin exists
            built_in_yt_nested_enabled = re.search(r"lavalink:\s*\n.*?\s+server:\s*\n.*?\s+sources:\s*\n.*?\s+youtube:\s*true", content, re.DOTALL | re.IGNORECASE)
            if built_in_yt_nested_enabled:
                config_ok = False
                warnings.append(textwrap.dedent("""
                    Built-in YouTube source MUST be disabled ('false') when using the YouTube plugin.
                    Found 'lavalink.server.sources.youtube: true'. Please change it to 'false'.
                """))

        spotify_plugin_present = os.path.exists(SPOTIFY_PLUGIN_JAR_PATH)
        if spotify_plugin_present:
             # Optional Check: Recommend using env vars for Spotify keys
            lavasrc_block_exists = re.search(r"^\s*lavasrc:", content, re.MULTILINE | re.IGNORECASE)
            if lavasrc_block_exists and ("${SPOTIFY_CLIENT_ID}" not in content or "${SPOTIFY_CLIENT_SECRET}" not in content):
                 warnings.append(textwrap.dedent("""
                    [Optional but Recommended] LavaSrc Spotify configuration should use environment variables.
                    Consider changing hardcoded clientId/clientSecret to:
                      clientId: ${SPOTIFY_CLIENT_ID}
                      clientSecret: ${SPOTIFY_CLIENT_SECRET}
                    (Ensure these variables are set in your .env file)
                 """))

        if not config_ok:
            print("\n" + "="*60)
            print("ERROR: Critical configuration issues found!")
            print(f"Please fix '{config_file_path}' based on the following:")
            for warning in warnings:
                print("-" * 20); print(warning)
            print("="*60 + "\n")
            return False
        elif warnings:
            print("\n" + "="*60); print("INFO: Configuration suggestions:")
            for warning in warnings: print("-" * 20); print(warning)
            print("="*60 + "\n")
            return True
        else:
            print("Basic plugin configuration checks passed.")
            return True
    except Exception as e:
        print(f"Error reading or checking config file '{config_file_path}': {e}")
        return False

def setup_lavalink():
    """Downloads Lavalink JAR, config, and required plugins if they don't exist."""
    os.makedirs(LAVALINK_DIR, exist_ok=True)
    os.makedirs(PLUGINS_DIR, exist_ok=True)
    jar_url, config_url = get_lavalink_urls(LAVALINK_VERSION)
    config_example_path = os.path.join(LAVALINK_DIR, EXAMPLE_CONFIG_NAME)
    files_downloaded = False

    if not os.path.exists(JAR_PATH):
        if not download_file(jar_url, JAR_PATH, f"Lavalink v{LAVALINK_VERSION} JAR"): return False
        files_downloaded = True
    else: print(f"Lavalink JAR ({JAR_NAME}) already exists.")

    if not os.path.exists(CONFIG_PATH):
        print(f"{CONFIG_NAME} not found.")
        if not download_file(config_url, config_example_path, "Lavalink example configuration"): return False
        try:
            shutil.move(config_example_path, CONFIG_PATH)
            print(f"Created {CONFIG_NAME} from example.")
            files_downloaded = True
        except OSError as e: print(f"Error moving example config: {e}"); return False
    else: print(f"Lavalink configuration ({CONFIG_NAME}) already exists.")

    if not os.path.exists(PLUGIN_JAR_PATH):
        print(f"YouTube Plugin JAR ({PLUGIN_JAR_NAME}) not found.")
        if download_file(PLUGIN_URL, PLUGIN_JAR_PATH, f"YouTube Plugin v{PLUGIN_VERSION} JAR"): files_downloaded = True
        else: print("Warning: Failed to download YouTube plugin.")
    else: print(f"YouTube Plugin JAR ({PLUGIN_JAR_NAME}) already exists.")

    if not os.path.exists(SPOTIFY_PLUGIN_JAR_PATH):
        print(f"Spotify Plugin JAR ({SPOTIFY_PLUGIN_JAR_NAME}) not found.")
        if download_file(SPOTIFY_PLUGIN_URL, SPOTIFY_PLUGIN_JAR_PATH, f"Spotify Plugin (Lavasrc) v{SPOTIFY_PLUGIN_VERSION} JAR"): files_downloaded = True
        else: print("Warning: Failed to download Spotify plugin.")
    else: print(f"Spotify Plugin JAR ({SPOTIFY_PLUGIN_JAR_NAME}) already exists.")

    if files_downloaded and (os.path.exists(PLUGIN_JAR_PATH) or os.path.exists(SPOTIFY_PLUGIN_JAR_PATH)):
         print("\n" + "="*60)
         print("ACTION REQUIRED: Lavalink/Config/Plugins were downloaded or updated.")
         print(f"Please review '{CONFIG_PATH}' and ensure it's configured correctly,")
         print("especially the 'plugins:' section and 'lavalink.server.sources'.")
         print("You may need to stop this script (Ctrl+C), edit the file, and restart.")
         print("="*60 + "\n")
         try: input("Press Enter to continue starting Lavalink (or Ctrl+C to stop)...")
         except KeyboardInterrupt: print("\nExiting script."); sys.exit(0)

    return True

def start_lavalink():
    """Sets up Lavalink files, loads .env, checks config, and starts the server."""
    # print("Skipping Java version check as requested.") # Removed this line

    if not setup_lavalink():
        sys.exit("Lavalink setup failed.")

    if os.path.exists(CONFIG_PATH) and not check_plugin_config(CONFIG_PATH):
         sys.exit("Exiting due to critical configuration issues.")
    elif not os.path.exists(CONFIG_PATH):
         print("Warning: application.yml not found. Lavalink running on defaults.")

    print("\nLoading environment variables from .env...")
    dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(dotenv_path):
        if load_dotenv(dotenv_path=dotenv_path, override=True):
            print("Successfully loaded environment variables from .env for Lavalink process.")
            if os.path.exists(SPOTIFY_PLUGIN_JAR_PATH) and (not os.getenv("SPOTIFY_CLIENT_ID") or not os.getenv("SPOTIFY_CLIENT_SECRET")):
                print("WARNING: SPOTIFY_CLIENT_ID or SPOTIFY_CLIENT_SECRET not found in loaded .env variables!")
                print("         Lavalink Spotify plugin (LavaSrc) will likely fail.")
        else: print("Warning: .env file found but failed to load.")
    else:
        print("Warning: .env file not found.")
        if os.path.exists(SPOTIFY_PLUGIN_JAR_PATH):
             print("         Since Spotify plugin JAR exists, missing .env is likely an error.")

    print("-" * 30)
    print(f"Attempting to start Lavalink v{LAVALINK_VERSION}...")
    print(f"Using JAR: {JAR_PATH}")
    if os.path.exists(CONFIG_PATH): print(f"Using Config: {CONFIG_PATH}")
    print(f"Plugins Directory: {PLUGINS_DIR}")
    if os.path.exists(PLUGIN_JAR_PATH): print(f" - Found YouTube Plugin: {PLUGIN_JAR_NAME}")
    if os.path.exists(SPOTIFY_PLUGIN_JAR_PATH): print(f" - Found Spotify Plugin: {SPOTIFY_PLUGIN_JAR_NAME}")
    print("-" * 30)

    # --- Prepare Java Command ---
    # Increased logging and force IPv4 for further debugging
    JAVA_EXECUTABLE = "/usr/lib/jvm/java-17-openjdk-amd64/bin/java" # Force Java 17
    java_command = [
        "java",
        "-Djava.net.preferIPv4Stack=true", # Force IPv4 - common network issue fix
        # Debug Logging Arguments (Enable these for MUCH more detail)
        "-Dlogging.level.root=INFO", # Keep root INFO unless desperate
        "-Dlogging.level.lavalink=DEBUG",
        "-Dlogging.level.lavalink.server=DEBUG",
        "-Dlogging.level.com.sedmelluq.discord.lavaplayer=DEBUG", # Lavaplayer core HTTP/loading
        "-Dlogging.level.dev.lavalink.youtube=DEBUG", # YouTube plugin detail
        "-Dlogging.level.dev.kaan.lavasrc=DEBUG",     # LavaSrc plugin detail
        "-jar",
        JAR_PATH
    ]

    print(f"Executing command: {' '.join(java_command)}")
    process = None
    try:
        process = subprocess.Popen(
            java_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1,
            encoding='utf-8', # Explicitly set encoding
            errors='replace' # Handle potential decoding errors in output
        )
        if process.stdout:
            for line in iter(process.stdout.readline, ''):
                if line: print(line, end='', flush=True) # Print immediately
        process.wait()
        print("-" * 30)
        print(f"Lavalink process finished unexpectedly with exit code: {process.returncode}")

    except KeyboardInterrupt:
        print("\nStopping Lavalink (Ctrl+C received)...")
        if process and process.poll() is None:
             process.terminate(); process.wait(timeout=5)
             print("Lavalink terminated.")
        print("Lavalink process stopped.") # More generic message
    except FileNotFoundError:
         print(f"\nError: Could not execute 'java'. Is Java installed and in PATH?")
         sys.exit("Failed to start Lavalink: Java not found.")
    except Exception as e:
        print(f"\nAn unexpected error occurred while trying to run Lavalink: {e}")
        if process and process.returncode is not None: print(f"Lavalink exit code: {process.returncode}")
        sys.exit("Failed to start Lavalink.")

if __name__ == "__main__":
    start_lavalink()

# --- END OF FILE start_lavalink.py ---