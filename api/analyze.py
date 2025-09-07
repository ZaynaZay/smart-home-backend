import os
import logging
import traceback
import base64
import cv2
import numpy as np
import tensorflow as tf
import keras
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from deepface import DeepFace
from supabase import create_client, Client
from dotenv import load_dotenv

# --- Setup & Initialization ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
load_dotenv()
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# --- Supabase Clients ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY")
if not all([SUPABASE_URL, SUPABASE_SERVICE_KEY, SUPABASE_ANON_KEY]):
    raise RuntimeError("Supabase URL, Service Key, and Anon Key must be set in .env file.")
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

# --- Helper Function ---
def preprocess_image_for_custom_model(img_color):
    if len(img_color.shape) == 2: gray_img = img_color
    else: gray_img = cv2.cvtColor(img_color, cv2.COLOR_BGR2GRAY)
    resized_img = cv2.resize(gray_img, (48, 48))
    normalized_img = resized_img / 255.0
    return np.expand_dims(np.expand_dims(normalized_img, axis=-1), axis=0)

# --- Main API Endpoint ---
@app.post("/api/analyze")
async def analyze_emotion(request: Request):
    """
    Analyzes an image for emotion using DeepFace and a custom model.
    Logs the emotion and triggers actions via a Supabase database function.
    """
    try:
        # --- 1. User Authentication ---
        auth_header = request.headers.get("authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or invalid Authorization header.")
        
        user_jwt = auth_header.split(" ")[1]
        try:
            # Use the admin client to verify the user's JWT
            current_user = supabase_admin.auth.get_user(user_jwt).user
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid or expired token.")

        # --- 2. Image Decoding ---
        body = await request.json()
        image_data_url = body.get("image")
        if not image_data_url: raise HTTPException(status_code=400, detail="No image data provided.")
        
        header, encoded = image_data_url.split(",", 1)
        decoded_image = base64.b64decode(encoded)
        nparr = np.frombuffer(decoded_image, np.uint8)
        img_color = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img_color is None: raise HTTPException(status_code=400, detail="Invalid image data.")

        # --- 3. Emotion Analysis (DeepFace & Custom Model) ---
        final_emotion, source, highest_confidence = "unknown", "none", 0.0
        
        # DeepFace analysis
        try:
            analysis = DeepFace.analyze(img_color, actions=['emotion'], enforce_detection=False, silent=True)
            if analysis and isinstance(analysis, list) and len(analysis) > 0:
                df_emotion, df_confidence = analysis[0]['dominant_emotion'], analysis[0]['emotion'][analysis[0]['dominant_emotion']] / 100.0
                if df_confidence > highest_confidence:
                    highest_confidence, final_emotion, source = df_confidence, df_emotion, "DeepFace"
        except Exception as e:
            logging.warning(f"DeepFace analysis failed: {e}")

        # Custom model analysis
        if custom_model:
            try:
                processed_img = preprocess_image_for_custom_model(img_color)
                prediction_result = custom_model(tf.constant(processed_img, dtype=tf.float32))
                prediction_tensor = list(prediction_result.values())[0]
                cm_confidence = np.max(prediction_tensor)
                if cm_confidence > highest_confidence:
                    final_emotion = EMOTION_LABELS[np.argmax(prediction_tensor)]
                    source = "Custom Model"
            except Exception as e:
                logging.warning(f"Custom model prediction failed: {e}")
        
        logging.info(f"🏆 Final Emotion: {final_emotion} for User: {current_user.id}")
        
        # --- 4. Database Logging & Command Generation ---
        if final_emotion != "unknown":
            # Log the emotion with the admin client
            supabase_admin.from_("emotion_logs").insert({"user_id": current_user.id, "emotion": final_emotion}).execute()
            
            try:
                # Call the RPC function using the admin client, passing the user_id
                result = supabase_admin.rpc('process_emotion_and_get_commands', {'detected_emotion': final_emotion, 'user_id_param': str(current_user.id)}).execute()

                if result.data and result.data.get('status') == 'ok':
                    commands = result.data.get('commands', [])
                    if commands:
                        logging.info(f"✅ DB function successfully inserted {len(commands)} command(s).")
                elif result.data and result.data.get('status') == 'snoozed':
                    logging.info("User is snoozed. No commands were inserted.")

            except Exception as db_error:
                logging.error(f"Error calling database function: {db_error}\n{traceback.format_exc()}")

        return {"final_emotion": final_emotion, "source": source}

    except HTTPException:
        # Re-raise HTTPException to be handled by FastAPI's error handler
        raise
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="An internal server error occurred.")