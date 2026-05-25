import hashlib
import base64
from cryptography.fernet import Fernet
from app.config import get_settings

settings = get_settings()


def _derive_fernet_key(secret: str) -> bytes:
    """Derive a valid 32-byte Fernet key from any secret string."""
    digest = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def get_cipher() -> Fernet:
    key = _derive_fernet_key(settings.SECRET_KEY)
    return Fernet(key)


def encrypt_value(value: str) -> str:
    if not value:
        return ""
    cipher = get_cipher()
    return cipher.encrypt(value.encode()).decode()


def decrypt_value(encrypted: str) -> str:
    if not encrypted:
        return ""
    cipher = get_cipher()
    return cipher.decrypt(encrypted.encode()).decode()


def mask_key(key: str) -> str:
    """Show only first 8 chars of an API key for display."""
    if not key:
        return ""
    prefix = key[:8]
    return f"{prefix}..."
