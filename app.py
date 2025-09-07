from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import base64
import cv2
import numpy as np
from deepface import DeepFace

app = FastAPI()

# Configure CORS to allow our Vercel frontend to talk to this new service
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In a real production app, you'd put your Vercel URL here
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"status": "WellnessHub AI Backend is running"}

# The endpoint will now be at /analyze
@app.post("/analyze")
async def analyze_emotion(request: Request):
    try:
        body = await request.json()
        image_data_url = body.get("image")

        if not image_data_url:
            return {"error": "No image data provided"}, 400

        header, encoded = image_data_url.split(",", 1)
        decoded_image = base64.b64decode(encoded)
        nparr = np.frombuffer(decoded_image, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        analysis = DeepFace.analyze(
            img, 
            actions=['emotion'], 
            enforce_detection=False
        )

        if analysis and isinstance(analysis, list) and len(analysis) > 0:
            dominant_emotion = analysis[0]['dominant_emotion']
            return {"emotion": dominant_emotion}
        else:
            return {"emotion": "unknown"}

    except Exception as e:
        print(f"An error occurred: {e}")
        return {"error": "An error occurred during analysis"}, 500