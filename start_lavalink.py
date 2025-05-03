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
        # Use '--version' for modern Java, redirect stderr to stdout for compatibility
        result = subprocess.run(
            ["java", "--version"],
            capture_output=True, text=True, check=False, stderr=subprocess.STDOUT
        )
        # If '--version' failed, try '-version' (older Java)
        if result.returncode != 0 or "Runtime Environment" not in result.stdout:
             result_old = subprocess.run(
                 ["java", "-version"],
                 capture_output=True, text=True, check=False, stderr=subprocess.STDOUT
             )
             # Prioritize output from '-version' if '--version' seemed invalid or failed differently
             if result_old.returncode == 0 and "Runtime Environment" in result_old.stdout:
                 result = result_old
             # Handle command not found specifically
             elif 'not found' in result.stdout.lower() or 'not recognized' in result.stdout.lower():
                 raise FileNotFoundError("Java command not found")
             # If both failed non-specifically, raise based on the first attempt
             elif result.returncode != 0:
                  raise subprocess.CalledProcessError(result.returncode, result.args, output=result.stdout)

        output = result.stdout # Output is now consistently in stdout
        # Regex to find version numbers like 21.0.6 or 17.0.1 or 1.8.0_301
        match = re.search(r'(?:version|openjdk)\s+"?(\d+)(?:\.(\d+))?(?:\.(\d+))?(_\d+)?.*"?', output, re.IGNORECASE)

        if match:
            major = int(match.group(1))
            # Handle Java 8 format "1.8.0"
            if major == 1 and match.group(2):
                major = int(match.group(2))

            print(f"Detected Java major version: {major}")
            return major, output
        else:
            print("Could not parse Java version string.")
            full_output = f"--- Combined Output ---\n{output}"
            return None, full_output

    except FileNotFoundError:
        print("Error: 'java' command not found. Is Java installed and in your PATH?")
        return None, "Java command not found."
    except subprocess.CalledProcessError as e:
        print(f"Error running Java version check (Return Code: {e.returncode}):")
        full_output = f"--- Combined Output ---\n{e.output or '[No Output]'}"
        print(full_output)
        return None, full_output
    except Exception as e:
        print(f"An unexpected error occurred while checking Java version: {e}")
        try: err_output = result.stdout if 'result' in locals() and hasattr(result, 'stdout') else str(e)
        except: err_output = str(e)
        return None, err_output

def check_plugin_config(config_file_path):
    """Checks if application.yml seems configured correctly for YouTube and Spotify plugins."""
    if not os.path.exists(config_file_path):
        print(f"Warning: Config file '{config_file_path}' not found for checking plugin settings.")
        return False # Cannot check

    print(f"Checking '{config_file_path}' for common plugin configuration issues...")
    config_ok = True
    warnings = []

    try:
        with open(config_file_path, 'r', encoding='utf-8') as f: # Specify encoding
            content = f.read()

        # --- Check YouTube Plugin Settings ---
        youtube_plugin_present = os.path.exists(PLUGIN_JAR_PATH)
        if youtube_plugin_present:
            # 1. Check if built-in YT source is disabled
            built_in_yt_enabled = re.search(r"^\s*youtube:\s*true", content, re.MULTILINE | re.IGNORECASE) is not None
            # Handle more complex nested structure
            built_in_yt_nested_enabled = re.search(r"lavalink:\s*\n.*?\s+server:\s*\n.*?\s+sources:\s*\n.*?\s+youtube:\s*true", content, re.DOTALL | re.IGNORECASE) is not None
            if built_in_yt_enabled or built_in_yt_nested_enabled:
                config_ok = False
                warnings.append(textwrap.dedent("""
                    Built-in YouTube source MUST be disabled when using the YouTube plugin.
                    Please ensure 'lavalink.server.sources.youtube' is set to 'false'.
                    Example:
                      lavalink:
                        server:
                          sources:
                            youtube: false
                """))

            # 2. Check if 'plugins:' block exists and has 'youtube:' entry
            plugins_block = re.search(r"^\s*plugins:", content, re.MULTILINE)
            youtube_plugin_entry = re.search(r"^\s*plugins:\s*\n.*?\s+youtube:", content, re.DOTALL | re.IGNORECASE)
            if not plugins_block or not youtube_plugin_entry:
                 config_ok = False
                 warnings.append(textwrap.dedent("""
                    YouTube plugin block seems missing or incorrectly placed under 'plugins:'.
                    Please ensure a root-level 'plugins:' block exists with a 'youtube:' entry.
                    Example:
                      plugins:
                        youtube:
                          enabled: true # Optional, defaults to true if block exists
                 """))

        # --- Check Spotify Plugin (LavaSrc) Settings ---
        spotify_plugin_present = os.path.exists(SPOTIFY_PLUGIN_JAR_PATH)
        if spotify_plugin_present:
            # 1. Check if 'plugins:' block exists and has 'lavasrc:' entry
            plugins_block = re.search(r"^\s*plugins:", content, re.MULTILINE)
            lavasrc_plugin_entry = re.search(r"^\s*plugins:\s*\n.*?\s+lavasrc:", content, re.DOTALL | re.IGNORECASE)
            if not plugins_block or not lavasrc_plugin_entry:
                 config_ok = False
                 warnings.append(textwrap.dedent("""
                    LavaSrc plugin block seems missing or incorrectly placed under 'plugins:'.
                    Please ensure a root-level 'plugins:' block exists with a 'lavasrc:' entry.
                    Example:
                      plugins:
                        lavasrc:
                          providers:
                            spotify:
                              clientId: ${SPOTIFY_CLIENT_ID}
                              clientSecret: ${SPOTIFY_CLIENT_SECRET}
                 """))
            # 2. Check for the environment variable placeholders (doesn't validate the vars themselves)
            spotify_client_id_placeholder = re.search(r"clientId:\s*\$\{SPOTIFY_CLIENT_ID\}", content)
            spotify_client_secret_placeholder = re.search(r"clientSecret:\s*\$\{SPOTIFY_CLIENT_SECRET\}", content)
            if lavasrc_plugin_entry and (not spotify_client_id_placeholder or not spotify_client_secret_placeholder):
                 config_ok = False # Technically might work if hardcoded, but recommend env vars
                 warnings.append(textwrap.dedent("""
                    LavaSrc Spotify configuration should use environment variables.
                    Please ensure 'clientId' and 'clientSecret' under 'lavasrc.providers.spotify'
                    are set like this:
                      clientId: ${SPOTIFY_CLIENT_ID}
                      clientSecret: ${SPOTIFY_CLIENT_SECRET}
                    (Ensure these variables are set in your .env file)
                 """))

        # --- Final Output ---
        if not config_ok:
            print("\n" + "="*60)
            print("WARNING: Potential configuration issues found!")
            print(f"Please review '{config_file_path}' based on the following:")
            for warning in warnings:
                print("-" * 20)
                print(warning)
            print("="*60 + "\n")
            return False
        else:
            print("Basic plugin configuration appears present (manual verification recommended).")
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
             # Don't mark as files_downloaded if only optional plugin failed
        else:
             files_downloaded = True # Mark if essential plugin downloaded
    else:
        print(f"YouTube Plugin JAR ({PLUGIN_JAR_NAME}) already exists.")

    # --- Setup Spotify Plugin (Lavasrc) ---
    if not os.path.exists(SPOTIFY_PLUGIN_JAR_PATH):
        print(f"Spotify Plugin JAR ({SPOTIFY_PLUGIN_JAR_NAME}) not found.")
        if not download_file(SPOTIFY_PLUGIN_URL, SPOTIFY_PLUGIN_JAR_PATH, f"Spotify Plugin (Lavasrc) v{SPOTIFY_PLUGIN_VERSION} JAR"):
             print("Warning: Failed to download Spotify plugin. Spotify functionality will be unavailable.")
             # Don't mark as files_downloaded if only optional plugin failed
        else:
             files_downloaded = True # Mark if essential plugin downloaded
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
        # else:
             # Config check happens later before launch anyway
             # check_plugin_config(CONFIG_PATH)
    elif not os.path.exists(CONFIG_PATH):
         print(f"Warning: Config file '{CONFIG_PATH}' not found, and no plugins downloaded.")
         print("Lavalink will start with default settings and limited sources.")
    else:
        print("No plugin JARs found in the plugins directory. Functionality may be limited.")
        # Check if config *disables* built-in YT unnecessarily if no plugin exists
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                content = f.read()
            if re.search(r"lavalink:\s*\n.*?\s+server:\s*\n.*?\s+sources:\s*\n.*?\s+youtube:\s*false", content, re.DOTALL | re.IGNORECASE):
                print("\nWARNING: Built-in YouTube source is disabled in config, but no YouTube plugin JAR was found!")
                print("YouTube playback will likely fail. Either remove the plugin JAR or enable the built-in source.\n")
        except Exception: pass # Ignore errors reading config here

    return True

def start_lavalink():
    """Checks Java, sets up Lavalink files, loads .env, and starts the server."""
    java_major_version, java_version_output = check_java_version()

    if java_major_version is None:
        print("-" * 30); print("Java Version Check Output:"); print(java_version_output); print("-" * 30)
        sys.exit(f"Failed to determine Java version. Lavalink v{LAVALINK_VERSION.split('.')[0]} requires Java {REQUIRED_JAVA_VERSION} or higher.")

    if java_major_version < REQUIRED_JAVA_VERSION:
        print("-" * 30); print("Java Version Check Output:"); print(java_version_output); print("-" * 30)
        sys.exit(f"Error: Incompatible Java version detected (Version {java_major_version}). Lavalink v{LAVALINK_VERSION.split('.')[0]} requires Java {REQUIRED_JAVA_VERSION} or higher.")
    else:
        print(f"Java version {java_major_version} is compatible (Required: {REQUIRED_JAVA_VERSION}+).")

    # Perform file setup (downloads etc)
    if not setup_lavalink():
        sys.exit("Lavalink setup failed. Please check errors above.")

    # Check config validity *after* setup potentially created/modified it
    if os.path.exists(CONFIG_PATH) and not check_plugin_config(CONFIG_PATH):
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
            if not os.getenv("SPOTIFY_CLIENT_ID") or not os.getenv("SPOTIFY_CLIENT_SECRET"):
                print("WARNING: SPOTIFY_CLIENT_ID or SPOTIFY_CLIENT_SECRET not found in loaded environment variables!")
                print("         Lavalink Spotify plugin (LavaSrc) will likely fail.")
            # else:
            #     print("Spotify credentials found in environment.") # Less verbose
        else:
            print("Warning: .env file found but python-dotenv failed to load it.")
    else:
        print("Warning: .env file not found. Lavalink might miss required environment variables (e.g., Spotify keys).")
        print("         Ensure .env is in the same directory as this script or specify path.")
        # Exit if Spotify plugin exists but keys aren't loaded? Maybe too strict.
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
    # Note: Environment variables loaded above by load_dotenv() will be
    # automatically inherited by the subprocess started by Popen/run.
    # No need to manually set os.environ here again.

    java_command = [
        "java",
        # --- Optional JVM / Logging Arguments ---
        # Memory limits (adjust as needed)
        # "-Xms512m",
        # "-Xmx1024m",
        # Force IPv4 if experiencing network issues
        # "-Djava.net.preferIPv4Stack=true",
        # Lavalink/Plugin Debug Logging (Uncomment specific lines if needed)
        # "-Dlogging.level.root=DEBUG", # Very verbose
        "-Dlogging.level.lavalink=INFO", # Lavalink core logs
        "-Dlogging.level.lavalink.server=INFO",
        # "-Dlogging.level.com.sedmelluq.discord.lavaplayer=DEBUG", # Lavaplayer core
        "-Dlogging.level.dev.lavalink.youtube=INFO", # YouTube plugin logs (use DEBUG for more detail)
        "-Dlogging.level.dev.kaan.lavasrc=INFO",     # LavaSrc plugin logs (use DEBUG for more detail)
        # --- Main Arguments ---
        "-jar",
        JAR_PATH  # Use the variable holding the path
        # Optional: Explicitly point to config if needed, but Lavalink usually finds it
        # f"--spring.config.location=file:{CONFIG_PATH}"
    ]

    # --- Start Lavalink Process ---
    print(f"Executing command: {' '.join(java_command)}") # Show the command being run
    process = None # Initialize process variable
    try:
        # Use Popen to run in background and stream output
        process = subprocess.Popen(
            java_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, # Redirect stderr to stdout
            universal_newlines=True,  # Decode output as text
            bufsize=1                 # Line buffered
        )

        # Print output in real-time
        if process.stdout:
            for line in iter(process.stdout.readline, ''):
                if line: # Avoid printing empty lines if process closes stream
                    print(line, end='', flush=True) # Print immediately
        else:
             print("Warning: Could not attach to Lavalink process stdout.")

        # Wait for process to complete (normally it runs until stopped)
        process.wait()
        print("-" * 30)
        print(f"Lavalink process finished unexpectedly with exit code: {process.returncode}")

    except KeyboardInterrupt:
        print("\nStopping Lavalink (Ctrl+C received)...")
        if process and process.poll() is None: # Check if process exists and is running
             # Give it a chance to shut down gracefully
             process.terminate()
             try:
                 process.wait(timeout=5) # Wait up to 5 seconds
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
