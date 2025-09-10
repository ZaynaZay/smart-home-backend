import os
import logging
import traceback
import base64
import cv2
import numpy as np
import tensorflow as tf
import keras
import subprocess
import time

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from deepface import DeepFace
from supabase import create_client, Client
from dotenv import load_dotenv

# --- Setup & Initialization ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
load_dotenv()
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# --- Supabase Clients ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
if not all([SUPABASE_URL, SUPABASE_SERVICE_KEY]):
    raise RuntimeError("Supabase URL and Service Key must be set in .env file.")
supabase_admin: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# --- Load Custom Model ---
MODEL_PATH = os.path.join(os.path.dirname(__file__), '..', 'emotion_model_savedmodel')
custom_model = None
try:
    if os.path.isdir(MODEL_PATH):
        custom_model = keras.layers.TFSMLayer(MODEL_PATH, call_endpoint='serving_default')
        logging.info("✅ Custom emotion model loaded successfully as TFSMLayer.")
    else:
        logging.error(f"❌ Custom model directory not found at: {MODEL_PATH}")
except Exception as e:
    logging.error(f"❌ Error loading custom model: {e}\n{traceback.format_exc()}")

EMOTION_LABELS = ['angry', 'disgust', 'fear', 'happy', 'neutral', 'sad', 'surprise']

# --- EMOTION → Music/Wallpaper Map ---
EMOTION_MAP = {
    "angry": {
        "music": "/home/Ares/Music/Energetic",
        "wallpaper": "/home/Ares/Pictures/Wallpapers/hopeful.jpg"
    },
    "disgust": {
        "music": "/home/Ares/Music/Energetic",
        "wallpaper": "/home/Ares/Pictures/Wallpapers/hopeful.jpg"
    },
    "fear": {
        "music": "/home/Ares/Music/Calm",
        "wallpaper": "/home/Ares/Pictures/Wallpapers/serene_blue.jpg"
    },
    "happy": {
        "music": "/home/Ares/Music/Uplifting",
        "wallpaper": "/home/Ares/Pictures/Wallpapers/hopeful.jpg"
    },
    "neutral": {
        "music": "/home/Ares/Music/Calm",
        "wallpaper": "/home/Ares/Pictures/Wallpapers/serene_blue.jpg"
    },
    "sad": {
        "music": "/home/Ares/Music/Calm",
        "wallpaper": "/home/Ares/Pictures/Wallpapers/serene_blue.jpg"
    },
    "surprise": {
        "music": "/home/Ares/Music/Uplifting",
        "wallpaper": "/home/Ares/Pictures/Wallpapers/hopeful.jpg"
    }
}


# --- Pydantic Model ---
class AnalyzeRequest(BaseModel):
    image: str  # Expecting a data URL string

# --- Helper Functions ---
def preprocess_image_for_custom_model(img_color):
    """
    Preprocesses the image for the custom emotion detection model.
    """
    if len(img_color.shape) == 2:
        gray_img = img_color
    else:
        gray_img = cv2.cvtColor(img_color, cv2.COLOR_BGR2GRAY)
    resized_img = cv2.resize(gray_img, (48, 48))
    normalized_img = resized_img / 255.0
    return np.expand_dims(np.expand_dims(normalized_img, axis=-1), axis=0)

def detect_desktop_env():
    """
    Detects the desktop environment.
    """
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    if "kde" in desktop:
        return "kde"
    elif "xfce" in desktop:
        return "xfce"
    else:
        return "unknown"

def change_wallpaper(file_path: str):
    """
    Changes wallpaper depending on desktop environment (KDE or XFCE).
    """
    if not os.path.exists(file_path):
        logging.warning(f"❌ ERROR: Wallpaper image not found at: {file_path}")
        return

    env = detect_desktop_env()
    logging.info(f"🖼️  Detected Desktop Environment: {env.upper()}")
    logging.info(f"🖼️  Changing wallpaper to: {file_path}")

    try:
        if env == "kde":
            # KDE Plasma wallpaper change
            script = f"""
var Desktops = desktops();
for (i=0;i<Desktops.length;i++) {{
    d = Desktops[i];
    d.wallpaperPlugin = 'org.kde.image';
    d.currentConfigGroup = Array('Wallpaper', 'org.kde.image', 'General');
    d.writeConfig('Image', 'file://{file_path}');
}}
"""
            subprocess.run([
                "qdbus",
                "org.kde.plasmashell",
                "/PlasmaShell",
                "org.kde.PlasmaShell.evaluateScript",
                script
            ], check=True, capture_output=True, text=True)
            logging.info("✅ SUCCESS: Wallpaper changed in KDE Plasma.")

        elif env == "xfce":
            command = [
                "xfconf-query",
                "-c", "xfce4-desktop",
                "-p", "/backdrop/screen0/monitor0/workspace0/last-image",
                "-s", file_path
            ]
            subprocess.run(command, check=True, capture_output=True, text=True)
            subprocess.run(["xfdesktop", "--reload"], check=False)
            logging.info("✅ SUCCESS: Wallpaper changed in XFCE.")

        else:
            logging.warning("⚠️ WARNING: Unknown desktop environment. Wallpaper not changed.")

    except FileNotFoundError as e:
        logging.error(f"❌ ERROR: Required command not found: {e}")
    except subprocess.CalledProcessError as e:
        logging.error(f"❌ ERROR: Wallpaper command failed. Details: {e.stderr}")
    except Exception as e:
        logging.error(f"❌ ERROR: Unexpected error: {e}")


def play_music(file_path: str):
    """
    Writes the music file path to a command file for the desktop agent to read.
    """
    COMMAND_FILE = "/tmp/media_player.command"
    logging.info(f"🎵 Sending command to play: {file_path}")
    try:
        with open(COMMAND_FILE, 'w') as f:
            f.write(file_path)
        logging.info("✅ SUCCESS: Command sent to desktop agent.")
    except Exception as e:
        logging.error(f"❌ ERROR: Could not write command file: {e}")

# --- Main API Endpoint ---
@app.post("/api/analyze")
async def analyze_emotion(request: Request, body: AnalyzeRequest):
    try:
        auth_header = request.headers.get("authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or invalid Authorization header.")
        user_jwt = auth_header.split(" ")[1]
        try:
            user_response = await run_in_threadpool(supabase_admin.auth.get_user, user_jwt)
            current_user = user_response.user
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid or expired token.")

        # Decode image
        header, encoded = body.image.split(",", 1)
        decoded_image = base64.b64decode(encoded)
        nparr = np.frombuffer(decoded_image, np.uint8)
        img_color = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img_color is None:
            raise HTTPException(status_code=400, detail="Invalid image data.")

        # Analyze emotion
        # final_emotion, source = "unknown", "none"
        try:
            analysis = await run_in_threadpool(
                DeepFace.analyze, img_path=img_color,
                actions=['emotion'], enforce_detection=False, silent=True
            )
            if analysis and isinstance(analysis, list) and len(analysis) > 0:
                final_emotion = analysis[0]['dominant_emotion']
                source = "DeepFace"
        except Exception as e:
            logging.warning(f"DeepFace failed: {e}")

        # If a valid emotion is detected, change music and wallpaper
        if final_emotion in EMOTION_MAP:
            music_file = EMOTION_MAP[final_emotion]["music"]
            wallpaper_file = EMOTION_MAP[final_emotion]["wallpaper"]

            # Run in threadpool to avoid blocking the API
            await run_in_threadpool(play_music, music_file)
            await run_in_threadpool(change_wallpaper, wallpaper_file)
        
        logging.info(f"🏆 Detected Emotion: {final_emotion}")

        return {"final_emotion": final_emotion, "source": source}

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Unexpected error: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Internal server error.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)