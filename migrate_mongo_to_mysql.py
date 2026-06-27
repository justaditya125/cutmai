"""
MongoDB Atlas → MySQL Migration Script
Migrates all collections from MongoDB Atlas to local MySQL database.
"""
import pymongo
import mysql.connector
import os
import sys
from datetime import datetime, timezone
from bson import ObjectId
from dotenv import load_dotenv

# Load .env from botai directory
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'botai', '.env')
load_dotenv(env_path)

# ─── CONFIG ───────────────────────────────────────────────────────────────────
MONGO_URI = "mongodb+srv://adityasah_db_user:adityasah2004@cluster0.onagysb.mongodb.net/cutm_ai?retryWrites=true&w=majority"

MYSQL_CONFIG = {
    'host': os.getenv('MYSQL_HOST', 'localhost'),
    'port': int(os.getenv('MYSQL_PORT', 3306)),
    'user': os.getenv('MYSQL_USER', 'root'),
    'password': os.getenv('MYSQL_PASSWORD', ''),
    'database': os.getenv('MYSQL_DATABASE', 'cutm_ai'),
}

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def parse_datetime(val):
    """Convert various datetime formats to Python datetime."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        try:
            # Handle ISO format
            return datetime.fromisoformat(val.replace('Z', '+00:00')).replace(tzinfo=None)
        except Exception:
            pass
    return None


def to_str(val):
    """Convert value to string, handling ObjectId."""
    if val is None:
        return None
    if isinstance(val, ObjectId):
        return str(val)
    return str(val)


def to_int(val, default=0):
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def to_bool(val, default=False):
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    if isinstance(val, int):
        return bool(val)
    if isinstance(val, str):
        return val.lower() in ('true', '1', 'yes')
    return default


# ─── MIGRATION FUNCTIONS ─────────────────────────────────────────────────────

def migrate_users(mysql_cur, mongo_db):
    """Migrate users collection."""
    collection = mongo_db['users']
    docs = list(collection.find())
    count = 0
    for doc in docs:
        try:
            mysql_cur.execute("""
                INSERT IGNORE INTO users 
                (id, email, password_hash, salt, name, google_id, profile_picture, 
                 login_method, is_approved, token_limit, is_active, is_admin,
                 total_tokens_used, total_messages, created_at, updated_at, last_login)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                to_str(doc['_id']),
                doc.get('email', ''),
                doc.get('password_hash', ''),
                doc.get('salt'),
                doc.get('name', ''),
                doc.get('google_id'),
                doc.get('profile_picture'),
                doc.get('login_method', 'email'),
                to_bool(doc.get('is_approved'), True),
                to_int(doc.get('token_limit'), 1000000),
                to_bool(doc.get('is_active'), True),
                to_bool(doc.get('is_admin'), False),
                to_int(doc.get('total_tokens_used'), 0),
                to_int(doc.get('total_messages'), 0),
                parse_datetime(doc.get('created_at')),
                parse_datetime(doc.get('updated_at')),
                parse_datetime(doc.get('last_login')),
            ))
            count += 1
        except mysql.connector.IntegrityError:
            pass  # Duplicate ID, skip
        except Exception as e:
            print(f"  [WARN] users skip {doc.get('email', '?')}: {e}")
    return count


def migrate_conversations(mysql_cur, mongo_db):
    """Migrate conversations collection."""
    collection = mongo_db['conversations']
    docs = list(collection.find())
    count = 0
    for doc in docs:
        try:
            mysql_cur.execute("""
                INSERT IGNORE INTO conversations 
                (id, user_id, title, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                to_str(doc['_id']),
                to_str(doc.get('user_id')),
                doc.get('title', 'New Chat')[:255],
                parse_datetime(doc.get('created_at')),
                parse_datetime(doc.get('updated_at')),
            ))
            count += 1
        except mysql.connector.IntegrityError:
            pass
        except Exception as e:
            print(f"  [WARN] conversations skip {doc.get('_id', '?')}: {e}")
    return count


def migrate_messages(mysql_cur, mongo_db):
    """Migrate messages collection."""
    collection = mongo_db['messages']
    docs = list(collection.find())
    count = 0
    for doc in docs:
        try:
            content = doc.get('content', '')
            # Truncate extremely long content (MySQL longtext has limits in practice)
            if len(content) > 100000:
                content = content[:100000] + "... [truncated]"

            mysql_cur.execute("""
                INSERT IGNORE INTO messages 
                (id, conversation_id, user_id, role, content, feedback, edited, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                to_str(doc['_id']),
                to_str(doc.get('conversation_id')),
                to_str(doc.get('user_id')),
                doc.get('role', 'user'),
                content,
                doc.get('feedback', 'none'),
                to_bool(doc.get('edited'), False),
                parse_datetime(doc.get('created_at')),
            ))
            count += 1
        except mysql.connector.IntegrityError:
            pass
        except Exception as e:
            print(f"  [WARN] messages skip {doc.get('_id', '?')}: {e}")
    return count


def migrate_token_usage(mysql_cur, mongo_db):
    """Migrate token_usage collection."""
    collection = mongo_db['token_usage']
    docs = list(collection.find())
    count = 0
    for doc in docs:
        try:
            mysql_cur.execute("""
                INSERT IGNORE INTO token_usage 
                (id, user_id, input_tokens, output_tokens, cache_creation_input_tokens,
                 cache_read_input_tokens, total_tokens, model, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                to_str(doc['_id']),
                to_str(doc.get('user_id')),
                to_int(doc.get('input_tokens')),
                to_int(doc.get('output_tokens')),
                to_int(doc.get('cache_creation_input_tokens')),
                to_int(doc.get('cache_read_input_tokens')),
                to_int(doc.get('total_tokens')),
                doc.get('model', ''),
                parse_datetime(doc.get('created_at')),
            ))
            count += 1
        except mysql.connector.IntegrityError:
            pass
        except Exception as e:
            print(f"  [WARN] token_usage skip {doc.get('_id', '?')}: {e}")
    return count


def migrate_user_sessions(mysql_cur, mongo_db):
    """Migrate user_sessions collection."""
    collection = mongo_db['user_sessions']
    docs = list(collection.find())
    count = 0
    for doc in docs:
        try:
            mysql_cur.execute("""
                INSERT IGNORE INTO user_sessions 
                (id, user_id, session_token, expires_at, created_at, ip_address, user_agent, last_activity)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                to_str(doc['_id']),
                to_str(doc.get('user_id')),
                doc.get('session_token', ''),
                parse_datetime(doc.get('expires_at')),
                parse_datetime(doc.get('created_at')),
                doc.get('ip_address'),
                doc.get('user_agent'),
                parse_datetime(doc.get('last_activity')) or parse_datetime(doc.get('created_at')),
            ))
            count += 1
        except mysql.connector.IntegrityError:
            pass
        except Exception as e:
            print(f"  [WARN] user_sessions skip {doc.get('_id', '?')}: {e}")
    return count


def migrate_security_logs(mysql_cur, mongo_db):
    """Migrate security_logs collection. MongoDB uses 'desc', MySQL uses 'description'."""
    collection = mongo_db['security_logs']
    docs = list(collection.find())
    count = 0
    for doc in docs:
        try:
            mysql_cur.execute("""
                INSERT IGNORE INTO security_logs 
                (id, user_ip, type, description, risk, timestamp)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                to_str(doc['_id']),
                doc.get('user_ip', ''),
                doc.get('type', ''),
                doc.get('desc') or doc.get('description', ''),
                doc.get('risk', 'LOW'),
                parse_datetime(doc.get('timestamp')),
            ))
            count += 1
        except mysql.connector.IntegrityError:
            pass
        except Exception as e:
            print(f"  [WARN] security_logs skip {doc.get('_id', '?')}: {e}")
    return count


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  MongoDB Atlas -> MySQL Migration")
    print("=" * 60)

    # Connect to MongoDB Atlas
    print("\n[1/3] Connecting to MongoDB Atlas...")
    try:
        mongo_client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=10000)
        mongo_client.admin.command('ping')
        mongo_db = mongo_client['cutm_ai']
        collections = mongo_db.list_collection_names()
        print(f"  Connected! Found {len(collections)} collections")
    except Exception as e:
        print(f"  FAILED: {e}")
        sys.exit(1)

    # Connect to MySQL
    print("\n[2/3] Connecting to MySQL...")
    try:
        mysql_conn = mysql.connector.connect(**MYSQL_CONFIG)
        mysql_cur = mysql_conn.cursor()
        print(f"  Connected to {MYSQL_CONFIG['database']}@{MYSQL_CONFIG['host']}")
    except Exception as e:
        print(f"  FAILED: {e}")
        sys.exit(1)

    # Migrate each collection
    print("\n[3/3] Migrating data...")
    total = 0
    migrations = [
        ("users", migrate_users),
        ("conversations", migrate_conversations),
        ("messages", migrate_messages),
        ("token_usage", migrate_token_usage),
        ("user_sessions", migrate_user_sessions),
        ("security_logs", migrate_security_logs),
    ]

    for name, func in migrations:
        if name in collections:
            mongo_count = mongo_db[name].count_documents({})
            print(f"\n  Migrating {name} ({mongo_count} documents)...")
            count = func(mysql_cur, mongo_db)
            mysql_conn.commit()
            print(f"  -> Inserted {count}/{mongo_count} into MySQL")
            total += count
        else:
            print(f"\n  Skipping {name} (not found in MongoDB)")

    # Summary
    print("\n" + "=" * 60)
    print(f"  MIGRATION COMPLETE: {total} total records migrated")
    print("=" * 60)

    # Verify counts
    print("\n  Verification:")
    for name, _ in migrations:
        try:
            mysql_cur.execute(f"SELECT COUNT(*) FROM {name}")
            count = mysql_cur.fetchone()[0]
            mongo_count = mongo_db[name].count_documents({}) if name in collections else 0
            status = "OK" if count >= mongo_count or mongo_count == 0 else "MISMATCH"
            print(f"    {name}: MySQL={count}, MongoDB={mongo_count} [{status}]")
        except Exception as e:
            print(f"    {name}: ERROR - {e}")

    mysql_cur.close()
    mysql_conn.close()
    mongo_client.close()
    print("\n  Done!")


if __name__ == '__main__':
    main()
