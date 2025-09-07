import asyncio
import os
import subprocess
import json
import base64
import websockets
from dotenv import load_dotenv
import time
import logging
import sys

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Configuration Loading ---
def load_config(jwt_from_arg: str):
    """Loads and validates configuration from the .env file and a passed JWT."""
    logging.info("--- WellnessHub Local Agent (WebSocket Version) ---")
    
    load_dotenv()
    
    url = os.environ.get("SUPABASE_URL")
    anon_key = os.environ.get("SUPABASE_ANON_KEY")
    
    # Use the JWT passed as a command-line argument
    jwt = jwt_from_arg

    if not all([url, anon_key, jwt]):
        logging.critical("❌ FATAL ERROR: SUPABASE_URL, SUPABASE_ANON_KEY, and a valid JWT must all be provided.")
        return None, None, None

    try:
        # Decode the JWT to get the user ID
        # The payload is the second part of the JWT
        payload_b64 = jwt.split('.')[1]
        # Pad the base64 string to a multiple of 4 if necessary
        decoded_payload = base64.b64decode(payload_b64 + "==").decode('utf-8')
        user_id = json.loads(decoded_payload).get('sub')
        if not user_id: raise ValueError("User ID ('sub' claim) not found in JWT.")
        
        # Construct the WebSocket URL
        ws_url = url.replace('http', 'ws').replace('https', 'wss')
        realtime_url = f"{ws_url}/realtime/v1/websocket?apikey={anon_key}&vsn=1.0.0"
        
        logging.info(f"✅ Configuration loaded for user: {user_id}")
        return realtime_url, user_id, jwt
    except Exception as e:
        logging.critical(f"❌ FATAL ERROR: Invalid configuration. Details: {e}")
        return None, None, None

# --- Action Functions ---
def change_wallpaper(image_path: str):
    logging.info(f"🖼️  Changing wallpaper to: {image_path}")
    try:
        # Check if the file exists before attempting to change
        if not os.path.exists(image_path):
            logging.error(f"    ❌ ERROR: Wallpaper image not found at: {image_path}")
            return

        # Ensure xfconf-query is installed and available
        subprocess.run(["xfconf-query", "-c", "xfce4-desktop", "-p", "/backdrop/screen0/monitor0/workspace0/last-image", "-s", image_path], check=True, capture_output=True, text=True)
        logging.info("    ✅ Wallpaper changed successfully.")
    except FileNotFoundError:
        logging.error("    ❌ ERROR: 'xfconf-query' not found. Is XFCE desktop environment installed and configured correctly?")
    except subprocess.CalledProcessError as e:
        logging.error(f"    ❌ ERROR changing wallpaper: {e.stderr}")
    except Exception as e:
        logging.error(f"    ❌ An unexpected ERROR occurred while changing wallpaper: {e}")

def play_music(file_path: str):
    logging.info(f"🎵  Playing music file: {file_path}")
    try:
        if not os.path.exists(file_path):
            logging.error(f"    ❌ ERROR: Music file not found at: {file_path}")
            return

        # Use MOC (Music On Console)
        # -S: stop the current player; -c: clear the playlist; -a: add file; -p: play
        subprocess.run(["mocp", "-S"], check=False, capture_output=True) # Don't check=True as it may fail if mocp is not running
        subprocess.run(["mocp", "-c", "-a", file_path, "-p"], check=True, capture_output=True)
        logging.info("    ✅ Music started successfully.")
    except FileNotFoundError:
        logging.error("    ❌ ERROR: 'mocp' not found. Please install MOCP for music playback.")
    except subprocess.CalledProcessError as e:
        logging.error(f"    ❌ ERROR controlling MOC: {e.stderr}")
    except Exception as e:
        logging.error(f"    ❌ An unexpected ERROR occurred while playing music: {e}")

def speak_message(message: str):
    logging.info(f"🗣️  Saying: '{message}'")
    try:
        # Use espeak
        subprocess.run(["espeak", f'{message}'], check=True, capture_output=True)
        logging.info("    ✅ Message spoken successfully.")
    except FileNotFoundError:
        logging.error("    ❌ ERROR: 'espeak' not found. Please install espeak for text-to-speech.")
    except subprocess.CalledProcessError as e:
        logging.error(f"    ❌ ERROR with espeak: {e.stderr}")
    except Exception as e:
        logging.error(f"    ❌ An unexpected ERROR occurred while speaking: {e}")

# --- WebSocket Message Handling ---
ACTION_MAP = {"change_wallpaper": change_wallpaper, "play_music": play_music, "speak": speak_message}

def handle_message(message_str):
    """Parses incoming WebSocket messages from Supabase and triggers actions."""
    try:
        message = json.loads(message_str)
        
        # Acknowledge successful subscription
        if message.get("event") == "phx_reply" and message.get("payload", {}).get("status") == "ok":
            logging.info("✅ Successfully subscribed to Realtime channel.")
            return

        # Process a new command
        if (message.get("event") == "postgres_changes" and 
            message.get("payload", {}).get("data", {}).get("table") == "commands"):
            
            record = message.get("payload", {}).get("data", {}).get("record", {})
            action_name = record.get("action")
            payload_value = record.get("payload")

            if action_name in ACTION_MAP:
                logging.info("\n--- New Command Received ---")
                ACTION_MAP[action_name](payload_value)
                logging.info("--- Command Processed ---\n")
    except json.JSONDecodeError:
        logging.warning(f"Received malformed JSON message: {message_str}")
    except Exception as e:
        logging.error(f"An error occurred while handling a message: {e}")

# --- Main Connection Loop ---
async def listen_to_supabase(ws_url, user_id, jwt):
    """Connects to Supabase Realtime and handles the subscription and heartbeat loop."""
    # The topic must be dynamic to match the user
    topic = f"realtime:public:commands:user_id=eq.{user_id}"
    ref_counter = 1
    
    while True:
        try:
            async with websockets.connect(ws_url) as websocket:
                logging.info("✅ WebSocket connected to Supabase.")
                
                # Subscription message
                subscribe_msg = json.dumps({
                    "topic": topic, "event": "phx_join",
                    "payload": {
                        "config": {"postgres_changes": [{"event": "INSERT", "schema": "public", "table": "commands"}]},
                        "access_token": jwt
                    },
                    "ref": str(ref_counter)
                })
                await websocket.send(subscribe_msg)
                ref_counter += 1
                last_heartbeat = time.time()

                while True:
                    # Send heartbeats to keep the connection alive
                    if time.time() - last_heartbeat > 25:
                        heartbeat_msg = json.dumps({"topic": "phoenix", "event": "heartbeat", "payload": {}, "ref": str(ref_counter)})
                        await websocket.send(heartbeat_msg)
                        ref_counter += 1
                        last_heartbeat = time.time()
                    
                    try:
                        # Wait for a message with a timeout
                        message = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                        handle_message(message)
                    except asyncio.TimeoutError:
                        # Timeout is normal, loop to check for heartbeat
                        continue
        
        except Exception as e:
            logging.warning(f"Connection lost: {e}. Reconnecting in 5 seconds...")
            
        await asyncio.sleep(5)

async def main():
    # Check if a JWT was provided as a command-line argument
    if len(sys.argv) > 1:
        jwt_from_arg = sys.argv[1]
    else:
        logging.critical("❌ FATAL ERROR: JWT not provided. Usage: python local_agent.py <your_jwt_token>")
        return

    realtime_url, user_id, jwt = load_config(jwt_from_arg)
    if not realtime_url:
        return
    await listen_to_supabase(realtime_url, user_id, jwt)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nAgent stopped by user. Goodbye!")