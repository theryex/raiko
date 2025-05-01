import os
import sys
import subprocess
import urllib.request
import urllib.error
import platform
import re
import shutil

# --- Configuration ---
# Check the Lavalink releases page for the latest stable v4 version:
# https://github.com/lavalink-devs/Lavalink/releases
LAVALINK_VERSION = "4.0.8"  # <--- Update this to the desired Lavalink v4 version
REQUIRED_JAVA_VERSION = 17 # Lavalink v4 requires Java 17 or higher
# --- End Configuration ---

LAVALINK_DIR = "lavalink"
JAR_NAME = "Lavalink.jar"
CONFIG_NAME = "application.yml"
EXAMPLE_CONFIG_NAME = "application.yml.example" # Name of the example file on GitHub

JAR_PATH = os.path.join(LAVALINK_DIR, JAR_NAME)
CONFIG_PATH = os.path.join(LAVALINK_DIR, CONFIG_NAME)

def get_lavalink_urls(version):
    """Gets the download URLs for the JAR and example config for a specific version."""
    base_url = f"https://github.com/lavalink-devs/Lavalink/releases/download/{version}/"
    jar_url = base_url + JAR_NAME
    # Example config is usually in the source tree, not release assets directly
    config_url = f"https://raw.githubusercontent.com/lavalink-devs/Lavalink/{version}/LavalinkServer/{EXAMPLE_CONFIG_NAME}"
    return jar_url, config_url

def download_file(url, destination_path, description):
    """Downloads a file from a URL to a destination path."""
    print(f"Downloading {description} from {url}...")
    try:
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(destination_path), exist_ok=True)
        
        # Use shutil.copyfileobj for potentially large files
        with urllib.request.urlopen(url) as response, open(destination_path, 'wb') as out_file:
            if response.status == 200:
                shutil.copyfileobj(response, out_file)
                print(f"{description} download complete!")
                return True
            else:
                 print(f"Error downloading {description}: HTTP Status {response.status}")
                 return False
    except urllib.error.URLError as e:
        print(f"Error downloading {description}: {e}")
        # Clean up partially downloaded file if it exists
        if os.path.exists(destination_path):
            os.remove(destination_path)
        return False
    except Exception as e:
        print(f"An unexpected error occurred during download: {e}")
        if os.path.exists(destination_path):
            os.remove(destination_path)
        return False

def check_java_version():
    """Checks if a compatible Java version is installed and returns its major version."""
    print("Checking Java version...")
    try:
        # Running 'java -version' prints to stderr
        result = subprocess.run(["java", "-version"], capture_output=True, text=True, check=True, stderr=subprocess.PIPE)
        output = result.stderr # Version info is typically on stderr
        
        # Regex to find version string like "17.0.1" or "1.8.0_292"
        match = re.search(r'version "(\d+)(?:\.(\d+))?.*?"', output)
        if match:
            major = int(match.group(1))
            # Handle pre-Java 9 versions (e.g., "1.8")
            if major == 1:
                minor_match = re.search(r'version "1\.(\d+).*?"', output)
                if minor_match:
                     major = int(minor_match.group(1)) # Use the minor version as major (e.g., 8 for 1.8)
                else:
                    print("Could not parse Java minor version for pre-Java 9 format.")
                    return None, output # Return None and the output for debugging

            print(f"Detected Java major version: {major}")
            return major, output
        else:
            print("Could not parse Java version string from output.")
            return None, output # Return None and the output for debugging

    except FileNotFoundError:
        print("Error: 'java' command not found. Is Java installed and in your PATH?")
        return None, "Java command not found."
    except subprocess.CalledProcessError as e:
        print(f"Error running 'java -version': {e}")
        print("Output:", e.output)
        print("Stderr:", e.stderr)
        return None, e.stderr or e.output
    except Exception as e:
        print(f"An unexpected error occurred while checking Java version: {e}")
        return None, str(e)


def setup_lavalink():
    """Downloads Lavalink JAR and config if they don't exist."""
    jar_url, config_url = get_lavalink_urls(LAVALINK_VERSION)
    config_example_path = os.path.join(LAVALINK_DIR, EXAMPLE_CONFIG_NAME)

    # Download Lavalink.jar if needed
    if not os.path.exists(JAR_PATH):
        if not download_file(jar_url, JAR_PATH, f"Lavalink v{LAVALINK_VERSION} JAR"):
            return False # Exit setup if JAR download fails
    else:
        print(f"Lavalink JAR ({JAR_NAME}) already exists.")

    # Download application.yml.example if application.yml doesn't exist
    if not os.path.exists(CONFIG_PATH):
        print(f"{CONFIG_NAME} not found.")
        # Download the example file first
        if not download_file(config_url, config_example_path, "Lavalink example configuration"):
            print("Failed to download example configuration. Cannot create application.yml.")
            return False # Cannot proceed without config

        # Rename example to application.yml
        try:
            shutil.move(config_example_path, CONFIG_PATH)
            print(f"Renamed {EXAMPLE_CONFIG_NAME} to {CONFIG_NAME}.")
            print(f"IMPORTANT: Review and customize '{CONFIG_PATH}' if needed (e.g., password, port).")
        except OSError as e:
            print(f"Error renaming example config: {e}")
            return False
    else:
         print(f"Lavalink configuration ({CONFIG_NAME}) already exists.")

    return True # Setup successful


def start_lavalink():
    """Checks Java, sets up Lavalink files, and starts the server."""
    java_major_version, java_version_output = check_java_version()

    if java_major_version is None:
        print("-" * 30)
        print("Java Version Check Output:")
        print(java_version_output)
        print("-" * 30)
        sys.exit(f"Failed to determine Java version. Lavalink v{LAVALINK_VERSION.split('.')[0]} requires Java {REQUIRED_JAVA_VERSION} or higher.")

    if java_major_version < REQUIRED_JAVA_VERSION:
        print("-" * 30)
        print("Java Version Check Output:")
        print(java_version_output)
        print("-" * 30)
        sys.exit(f"Error: Incompatible Java version detected (Version {java_major_version}). Lavalink v{LAVALINK_VERSION.split('.')[0]} requires Java {REQUIRED_JAVA_VERSION} or higher.")
    else:
        print(f"Java version {java_major_version} is compatible (Required: {REQUIRED_JAVA_VERSION}+).")

    # Proceed with download/setup
    if not setup_lavalink():
        sys.exit("Lavalink setup failed. Please check errors above.")

    print("-" * 30)
    print(f"Attempting to start Lavalink v{LAVALINK_VERSION}...")
    print(f"Using JAR: {JAR_PATH}")
    print(f"Using Config: {CONFIG_PATH}")
    print("-" * 30)

    try:
        # Use subprocess.run which waits for completion, or Popen for background running
        # Using run here to keep the script attached to Lavalink's output
        process = subprocess.run(
            ["java", "-jar", JAR_PATH], # Spring Boot usually finds application.yml in the same dir automatically
            # If needed, explicitly specify config:
            # ["java", "-jar", JAR_PATH, f"--spring.config.location=file:{CONFIG_PATH}"],
            cwd=LAVALINK_DIR, # Run java from within the lavalink directory
            check=False # Don't throw error immediately, let user see Lavalink output/errors
        )
        print(f"Lavalink process finished with exit code: {process.returncode}")

    except KeyboardInterrupt:
        print("\nLavalink stopped by user.")
    except Exception as e:
        print(f"An error occurred while trying to run Lavalink: {e}")
        sys.exit("Failed to start Lavalink.")

if __name__ == "__main__":
    start_lavalink()