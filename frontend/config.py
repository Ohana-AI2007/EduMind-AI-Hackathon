import os

from dotenv import load_dotenv

load_dotenv()

BACKEND_URL = os.getenv("BACKEND_URL", "https://edumind-ai-hackathon-1.onrender.com/")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
try:
    MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))
except ValueError:
    MAX_UPLOAD_MB = 50
try:
    PORT = int(os.getenv("PORT", "5000"))
except ValueError:
    PORT = 5000