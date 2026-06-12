"""
Configuration module - Load all settings from environment variables
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Robust check for .env file location in either the parent or grandparent folder
env_path = Path(__file__).parent.parent / '.env'
if not env_path.exists():
    env_path = Path(__file__).parent.parent.parent / '.env'
load_dotenv(env_path)

# ========== DATABASE ==========
DATABASE_URL = os.getenv('MONGODB_URI') or os.getenv('MONGO_URI') or 'mongodb://localhost:27017/'
DATABASE_NAME = os.getenv('DATABASE_NAME', 'cutm_ai')

# ========== API KEYS ==========
CLAUDE_API_KEYS_STR = os.getenv('CLAUDE_API_KEYS', '')
CLAUDE_API_KEY_STR = os.getenv('CLAUDE_API_KEY', '')
keys_source = CLAUDE_API_KEYS_STR if CLAUDE_API_KEYS_STR else CLAUDE_API_KEY_STR
ANTHROPIC_API_KEYS = [k.strip() for k in keys_source.split(',') if k.strip()]

GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET', '')

# ========== FILE UPLOAD ==========
MAX_FILE_SIZE_MB = 500
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
UPLOAD_DIR = Path(__file__).parent.parent / 'uploads'

ALLOWED_FILE_TYPES = {
    'video': ['mp4', 'webm', 'mov', 'avi', 'mkv'],
    'document': ['pdf', 'docx', 'xlsx', 'pptx', 'txt', 'doc'],
    'image': ['jpg', 'jpeg', 'png', 'gif', 'bmp'],
    'audio': ['mp3', 'wav', 'flac', 'm4a'],
    'code': ['py', 'js', 'java', 'cpp', 'c', 'html', 'css', 'sql'],
    'archive': ['zip', 'rar', '7z', 'tar', 'gz']
}

# ========== EMAIL ==========
SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', 587))
SMTP_EMAIL = os.getenv('SMTP_EMAIL', '')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')
ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', '')
ENABLE_USER_USAGE_EMAILS = os.getenv('ENABLE_USER_USAGE_EMAILS', 'True') == 'True'
USER_DAILY_WARNING_THRESHOLD_USD = float(os.getenv('USER_DAILY_WARNING_THRESHOLD_USD', '0.50'))

# ========== SECURITY ==========
ALLOWED_DOMAINS = ['cutm.ac.in', 'cutmap.ac.in']
SESSION_TIMEOUT_DAYS = 30
JWT_SECRET = os.getenv('JWT_SECRET', 'change-me-in-production')
PASSWORD_MIN_LENGTH = 8


# ========== MODELS ==========
DEFAULT_MODEL = 'claude-3-5-sonnet-20241022'
ADMIN_MODEL = 'claude-3-5-sonnet-20241022'
USER_MODEL = 'claude-3-5-haiku-20241022'
DEFAULT_MAX_TOKENS = 2000

# ========== LOGGING ==========
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
DEBUG_MODE = os.getenv('DEBUG_MODE', 'False') == 'True'

# Create directories if they don't exist
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
for file_type in ALLOWED_FILE_TYPES.keys():
    (UPLOAD_DIR / file_type).mkdir(parents=True, exist_ok=True)

print(f"Settings loaded from {env_path}")
print(f"Upload directory: {UPLOAD_DIR}")
