import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    APP_NAME: str = "AI Image & Video Generation Platform"
    DEBUG: bool = os.getenv("DEBUG", "true").lower() == "true"

    SECRET_KEY: str = os.getenv("SECRET_KEY", "")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "sqlite:///./app.db"
    )

    UPLOAD_DIR: str = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "uploads")
    IMAGE_UPLOAD_DIR: str = os.path.join(UPLOAD_DIR, "images")
    VIDEO_UPLOAD_DIR: str = os.path.join(UPLOAD_DIR, "videos")
    GENERATED_DIR: str = os.path.join(UPLOAD_DIR, "generated")

    DMXAPI_BASE_URL: str = os.getenv("DMXAPI_BASE_URL", "https://www.dmxapi.cn")
    DMXAPI_API_KEY: str = os.getenv("DMXAPI_API_KEY", "")

    DMXAPI_TXT2IMG_TIMEOUT: int = int(os.getenv("DMXAPI_TXT2IMG_TIMEOUT", "300"))
    DMXAPI_IMG2IMG_READ_TIMEOUT: int = int(os.getenv("DMXAPI_IMG2IMG_READ_TIMEOUT", "1200"))
    DMXAPI_IMG2IMG_CONNECT_TIMEOUT: int = int(os.getenv("DMXAPI_IMG2IMG_CONNECT_TIMEOUT", "60"))

    DEFAULT_ADMIN_USERNAME: str = os.getenv("DEFAULT_ADMIN_USERNAME", "admin")
    DEFAULT_ADMIN_EMAIL: str = os.getenv("DEFAULT_ADMIN_EMAIL", "admin@example.com")
    DEFAULT_ADMIN_PASSWORD: str = os.getenv("DEFAULT_ADMIN_PASSWORD", "")

    CORS_ORIGINS: list = [
        "http://localhost:3000", "http://127.0.0.1:3000", "http://192.168.3.216:3000",
        "http://localhost:3001", "http://127.0.0.1:3001",
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:5174", "http://127.0.0.1:5174",
        "http://192.168.3.109:5174",
        "http://localhost:5175", "http://127.0.0.1:5175",
        "http://192.168.3.109:5175",
        "http://localhost:5275", "http://127.0.0.1:5275",
        "http://192.168.3.109:5275",
        "http://localhost:5176", "http://127.0.0.1:5176",
        "http://192.168.3.109:5176",
    ]


settings = Settings()
