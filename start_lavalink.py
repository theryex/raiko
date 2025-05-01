import os
import sys
import subprocess
import urllib.request
import platform

def download_lavalink():
    lavalink_url = "https://github.com/lavalink-devs/Lavalink/releases/download/3.7.11/Lavalink.jar"
    jar_path = os.path.join("lavalink", "Lavalink.jar")
    
    if not os.path.exists("lavalink"):
        os.makedirs("lavalink")
    
    if not os.path.exists(jar_path):
        print("Downloading Lavalink.jar...")
        urllib.request.urlretrieve(lavalink_url, jar_path)
        print("Download complete!")

def check_java():
    try:
        subprocess.run(["java", "-version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def start_lavalink():
    if not check_java():
        print("Java is not installed or not in PATH. Please install Java 11 or higher.")
        sys.exit(1)
    
    download_lavalink()
    
    jar_path = os.path.join("lavalink", "Lavalink.jar")
    config_path = os.path.join("lavalink", "application.yml")
    
    print("Starting Lavalink server...")
    subprocess.run(["java", "-jar", jar_path, "--spring.config.location=" + config_path])

if __name__ == "__main__":
    start_lavalink() 