import os
import subprocess
import time

LAVALINK_DIR = "lavalink"
CONFIG_NAME = "application.yml"
CONFIG_PATH = os.path.join(LAVALINK_DIR, CONFIG_NAME)
JAR_NAME = "Lavalink.jar" # Assuming the jar is named Lavalink.jar and in the same directory as the script
JAR_PATH = os.path.join(LAVALINK_DIR, JAR_NAME)

# Function to find java executable
def find_java():
    java_home = os.environ.get('JAVA_HOME')
    if java_home:
        return os.path.join(java_home, 'bin', 'java')
    return 'java'

def start_lavalink():
    java_executable = find_java()

    # Ensure the config file exists
    if not os.path.exists(CONFIG_PATH):
        print(f"Error: Configuration file not found at {CONFIG_PATH}")
        # Attempt to copy from example if it exists
        example_config_path = os.path.join(LAVALINK_DIR, "example.application.yml")
        if os.path.exists(example_config_path):
            try:
                import shutil
                shutil.copy(example_config_path, CONFIG_PATH)
                print(f"Copied example configuration to {CONFIG_PATH}")
            except Exception as e:
                print(f"Could not copy example configuration: {e}")
                return None
        else:
            print("No example configuration found to copy.")
            return None
    
    # Ensure the Lavalink.jar exists
    if not os.path.exists(JAR_PATH):
        print(f"Error: Lavalink.jar not found at {JAR_PATH}")
        print("Please download Lavalink.jar and place it in the 'lavalink' directory.")
        print("You can download it from: https://ci.fredboat.com/repository/download/Lavalink_Build/latest.lastSuccessful/Lavalink.jar?guest=1")
        return None

    java_command = [
        java_executable,
        f"-Dspring.config.location=file:{os.path.abspath(CONFIG_PATH)}", # Use absolute path with file: prefix
        # Add other JVM options if needed, e.g., memory allocation
        # "-Xmx1G", 
        # "-Xms1G",
        "-Djava.net.preferIPv4Stack=true", # Optional: some networks might need this
        "-jar",
        JAR_PATH
    ]

    print(f"Starting Lavalink with command: {' '.join(java_command)}")

    try:
        # Start Lavalink as a subprocess
        # Use Popen for non-blocking execution if you want to run other things in Python
        # For a simple startup script, call can be fine if it blocks until Lavalink is manually stopped.
        process = subprocess.Popen(java_command, cwd=LAVALINK_DIR)
        print(f"Lavalink started with PID: {process.pid}")
        return process
    except FileNotFoundError:
        print(f"Error: Java executable not found at '{java_executable}'. Please ensure Java is installed and in your PATH or JAVA_HOME is set.")
        return None
    except Exception as e:
        print(f"An error occurred while starting Lavalink: {e}")
        return None

if __name__ == "__main__":
    lavalink_process = start_lavalink()

    if lavalink_process:
        try:
            # Keep the script running, or Lavalink will stop if it's a child process
            # and not detached.
            while True:
                time.sleep(60) # Keep main thread alive
        except KeyboardInterrupt:
            print("Stopping Lavalink...")
            lavalink_process.terminate() # Send SIGTERM
            try:
                lavalink_process.wait(timeout=10) # Wait for Lavalink to shut down
            except subprocess.TimeoutExpired:
                print("Lavalink did not terminate gracefully, killing...")
                lavalink_process.kill() # Send SIGKILL
            print("Lavalink stopped.")
    else:
        print("Lavalink could not be started.")
