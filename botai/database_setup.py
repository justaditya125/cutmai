#!/usr/bin/env python3
import os
import sys
import io
from datetime import datetime

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from botai.config import settings
from botai.config.mysql_config import get_db, close_db
from botai.utils.auth_utils import hash_password


def create_database_if_not_exists():
    """Connect to MySQL without a database and create the target database if it doesn't exist."""
    import mysql.connector
    try:
        conn = mysql.connector.connect(
            host=settings.MYSQL_HOST,
            port=settings.MYSQL_PORT,
            user=settings.MYSQL_USER,
            password=settings.MYSQL_PASSWORD,
            charset='utf8mb4',
            use_unicode=True,
        )
        cursor = conn.cursor()
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{settings.MYSQL_DATABASE}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        cursor.close()
        conn.close()
        print(f"[OK] Database '{settings.MYSQL_DATABASE}' ensured")
    except Exception as e:
        print(f"[ERROR] Failed to create database: {e}")
        sys.exit(1)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id CHAR(24) PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255),
    salt VARCHAR(255),
    name VARCHAR(255),
    google_id VARCHAR(255) UNIQUE,
    profile_picture TEXT,
    login_method VARCHAR(50) DEFAULT 'email',
    is_approved TINYINT(1) DEFAULT 1,
    token_limit INT DEFAULT 1000000,
    is_active TINYINT(1) DEFAULT 1,
    is_admin TINYINT(1) DEFAULT 0,
    total_tokens_used BIGINT DEFAULT 0,
    total_messages INT DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_login DATETIME,
    INDEX idx_created_at (created_at),
    INDEX idx_google_id (google_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS user_sessions (
    id CHAR(24) PRIMARY KEY,
    user_id CHAR(24) NOT NULL,
    session_token VARCHAR(255) NOT NULL UNIQUE,
    expires_at DATETIME NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    ip_address VARCHAR(45),
    user_agent TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_session_token (session_token),
    INDEX idx_user_id (user_id),
    INDEX idx_expires_at (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS conversations (
    id CHAR(24) PRIMARY KEY,
    user_id CHAR(24) NOT NULL,
    title VARCHAR(255) DEFAULT 'New Chat',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    gdrive_url TEXT,
    gdrive_context LONGTEXT,
    gdrive_file_names JSON,
    gdrive_loaded_at DATETIME,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user_id (user_id),
    INDEX idx_updated_at (updated_at),
    INDEX idx_gdrive_loaded_at (gdrive_loaded_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS messages (
    id CHAR(24) PRIMARY KEY,
    conversation_id CHAR(24) NOT NULL,
    user_id CHAR(24) NOT NULL,
    role VARCHAR(20) NOT NULL,
    content LONGTEXT,
    file_references JSON,
    feedback VARCHAR(20) DEFAULT 'none',
    edited TINYINT(1) DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_conversation_id (conversation_id),
    INDEX idx_user_id (user_id),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS token_usage (
    id CHAR(24) PRIMARY KEY,
    user_id CHAR(24) NOT NULL,
    input_tokens INT DEFAULT 0,
    output_tokens INT DEFAULT 0,
    cache_creation_input_tokens INT DEFAULT 0,
    cache_read_input_tokens INT DEFAULT 0,
    total_tokens INT DEFAULT 0,
    model VARCHAR(100),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user_id (user_id),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS files (
    id CHAR(24) PRIMARY KEY,
    user_id CHAR(24) NOT NULL,
    filename VARCHAR(255),
    file_type VARCHAR(50),
    size_bytes BIGINT DEFAULT 0,
    path TEXT,
    sha256 VARCHAR(64),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user_id (user_id),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS analytics_events (
    id CHAR(24) PRIMARY KEY,
    event_type VARCHAR(100),
    user_id CHAR(24),
    data JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_event_type (event_type),
    INDEX idx_user_id (user_id),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS artifacts (
    id CHAR(24) PRIMARY KEY,
    user_id CHAR(24),
    conversation_id CHAR(24),
    message_id CHAR(24),
    artifact_type VARCHAR(50),
    content LONGTEXT,
    char_count INT DEFAULT 0,
    version INT DEFAULT 1,
    parent_id CHAR(24),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_id (user_id),
    INDEX idx_conversation_id (conversation_id),
    INDEX idx_created_at (created_at),
    INDEX idx_artifact_type (artifact_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS embeddings (
    id CHAR(24) PRIMARY KEY,
    user_id CHAR(24),
    file_id CHAR(24),
    text TEXT,
    chunk_index INT,
    vector JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_id (user_id),
    INDEX idx_file_id (file_id),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS conversation_memory (
    id CHAR(24) PRIMARY KEY,
    user_id CHAR(24),
    content TEXT,
    tags JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_id (user_id),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS usage_logs (
    id CHAR(24) PRIMARY KEY,
    user_id CHAR(24),
    conversation_id CHAR(24),
    model VARCHAR(100),
    input_tokens INT DEFAULT 0,
    output_tokens INT DEFAULT 0,
    cache_creation_input_tokens INT DEFAULT 0,
    cache_read_input_tokens INT DEFAULT 0,
    total_tokens INT DEFAULT 0,
    total_cost_usd DECIMAL(12,6) DEFAULT 0,
    latency_ms DECIMAL(10,2) DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_id (user_id),
    INDEX idx_model (model),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS thinking_sessions (
    id CHAR(24) PRIMARY KEY,
    user_id CHAR(24),
    conversation_id CHAR(24),
    question TEXT,
    thinking_length INT DEFAULT 0,
    answer_length INT DEFAULT 0,
    budget_tokens INT DEFAULT 0,
    input_tokens INT DEFAULT 0,
    output_tokens INT DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_id (user_id),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS audit_logs (
    id CHAR(24) PRIMARY KEY,
    actor VARCHAR(255),
    action VARCHAR(255),
    resource VARCHAR(255),
    outcome VARCHAR(50) DEFAULT 'SUCCESS',
    metadata JSON,
    risk VARCHAR(20) DEFAULT 'LOW',
    ts DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_actor (actor),
    INDEX idx_ts (ts)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS security_logs (
    id CHAR(24) PRIMARY KEY,
    user_ip VARCHAR(45),
    type VARCHAR(100),
    description TEXT,
    risk VARCHAR(20),
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_timestamp (timestamp),
    INDEX idx_type (type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""


def create_user_helper(db, email, password=None, name=None, login_method='email', google_id=None, profile_picture=None, is_admin=False, is_approved=None):
    try:
        password_hash = hash_password(password) if password else None
        if is_approved is None:
            is_approved = True
        user_doc = {
            "email": email.strip().lower(),
            "password_hash": password_hash,
            "name": name.strip() if name else None,
            "profile_picture": profile_picture,
            "login_method": login_method,
            "is_approved": is_approved,
            "token_limit": 1000000,
            "is_active": True,
            "is_admin": is_admin,
            "total_tokens_used": 0,
            "total_messages": 0,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
            "last_login": None
        }
        if google_id is not None:
            user_doc["google_id"] = google_id
        result = db.users.insert_one(user_doc)
        print(f"[OK] User created successfully: {email}")
        return result.inserted_id
    except Exception as e:
        if 'Duplicate' in str(e) or '1062' in str(e):
            print(f"[WARN] User with email/google_id already exists: {email}")
        else:
            print(f"[ERROR] Error creating user: {e}")
        return None


def setup_database():
    print("[START] Setting up Claude Chatbot Database on MySQL...")

    create_database_if_not_exists()

    db = get_db()
    if db is not None:
        try:
            db.command('ping')
            print("[OK] Connected to MySQL successfully")

            conn = db.get_connection()
            cursor = conn.cursor()
            try:
                for statement in SCHEMA_SQL.split(';'):
                    stmt = statement.strip()
                    if stmt:
                        cursor.execute(stmt + ';')
                conn.commit()
                print("[OK] All tables created/verified successfully")
            except Exception as e:
                conn.rollback()
                print(f"[ERROR] Schema creation error: {e}")
                raise
            finally:
                cursor.close()

            test_user = db.users.find_one({"email": "test@example.com", "is_active": True})
            if not test_user:
                test_user_id = create_user_helper(
                    db,
                    email="test@example.com",
                    password="test123",
                    name="Test User",
                    login_method="email",
                    is_admin=False
                )
                if test_user_id:
                    print(f"[OK] Test user seeded successfully with ID: {test_user_id}")
            else:
                print("[INFO] Seed user 'test@example.com' already exists")

            db.users.update_one(
                {"is_admin": {"$ne": False}, "email": {"$ne": "secure_admin"}},
                {"$set": {"is_admin": False}}
            )

            db.users.update_one(
                {"is_approved": {"$ne": True}},
                {"$set": {"is_approved": True}}
            )

            db.users.update_one(
                {"token_limit": {"$exists": False}},
                {"$set": {"token_limit": 1000000}}
            )

            admin_password = os.environ.get('ADMIN_PASSWORD', 'admin123')
            admin_user = db.users.find_one({"email": "secure_admin", "is_active": True})
            if not admin_user:
                admin_id = create_user_helper(
                    db,
                    email="secure_admin",
                    password=admin_password,
                    name="System Admin",
                    login_method="email",
                    is_admin=True
                )
                if admin_id:
                    print(f"[OK] Admin account seeded (email=secure_admin, password from ADMIN_PASSWORD in .env)")
            else:
                db.users.update_one(
                    {"email": "secure_admin"},
                    {"$set": {"is_admin": True, "name": "System Admin"}}
                )
                print("[INFO] Admin account 'secure_admin' verified")

            db.users.update_one(
                {"email": "221801380012@cutmap.ac.in"},
                {"$set": {"is_admin": False}}
            )
            print("[OK] Revoked admin privileges from Google Sign-In user '221801380012@cutmap.ac.in'")

        except Exception as e:
            print(f"[ERROR] Error during database setup: {e}")
        finally:
            close_db()
    else:
        print("[ERROR] MySQL database initialization failed!")


if __name__ == "__main__":
    setup_database()
