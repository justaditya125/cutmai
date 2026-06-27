"""
Authentication utilities - Password hashing, token generation
"""
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from botai.config import settings

# bcrypt import with fallback
try:
    import bcrypt as _bcrypt
    _HAS_BCRYPT = True
except ImportError:
    _HAS_BCRYPT = False


def convert_to_alphanumeric(password: str) -> str:
    """
    Deterministically convert any password to a 12-character alphanumeric string.
    Uses SHA-256 for entropy distribution. Kept ONLY for legacy hash verification.
    """
    if not password:
        return ""
    h = hashlib.sha256(password.encode('utf-8')).digest()
    chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    result = []
    for i in range(12):
        byte_val = h[i*2] + (h[i*2 + 1] << 8)
        result.append(chars[byte_val % len(chars)])
    return "".join(result)


def hash_password(password: str) -> str:
    """Hash password with bcrypt. Returns 'bcrypt:$2b$...' format."""
    if _HAS_BCRYPT:
        pw_bytes = password.encode('utf-8')
        salt = _bcrypt.gensalt(rounds=12)
        hashed = _bcrypt.hashpw(pw_bytes, salt)
        return f"bcrypt:{hashed.decode('utf-8')}"

    # Fallback: PBKDF2 with 600,000 iterations (NIST recommended minimum)
    converted = convert_to_alphanumeric(password)
    salt = secrets.token_hex(16)
    password_hash = hashlib.pbkdf2_hmac('sha256', converted.encode('utf-8'), salt.encode('utf-8'), 600000)
    return f"pbkdf2:{salt}:{password_hash.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """
    Verify password against stored hash.
    Supports:
      - bcrypt:$2b$... format (new passwords)
      - pbkdf2:salt:hex format (migrated legacy)
      - salt:hex format (old legacy without prefix)
    """
    if not password or not stored_hash:
        return False

    try:
        if stored_hash.startswith('bcrypt:'):
            if not _HAS_BCRYPT:
                return False
            return _bcrypt.checkpw(password.encode('utf-8'), stored_hash[7:].encode('utf-8'))

        if stored_hash.startswith('pbkdf2:'):
            parts = stored_hash[7:].split(':')
            if len(parts) != 2:
                return False
            salt, hash_hex = parts
            # PBKDF2 hashes were created with converted password
            converted = convert_to_alphanumeric(password)
            password_hash = hashlib.pbkdf2_hmac('sha256', converted.encode('utf-8'), salt.encode('utf-8'), 600000)
            if hmac.compare_digest(password_hash.hex(), hash_hex):
                return True
            # Also try raw password (some versions)
            password_hash_raw = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 600000)
            return hmac.compare_digest(password_hash_raw.hex(), hash_hex)

        # Old format: salt:hex (no prefix) — legacy converted + PBKDF2
        if ':' in stored_hash:
            salt, hash_hex = stored_hash.split(':', 1)
            # Method 1: Check converted password (old legacy)
            converted = convert_to_alphanumeric(password)
            password_hash = hashlib.pbkdf2_hmac('sha256', converted.encode('utf-8'), salt.encode('utf-8'), 100000)
            if hmac.compare_digest(password_hash.hex(), hash_hex):
                return True
            # Method 2: Check raw password (some old users)
            password_hash_raw = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
            return hmac.compare_digest(password_hash_raw.hex(), hash_hex)

        return False
    except Exception:
        return False


def needs_rehash(stored_hash: str) -> bool:
    """Check if a password hash should be upgraded on next successful login."""
    return not stored_hash.startswith('bcrypt:')


def generate_session_token() -> str:
    """Generate a secure session token"""
    return secrets.token_hex(32)


def is_token_valid(created_at: datetime, days: int = settings.SESSION_TIMEOUT_DAYS) -> bool:
    """Check if token is still valid"""
    if created_at is None:
        return False
    expiry = created_at + timedelta(days=days)
    return datetime.now(timezone.utc) < expiry
