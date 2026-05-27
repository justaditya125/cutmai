#!/usr/bin/env python3
import http.server
import socketserver
import json
import os
import time
import urllib.request
import urllib.error
import secrets
import hashlib
from collections import defaultdict
from datetime import datetime, timedelta
from pymongo import MongoClient
from bson import ObjectId

# ─── Load secrets from .env (never hardcode credentials) ─────────────────────
try:
    from dotenv import load_dotenv
    base_dir = os.path.dirname(os.path.abspath(__file__))
    load_dotenv(os.path.join(base_dir, '.env'))
except ImportError:
    pass  # dotenv optional; fall back to environment variables

PORT     = 3000
DB_NAME  = 'cutm_ai'

import threading

MONGO_URI       = os.environ.get('MONGO_URI', '')
CLAUDE_API_KEY  = os.environ.get('CLAUDE_API_KEY', '')
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '')

# Multi-key load balancing support
CLAUDE_API_KEYS_STR = os.environ.get('CLAUDE_API_KEYS', '')
CLAUDE_API_KEYS = []
for key_source in [CLAUDE_API_KEYS_STR, CLAUDE_API_KEY]:
    if key_source:
        CLAUDE_API_KEYS.extend([k.strip() for k in key_source.split(',') if k.strip()])


class KeyRotator:
    def __init__(self, keys):
        self.keys = keys
        self._index = 0
        self._lock = threading.Lock()
        
    def get_key(self):
        if not self.keys:
            return ""
        with self._lock:
            key = self.keys[self._index]
            self._index = (self._index + 1) % len(self.keys)
            print(f"🔄 [Load Balancer] Rotating API Key: using key ending in ...{key[-8:] if len(key) > 8 else '???'}")
            return key

api_key_rotator = KeyRotator(CLAUDE_API_KEYS)

if not MONGO_URI:
    print('⚠️  WARNING: MONGO_URI not set. Add it to your .env file.')
if not CLAUDE_API_KEYS:
    print('⚠️  WARNING: No Claude API keys loaded. Set CLAUDE_API_KEY or CLAUDE_API_KEYS in .env')
else:
    print(f"✅ Loaded {len(CLAUDE_API_KEYS)} Claude API keys for round-robin load balancing.")

# ─── Rate Limiter ─────────────────────────────────────────────────────────────
# Tracks per-IP attempt timestamps for sensitive endpoints.
_rate_store: dict = defaultdict(list)

def is_rate_limited(ip: str, endpoint: str, limit: int = 10, window: int = 60) -> bool:
    """
    Returns True if `ip` has exceeded `limit` calls to `endpoint` in the last
    `window` seconds.  Automatically prunes stale entries.
    """
    key = f"{ip}:{endpoint}"
    now = time.monotonic()
    _rate_store[key] = [t for t in _rate_store[key] if now - t < window]
    if len(_rate_store[key]) >= limit:
        return True
    _rate_store[key].append(now)
    return False

# ─── Database Helper ──────────────────────────────────────────────────────────
# Single long-lived client with built-in connection pool (replaces per-request connections)
try:
    _mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
except Exception as _e:
    print(f"❌ MongoDB client init error: {_e}")
    _mongo_client = None

def get_db():
    """Return the shared database reference (connection-pooled)."""
    if _mongo_client is None:
        return None
    try:
        return _mongo_client[DB_NAME]
    except Exception as e:
        print(f"❌ DB access error: {e}")
        return None

def hash_password(password):
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
    return f"{salt}:{h.hex()}"

def verify_password(password, stored):
    try:
        salt, h = stored.split(':')
        return hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000).hex() == h
    except:
        return False

def create_session(db, user_id, ip=None, ua=None):
    token = secrets.token_urlsafe(32)
    expires = datetime.now() + timedelta(days=30)
    u_id = ObjectId(user_id) if isinstance(user_id, (str, bytes)) else user_id
    try:
        db.user_sessions.insert_one({
            "user_id": u_id,
            "session_token": token,
            "expires_at": expires,
            "created_at": datetime.now(),
            "ip_address": ip,
            "user_agent": ua
        })
        return token
    except Exception as e:
        print(f"❌ Session error: {e}")
        return secrets.token_urlsafe(32)  # fallback token

def save_token_usage(db, user_id, input_tokens, output_tokens, model='claude-3-5-sonnet-20241022'):
    """Save token usage to database and print detailed log"""
    total = input_tokens + output_tokens
    u_id = ObjectId(user_id) if isinstance(user_id, (str, bytes)) else user_id
    try:
        # Insert token usage record
        db.token_usage.insert_one({
            "user_id": u_id,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total,
            "model": model,
            "created_at": datetime.now()
        })

        # Update user total tokens
        db.users.update_one(
            {"_id": u_id},
            {
                "$inc": {
                    "total_tokens_used": total,
                    "total_messages": 1
                },
                "$set": {
                    "updated_at": datetime.now()
                }
            }
        )

        # Fetch updated user stats for logging
        user = db.users.find_one({"_id": u_id})

        # ── Real-time console log ──────────────────────────────────────────
        print("\n" + "="*55)
        print(f"  📊 TOKEN USAGE LOG")
        print("="*55)
        print(f"  👤 User     : {user['email']}")
        print(f"  📥 Input    : {input_tokens} tokens")
        print(f"  📤 Output   : {output_tokens} tokens")
        print(f"  🔢 This msg : {total} tokens")
        print(f"  📈 Total    : {user['total_tokens_used']} tokens (lifetime)")
        print(f"  💬 Messages : {user['total_messages']} total")
        print("="*55 + "\n")

    except Exception as e:
        print(f"❌ Token save error: {e}")

# ─── Request Handler ──────────────────────────────────────────────────────────
class ChatbotHandler(http.server.SimpleHTTPRequestHandler):

    def log_message(self, format, *args):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {format % args}")

    def log_error(self, format, *args):
        # Suppress noisy browser connection-drop messages (WinError 10054)
        msg = format % args
        if 'ConnectionResetError' in msg or '10054' in msg or 'BrokenPipeError' in msg:
            return
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ERROR: {msg}")

    def end_headers(self):
        # Restrict CORS to our own origin — not the whole internet
        origin = self.headers.get('Origin', '')
        allowed = f'http://localhost:{PORT}'
        self.send_header('Access-Control-Allow-Origin', allowed if origin.startswith('http://localhost') else allowed)
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Vary', 'Origin')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_POST(self):
        try:
            if   self.path == '/api/auth/register':          self.handle_register()
            elif self.path == '/api/auth/login':             self.handle_login()
            elif self.path == '/api/auth/google':            self.handle_google()
            elif self.path == '/api/auth/verify':            self.handle_verify()
            elif self.path == '/api/auth/logout':            self.handle_logout()
            elif self.path == '/api/claude':                 self.handle_claude()
            elif self.path == '/api/conversations/new':      self.handle_new_conversation()
            elif self.path == '/api/conversations/list':     self.handle_list_conversations()
            elif self.path == '/api/conversations/messages': self.handle_get_messages()
            elif self.path == '/api/conversations/delete':   self.handle_delete_conversation()
            elif self.path == '/api/conversations/rename':   self.handle_rename_conversation()
            elif self.path == '/api/admin/stats':            self.handle_admin_stats()
            else: self.send_json(404, {'error': 'Not found'})
        except Exception as e:
            print(f"❌ POST error: {e}")
            self.send_json(500, {'error': 'Internal server error'})

    # ── Conversation APIs ─────────────────────────────────────────────────────
    def get_user_from_token(self, token):
        """Helper: get user_id from session token"""
        if not token: return None
        db = get_db()
        if db is None: return None
        try:
            session = db.user_sessions.find_one({
                "session_token": token,
                "expires_at": {"$gt": datetime.now()}
            })
            if session:
                user = db.users.find_one({"_id": session['user_id'], "is_active": True})
                if user:
                    user['id'] = str(user['_id'])
                    return user
            return None
        except Exception as e:
            print(f"Error fetching user from session token: {e}")
            return None

    def handle_new_conversation(self):
        data  = self.read_body()
        token = data.get('session_token', '')
        title = data.get('title', 'New Chat')
        user  = self.get_user_from_token(token)
        if not user:
            return self.send_json(401, {'error': 'Unauthorized'})
        db = get_db()
        if db is None: return self.send_json(500, {'error': 'DB error'})
        try:
            conv_doc = {
                "user_id": ObjectId(user['id']),
                "title": title,
                "created_at": datetime.now(),
                "updated_at": datetime.now()
            }
            res = db.conversations.insert_one(conv_doc)
            conv_id = str(res.inserted_id)
            self.send_json(200, {'success': True, 'conversation_id': conv_id, 'title': title})
        except Exception as e:
            self.send_json(500, {'error': str(e)})

    def handle_list_conversations(self):
        data  = self.read_body()
        token = data.get('session_token', '')
        user  = self.get_user_from_token(token)
        if not user:
            return self.send_json(401, {'error': 'Unauthorized'})
        db = get_db()
        if db is None: return self.send_json(500, {'error': 'DB error'})
        try:
            # Query conversations owned by user sorted by updated_at desc
            convs = list(db.conversations.find({"user_id": ObjectId(user['id'])}).sort("updated_at", -1))
            
            conv_list = []
            for c in convs:
                # Count messages for this conversation
                msg_count = db.messages.count_documents({"conversation_id": c['_id']})
                
                c_created = c.get("created_at")
                c_updated = c.get("updated_at")
                
                conv_list.append({
                    "id": str(c['_id']),
                    "title": c.get("title", "New Conversation"),
                    "created_at": c_created.strftime('%Y-%m-%d %H:%M:%S') if isinstance(c_created, datetime) else str(c_created),
                    "updated_at": c_updated.strftime('%Y-%m-%d %H:%M:%S') if isinstance(c_updated, datetime) else str(c_updated),
                    "message_count": msg_count
                })
            
            self.send_json(200, {'conversations': conv_list})
        except Exception as e:
            self.send_json(500, {'error': str(e)})

    def handle_get_messages(self):
        data    = self.read_body()
        token   = data.get('session_token', '')
        conv_id = data.get('conversation_id')
        user    = self.get_user_from_token(token)
        if not user:
            return self.send_json(401, {'error': 'Unauthorized'})
        db = get_db()
        if db is None: return self.send_json(500, {'error': 'DB error'})
        try:
            c_id = ObjectId(conv_id) if isinstance(conv_id, str) else conv_id
            # Verify ownership
            conv = db.conversations.find_one({"_id": c_id, "user_id": ObjectId(user['id'])})
            if not conv:
                return self.send_json(403, {'error': 'Forbidden'})
                
            msgs = list(db.messages.find({"conversation_id": c_id}).sort("created_at", 1))
            msg_list = []
            for m in msgs:
                m_created = m.get("created_at")
                msg_list.append({
                    "role": m.get("role"),
                    "content": m.get("content"),
                    "created_at": m_created.strftime('%Y-%m-%d %H:%M:%S') if isinstance(m_created, datetime) else str(m_created)
                })
            self.send_json(200, {'messages': msg_list})
        except Exception as e:
            self.send_json(500, {'error': str(e)})

    def handle_delete_conversation(self):
        data    = self.read_body()
        token   = data.get('session_token', '')
        conv_id = data.get('conversation_id')
        user    = self.get_user_from_token(token)
        if not user:
            return self.send_json(401, {'error': 'Unauthorized'})
        db = get_db()
        if db is None: return self.send_json(500, {'error': 'DB error'})
        try:
            c_id = ObjectId(conv_id) if isinstance(conv_id, str) else conv_id
            
            # Verify ownership and delete conversation
            res = db.conversations.delete_one({"_id": c_id, "user_id": ObjectId(user['id'])})
            if res.deleted_count > 0:
                # Cascade delete associated messages
                db.messages.delete_many({"conversation_id": c_id})
                
            self.send_json(200, {'success': True})
        except Exception as e:
            self.send_json(500, {'error': str(e)})

    def handle_rename_conversation(self):
        data    = self.read_body()
        token   = data.get('session_token', '')
        conv_id = data.get('conversation_id')
        title   = data.get('title', 'New Chat')
        user    = self.get_user_from_token(token)
        if not user:
            return self.send_json(401, {'error': 'Unauthorized'})
        db = get_db()
        if db is None: return self.send_json(500, {'error': 'DB error'})
        try:
            c_id = ObjectId(conv_id) if isinstance(conv_id, str) else conv_id
            db.conversations.update_one(
                {"_id": c_id, "user_id": ObjectId(user['id'])},
                {"$set": {"title": title, "updated_at": datetime.now()}}
            )
            self.send_json(200, {'success': True})
        except Exception as e:
            self.send_json(500, {'error': str(e)})

    # ── Admin Stats API ───────────────────────────────────────────────────────
    def handle_admin_stats(self):
        data  = self.read_body()
        token = data.get('session_token', '')
        user  = self.get_user_from_token(token)
        
        if not user or not user.get('is_admin', False):
            return self.send_json(403, {'error': 'Forbidden: Admin access required'})

        db = get_db()
        if db is None:
            return self.send_json(500, {'error': 'Database unavailable'})
        try:
            # All users
            users = list(db.users.find())
            
            users_list = []
            for u in users:
                u_id = u['_id']
                conv_count = db.conversations.count_documents({"user_id": u_id})
                sess_count = db.user_sessions.count_documents({"user_id": u_id, "expires_at": {"$gt": datetime.now()}})
                
                u_ll = u.get("last_login")
                u_ca = u.get("created_at")
                
                users_list.append({
                    "id": str(u_id),
                    "email": u.get("email"),
                    "name": u.get("name"),
                    "login_method": u.get("login_method", "email"),
                    "total_tokens_used": u.get("total_tokens_used", 0),
                    "total_messages": u.get("total_messages", 0),
                    "last_login": u_ll.strftime('%Y-%m-%d %H:%M:%S') if isinstance(u_ll, datetime) else 'Never',
                    "created_at": u_ca.strftime('%Y-%m-%d %H:%M:%S') if isinstance(u_ca, datetime) else '',
                    "total_conversations": conv_count,
                    "active_sessions": sess_count
                })
            
            # Sort users by total tokens descend (same as MySQL table view)
            users_list.sort(key=lambda x: x['total_tokens_used'], reverse=True)

            # Summary counts
            total_users = len(users_list)
            grand_total = sum(u.get("total_tokens_used", 0) for u in users)
            total_msgs = sum(u.get("total_messages", 0) for u in users)
            active_sessions = db.user_sessions.count_documents({"expires_at": {"$gt": datetime.now()}})
            total_convs = db.conversations.count_documents({})

            # Recent activity logs
            recent = list(db.token_usage.find().sort("created_at", -1).limit(20))
            recent_list = []
            for r in recent:
                user_doc = db.users.find_one({"_id": r['user_id']})
                email = user_doc['email'] if user_doc else 'unknown'
                r_ca = r.get("created_at")
                recent_list.append({
                    "email": email,
                    "input_tokens": r.get("input_tokens", 0),
                    "output_tokens": r.get("output_tokens", 0),
                    "total_tokens": r.get("total_tokens", 0),
                    "created_at": r_ca.strftime('%Y-%m-%d %H:%M:%S') if isinstance(r_ca, datetime) else ''
                })

            # Active sessions
            sessions = list(db.user_sessions.find({"expires_at": {"$gt": datetime.now()}}).sort("created_at", -1))
            sessions_list = []
            for s in sessions:
                user_doc = db.users.find_one({"_id": s['user_id']})
                email = user_doc['email'] if user_doc else 'unknown'
                name = user_doc['name'] if user_doc else '-'
                s_ca = s.get("created_at")
                s_ea = s.get("expires_at")
                sessions_list.append({
                    "email": email,
                    "name": name,
                    "ip_address": s.get("ip_address", "unknown"),
                    "created_at": s_ca.strftime('%Y-%m-%d %H:%M:%S') if isinstance(s_ca, datetime) else '',
                    "expires_at": s_ea.strftime('%Y-%m-%d %H:%M:%S') if isinstance(s_ea, datetime) else ''
                })

            self.send_json(200, {
                'users': users_list,
                'summary': {
                    'total_users': total_users,
                    'grand_total_tokens': int(grand_total),
                    'total_messages': int(total_msgs),
                    'active_sessions': active_sessions,
                    'total_conversations': total_convs
                },
                'recent_activity': recent_list,
                'active_sessions': sessions_list
            })
        except Exception as e:
            print(f"❌ Admin stats error: {e}")
            self.send_json(500, {'error': str(e)})

    def handle_proxy_image(self):
        self.send_json(403, {'error': 'Image generation is currently disabled'})

    def read_body(self):
        length = int(self.headers.get('Content-Length', 0))
        return json.loads(self.rfile.read(length).decode('utf-8')) if length else {}

    # ── Register ──────────────────────────────────────────────────────────────
    def handle_register(self):
        # Rate limit: 5 registrations per IP per 10 minutes
        if is_rate_limited(self.client_address[0], 'register', limit=5, window=600):
            return self.send_json(429, {'success': False, 'error': 'Too many requests. Please wait a few minutes.'})

        data = self.read_body()
        email    = data.get('email', '').strip().lower()
        password = data.get('password', '').strip()
        name     = data.get('name', '').strip()

        if not email or not password or not name:
            return self.send_json(400, {'success': False, 'error': 'All fields required'})

        if len(password) < 6:
            return self.send_json(400, {'success': False, 'error': 'Password must be at least 6 characters'})

        # Domain restriction - server side standard registration
        domain = email.split('@')[-1].lower() if '@' in email else ''
        if domain not in ['cutmap.ac.in', 'cutm.ac.in']:
            print(f"❌ Blocked standard register: {email}")
            return self.send_json(403, {
                'success': False,
                'error': 'Access denied. Only institutional domains (@cutmap.ac.in and @cutm.ac.in) are allowed.'
            })

        db = get_db()
        if db is None:
            return self.send_json(500, {'success': False, 'error': 'Database unavailable'})

        try:
            # Check existing user
            existing = db.users.find_one({"email": email})
            if existing:
                return self.send_json(409, {'success': False, 'error': 'Email already registered'})

            # Create user
            pw_hash = hash_password(password)
            user_doc = {
                "email": email,
                "password_hash": pw_hash,
                "name": name,
                "profile_picture": None,
                "login_method": "email",
                "is_active": True,
                "is_admin": False,
                "total_tokens_used": 0,
                "total_messages": 0,
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
                "last_login": datetime.now()
            }
            res = db.users.insert_one(user_doc)
            user_id = res.inserted_id

            token = create_session(db, user_id,
                                   self.client_address[0],
                                   self.headers.get('User-Agent'))

            print(f"✅ New user registered: {email}")
            self.send_json(201, {
                'success': True,
                'user': {'id': str(user_id), 'email': email, 'name': name,
                         'login_method': 'email', 'profile_picture': None, 'is_admin': False},
                'session_token': token
            })
        except Exception as e:
            print(f"❌ Register error: {e}")
            self.send_json(500, {'success': False, 'error': 'Registration failed'})

    # ── Login ─────────────────────────────────────────────────────────────────
    def handle_login(self):
        # Rate limit: 10 attempts per IP per 60 seconds (brute-force guard)
        if is_rate_limited(self.client_address[0], 'login', limit=10, window=60):
            return self.send_json(429, {'success': False, 'error': 'Too many login attempts. Please wait 60 seconds.'})

        data = self.read_body()
        email    = data.get('email', '').strip().lower()
        password = data.get('password', '').strip()

        if not email or not password:
            return self.send_json(400, {'success': False, 'error': 'Email and password required'})

        db = get_db()
        if db is None:
            return self.send_json(500, {'success': False, 'error': 'Database unavailable'})

        try:
            user = db.users.find_one({"email": email, "is_active": True})

            if not user or not user.get('password_hash') or not verify_password(password, user['password_hash']):
                return self.send_json(401, {'success': False, 'error': 'Invalid email or password'})

            # Update last login
            db.users.update_one(
                {"_id": user['_id']},
                {"$set": {"last_login": datetime.now(), "updated_at": datetime.now()}}
            )

            token = create_session(db, user['_id'],
                                   self.client_address[0],
                                   self.headers.get('User-Agent'))

            print(f"✅ Login: {email}")
            self.send_json(200, {
                'success': True,
                'user': {
                    'id': str(user['_id']), 'email': user['email'],
                    'name': user.get('name'), 'login_method': user.get('login_method', 'email'),
                    'profile_picture': user.get('profile_picture'),
                    'is_admin': user.get('is_admin', False)
                },
                'session_token': token
            })
        except Exception as e:
            print(f"❌ Login error: {e}")
            self.send_json(500, {'success': False, 'error': 'Login failed'})

    # ── Google Auth (server-side JWT verification) ────────────────────────────
    def handle_google(self):
        # Rate limit: 10 Google auth attempts per IP per 60 seconds
        if is_rate_limited(self.client_address[0], 'google', limit=10, window=60):
            return self.send_json(429, {'success': False, 'error': 'Too many requests. Please wait.'})

        data       = self.read_body()
        credential = data.get('credential', '')   # raw Google JWT (preferred)
        google_id  = data.get('google_id', '')    # fallback: pre-decoded sub
        email      = data.get('email', '').strip().lower()
        name       = data.get('name', '')
        picture    = data.get('picture', '')

        # ── Verify the Google JWT server-side ─────────────────────────────────
        if credential and GOOGLE_CLIENT_ID:
            try:
                from google.oauth2 import id_token
                from google.auth.transport import requests as g_requests
                id_info = id_token.verify_oauth2_token(
                    credential,
                    g_requests.Request(),
                    GOOGLE_CLIENT_ID,
                    clock_skew_in_seconds=10
                )
                # Override with verified values — never trust client-supplied data
                google_id = id_info['sub']
                email     = id_info['email'].strip().lower()
                name      = id_info.get('name', name)
                picture   = id_info.get('picture', picture)
                print(f"✅ Google JWT verified for: {email}")
            except Exception as verify_err:
                print(f"❌ Google JWT verification failed: {verify_err}")
                return self.send_json(401, {'success': False, 'error': 'Google token verification failed. Please sign in again.'})
        elif not google_id or not email:
            return self.send_json(400, {'success': False, 'error': 'Missing Google credential data'})
        else:
            # credential not sent AND no GOOGLE_CLIENT_ID configured — log warning
            print('⚠️  Google login: JWT not verified (GOOGLE_CLIENT_ID not set or credential not provided)')

        # Domain restriction — server side
        domain = email.split('@')[-1].lower() if '@' in email else ''
        if domain not in ['cutmap.ac.in', 'cutm.ac.in']:
            print(f"❌ Blocked Google login: {email}")
            return self.send_json(403, {
                'success': False,
                'error': 'Access denied. Only @cutmap.ac.in and @cutm.ac.in are allowed.'
            })

        db = get_db()
        if db is None:
            return self.send_json(500, {'success': False, 'error': 'Database unavailable'})

        try:
            # Lookup by verified Google ID first, then fall back to email
            user = db.users.find_one({"google_id": google_id})

            if not user:
                user = db.users.find_one({"email": email})
                if user:
                    # Link Google ID to existing email account
                    db.users.update_one(
                        {"_id": user['_id']},
                        {"$set": {
                            "google_id": google_id,
                            "name": name,
                            "profile_picture": picture,
                            "login_method": 'google',
                            "updated_at": datetime.now()
                        }}
                    )
                    user = db.users.find_one({"_id": user['_id']})
                else:
                    # Create new Google user
                    res = db.users.insert_one({
                        "email": email,
                        "name": name,
                        "profile_picture": picture,
                        "login_method": "google",
                        "google_id": google_id,
                        "is_active": True,
                        "is_admin": False,
                        "total_tokens_used": 0,
                        "total_messages": 0,
                        "created_at": datetime.now(),
                        "updated_at": datetime.now(),
                        "last_login": datetime.now()
                    })
                    user = db.users.find_one({"_id": res.inserted_id})

            # Update last login timestamp
            db.users.update_one(
                {"_id": user['_id']},
                {"$set": {"last_login": datetime.now(), "updated_at": datetime.now()}}
            )

            token = create_session(db, user['_id'],
                                   self.client_address[0],
                                   self.headers.get('User-Agent'))

            print(f"✅ Google login: {email}")
            self.send_json(200, {
                'success': True,
                'user': {
                    'id': str(user['_id']), 'email': user['email'],
                    'name': user.get('name'), 'login_method': 'google',
                    'profile_picture': user.get('profile_picture'),
                    'is_admin': user.get('is_admin', False)
                },
                'session_token': token
            })
        except Exception as e:
            print(f"❌ Google auth error: {e}")
            self.send_json(500, {'success': False, 'error': 'Google authentication failed'})

    # ── Verify Session ────────────────────────────────────────────────────────
    def handle_verify(self):
        data  = self.read_body()
        token = data.get('session_token', '')

        if not token:
            return self.send_json(400, {'valid': False, 'error': 'Token required'})

        db = get_db()
        if db is None:
            return self.send_json(500, {'valid': False, 'error': 'Database unavailable'})

        try:
            session = db.user_sessions.find_one({
                "session_token": token,
                "expires_at": {"$gt": datetime.now()}
            })
            if session:
                user = db.users.find_one({"_id": session['user_id'], "is_active": True})
                if user:
                    return self.send_json(200, {
                        'valid': True,
                        'user': {
                            'id': str(user['_id']), 'email': user['email'],
                            'name': user.get('name'), 'login_method': user.get('login_method', 'email'),
                            'profile_picture': user.get('profile_picture'),
                            'is_admin': user.get('is_admin', False)
                        }
                    })
            self.send_json(401, {'valid': False, 'error': 'Invalid or expired session'})
        except Exception as e:
            print(f"❌ Verify error: {e}")
            self.send_json(500, {'valid': False, 'error': 'Verification failed'})

    # ── Logout ────────────────────────────────────────────────────────────────
    def handle_logout(self):
        data  = self.read_body()
        token = data.get('session_token', '')

        db = get_db()
        if db is not None and token:
            try:
                db.user_sessions.delete_one({"session_token": token})
                print(f"✅ Logged out session: {token[:20]}...")
            except Exception as e:
                print(f"❌ Logout error: {e}")

        self.send_json(200, {'success': True})

    # ── Claude API ────────────────────────────────────────────────────────────
    def handle_claude(self):
        # Rate limit: 30 Claude messages per IP per 60 seconds (abuse/cost guard)
        if is_rate_limited(self.client_address[0], 'claude', limit=30, window=60):
            return self.send_json(429, {'error': 'Rate limit reached. Please slow down.'})

        data = self.read_body()

        session_token = data.get('session_token', '')
        conv_id       = data.get('conversation_id')
        user_message  = data.get('user_message', '')
        user_info     = self.get_user_from_token(session_token)
        user_id       = ObjectId(user_info['id']) if user_info else None

        db = get_db()

        # Auto-create conversation if none provided
        if db is not None and user_id and not conv_id:
            try:
                # Generate title from first message (first 40 chars)
                title = (user_message[:40] + '...') if len(user_message) > 40 else user_message or 'New Chat'
                conv_doc = {
                    "user_id": user_id,
                    "title": title,
                    "created_at": datetime.now(),
                    "updated_at": datetime.now()
                }
                res = db.conversations.insert_one(conv_doc)
                conv_id = str(res.inserted_id)
            except Exception as e:
                print(f"Auto-conversation creation failed: {e}")

        # Helper functions for Token Optimization
        def trim_messages(messages_list, max_messages=20):
            """Trims message history to optimize tokens. Ensures alternating user/assistant roles."""
            if not messages_list:
                return []
            if len(messages_list) <= max_messages:
                return messages_list
            trimmed = messages_list[-max_messages:]
            if trimmed and trimmed[0].get('role') == 'assistant':
                trimmed = trimmed[1:]
            return trimmed

        def summarize_history(messages_list):
            """Generates a high-density 2-3 sentence summary of older messages using Haiku."""
            active_key = api_key_rotator.get_key()
            if not active_key:
                return None
            try:
                summary_prompt = "You are an assistant that summarizes the provided conversation history into a very brief, high-density summary (2-3 sentences max) highlighting key contexts, decisions, and facts."
                payload = json.dumps({
                    'model': 'claude-3-5-haiku-20241022',
                    'max_tokens': 300,
                    'system': summary_prompt,
                    'messages': messages_list + [{'role': 'user', 'content': 'Summarize the context of this conversation so far in 2-3 sentences.'}]
                }).encode('utf-8')
                
                req_obj = urllib.request.Request(
                    'https://api.anthropic.com/v1/messages',
                    data=payload,
                    headers={
                        'Content-Type': 'application/json',
                        'x-api-key': active_key,
                        'anthropic-version': '2023-06-01'
                    }
                )
                with urllib.request.urlopen(req_obj) as resp_obj:
                    resp_json = json.loads(resp_obj.read())
                    if resp_json.get('content') and resp_json['content'][0].get('text'):
                        return resp_json['content'][0]['text']
            except Exception as se:
                print(f"⚠️ Summarization failed: {se}")
            return None

        # Compressed system prompt (43% fewer words/tokens for premium performance)
        system_instructions = (
            "You are CUTM AI, a helpful, premium AI assistant developed for Centurion University of Technology and Management (CUTM). "
            "Always use proper markdown code blocks with language tags for code. "
            "Note: Image generation is currently disabled. If the user asks you to draw, paint, generate, or create an image/graphic, "
            "politely inform them that this feature is currently disabled."
        )

        messages = data.get('messages', [])
        
        # Apply Smart Summarization & Context Trimming
        if len(messages) > 30:
            messages_to_summarize = messages[:-15]
            recent_messages = messages[-15:]
            if recent_messages and recent_messages[0].get('role') == 'assistant':
                recent_messages = recent_messages[1:]
                
            summary = summarize_history(messages_to_summarize)
            if summary:
                system_instructions += f"\n\nHere is a summary of the earlier part of the conversation for your context:\n{summary}"
            messages = recent_messages
        else:
            messages = trim_messages(messages, max_messages=20)

        # Respect the model chosen in the frontend dropdown; fall back to Haiku
        chosen_model = data.get('model', 'claude-haiku-4-5')
        claude_payload = json.dumps({
            'model': chosen_model,
            'max_tokens': data.get('max_tokens', 4096),
            'system': system_instructions,
            'messages': messages
        }).encode('utf-8')

        active_key = api_key_rotator.get_key()
        if not active_key:
            return self.send_json(500, {'error': 'No API keys configured'})

        try:
            req = urllib.request.Request(
                'https://api.anthropic.com/v1/messages',
                data=claude_payload,
                headers={
                    'Content-Type': 'application/json',
                    'x-api-key': active_key,
                    'anthropic-version': '2023-06-01'
                }
            )

            with urllib.request.urlopen(req) as resp:
                response_data = resp.read()
                response_json = json.loads(response_data)

                assistant_text = ''
                if response_json.get('content'):
                    assistant_text = response_json['content'][0].get('text', '')

                # Save messages to DB
                if db is not None and user_id and conv_id and user_message:
                    try:
                        c_id = ObjectId(conv_id) if isinstance(conv_id, str) else conv_id
                        # Save user message
                        db.messages.insert_one({
                            "conversation_id": c_id,
                            "user_id": user_id,
                            "role": 'user',
                            "content": user_message,
                            "created_at": datetime.now()
                        })
                        # Save assistant response
                        if assistant_text:
                            db.messages.insert_one({
                                "conversation_id": c_id,
                                "user_id": user_id,
                                "role": 'assistant',
                                "content": assistant_text,
                                "created_at": datetime.now()
                            })
                        # Update conversation timestamp
                        db.conversations.update_one(
                            {"_id": c_id},
                            {"$set": {"updated_at": datetime.now()}}
                        )

                        # Save token usage
                        usage = response_json.get('usage', {})
                        save_token_usage(db, user_id, usage.get('input_tokens', 0), usage.get('output_tokens', 0), data.get('model', 'claude-3-5-sonnet-20241022'))
                    except Exception as e:
                        print(f"❌ Message save error: {e}")

                # Add conversation_id to response
                response_json['conversation_id'] = str(conv_id)

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(response_json).encode('utf-8'))

        except urllib.error.HTTPError as e:
            err = e.read().decode('utf-8')
            print(f"❌ Claude API error: {e.code} - {err}")
            self.send_response(e.code)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(err.encode('utf-8'))

        except Exception as e:
            print(f"❌ Claude error: {e}")
            self.send_json(500, {'error': str(e)})

    # ── Serve HTML files ──────────────────────────────────────────────────────
    def do_GET(self):
        if self.path.startswith('/api/proxy/image'):
            self.handle_proxy_image()
            return

        routes = {
            '/':            'login.html',
            '/login.html':  'login.html',
            '/index.html':  'index.html',
            '/signup.html': 'signup.html',
            '/admin':       'admin.html',
            '/admin.html':  'admin.html',
        }
        filename = routes.get(self.path)



        if filename:
            try:
                base_dir = os.path.dirname(os.path.abspath(__file__))
                full_path = os.path.join(base_dir, filename)
                with open(full_path, 'rb') as f:
                    content = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html')
                self.end_headers()
                self.wfile.write(content)
            except FileNotFoundError:
                self.send_error(404, f"{filename} not found")
        else:
            try:
                super().do_GET()
            except:
                self.send_error(404, "Not found")

    # ── JSON helper ───────────────────────────────────────────────────────────
    def send_json(self, status, data):
        try:
            body = json.dumps(data).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            print(f"❌ send_json error: {e}")


# ─── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    print("🚀 Starting CUTM AI Chatbot Server...")

    # Test DB connection
    db = get_db()
    if db is not None:
        try:
            db.command('ping')
            print("✅ MongoDB database connected successfully")
        except Exception as e:
            print(f"⚠️  MongoDB connection failed: {e}")
    else:
        print("⚠️  MongoDB not connected - check credentials in MONGO_URI")

    class ThreadedServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
        allow_reuse_address = True
        daemon_threads = True  # clean shutdown on Ctrl+C

        def handle_error(self, request, client_address):
            import sys
            exc_type, exc_val, _ = sys.exc_info()
            # Silently ignore browser connection drops (very common, not real errors)
            if exc_type in (ConnectionResetError, BrokenPipeError):
                return
            if exc_type is OSError and getattr(exc_val, 'winerror', None) == 10054:
                return
            super().handle_error(request, client_address)

    with ThreadedServer(("", PORT), ChatbotHandler) as httpd:
        print(f"🌐 Server running at http://localhost:{PORT}")
        print("📊 Token usage will be tracked in MongoDB Atlas")
        print("Press Ctrl+C to stop\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n🛑 Server stopped")
            httpd.shutdown()
