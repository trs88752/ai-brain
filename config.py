import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:

    # Secret Key
    SECRET_KEY = "AI_SECOND_BRAIN_2026_SECRET_KEY"

    # SQLite Database
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(BASE_DIR, "database.db")

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Upload Folders
    PDF_UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads", "pdfs")

    IMAGE_UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads", "images")

    VOICE_UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads", "voice")

    PROFILE_UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads", "profile")

    MAX_CONTENT_LENGTH = 100 * 1024 * 1024

    ALLOWED_IMAGE_EXTENSIONS = {
        "png",
        "jpg",
        "jpeg",
        "gif",
        "webp"
    }

    ALLOWED_PDF_EXTENSIONS = {
        "pdf"
    }

    AI_MODEL = "gemini-2.5-flash"

    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")