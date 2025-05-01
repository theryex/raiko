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
LAVALINK_VERSION = "4.0.8"  # <-- Updated Lavalink Version
REQUIRED_JAVA_VERSION = 17 # Lavalink v4 requires Java 17 or higher

# --- YouTube Plugin Configuration ---
# IMPORTANT: Check the plugin releases page for the latest version compatible with Lavalink v4.0.8
# e.g., https://github.com/lavalink-plugins/youtube/releases
PLUGIN_VERSION = "1.13.0" # <-- !!! VERIFY AND UPDATE THIS VERSION !!!
PLUGIN_NAME = "youtube-v2"
PLUGIN_JAR_NAME = f"{PLUGIN_NAME}-{PLUGIN_VERSION}.jar"
# Adjust owner/repo if the official plugin location changes
PLUGIN_REPO_OWNER = "lavalink-plugins"
PLUGIN_REPO_NAME = "youtube"
# --- End Configuration ---

LAVALINK_DIR = "lavalink"
JAR_NAME = "Lavalink.jar"
CONFIG_NAME = "application.yml"
EXAMPLE_CONFIG_NAME = "application.yml.example"
PLUGINS_DIR = os.path.join(LAVALINK_DIR, "plugins") # Standard directory for Lavalink plugins

JAR_PATH = os.path.join(LAVALINK_DIR, JAR_NAME)
CONFIG_PATH = os.path.join(LAVALINK_DIR, CONFIG_NAME)
PLUGIN_JAR_PATH = os.path.join(PLUGINS_DIR, PLUGIN_JAR_NAME)

def get_lavalink_urls(version):
    """Gets the download URLs for the JAR and example config for a specific version."""
    base_url = f"https://github.com/lavalink-devs/Lavalink/releases/download/{version}/"
    jar_url = base_url + JAR_NAME
    config_url = f"https://raw.githubusercontent.com/lavalink-devs/Lavalink/{version}/LavalinkServer/{EXAMPLE_CONFIG_NAME}"
    return jar_url, config_url

def get_plugin_url(owner, repo, version, jar_name):
     """Gets the download URL for the plugin JAR."""
     # Note: Some plugins might use different URL structures or artifact names
     return f"https://github.com/{owner}/{repo}/releases/download/{version}/{jar_name}"

def download_file(url, destination_path, description):
    """Downloads a file from a URL to a destination path."""
    print(f"Downloading {description} from {url}...")
    try:
        os.makedirs(os.path.dirname(destination_path), exist_ok=True)
        with urllib.request.urlopen(url) as response, open(destination_path, 'wb') as out_file:
            if response.status == 200:
                shutil.copyfileobj(response, out_file)
                print(f"{description} download complete!")
                return True
            else:
                 print(f"Error downloading {description}: HTTP Status {response.status} {response.reason}")
                 return False
    except urllib.error.HTTPError as e:
        # Specifically catch HTTP errors for better messages (like 404 Not Found)
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

        # Basic checks (YAML is whitespace sensitive, so these are approximations)
        # 1. Check if built-in youtube source is disabled
        #    Matches variations like 'youtube: false' under 'sources:' which is under 'server:' under 'lavalink:'
        disabled_pattern = re.compile(r"lavalink:\s*\n(.*?)\s+server:\s*\n(.*?)\s+sources:\s*\n(.*?)\s+youtube:\s*false", re.DOTALL | re.MULTILINE)
        # 2. Check if a top-level 'plugins:' key exists
        plugins_pattern = re.compile(r"^\s*plugins:", re.MULTILINE)

        built_in_disabled = disabled_pattern.search(content) is not None
        plugins_block_exists = plugins_pattern.search(content) is not None

        if not built_in_disabled:
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

        if not plugins_block_exists:
            print("\n" + "="*50)
            print("WARNING: Top-level 'plugins:' block may be missing!")
            print(f"Please ensure your '{config_file_path}' contains a block like this at the root level:")
            print(textwrap.dedent("""
              plugins:
                youtube: # Or configure other plugins here
                  enabled: true
                  # Add other youtube plugin specific options if needed, e.g.:
                  # allowSearch: true
                  # clients:
                  #  - MUSIC
                  #  - WEB
                  # See plugin documentation for details.
            """))
            print("="*50 + "\n")

        if built_in_disabled and plugins_block_exists:
            print("Basic plugin configuration appears present (manual verification recommended).")
            return True
        else:
            # One or both checks failed
            print(f"Action required: Please review and edit '{config_file_path}' based on the warnings above.")
            return False # Indicate checks failed

    except Exception as e:
        print(f"Error reading or checking config file '{config_file_path}': {e}")
        return False # Indicate check failed


def setup_lavalink():
    """Downloads Lavalink JAR, config, and YouTube plugin if they don't exist."""
    # --- Setup Main Lavalink ---
    jar_url, config_url = get_lavalink_urls(LAVALINK_VERSION)
    config_example_path = os.path.join(LAVALINK_DIR, EXAMPLE_CONFIG_NAME)
    config_downloaded = False

    # Download Lavalink.jar if needed
    if not os.path.exists(JAR_PATH):
        if not download_file(jar_url, JAR_PATH, f"Lavalink v{LAVALINK_VERSION} JAR"):
            return False
    else:
        print(f"Lavalink JAR ({JAR_NAME}) already exists.")

    # Download application.yml.example if application.yml doesn't exist
    if not os.path.exists(CONFIG_PATH):
        print(f"{CONFIG_NAME} not found.")
        if not download_file(config_url, config_example_path, "Lavalink example configuration"):
            print("Failed to download example configuration. Cannot create application.yml.")
            return False
        try:
            shutil.move(config_example_path, CONFIG_PATH)
            print(f"Created {CONFIG_NAME} from example.")
            config_downloaded = True # Mark that we just created it
        except OSError as e:
            print(f"Error moving example config: {e}")
            return False
    else:
         print(f"Lavalink configuration ({CONFIG_NAME}) already exists.")

    # --- Setup YouTube Plugin ---
    plugin_url = get_plugin_url(PLUGIN_REPO_OWNER, PLUGIN_REPO_NAME, PLUGIN_VERSION, PLUGIN_JAR_NAME)
    plugin_downloaded = False

    if not os.path.exists(PLUGIN_JAR_PATH):
        print(f"YouTube Plugin JAR ({PLUGIN_JAR_NAME}) not found.")
        if not download_file(plugin_url, PLUGIN_JAR_PATH, f"YouTube Plugin v{PLUGIN_VERSION} JAR"):
             print("Continuing without YouTube plugin download.")
             # Don't fail the whole setup if plugin download fails, maybe user doesn't need it
        else:
             plugin_downloaded = True
    else:
        print(f"YouTube Plugin JAR ({PLUGIN_JAR_NAME}) already exists.")

    # --- Check Configuration for Plugin ---
    if os.path.exists(PLUGIN_JAR_PATH):
        if config_downloaded or plugin_downloaded:
             # If we just downloaded either the config or the plugin, remind user to configure
             print("\n" + "="*50)
             print("ACTION REQUIRED: Lavalink config or YouTube plugin was just downloaded.")
             print(f"Please review '{CONFIG_PATH}' and ensure it's configured correctly for the YouTube plugin:")
             print("  1. Disable built-in source: Set `lavalink.server.sources.youtube` to `false`.")
             print("  2. Add/configure the `plugins:` block at the root level.")
             print("See plugin documentation for details on options within the 'plugins:' block.")
             print("You may need to stop this script, edit the file, and restart.")
             print("="*50 + "\n")
        else:
             # Both config and plugin existed before, check if config looks okay
             check_plugin_config(CONFIG_PATH)
    else:
        print("YouTube Plugin JAR not found, skipping configuration check.")


    return True # Setup overall successful, even if config needs manual edits


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

    # Proceed with download/setup
    if not setup_lavalink():
        sys.exit("Lavalink setup failed. Please check errors above.")

    print("-" * 30)
    print(f"Attempting to start Lavalink v{LAVALINK_VERSION} with YouTube Plugin v{PLUGIN_VERSION} (if present)...")
    print(f"Using JAR: {JAR_PATH}")
    print(f"Using Config: {CONFIG_PATH}")
    if os.path.exists(PLUGIN_JAR_PATH):
        print(f"Using Plugin: {PLUGIN_JAR_PATH}")
    print("-" * 30)

    # --- Start Lavalink with Debug Flags ---
    java_command = [
        "java",
        # Add logging level arguments BEFORE -jar
        "-Dlogging.level.lavalink=DEBUG", # General Lavalink Debug
        "-Dlogging.level.com.sedmelluq.discord.lavaplayer=DEBUG", # Lavaplayer Debug
        "-Dlogging.level.plugin.youtube=DEBUG", # YouTube Plugin Debug (adjust logger name if needed)
        "-jar",
        JAR_NAME # Relative path works because we set cwd
    ]

    try:
        process = subprocess.run(
            java_command,
            cwd=LAVALINK_DIR, # Run java from within the lavalink directory
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