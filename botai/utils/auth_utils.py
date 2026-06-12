"""
Authentication utilities - Password hashing, token generation
"""
import hashlib
import os
import secrets
from datetime import datetime, timedelta
from botai.config import settings

def convert_to_alphanumeric(password: str) -> str:
    """
    Deterministically convert any password to a 12-character alphanumeric string.
    Uses SHA-256 for entropy distribution. Required for backwards compatibility.
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
    """
    Hash password with salt. Returns stored_hash as 'salt:password_hash_hex'.
    Required to match the MongoDB Atlas storage scheme.
    """
    converted = convert_to_alphanumeric(password)
    salt = secrets.token_hex(16)
    password_hash = hashlib.pbkdf2_hmac('sha256', converted.encode('utf-8'), salt.encode('utf-8'), 100000)
    return f"{salt}:{password_hash.hex()}"

def verify_password(password: str, stored_hash: str) -> bool:
    """
    Verify password against stored PBKDF2 hash in 'salt:hash' format.
    Supports both custom alphanumeric-converted hashes and raw fallback hashes for backwards compatibility.
    """
    if not password or not stored_hash or ':' not in stored_hash:
        return False
        
    try:
        salt, hash_hex = stored_hash.split(':')
        
        # Method 1: Check converted password
        converted = convert_to_alphanumeric(password)
        password_hash = hashlib.pbkdf2_hmac('sha256', converted.encode('utf-8'), salt.encode('utf-8'), 100000)
        if password_hash.hex() == hash_hex:
            return True
            
        # Method 2: Check raw password (backward compatibility for some older users)
        password_hash_raw = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
        return password_hash_raw.hex() == hash_hex
    except Exception:
        return False

def generate_session_token() -> str:
    """Generate a secure session token"""
    return secrets.token_hex(32)

def is_token_valid(created_at: datetime, days: int = settings.SESSION_TIMEOUT_DAYS) -> bool:
    """Check if token is still valid"""
    if created_at is None:
        return False
    expiry = created_at + timedelta(days=days)
    return datetime.utcnow() < expiry
