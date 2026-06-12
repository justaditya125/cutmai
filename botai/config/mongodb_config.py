"""
MongoDB configuration - Database connection setup
"""
from pymongo import MongoClient
from botai.config import settings

_db = None
_client = None

def get_db():
    """Get MongoDB database instance"""
    global _db, _client
    if _db is None:
        _client = MongoClient(settings.DATABASE_URL, serverSelectionTimeoutMS=5000)
        _db = _client[settings.DATABASE_NAME]
        print(f"Connected to MongoDB: {settings.DATABASE_NAME}")
    return _db

def init_db():
    """Initialize database (create indexes, etc.)"""
    db = get_db()
    # Ping to trigger connection check and fail fast if down
    db.command('ping')
    print("MongoDB initialized")
    return True

def close_db():
    """Gracefully closes MongoDB connections"""
    global _db, _client
    if _client is not None:
        _client.close()
        print("MongoDB connection pool closed")
    _client = None
    _db = None
