import asyncio
import os
import subprocess
import json
import base64
import websockets
from dotenv import load_dotenv
import logging
import sys

# --- Setup Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout,
)

# --- Configuration ---
load_dotenv()
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY")

# --- Action Functions (with Desktop Environment Detection) ---

def detect_desktop_env():
    """
    Detects the current desktop environment to use the correct command.
    """
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    if "kde" in desktop:
        return "kde"
    elif "xfce" in desktop:
        return "xfce"
    else:
        logging.warning(f"Unsupported desktop environment detected: {desktop}")
        return "unknown"

def change_wallpaper(image_path: str):
    """
    Changes the desktop wallpaper based on the detected environment (KDE or XFCE).
    """
    logging.info(f"🖼️  Changing wallpaper to: {image_path}")
    if not os.path.exists(image_path):
        logging.error(f"    ❌ ERROR: Wallpaper image not found at: {image_path}")
        return

    env = detect_desktop_env()
    logging.info(f"    Detected Desktop Environment: {env.upper()}")

    try:
        if env == "kde":
            kde_script = f"""
            var Desktops = desktops();
            for (i=0;i<Desktops.length;i++) {{
                d = Desktops[i];
                d.wallpaperPlugin = 'org.kde.image';
                d.currentConfigGroup = Array('Wallpaper', 'org.kde.image', 'General');
                d.writeConfig('Image', 'file://{image_path}');
            }}
            """
            subprocess.run(
                ["qdbus", "org.kde.plasmashell", "/PlasmaShell", "org.kde.PlasmaShell.evaluateScript", kde_script],
                check=True, capture_output=True, text=True
            )
            logging.info("    ✅ Wallpaper changed successfully for KDE Plasma.")

        elif env == "xfce":
            subprocess.run(
                ["xfconf-query", "-c", "xfce4-desktop", "-p", "/backdrop/screen0/monitor0/workspace0/last-image", "-s", image_path],
                check=True, capture_output=True, text=True
            )
            subprocess.run(["xfdesktop", "--reload"], check=False)
            logging.info("    ✅ Wallpaper changed successfully for XFCE.")

        else:
            logging.warning("    ⚠️ WARNING: Unknown or unsupported desktop environment. Wallpaper not changed.")

    except FileNotFoundError as e:
        logging.error(f"    ❌ ERROR: A required command was not found. Please ensure 'qdbus' (for KDE) or 'xfconf-query' (for XFCE) is installed. Details: {e}")
    except subprocess.CalledProcessError as e:
        logging.error(f"    ❌ ERROR: The wallpaper command failed. Details: {e.stderr.strip()}")
    except Exception as e:
        logging.error(f"    ❌ An unexpected ERROR occurred while changing wallpaper: {e}")

def play_music(file_path: str):
    """Plays a music file using VLC in command-line mode (no GUI)."""
    logging.info(f"🎵  Playing music file with VLC: {file_path}")
    if not os.path.exists(file_path):
        logging.error(f"    ❌ ERROR: Music file not found at: {file_path}")
        return
    try:
        subprocess.run(["killall", "vlc"], check=False, capture_output=True)
        subprocess.Popen(["cvlc", "--play-and-exit", file_path], 
                         stdout=subprocess.DEVNULL, 
                         stderr=subprocess.DEVNULL)
        logging.info("    ✅ Music started successfully with VLC.")
    except FileNotFoundError:
        logging.error("    ❌ ERROR: 'vlc' command not found. Please ensure VLC is installed ('sudo apt install vlc').")
    except Exception as e:
        logging.error(f"    ❌ An unexpected ERROR occurred while playing music with VLC: {e}")


def speak_message(message: str):
    """Speaks a message using the espeak text-to-speech engine."""
    logging.info(f"🗣️  Saying: '{message}'")
    try:
        subprocess.run(["espeak", message], check=True, capture_output=True)
        logging.info("    ✅ Message spoken successfully.")
    except FileNotFoundError:
        logging.error("    ❌ ERROR: 'espeak' not found. Please install espeak for text-to-speech.")
    except subprocess.CalledProcessError as e:
        logging.error(f"    ❌ ERROR with espeak: {e.stderr.strip()}")

# Maps action strings to functions
ACTION_MAP = {
    "change_wallpaper": change_wallpaper,
    "play_music": play_music,
    "speak_message": speak_message
}

def get_user_id_from_jwt(jwt: str) -> str | None:
    """Safely decodes a JWT to extract the user ID ('sub' claim)."""
    try:
        # The payload is the second part of the JWT, encoded in base64.
        payload_b64 = jwt.split('.')[1]
        # Python's base64 decoder requires padding.
        decoded_payload = base64.b64decode(payload_b64 + "==").decode('utf-8')
        user_id = json.loads(decoded_payload).get('sub')
        if not user_id:
            raise ValueError("User ID ('sub' claim) not found in JWT.")
        return user_id
    except Exception as e:
        logging.critical(f"❌ FATAL ERROR: Invalid JWT provided. Could not decode user ID. Details: {e}")
        return None

async def send_heartbeat(websocket):
    """Sends a heartbeat message every 30 seconds to keep the connection alive."""
    ref_counter = 1
    while True:
        try:
            heartbeat_msg = {
                "topic": "phoenix",
                "event": "heartbeat",
                "payload": {},
                "ref": str(ref_counter)
            }
            await websocket.send(json.dumps(heartbeat_msg))
            ref_counter += 1
            await asyncio.sleep(30)
        except websockets.exceptions.ConnectionClosed:
            logging.warning("Connection closed while sending heartbeat. Stopping heartbeat task.")
            break

async def listen_to_supabase(ws_url: str, user_jwt: str):
    """Connects to Supabase Realtime, subscribes to commands, and executes them."""
    ref_counter = 1
    
    while True:
        try:
            async with websockets.connect(ws_url) as websocket:
                logging.info("✅ WebSocket connected to Supabase Realtime.")
                
                # Subscribe to INSERT events on the public 'commands' table.
                # Supabase will use the access_token (JWT) to apply Row Level Security,
                # ensuring we only receive rows matching our user_id.
                subscribe_msg = {
                    "topic": "realtime:public:commands",
                    "event": "phx_join",
                    "payload": {
                        "config": {
                            "postgres_changes": [
                                {"event": "INSERT", "schema": "public", "table": "commands"}
                            ]
                        },
                        "access_token": user_jwt,
                    },
                    "ref": str(ref_counter),
                }
                
                await websocket.send(json.dumps(subscribe_msg))
                ref_counter += 1

                # Start the heartbeat as a concurrent background task.
                heartbeat_task = asyncio.create_task(send_heartbeat(websocket))

                # Main loop to listen for messages from the server.
                async for message_str in websocket:
                    message = json.loads(message_str)
                    
                    # Log successful subscription reply from Supabase.
                    if message.get("event") == "phx_reply" and message.get("payload", {}).get("status") == "ok":
                        logging.info("✅ Successfully subscribed to the 'commands' channel.")

                    # Check for a new database INSERT event.
                    if message.get("event") == "postgres_changes" and message["payload"]["type"] == "INSERT":
                        command = message["payload"]["data"]
                        action = command.get("action")
                        payload = command.get("payload")
                        
                        logging.info("\n--- New Command Received ---")
                        if action in ACTION_MAP:
                            ACTION_MAP[action](payload)
                        else:
                            logging.warning(f"  ❓ Unknown action received: '{action}'")
                        logging.info("--- Command Processed ---\n")

                # If the loop exits, ensure the heartbeat task is cancelled.
                heartbeat_task.cancel()

        except websockets.exceptions.ConnectionClosed as e:
            logging.warning(f"Connection closed: {e}. Reconnecting in 5 seconds...")
        except Exception as e:
            logging.error(f"An unexpected error occurred: {e}. Reconnecting in 5 seconds...")
        
        await asyncio.sleep(5)

def main():
    """Parses arguments, validates config, and starts the agent."""
    logging.info("--- WellnessHub Local Agent Initializing ---")
    
    # 1. Check for required environment variables.
    if not all([SUPABASE_URL, SUPABASE_ANON_KEY]):
        logging.critical("❌ FATAL ERROR: SUPABASE_URL and SUPABASE_ANON_KEY must be set in .env file.")
        return

    # 2. Check for the JWT from command-line arguments.
    if len(sys.argv) < 2:
        logging.critical("❌ FATAL ERROR: JWT not provided. Usage: python local_agent.py <your_jwt_token>")
        return
    user_jwt = sys.argv[1]

    # 3. Construct the WebSocket URL.
    # Note: Supabase URLs from the dashboard often start with 'https://'. We replace it with 'wss://'.
    ws_base_url = SUPABASE_URL.replace('http://', 'ws://').replace('https://', 'wss://')
    ws_url = f"{ws_base_url}/realtime/v1/websocket?apikey={SUPABASE_ANON_KEY}&vsn=1.0.0"

    # 4. Start the main asyncio event loop.
    try:
        asyncio.run(listen_to_supabase(ws_url, user_jwt))
    except KeyboardInterrupt:
        logging.info("\nAgent stopped by user. Goodbye!")

if __name__ == "__main__":
    main()