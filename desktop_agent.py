import subprocess
import time
import logging
import os

COMMAND_FILE = "/tmp/media_player.command"
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def play_media(path: str):
    """
    Plays a media file or all media within a directory using VLC.
    """
    if not os.path.exists(path):
        logging.warning(f"❌ ERROR: Media path not found at: {path}")
        return

    # Determine if the path is a file or a directory for logging purposes
    media_type = "folder" if os.path.isdir(path) else "file"
    logging.info(f"🎵 Received command to play {media_type}: {path}")

    try:
        # Stop any currently running VLC instance to start the new playlist
        subprocess.run(["killall", "vlc"], check=False, stderr=subprocess.DEVNULL)
        time.sleep(0.5)  # Give it a moment to close gracefully

        # VLC can open a directory directly and will play all media inside it
        subprocess.Popen(["vlc", path])
        logging.info(f"✅ SUCCESS: VLC launched to play media from {path}.")
    except FileNotFoundError:
        logging.error("❌ ERROR: 'vlc' command not found. Is VLC installed and in your PATH?")
    except Exception as e:
        logging.error(f"❌ ERROR: Failed to launch VLC: {e}")

if __name__ == "__main__":
    logging.info("Desktop agent started. Watching for commands...")
    last_command_time = 0
    # Initialize last_command_time if the file already exists on startup
    if os.path.exists(COMMAND_FILE):
        last_command_time = os.path.getmtime(COMMAND_FILE)

    while True:
        try:
            if os.path.exists(COMMAND_FILE):
                current_mod_time = os.path.getmtime(COMMAND_FILE)
                if current_mod_time > last_command_time:
                    with open(COMMAND_FILE, 'r') as f:
                        command_path = f.read().strip()
                    if command_path:
                        play_media(command_path)
                    last_command_time = current_mod_time
            time.sleep(2) # Check every 2 seconds
        except FileNotFoundError:
            # This can happen in a race condition if the file is deleted
            # between os.path.exists and os.path.getmtime. We can safely ignore it.
            time.sleep(2)
        except Exception as e:
            logging.error(f"An unexpected error occurred in the watch loop: {e}")
            time.sleep(5) # Wait a bit longer after an error