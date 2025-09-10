import subprocess
import time
import logging
import os

COMMAND_FILE = "/tmp/media_player.command"
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def play_music(file_path: str):
    if not os.path.exists(file_path):
        logging.warning(f"❌ ERROR: Music file not found at: {file_path}")
        return

    logging.info(f"🎵 Received command to play: {file_path}")
    try:
        subprocess.run(["killall", "vlc"], check=False)
        time.sleep(0.5)
        subprocess.Popen(["vlc", file_path])
        logging.info("✅ SUCCESS: VLC launched.")
    except Exception as e:
        logging.error(f"❌ ERROR: Failed to launch VLC: {e}")

if __name__ == "__main__":
    logging.info("Desktop agent started. Watching for commands...")
    last_command_time = 0
    if os.path.exists(COMMAND_FILE):
        last_command_time = os.path.getmtime(COMMAND_FILE)

    while True:
        if os.path.exists(COMMAND_FILE):
            current_mod_time = os.path.getmtime(COMMAND_FILE)
            if current_mod_time > last_command_time:
                with open(COMMAND_FILE, 'r') as f:
                    command = f.read().strip()
                if command:
                    play_music(command)
                last_command_time = current_mod_time
        time.sleep(2) # Check every 2 seconds