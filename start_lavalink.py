import os
import sys
import subprocess
import urllib.request
import urllib.error
import platform
import re
import shutil
import textwrap  # For formatting warning messages
from dotenv import load_dotenv # <-- Ensure this is imported

# --- Configuration ---
# Check the Lavalink releases page for the latest stable version:
# https://github.com/lavalink-devs/Lavalink/releases
LAVALINK_VERSION = "3.7.11"  # <-- Set desired Lavalink Version
# REQUIRED_JAVA_VERSION = 17 # Lavalink requires Java 17 or higher (REMOVED CHECK)

# --- YouTube Plugin Configuration ---
# https://github.com/lavalink-devs/youtube-source/releases
PLUGIN_VERSION = "1.13.0" # <-- Use the latest compatible version
PLUGIN_NAME = "youtube-plugin"
PLUGIN_JAR_NAME = f"{PLUGIN_NAME}-{PLUGIN_VERSION}.jar"
PLUGIN_URL = f"https://github.com/lavalink-devs/youtube-source/releases/download/{PLUGIN_VERSION}/{PLUGIN_JAR_NAME}"

# --- Spotify Plugin Configuration (Lavasrc) ---
# Check Lavasrc releases for compatibility:
# https://github.com/topi314/LavaSrc/releases
SPOTIFY_PLUGIN_NAME = "lavasrc-plugin"
SPOTIFY_PLUGIN_VERSION = "4.0.0" # <-- Use a compatible version
SPOTIFY_PLUGIN_JAR_NAME = f"LavaSrc-{SPOTIFY_PLUGIN_VERSION}.jar"
SPOTIFY_PLUGIN_URL = f"https://github.com/topi314/LavaSrc/releases/download/{SPOTIFY_PLUGIN_VERSION}/LavaSrc-{SPOTIFY_PLUGIN_VERSION}.jar"
# --- End Configuration ---

LAVALINK_DIR = "lavalink"
JAR_NAME = "Lavalink.jar"
CONFIG_NAME = "application.yml"
EXAMPLE_CONFIG_NAME = "application.yml.example"
PLUGINS_DIR = os.path.join(LAVALINK_DIR, "plugins") # Standard directory for Lavalink plugins

JAR_PATH = os.path.join(LAVALINK_DIR, JAR_NAME)
CONFIG_PATH = os.path.join(LAVALINK_DIR, CONFIG_NAME)
PLUGIN_JAR_PATH = os.path.join(PLUGINS_DIR, PLUGIN_JAR_NAME)
SPOTIFY_PLUGIN_JAR_PATH = os.path.join(PLUGINS_DIR, SPOTIFY_PLUGIN_JAR_NAME)

def get_lavalink_urls(version):
    """Gets the download URLs for the JAR and example config for a specific version."""
    base_url = f"https://github.com/lavalink-devs/Lavalink/releases/download/{version}/"
    jar_url = base_url + JAR_NAME
    config_url = f"https://raw.githubusercontent.com/lavalink-devs/Lavalink/{version}/LavalinkServer/{EXAMPLE_CONFIG_NAME}"
    return jar_url, config_url

def download_file(url, destination_path, description):
    """Downloads a file from a URL to a destination path."""
    print(f"Downloading {description} from {url}...")
    try:
        os.makedirs(os.path.dirname(destination_path), exist_ok=True)
        # Add a user-agent header, as some hosts might block default python agent
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
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
        print(f"Error downloading {description}: HTTP Error {e.code}: {e.reason}")
        print(f"Please check if the URL is correct and the version exists: {url}")
        if os.path.exists(destination_path): os.remove(destination_path)
        return False
    except urllib.error.URLError as e:
        print(f"Error downloading {description}: {e.reason}")
        if os.path.exists(destination_path): os.remove(destination_path)
        return False
    except Exception as e:
        print(f"An unexpected error occurred during download: {e}")
        if os.path.exists(destination_path): os.remove(destination_path)
        return False

# --- Java Version Check Function REMOVED ---

def check_plugin_config(config_file_path):
    """Checks application.yml for common critical plugin configuration issues."""
    if not os.path.exists(config_file_path):
        print(f"Warning: Config file '{config_file_path}' not found for checking plugin settings.")
        return True # Cannot check, assume ok for now

    print(f"Checking '{config_file_path}' for critical plugin configuration issues...")
    config_ok = True
    warnings = []

    try:
        with open(config_file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # --- Check YouTube Plugin Settings (Only check for built-in conflict) ---
        youtube_plugin_present = os.path.exists(PLUGIN_JAR_PATH)
        if youtube_plugin_present:
            # Check if built-in YT source is explicitly enabled (true) when plugin exists
            # This is the most critical conflict
            built_in_yt_nested_enabled = re.search(r"lavalink:\s*\n.*?\s+server:\s*\n.*?\s+sources:\s*\n.*?\s+youtube:\s*true", content, re.DOTALL | re.IGNORECASE)
            if built_in_yt_nested_enabled:
                config_ok = False
                warnings.append(textwrap.dedent("""
                    Built-in YouTube source MUST be disabled ('false') when using the YouTube plugin.
                    Found 'lavalink.server.sources.youtube: true'. Please change it to 'false'.
                """))

        # --- Check Spotify Plugin Settings (Only check for placeholder variables) ---
        spotify_plugin_present = os.path.exists(SPOTIFY_PLUGIN_JAR_PATH)
        if spotify_plugin_present:
            # Check if the lavasrc block seems to exist using a simpler check
            lavasrc_block_exists = re.search(r"^\s*lavasrc:", content, re.MULTILINE | re.IGNORECASE) is not None
            if lavasrc_block_exists:
                 # Check for the environment variable placeholders inside the file content
                 # This confirms the user intends to use env vars, even if the block structure check was removed
                 spotify_client_id_placeholder = "${SPOTIFY_CLIENT_ID}" in content
                 spotify_client_secret_placeholder = "${SPOTIFY_CLIENT_SECRET}" in content
                 if not spotify_client_id_placeholder or not spotify_client_secret_placeholder:
                      # This is less critical but good practice
                      warnings.append(textwrap.dedent("""
                        [Optional but Recommended] LavaSrc Spotify configuration should use environment variables.
                        Consider changing hardcoded clientId/clientSecret to:
                          clientId: ${SPOTIFY_CLIENT_ID}
                          clientSecret: ${SPOTIFY_CLIENT_SECRET}
                        (Ensure these variables are set in your .env file)
                      """))
            # Note: We removed the check for the existence of the 'lavasrc:' block under 'plugins:'
            # because that regex seemed to be the problem. We assume if the JAR is present,
            # the user intends to configure it. Lavalink will error if the config is truly malformed.

        # --- Final Output ---
        if not config_ok: # Only fail on critical issues (like youtube: true)
            print("\n" + "="*60)
            print("ERROR: Critical configuration issues found!")
            print(f"Please fix '{config_file_path}' based on the following:")
            for warning in warnings:
                print("-" * 20)
                print(warning)
            print("="*60 + "\n")
            return False # Return False for critical errors
        elif warnings: # Print optional warnings but allow script to continue
            print("\n" + "="*60)
            print("INFO: Configuration suggestions:")
            for warning in warnings:
                 print("-" * 20)
                 print(warning)
            print("="*60 + "\n")
            return True # Return True as warnings are not critical block
        else:
            print("Basic plugin configuration checks passed (manual verification still recommended).")
            return True

    except Exception as e:
        print(f"Error reading or checking config file '{config_file_path}': {e}")
        return False # Treat error as potential issue


def setup_lavalink():
    """Downloads Lavalink JAR, config, and required plugins if they don't exist."""
    os.makedirs(LAVALINK_DIR, exist_ok=True)
    os.makedirs(PLUGINS_DIR, exist_ok=True)

    jar_url, config_url = get_lavalink_urls(LAVALINK_VERSION)
    config_example_path = os.path.join(LAVALINK_DIR, EXAMPLE_CONFIG_NAME)
    files_downloaded = False

    # --- Setup Main Lavalink ---
    if not os.path.exists(JAR_PATH):
        if not download_file(jar_url, JAR_PATH, f"Lavalink v{LAVALINK_VERSION} JAR"):
            return False # Stop if core JAR download fails
        files_downloaded = True
    else:
        print(f"Lavalink JAR ({JAR_NAME}) already exists.")

    if not os.path.exists(CONFIG_PATH):
        print(f"{CONFIG_NAME} not found.")
        if not download_file(config_url, config_example_path, "Lavalink example configuration"):
            print("Failed to download example configuration. Cannot create application.yml.")
            # Clean up empty file if download failed badly
            if os.path.exists(config_example_path) and os.path.getsize(config_example_path) == 0:
                os.remove(config_example_path)
            return False
        try:
            shutil.move(config_example_path, CONFIG_PATH)
            print(f"Created {CONFIG_NAME} from example.")
            files_downloaded = True
        except OSError as e:
            print(f"Error moving example config: {e}")
            return False
    else:
         print(f"Lavalink configuration ({CONFIG_NAME}) already exists.")

    # --- Setup YouTube Plugin ---
    if not os.path.exists(PLUGIN_JAR_PATH):
        print(f"YouTube Plugin JAR ({PLUGIN_JAR_NAME}) not found.")
        if not download_file(PLUGIN_URL, PLUGIN_JAR_PATH, f"YouTube Plugin v{PLUGIN_VERSION} JAR"):
             print("Warning: Failed to download YouTube plugin. YouTube functionality via plugin will be unavailable.")
        else:
             files_downloaded = True
    else:
        print(f"YouTube Plugin JAR ({PLUGIN_JAR_NAME}) already exists.")

    # --- Setup Spotify Plugin (Lavasrc) ---
    if not os.path.exists(SPOTIFY_PLUGIN_JAR_PATH):
        print(f"Spotify Plugin JAR ({SPOTIFY_PLUGIN_JAR_NAME}) not found.")
        if not download_file(SPOTIFY_PLUGIN_URL, SPOTIFY_PLUGIN_JAR_PATH, f"Spotify Plugin (Lavasrc) v{SPOTIFY_PLUGIN_VERSION} JAR"):
             print("Warning: Failed to download Spotify plugin. Spotify functionality will be unavailable.")
        else:
             files_downloaded = True
    else:
        print(f"Spotify Plugin JAR ({SPOTIFY_PLUGIN_JAR_NAME}) already exists.")

    # --- Check Configuration for Plugins ---
    plugin_jars_present = os.path.exists(PLUGIN_JAR_PATH) or os.path.exists(SPOTIFY_PLUGIN_JAR_PATH)

    if plugin_jars_present:
        if files_downloaded:
             print("\n" + "="*60)
             print("ACTION REQUIRED: Lavalink/Config/Plugins were downloaded or updated.")
             print(f"Please review '{CONFIG_PATH}' and ensure it's configured correctly:")
             print("  1. Set Lavalink `server.password` (must match bot's .env).")
             print("  2. Disable built-in source if using YT plugin: `lavalink.server.sources.youtube: false`.")
             print("  3. Enable desired built-in sources (e.g., `soundcloud: true`).")
             print("  4. Configure `plugins:` block at the root level (NOT under lavalink.server):")
             print("     - Add `youtube:` block if using YT plugin.")
             print("     - Add `lavasrc:` block with Spotify `clientId: ${SPOTIFY_CLIENT_ID}`")
             print("       and `clientSecret: ${SPOTIFY_CLIENT_SECRET}`.")
             print("     (Ensure SPOTIFY_CLIENT_ID/SECRET are in your .env file)")
             print("     (See plugin documentation for details and other options)")
             print("You may need to stop this script (Ctrl+C), edit the file, and restart.")
             print("="*60 + "\n")
             try:
                 input("Press Enter to continue starting Lavalink (or Ctrl+C to stop and edit config)...")
             except KeyboardInterrupt:
                 print("\nExiting script to allow config editing.")
                 sys.exit(0)
        # else: # Config check now happens before launch regardless
             pass
    elif not os.path.exists(CONFIG_PATH):
         print(f"Warning: Config file '{CONFIG_PATH}' not found, and no plugins downloaded.")
         print("Lavalink will start with default settings and limited sources.")
    else:
        print("No plugin JARs found in the plugins directory. Functionality may be limited.")
        # Check if config *disables* built-in YT unnecessarily if no plugin exists
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                content = f.read()
            if re.search(r"lavalink:\s*\n.*?\s+server:\s*\n.*?\s+sources:\s*\n.*?\s+youtube:\s*false", content, re.DOTALL | re.IGNORECASE) \
               and not os.path.exists(PLUGIN_JAR_PATH): # Only warn if plugin is missing
                print("\nWARNING: Built-in YouTube source is disabled in config, but no YouTube plugin JAR was found!")
                print("YouTube playback will likely fail. Either remove the 'youtube: false' line or add the plugin JAR.\n")
        except Exception: pass # Ignore errors reading config here

    return True


def start_lavalink():
    """Sets up Lavalink files, loads .env, checks config, and starts the server."""
    print("Skipping Java version check as requested.") # Indicate check is skipped

    # Perform file setup (downloads etc)
    if not setup_lavalink():
        sys.exit("Lavalink setup failed. Please check errors above.")

    # Check config validity *after* setup potentially created/modified it
    if os.path.exists(CONFIG_PATH) and not check_plugin_config(CONFIG_PATH): # check_plugin_config returns False on critical errors
         print("Exiting due to critical configuration issues detected. Please edit application.yml and restart.")
         sys.exit(1)
    elif not os.path.exists(CONFIG_PATH):
         print("Warning: application.yml not found. Lavalink running on defaults.")


    # --- Load .env file HERE, before launching Java ---
    print("\nLoading environment variables from .env...")
    dotenv_path = os.path.join(os.path.dirname(__file__), '.env') # Explicitly look for .env next to this script
    if os.path.exists(dotenv_path):
        loaded = load_dotenv(dotenv_path=dotenv_path, override=True) # Override ensures script's env gets updated
        if loaded:
            print("Successfully loaded environment variables from .env for Lavalink process.")
            # Verify if specific needed vars were loaded into the Python script's environment
            if os.path.exists(SPOTIFY_PLUGIN_JAR_PATH) and (not os.getenv("SPOTIFY_CLIENT_ID") or not os.getenv("SPOTIFY_CLIENT_SECRET")):
                print("WARNING: SPOTIFY_CLIENT_ID or SPOTIFY_CLIENT_SECRET not found in loaded environment variables!")
                print("         Lavalink Spotify plugin (LavaSrc) will likely fail.")
        else:
            print("Warning: .env file found but python-dotenv failed to load it.")
    else:
        print("Warning: .env file not found. Lavalink might miss required environment variables (e.g., Spotify keys).")
        print("         Ensure .env is in the same directory as this script or specify path.")
        if os.path.exists(SPOTIFY_PLUGIN_JAR_PATH):
             print("         Since Spotify plugin JAR exists, missing .env is likely an error.")


    print("-" * 30)
    print(f"Attempting to start Lavalink v{LAVALINK_VERSION}...")
    print(f"Using JAR: {JAR_PATH}")
    if os.path.exists(CONFIG_PATH): print(f"Using Config: {CONFIG_PATH}")
    print(f"Plugins Directory: {PLUGINS_DIR}")
    # List found plugins again for clarity
    found_plugins = list(filter(os.path.isfile, [PLUGIN_JAR_PATH, SPOTIFY_PLUGIN_JAR_PATH]))
    if found_plugins:
        if os.path.exists(PLUGIN_JAR_PATH):
            print(f" - Found YouTube Plugin: {PLUGIN_JAR_NAME}")
        if os.path.exists(SPOTIFY_PLUGIN_JAR_PATH):
            print(f" - Found Spotify Plugin: {SPOTIFY_PLUGIN_JAR_NAME}")
    print("-" * 30)


    # --- Prepare Java Command ---
    java_command = [
        "java", # ASSUMES 'java' is in the system PATH
        # --- Optional JVM / Logging Arguments ---
        # "-Xms512m", "-Xmx1024m", # Memory limits
        # "-Djava.net.preferIPv4Stack=true", # Force IPv4
        "-Dlogging.level.lavalink=INFO",
        "-Dlogging.level.lavalink.server=INFO",
        # "-Dlogging.level.com.sedmelluq.discord.lavaplayer=DEBUG",
        "-Dlogging.level.dev.lavalink.youtube=INFO", # DEBUG for more YT plugin info
        "-Dlogging.level.dev.kaan.lavasrc=INFO",     # DEBUG for more LavaSrc info
        # --- Main Arguments ---
        "-jar",
        JAR_PATH
    ]

    # --- Start Lavalink Process ---
    print(f"Executing command: {' '.join(java_command)}")
    process = None
    try:
        process = subprocess.Popen(
            java_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1
        )
        if process.stdout:
            for line in iter(process.stdout.readline, ''):
                if line:
                    print(line, end='', flush=True)
        process.wait()
        print("-" * 30)
        print(f"Lavalink process finished unexpectedly with exit code: {process.returncode}")

    except KeyboardInterrupt:
        print("\nStopping Lavalink (Ctrl+C received)...")
        if process and process.poll() is None:
             process.terminate()
             try:
                 process.wait(timeout=5)
                 print("Lavalink terminated.")
             except subprocess.TimeoutExpired:
                 print("Lavalink did not terminate gracefully, killing...")
                 process.kill()
                 process.wait()
                 print("Lavalink killed.")
        else:
             print("Lavalink process was not running or already stopped.")

    except FileNotFoundError:
         print(f"\nError: Could not execute 'java'. Is Java installed and in PATH?")
         print(f"Attempted command: {' '.join(java_command)}")
         sys.exit("Failed to start Lavalink: Java not found.")
    except Exception as e:
        print(f"\nAn unexpected error occurred while trying to run Lavalink: {e}")
        if process and process.returncode is not None:
            print(f"Lavalink process may have exited with code: {process.returncode}")
        sys.exit("Failed to start Lavalink.")

# --- Main Execution Guard ---
if __name__ == "__main__":
    start_lavalink()
