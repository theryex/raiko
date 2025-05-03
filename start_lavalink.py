import os
import sys
import subprocess
import urllib.request
import urllib.error
import platform
import re
import shutil
import textwrap  # For formatting warning messages
from dotenv import load_dotenv

# --- Configuration ---
# Check the Lavalink releases page for the latest stable version:
# https://github.com/lavalink-devs/Lavalink/releases
LAVALINK_VERSION = "3.7.11"  # <-- Set desired Lavalink Version
REQUIRED_JAVA_VERSION = 17 # Lavalink requires Java 17 or higher

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

def check_java_version():
    """Checks if a compatible Java version is installed and returns its major version."""
    print("Checking Java version...")
    try:
        result = subprocess.run(
            ["java", "-version"],
            capture_output=True, text=True, check=False
        )
        if result.returncode != 0 and ('not found' in result.stderr.lower() or 'not recognized' in result.stderr.lower()):
             raise FileNotFoundError("Java command not found")
        if result.returncode != 0:
             raise subprocess.CalledProcessError(result.returncode, result.args, output=result.stdout, stderr=result.stderr)

        output = result.stderr
        match = re.search(r'(?:java|openjdk)\s+version\s+"(\d+)(?:\.(\d+))?.*?"', output, re.IGNORECASE)
        if match:
            major = int(match.group(1))
            if major == 1: # Handle 1.8 etc.
                minor_match = re.search(r'version\s+"1\.(\d+).*?"', output, re.IGNORECASE)
                major = int(minor_match.group(1)) if minor_match else major
            print(f"Detected Java major version: {major}")
            return major, output
        else:
            print("Could not parse Java version string from stderr.")
            full_output = f"--- Stderr ---\n{result.stderr}\n--- Stdout ---\n{result.stdout}"
            return None, full_output
    except FileNotFoundError:
        print("Error: 'java' command not found. Is Java installed and in your PATH?")
        return None, "Java command not found."
    except subprocess.CalledProcessError as e:
        print(f"Error running 'java -version' (Return Code: {e.returncode}):")
        full_output = f"--- Stderr ---\n{e.stderr or '[No Stderr]'}\n--- Stdout ---\n{e.output or '[No Stdout]'}"
        print(full_output)
        return None, full_output
    except Exception as e:
        print(f"An unexpected error occurred while checking Java version: {e}")
        try: err_output = result.stderr if 'result' in locals() and hasattr(result, 'stderr') else str(e)
        except: err_output = str(e)
        return None, err_output

def check_plugin_config(config_file_path):
    """Checks if application.yml seems configured for the YouTube plugin."""
    if not os.path.exists(config_file_path):
        print(f"Warning: Config file '{config_file_path}' not found for checking plugin settings.")
        return False # Cannot check

    print(f"Checking '{config_file_path}' for YouTube plugin configuration...")
    try:
        with open(config_file_path, 'r') as f:
            content = f.read()

        disabled_pattern = re.compile(r"lavalink:\s*\n(.*?)\s+server:\s*\n(.*?)\s+sources:\s*\n(.*?)\s+youtube:\s*false", re.DOTALL | re.MULTILINE)
        plugins_pattern = re.compile(r"^\s*plugins:", re.MULTILINE)
        # Check specifically for the 'youtube:' key under 'plugins:'
        # This assumes the plugin identifies itself as 'youtube' internally, which is standard
        youtube_plugin_config_pattern = re.compile(r"^\s*plugins:\s*\n(.*?)\s+youtube:", re.DOTALL | re.MULTILINE)

        built_in_disabled = disabled_pattern.search(content) is not None
        plugins_block_exists = plugins_pattern.search(content) is not None
        youtube_plugin_configured = youtube_plugin_config_pattern.search(content) is not None

        config_ok = True
        if not built_in_disabled:
            config_ok = False
            print("\n" + "="*50)
            print("WARNING: Built-in YouTube source may not be disabled!")
            print(f"Please ensure your '{config_file_path}' contains:")
            print(textwrap.dedent("""
              lavalink:
                server:
                  sources:
                    youtube: false # <-- MUST be false to use the plugin
            """))
            print("="*50 + "\n")

        if not plugins_block_exists or not youtube_plugin_configured:
            config_ok = False
            print("\n" + "="*50)
            print("WARNING: YouTube plugin block may be missing or incorrectly placed!")
            print(f"Please ensure your '{config_file_path}' contains a block like this at the root level:")
            print(textwrap.dedent("""
              plugins:
                youtube: # This MUST be the identifier 'youtube'
                  enabled: true
                  # Add other youtube plugin specific options if needed.
                  # See plugin documentation for details.
            """))
            print("="*50 + "\n")

        if config_ok:
            print("Basic plugin configuration appears present (manual verification recommended).")
            return True
        else:
            print(f"Action required: Please review and edit '{config_file_path}' based on the warnings above.")
            return False

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

    # --- Setup Main Lavalink ---
    if not os.path.exists(JAR_PATH):
        if not download_file(jar_url, JAR_PATH, f"Lavalink v{LAVALINK_VERSION} JAR"):
            return False
        files_downloaded = True
    else:
        print(f"Lavalink JAR ({JAR_NAME}) already exists.")

    if not os.path.exists(CONFIG_PATH):
        print(f"{CONFIG_NAME} not found.")
        if not download_file(config_url, config_example_path, "Lavalink example configuration"):
            print("Failed to download example configuration. Cannot create application.yml.")
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
             print("Continuing without YouTube plugin download (may cause issues).")
        else:
             files_downloaded = True
    else:
        print(f"YouTube Plugin JAR ({PLUGIN_JAR_NAME}) already exists.")

    # --- Setup Spotify Plugin (Lavasrc) ---
    if not os.path.exists(SPOTIFY_PLUGIN_JAR_PATH):
        print(f"Spotify Plugin JAR ({SPOTIFY_PLUGIN_JAR_NAME}) not found.")
        if not download_file(SPOTIFY_PLUGIN_URL, SPOTIFY_PLUGIN_JAR_PATH, f"Spotify Plugin (Lavasrc) v{SPOTIFY_PLUGIN_VERSION} JAR"):
             print("Continuing without Spotify plugin download (Spotify links won't work).")
        else:
             files_downloaded = True
    else:
        print(f"Spotify Plugin JAR ({SPOTIFY_PLUGIN_JAR_NAME}) already exists.")

    # --- Check Configuration for Plugins ---
    plugin_jars_present = os.path.exists(PLUGIN_JAR_PATH) or os.path.exists(SPOTIFY_PLUGIN_JAR_PATH)

    if plugin_jars_present:
        if files_downloaded:
             print("\n" + "="*50)
             print("ACTION REQUIRED: Lavalink/Config/Plugins were downloaded or updated.")
             print(f"Please review '{CONFIG_PATH}' and ensure it's configured correctly:")
             print("  1. Set Lavalink `server.password` (must match bot's .env).")
             print("  2. Disable built-in source: `lavalink.server.sources.youtube: false`.")
             print("  3. Enable built-in source: `lavalink.server.sources.soundcloud: true`.")
             print("  4. Configure `plugins:` block at the root level:")
             print("     - Add `youtube:` block if needed (can be empty if defaults are ok).")
             print("     - Add `lavasrc:` block with your Spotify `clientId` and `clientSecret`.")
             print("     (See plugin documentation for details and other options)")
             print("You may need to stop this script (Ctrl+C), edit the file, and restart.")
             print("="*50 + "\n")
             try:
                 input("Press Enter to continue starting Lavalink (or Ctrl+C to stop and edit config)...")
             except KeyboardInterrupt:
                 print("\nExiting script to allow config editing.")
                 sys.exit(0)
        else:
             check_plugin_config(CONFIG_PATH)
    else:
        print("No plugin JARs found in the plugins directory. Functionality will be limited.")

    return True

def start_lavalink():
    """Checks Java, sets up Lavalink files, and starts the server."""
    java_major_version, java_version_output = check_java_version()

    if java_major_version is None:
        print("-" * 30); print("Java Version Check Output:"); print(java_version_output); print("-" * 30)
        sys.exit(f"Failed to determine Java version. Lavalink v{LAVALINK_VERSION.split('.')[0]} requires Java {REQUIRED_JAVA_VERSION} or higher.")

    if java_major_version < REQUIRED_JAVA_VERSION:
        print("-" * 30); print("Java Version Check Output:"); print(java_version_output); print("-" * 30)
        sys.exit(f"Error: Incompatible Java version detected (Version {java_major_version}). Lavalink v{LAVALINK_VERSION.split('.')[0]} requires Java {REQUIRED_JAVA_VERSION} or higher.")
    else:
        print(f"Java version {java_major_version} is compatible (Required: {REQUIRED_JAVA_VERSION}+).")

    if not setup_lavalink():
        sys.exit("Lavalink setup failed. Please check errors above.")

    if not check_plugin_config(CONFIG_PATH) and os.path.exists(CONFIG_PATH):
         print("Exiting due to critical configuration issues detected.")
         sys.exit(1)

    print("-" * 30)
    print(f"Attempting to start Lavalink v{LAVALINK_VERSION}...")
    print(f"Using JAR: {JAR_PATH}")
    print(f"Using Config: {CONFIG_PATH}")
    print(f"Plugins Directory: {PLUGINS_DIR}")
    if os.path.exists(PLUGIN_JAR_PATH):
        print(f" - Found YouTube Plugin: {PLUGIN_JAR_NAME}")
    if os.path.exists(SPOTIFY_PLUGIN_JAR_PATH):
        print(f" - Found Spotify Plugin: {SPOTIFY_PLUGIN_JAR_NAME}")
    print("-" * 30)

    # Load environment variables from .env file
    load_dotenv()
    
    # Get Spotify credentials from .env
    spotify_client_id = os.getenv('SPOTIFY_CLIENT_ID')
    spotify_client_secret = os.getenv('SPOTIFY_CLIENT_SECRET')
    
    if not spotify_client_id or not spotify_client_secret:
        print("Error: SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET must be set in .env file")
        sys.exit(1)
    
    # Export Spotify credentials to environment
    os.environ['SPOTIFY_CLIENT_ID'] = spotify_client_id
    os.environ['SPOTIFY_CLIENT_SECRET'] = spotify_client_secret

    java_command = [
        "java",
        "-Dlogging.level.lavalink=INFO",
        "-Dlogging.level.dev.lavalink.jda=INFO",
        "-Dlogging.level.com.sedmelluq.discord.lavaplayer=INFO",
        "-Dlogging.level.lavalink.plugins.youtube=DEBUG",
        "-Dlogging.level.dev.kaan.lavasrc=DEBUG",
        "-jar",
        JAR_PATH  # Use the full path to the JAR
    ]

    try:
        process = subprocess.Popen(
            java_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True
        )
        
        # Print output in real-time
        for line in process.stdout:
            print(line, end='')
            
        # Wait for process to complete
        process.wait()
        
    except KeyboardInterrupt:
        print("\nStopping Lavalink...")
        process.terminate()
        process.wait()
    except FileNotFoundError:
         print(f"Error: Could not execute 'java'. Is Java installed and in PATH?")
         print(f"Attempted command: {' '.join(java_command)}")
         sys.exit("Failed to start Lavalink: Java not found.")
    except Exception as e:
        print(f"An unexpected error occurred while trying to run Lavalink: {e}")
        sys.exit("Failed to start Lavalink.")

if __name__ == "__main__":
    start_lavalink()