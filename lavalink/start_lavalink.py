import os
import sys
import subprocess
import urllib.request
import urllib.error
import platform
import re
import shutil
import textwrap
from dotenv import load_dotenv # Keep this if you were using it, though not strictly necessary for Lavalink launch itself unless passing env vars to Java

# Configuration
LAVALINK_VERSION = "4.0.8"

V4_YOUTUBE_PLUGIN_NAME = "youtube-source"
V4_YOUTUBE_PLUGIN_VERSION = "1.4.0" # Using a known version, check for latest if issues
V4_YOUTUBE_PLUGIN_JAR_NAME = f"{V4_YOUTUBE_PLUGIN_NAME}-{V4_YOUTUBE_PLUGIN_VERSION}.jar"
V4_YOUTUBE_PLUGIN_URL = f"https://github.com/lavalink-devs/youtube-source/releases/download/{V4_YOUTUBE_PLUGIN_VERSION}/{V4_YOUTUBE_PLUGIN_JAR_NAME}"

SPOTIFY_PLUGIN_NAME = "lavasrc-plugin"
SPOTIFY_PLUGIN_VERSION = "4.0.0" # Ensure this is compatible with Lavalink v4.0.8
SPOTIFY_PLUGIN_JAR_NAME = f"LavaSrc-{SPOTIFY_PLUGIN_VERSION}.jar"
SPOTIFY_PLUGIN_URL = f"https://github.com/topi314/LavaSrc/releases/download/{SPOTIFY_PLUGIN_VERSION}/LavaSrc-{SPOTIFY_PLUGIN_VERSION}.jar"

LAVALINK_DIR = "lavalink" # Relative to project root where this script is run
JAR_NAME = "Lavalink.jar"
CONFIG_NAME = "application.yml"
# For Lavalink v4, the example is often named application.yml.example or just application.yml in the repo
EXAMPLE_CONFIG_NAME = "application.yml" # Or application.yml.example if that's what the source repo uses
PLUGINS_DIR = os.path.join(LAVALINK_DIR, "plugins")

JAR_PATH = os.path.join(LAVALINK_DIR, JAR_NAME)
CONFIG_PATH = os.path.join(LAVALINK_DIR, CONFIG_NAME) # This should be lavalink/application.yml
V4_YOUTUBE_PLUGIN_JAR_PATH = os.path.join(PLUGINS_DIR, V4_YOUTUBE_PLUGIN_JAR_NAME)
SPOTIFY_PLUGIN_JAR_PATH = os.path.join(PLUGINS_DIR, SPOTIFY_PLUGIN_JAR_NAME)

def get_lavalink_server_urls(version):
    base_url = f"https://github.com/lavalink-devs/Lavalink/releases/download/{version}/"
    jar_url = base_url + JAR_NAME
    # Correct path for application.yml in Lavalink v4 repo (usually in LavalinkServer module)
    config_url = f"https://raw.githubusercontent.com/lavalink-devs/Lavalink/{version}/LavalinkServer/application.yml.example"
    return jar_url, config_url

def download_file_with_progress(url, destination_path, description):
    try:
        print(f"Downloading {description} from {url} to {destination_path}...")
        os.makedirs(os.path.dirname(destination_path), exist_ok=True)
        
        headers = {'User-Agent': 'Lavalink-Setup-Script/1.0'}
        req = urllib.request.Request(url, headers=headers)
        
        with urllib.request.urlopen(req) as response, open(destination_path, 'wb') as out_file:
            if response.status != 200:
                print(f"Error: Failed to download {description}. HTTP Status: {response.status}")
                if os.path.exists(destination_path): os.remove(destination_path)
                return False
            
            total_length = response.getheader('content-length')
            if total_length:
                total_length = int(total_length)
                bytes_so_far = 0
                
            shutil.copyfileobj(response, out_file) # Simpler copy, progress bar removed for brevity here
        print(f"Successfully downloaded {description}.")
        return True
    except urllib.error.HTTPError as e:
        print(f"HTTPError when downloading {description}: {e.code} {e.reason}")
        if os.path.exists(destination_path): os.remove(destination_path)
        return False
    except Exception as e:
        print(f"An unexpected error occurred downloading {description}: {e}")
        if os.path.exists(destination_path): os.remove(destination_path)
        return False

def setup_lavalink_environment():
    print("Setting up Lavalink environment...")
    os.makedirs(LAVALINK_DIR, exist_ok=True)
    os.makedirs(PLUGINS_DIR, exist_ok=True)

    jar_url, config_example_url = get_lavalink_server_urls(LAVALINK_VERSION)
    downloaded_config_example_path = os.path.join(LAVALINK_DIR, "application.yml.example")

    if not os.path.exists(JAR_PATH):
        print(f"{JAR_NAME} not found. Downloading...")
        if not download_file_with_progress(jar_url, JAR_PATH, JAR_NAME):
            print(f"Critical: Failed to download {JAR_NAME}. Cannot start Lavalink.")
            return False
    else:
        print(f"{JAR_NAME} already exists. Skipping download.")

    if not os.path.exists(CONFIG_PATH):
        print(f"{CONFIG_NAME} not found at {CONFIG_PATH}. Downloading example...")
        if not download_file_with_progress(config_example_url, downloaded_config_example_path, "application.yml.example"):
            print(f"Warning: Failed to download application.yml.example. You may need to create {CONFIG_PATH} manually.")
        else:
            try:
                shutil.move(downloaded_config_example_path, CONFIG_PATH)
                print(f"Moved example configuration to {CONFIG_PATH}.")
                print(f"IMPORTANT: Please review and edit {CONFIG_PATH} with your settings (e.g., password).")
            except OSError as e:
                print(f"Error moving example config: {e}. Please do so manually.")
                return False
    else:
        print(f"{CONFIG_PATH} already exists. Using existing configuration.")
        print(f"IMPORTANT: Ensure {CONFIG_PATH} is correctly configured (especially password).")


    # Download plugins
    if not os.path.exists(V4_YOUTUBE_PLUGIN_JAR_PATH):
        download_file_with_progress(V4_YOUTUBE_PLUGIN_URL, V4_YOUTUBE_PLUGIN_JAR_PATH, V4_YOUTUBE_PLUGIN_JAR_NAME)
    else:
        print(f"{V4_YOUTUBE_PLUGIN_JAR_NAME} already exists. Skipping download.")

    if not os.path.exists(SPOTIFY_PLUGIN_JAR_PATH):
        download_file_with_progress(SPOTIFY_PLUGIN_URL, SPOTIFY_PLUGIN_JAR_PATH, SPOTIFY_PLUGIN_JAR_NAME)
    else:
        print(f"{SPOTIFY_PLUGIN_JAR_NAME} already exists. Skipping download.")
        
    return True

def find_java_executable():
    java_home = os.environ.get('JAVA_HOME')
    if java_home:
        return os.path.join(java_home, 'bin', 'java')
    # Check system PATH if JAVA_HOME is not set
    return 'java' 

def launch_lavalink_process():
    if not setup_lavalink_environment():
        sys.exit("Lavalink environment setup failed. Please check errors above.")

    # This script assumes it's being run from the project root,
    # so CONFIG_PATH = "lavalink/application.yml" should be correct.
    # os.path.abspath will make it absolute from the CWD of this script.
    abs_config_path = os.path.abspath(CONFIG_PATH)
    
    java_executable = find_java_executable()

    java_command = [
        java_executable,
        f"-Dspring.config.location={abs_config_path}",
        "-Djava.net.preferIPv4Stack=true", # Optional
        # Add other JVM options here if needed, e.g., memory limits
        # "-Xmx1G",
        "-jar",
        JAR_PATH # JAR_PATH is already lavalink/Lavalink.jar
    ]

    print(f"DEBUG: Attempting to run Java command: {' '.join(java_command)}")
    
    # For Lavalink, it's better to run it with its working directory set to where the JAR is,
    # as it might look for other resources relative to itself.
    # However, since we explicitly set spring.config.location, this might be less critical.
    # Let's try running with CWD as project root first, as `start_lavalink.py` is there.
    # If issues persist, changing CWD to LAVALINK_DIR for Popen might be a next step.
    
    try:
        process = subprocess.Popen(
            java_command,
            # cwd=LAVALINK_DIR, # Optional: run java process with lavalink/ as its CWD
            stdout=sys.stdout, # Pipe Lavalink's stdout to this script's stdout
            stderr=sys.stderr, # Pipe Lavalink's stderr to this script's stderr
        )
        print(f"Lavalink launched with PID: {process.pid} (from Python script PID: {os.getpid()})")
        process.wait() # Wait for Lavalink to exit (e.g., if user Ctrl+C's this script)
    except FileNotFoundError:
        print(f"Error: Java executable not found at '{java_executable}'. Please ensure Java is installed and in your PATH or JAVA_HOME is set.")
    except Exception as e:
        print(f"An error occurred while trying to start or monitor Lavalink: {e}")
    finally:
        print("Lavalink process has exited.")


if __name__ == "__main__":
    # Optional: Load .env for this script if it needs any variables,
    # but typically not for just launching Lavalink unless passing specific things to Java.
    # dotenv_path = os.path.join(os.path.dirname(__file__), '.env') # If .env is in same dir as script
    # load_dotenv(dotenv_path=dotenv_path, override=True)
    
    launch_lavalink_process()
