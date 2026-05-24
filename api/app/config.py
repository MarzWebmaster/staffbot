from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
import secrets
from typing import List


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql://staffbot:staffbot@localhost:5432/staffbot_db"
    
    # Auth
    SECRET_KEY: str = secrets.token_urlsafe(32)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours
    
    # CORS — restrict to known domains
    CORS_ORIGINS: List[str] = [
        "https://staffbot.my",
        "https://api.staffbot.my",
        "https://admin.staffbot.my",
        "http://localhost:3000",
        "http://localhost:8000",
    ]
    
    # Stripe
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    
    # Cloudflare
    CLOUDFLARE_API_TOKEN: str = ""
    CLOUDFLARE_ZONE_ID: str = ""
    
    # Server B (Internal API via WireGuard)
    SERVER_B_API_URL: str = "http://10.0.0.2:8080"
    SERVER_B_API_KEY: str = ""
    
    # SMTP / Email
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "noreply@staffbot.my"
    
    # Admin notification contacts
    ADMIN_WHATSAPP: str = ""
    ADMIN_EMAIL: str = ""
    ADMIN_PHONE: str = ""
    
    # Domain
    DOMAIN: str = "staffbot.my"
    LANDING_PAGE_URL: str = "http://localhost:3000"
    
    # SMS API
    SMS_API_URL: str = ""
    SMS_API_KEY: str = ""
    
    # LLM / OpenRouter
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODEL: str = "deepseek/deepseek-chat"
    
    model_config = SettingsConfigDict(
        env_prefix="STAFFBOT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    return Settings()
