import os
import sys
import subprocess
import urllib.request
import urllib.error
import platform
import re
import shutil
import textwrap  # For formatting warning messages

# --- Configuration ---
# Check the Lavalink releases page for the latest stable v4 version:
# https://github.com/lavalink-devs/Lavalink/releases
LAVALINK_VERSION = "4.0.8"  # <-- Set desired Lavalink Version
REQUIRED_JAVA_VERSION = 17 # Lavalink v4 requires Java 17 or higher

# --- YouTube Plugin Configuration ---
# IMPORTANT: Check the plugin releases page for the latest version compatible with Lavalink v4.0.8
# e.g., https://github.com/lavalink-devs/youtube-source/releases
# Latest version as of checking: 1.13.0 (requires Lavalink 4.0.7+)
PLUGIN_VERSION = "1.13.0" # <-- Use the latest compatible version
PLUGIN_NAME = "youtube-plugin" # <-- Use the name as found in GitHub releases
# Construct JAR name based on official releases (e.g., youtube-1.3.0.jar)
PLUGIN_JAR_NAME = f"{PLUGIN_NAME}-{PLUGIN_VERSION}.jar" #<-- Correct format
# Direct URL to the plugin
PLUGIN_URL = "https://github.com/lavalink-devs/youtube-source/releases/download/1.13.0/youtube-plugin-1.13.0.jar"
# --- End Configuration ---

LAVALINK_DIR = "lavalink"
JAR_NAME = "Lavalink.jar"
CONFIG_NAME = "application.yml"
EXAMPLE_CONFIG_NAME = "application.yml.example"
PLUGINS_DIR = os.path.join(LAVALINK_DIR, "plugins") # Standard directory for Lavalink plugins

JAR_PATH = os.path.join(LAVALINK_DIR, JAR_NAME)
CONFIG_PATH = os.path.join(LAVALINK_DIR, CONFIG_NAME)
PLUGIN_JAR_PATH = os.path.join(PLUGINS_DIR, PLUGIN_JAR_NAME) # Path uses the specific JAR name

def get_lavalink_urls(version):
    """Gets the download URLs for the JAR and example config for a specific version."""
    base_url = f"https://github.com/lavalink-devs/Lavalink/releases/download/{version}/"
    jar_url = base_url + JAR_NAME
    config_url = f"https://raw.githubusercontent.com/lavalink-devs/Lavalink/{version}/LavalinkServer/{EXAMPLE_CONFIG_NAME}"
    return jar_url, config_url

# Removed get_plugin_url function as it's no longer needed for direct URL

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
    """Downloads Lavalink JAR, config, and YouTube plugin if they don't exist."""
    # --- Setup Main Lavalink ---
    jar_url, config_url = get_lavalink_urls(LAVALINK_VERSION)
    config_example_path = os.path.join(LAVALINK_DIR, EXAMPLE_CONFIG_NAME)
    config_downloaded = False

    if not os.path.exists(JAR_PATH):
        if not download_file(jar_url, JAR_PATH, f"Lavalink v{LAVALINK_VERSION} JAR"):
            return False
    else:
        print(f"Lavalink JAR ({JAR_NAME}) already exists.")

    if not os.path.exists(CONFIG_PATH):
        print(f"{CONFIG_NAME} not found.")
        if not download_file(config_url, config_example_path, "Lavalink example configuration"):
            print("Failed to download example configuration. Cannot create application.yml.")
            return False
        try:
            shutil.move(config_example_path, CONFIG_PATH)
            print(f"Created {CONFIG_NAME} from example.")
            config_downloaded = True
        except OSError as e:
            print(f"Error moving example config: {e}")
            return False
    else:
         print(f"Lavalink configuration ({CONFIG_NAME}) already exists.")

    # --- Setup YouTube Plugin using Direct URL ---
    plugin_url = PLUGIN_URL
    plugin_downloaded = False

    if not os.path.exists(PLUGIN_JAR_PATH):
        print(f"YouTube Plugin JAR ({PLUGIN_JAR_NAME}) not found.")
        # Attempt download using the direct URL
        if not download_file(plugin_url, PLUGIN_JAR_PATH, f"YouTube Plugin v{PLUGIN_VERSION} JAR"):
             print("Continuing without YouTube plugin download.")
        else:
             plugin_downloaded = True
    else:
        print(f"YouTube Plugin JAR ({PLUGIN_JAR_NAME}) already exists.")

    # --- Check Configuration for Plugin ---
    if os.path.exists(PLUGIN_JAR_PATH):
        if config_downloaded or plugin_downloaded:
             print("\n" + "="*50)
             print("ACTION REQUIRED: Lavalink config or YouTube plugin was just downloaded.")
             print(f"Please review '{CONFIG_PATH}' and ensure it's configured correctly for the YouTube plugin:")
             print("  1. Disable built-in source: Set `lavalink.server.sources.youtube` to `false`.")
             print("  2. Add/configure the `plugins:` block at the root level with `youtube:` under it.")
             print("See plugin documentation for details on options within the 'plugins:' block.")
             print("You may need to stop this script, edit the file, and restart.")
             print("="*50 + "\n")
             input("Press Enter to continue starting Lavalink (or Ctrl+C to stop and edit config)...")
        else:
             check_plugin_config(CONFIG_PATH)
    else:
        print("YouTube Plugin JAR not found, skipping configuration check.")

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

    if not check_plugin_config(CONFIG_PATH):
        print("Warning: Lavalink configuration may not be properly set up for the YouTube plugin.")

    print("-" * 30)
    print(f"Attempting to start Lavalink v{LAVALINK_VERSION} with Plugin {PLUGIN_JAR_NAME} (if present)...")
    print(f"Using JAR: {JAR_PATH}")
    print(f"Using Config: {CONFIG_PATH}")
    if os.path.exists(PLUGIN_JAR_PATH):
        print(f"Using Plugin: {PLUGIN_JAR_PATH}")
    print("-" * 30)

    # --- Start Lavalink with Debug Flags ---
    java_command = [
        "java",
        "-Dlogging.level.lavalink=DEBUG",
        "-Dlogging.level.com.sedmelluq.discord.lavaplayer=DEBUG",
        "-Dlogging.level.lavalink.plugins.youtube=DEBUG",
        "-jar",
        JAR_NAME
    ]

    try:
        process = subprocess.run(
            java_command,
            cwd=LAVALINK_DIR,
            check=False
        )
        print(f"Lavalink process finished with exit code: {process.returncode}")

    except KeyboardInterrupt:
        print("\nLavalink stopped by user.")
    except Exception as e:
        print(f"An error occurred while trying to run Lavalink: {e}")
        sys.exit("Failed to start Lavalink.")

if __name__ == "__main__":
    start_lavalink()