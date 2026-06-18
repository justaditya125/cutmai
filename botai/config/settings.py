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
RATE_LIMIT_LOGIN_PER_MIN = int(os.getenv('RATE_LIMIT_LOGIN_PER_MIN', '10'))
RATE_LIMIT_SIGNUP_PER_10MIN = int(os.getenv('RATE_LIMIT_SIGNUP_PER_10MIN', '5'))
RATE_LIMIT_API_PER_MIN = int(os.getenv('RATE_LIMIT_API_PER_MIN', '30'))

# ========== MODELS ==========
DEFAULT_MODEL = 'claude-3-5-sonnet-20241022'
ADMIN_MODEL = 'claude-3-5-sonnet-20241022'
USER_MODEL = 'claude-3-5-haiku-20241022'
DEFAULT_MAX_TOKENS = 2000

# Model registry — maps UI names to Anthropic model IDs + pricing (per 1M tokens USD)
MODEL_REGISTRY = {
    'claude-haiku-4-5': {
        'id': 'claude-haiku-4-5',
        'display': 'Claude 3.5 Haiku',
        'input_cost_per_1m': 0.25,
        'output_cost_per_1m': 1.25,
        'max_tokens': 8096,
        'supports_thinking': False,
        'provider': 'anthropic'
    },
    'claude-sonnet-4-5': {
        'id': 'claude-sonnet-4-5',
        'display': 'Claude 3.5 Sonnet',
        'input_cost_per_1m': 3.0,
        'output_cost_per_1m': 15.0,
        'max_tokens': 8096,
        'supports_thinking': True,
        'provider': 'anthropic'
    },
    'claude-opus-4-5': {
        'id': 'claude-opus-4-5',
        'display': 'Claude 3 Opus',
        'input_cost_per_1m': 15.0,
        'output_cost_per_1m': 75.0,
        'max_tokens': 4096,
        'supports_thinking': True,
        'provider': 'anthropic'
    },
}

# ========== LOGGING ==========
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
DEBUG_MODE = os.getenv('DEBUG_MODE', 'False') == 'True'

# ========== CAPABILITY FEATURE FLAGS ==========
# Set to False in .env to disable any module without code changes
ENABLE_MODEL_ORCHESTRATION = os.getenv('ENABLE_MODEL_ORCHESTRATION', 'True') == 'True'
ENABLE_EXTENDED_THINKING    = os.getenv('ENABLE_EXTENDED_THINKING',   'True') == 'True'
ENABLE_CONVERSATION_INTEL   = os.getenv('ENABLE_CONVERSATION_INTEL',  'True') == 'True'
ENABLE_ADVANCED_FILE_PROC   = os.getenv('ENABLE_ADVANCED_FILE_PROC',  'True') == 'True'
ENABLE_RAG                  = os.getenv('ENABLE_RAG',                 'False') == 'True'
ENABLE_WEB_SEARCH           = os.getenv('ENABLE_WEB_SEARCH',          'True') == 'True'
ENABLE_ARTIFACT_DETECTION   = os.getenv('ENABLE_ARTIFACT_DETECTION',  'True') == 'True'
ENABLE_CODE_SANDBOX         = os.getenv('ENABLE_CODE_SANDBOX',        'False') == 'True'
ENABLE_DATA_ANALYSIS        = os.getenv('ENABLE_DATA_ANALYSIS',       'True') == 'True'
ENABLE_VISION_INTELLIGENCE  = os.getenv('ENABLE_VISION_INTELLIGENCE', 'True') == 'True'
ENABLE_EXPORT_ENGINE        = os.getenv('ENABLE_EXPORT_ENGINE',       'True') == 'True'
ENABLE_INTEGRATIONS         = os.getenv('ENABLE_INTEGRATIONS',        'True') == 'True'
ENABLE_ANALYTICS            = os.getenv('ENABLE_ANALYTICS',           'True') == 'True'
ENABLE_SECURITY_LAYER       = os.getenv('ENABLE_SECURITY_LAYER',      'True') == 'True'

# ========== CAPABILITY SETTINGS ==========
# RAG
RAG_EMBEDDING_MODEL  = os.getenv('RAG_EMBEDDING_MODEL', 'all-MiniLM-L6-v2')
RAG_CHUNK_SIZE       = int(os.getenv('RAG_CHUNK_SIZE', '512'))
RAG_CHUNK_OVERLAP    = int(os.getenv('RAG_CHUNK_OVERLAP', '64'))
RAG_TOP_K            = int(os.getenv('RAG_TOP_K', '5'))

# Code Sandbox
SANDBOX_TIMEOUT_SECS = int(os.getenv('SANDBOX_TIMEOUT_SECS', '10'))
SANDBOX_MEMORY_MB    = int(os.getenv('SANDBOX_MEMORY_MB', '128'))

# Analytics
ANALYTICS_RETENTION_DAYS = int(os.getenv('ANALYTICS_RETENTION_DAYS', '90'))

# ========== EXTENDED FILE TYPES (for advanced file processor) ==========
ALLOWED_FILE_TYPES['document'] = list(set(
    ALLOWED_FILE_TYPES.get('document', []) +
    ['pptx', 'ppt', 'svg', 'json', 'xml', 'md', 'markdown', 'csv', 'log', 'rst']
))
ALLOWED_FILE_TYPES['archive'] = list(set(
    ALLOWED_FILE_TYPES.get('archive', []) + ['7z', 'tar', 'gz', 'bz2']
))

# Create directories if they don't exist
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
for file_type in ALLOWED_FILE_TYPES.keys():
    (UPLOAD_DIR / file_type).mkdir(parents=True, exist_ok=True)

print(f"Settings loaded from {env_path}")
print(f"Upload directory: {UPLOAD_DIR}")
