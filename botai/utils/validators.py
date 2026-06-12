"""
Input validators - File validation, email validation, etc.
"""
import re
from botai.config import settings

def validate_email(email: str) -> bool:
    """Validate email format"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def validate_institutional_domain(email: str) -> bool:
    """Check if email is from allowed institutional domain"""
    domain = email.split('@')[1].lower() if '@' in email else ''
    return domain in settings.ALLOWED_DOMAINS

def validate_file_type(filename: str) -> str:
    """
    Determine file type by extension
    Returns: 'document', 'image', 'video', 'audio', 'code', 'archive', or 'unknown'
    """
    ext = filename.lower().split('.')[-1] if '.' in filename else ''
    
    for file_type, extensions in settings.ALLOWED_FILE_TYPES.items():
        if ext in extensions:
            return file_type
    
    return 'unknown'

def validate_file_size(size_bytes: int) -> bool:
    """Check if file size is within limit"""
    return size_bytes <= settings.MAX_FILE_SIZE_BYTES

def validate_password_strength(password: str) -> bool:
    """Validate password strength"""
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        return False
    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit = any(c.isdigit() for c in password)
    return has_upper and has_lower and has_digit

def sanitize_input(text: str) -> str:
    """Remove potentially dangerous characters and HTML tags"""
    if not text:
        return ""
    # Remove SQL injection attempts
    text = text.replace(';', '').replace('--', '').replace('/*', '').replace('*/', '')
    # Remove HTML/script tags
    text = re.sub(r'<[^>]+>', '', text)
    return text.strip()
