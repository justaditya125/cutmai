"""
Authentication routes
"""
import json
import os
import secrets
from datetime import datetime, timedelta
from botai.config import settings
from botai.config.mysql_config import get_db
from botai.utils.auth_utils import hash_password, verify_password
from botai.utils.validators import validate_email
from botai.utils.logger import log_suspicious_activity
from botai.utils.rate_limiter import is_rate_limited

def create_session(db, user_id, ip=None, ua=None):
    token = secrets.token_urlsafe(32)
    expires = datetime.now() + timedelta(days=30)
    u_id = user_id
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
        print(f"[ERROR] Session error: {e}")
        return None

def get_user_quota_info(db, user_id, user_doc=None):
    """Calculates and returns user's token usage, limit, balance, and credits consumed."""
    from botai.capabilities.model_orchestration.cost_estimator import cost_estimator
    if user_doc is None:
        user_doc = db.users.find_one({"_id": user_id})
    if not user_doc:
        return None
    
    # Calculate user credits
    credits = 0.0
    try:
        user_tokens = list(db.token_usage.find({"user_id": user_id}))
        for r in user_tokens:
            m = r.get("model", "")
            in_t = r.get("input_tokens", 0)
            out_t = r.get("output_tokens", 0)
            c_write = r.get("cache_creation_input_tokens", 0)
            c_read = r.get("cache_read_input_tokens", 0)
            
            est = cost_estimator.estimate(m, in_t, out_t, c_write, c_read)
            credits += est['total_cost']
    except Exception as ex:
        print(f"Error calculating credits for user {user_id}: {ex}")

    total_tokens = user_doc.get("total_tokens_used") or 0
    limit = user_doc.get("token_limit") or 1000000
    balance = max(0, limit - total_tokens)
    
    return {
        'total_tokens_used': total_tokens,
        'token_limit': limit,
        'token_balance': balance,
        'credits_used': credits
    }

def handle_post(handler):
    path = handler.path
    if path == '/api/auth/register':
        handle_register(handler)
    elif path == '/api/auth/login':
        handle_login(handler)
    elif path == '/api/auth/google':
        handle_google(handler)
    elif path == '/api/auth/verify':
        handle_verify(handler)
    elif path == '/api/auth/logout':
        handle_logout(handler)
    else:
        handler.send_json(404, {'error': 'Not found'})

def handle_register(handler):
    client_ip = handler.get_client_ip()
    # Rate limit: 5 registrations per IP per 10 minutes
    if is_rate_limited(client_ip, 'register', limit=5, window=600):
        return handler.send_json(429, {'success': False, 'error': 'Too many requests. Please wait a few minutes.'})

    data = handler.read_body()
    email    = data.get('email', '').strip().lower()
    password = data.get('password', '').strip()
    name     = data.get('name', '').strip()

    if not email or not password or not name:
        return handler.send_json(400, {'success': False, 'error': 'All fields required'})

    if len(password) < 6:
        return handler.send_json(400, {'success': False, 'error': 'Password must be at least 6 characters'})

    # Domain restriction
    domain = email.split('@')[-1].lower() if '@' in email else ''
    if domain not in settings.ALLOWED_DOMAINS:
        log_suspicious_activity(email, "Blocked Registration", f"Standard registration attempt from non-institutional domain from IP {client_ip}", "MEDIUM")
        print(f"[BLOCKED] Blocked standard register: {email}")
        return handler.send_json(403, {
            'success': False,
            'error': 'Access denied. Only institutional domains (@cutmap.ac.in and @cutm.ac.in) are allowed.'
        })

    db = get_db()
    if db is None:
        return handler.send_json(500, {'success': False, 'error': 'Database unavailable'})

    try:
        # Check existing user
        existing = db.users.find_one({"email": email})
        if existing:
            return handler.send_json(409, {'success': False, 'error': 'Email already registered'})

        # Create user
        pw_hash = hash_password(password)
        user_doc = {
            "email": email,
            "password_hash": pw_hash,
            "name": name,
            "profile_picture": None,
            "login_method": "email",
            "is_approved": True,
            "token_limit": 1000000,
            "is_active": True,
            "is_admin": False,
            "total_tokens_used": 0,
            "total_messages": 0,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
            "last_login": datetime.now()
        }
        try:
            res = db.users.insert_one(user_doc)
            user_id = res.inserted_id
        except Exception as insert_err:
            if 'Duplicate' in str(insert_err) or '1062' in str(insert_err):
                return handler.send_json(409, {'success': False, 'error': 'Email already registered'})
            raise

        token = create_session(db, user_id, client_ip, handler.headers.get('User-Agent'))
        print(f"[OK] New user registered and logged in: {email}")
        handler.send_json(201, {
            'success': True,
            'user': {
                'id': user_id,
                'email': email,
                'name': name,
                'login_method': 'email',
                'profile_picture': None,
                'is_admin': False
            },
            'session_token': token,
            'message': 'Account created successfully!'
        })
    except Exception as e:
        print(f"[ERROR] Register error: {e}")
        handler.send_json(500, {'success': False, 'error': 'Registration failed'})

def handle_login(handler):
    client_ip = handler.get_client_ip()
    # Rate limit: 10 attempts per IP per 60 seconds
    if is_rate_limited(client_ip, 'login', limit=10, window=60):
        return handler.send_json(429, {'success': False, 'error': 'Too many login attempts. Please wait 60 seconds.'})

    data = handler.read_body()
    email    = data.get('email', '').strip().lower()
    password = data.get('password', '').strip()

    if not email or not password:
        return handler.send_json(400, {'success': False, 'error': 'Email and password required'})

    db = get_db()
    if db is None:
        return handler.send_json(500, {'success': False, 'error': 'Database unavailable'})

    try:
        user = db.users.find_one({"email": email, "is_active": True})

        if not user or not user.get('password_hash') or not verify_password(password, user['password_hash']):
            log_suspicious_activity(email or client_ip, "Failed Login", f"Incorrect password attempt for standard login from IP {client_ip}", "LOW")
            return handler.send_json(401, {'success': False, 'error': 'Invalid email or password'})

        # Update last login
        db.users.update_one(
            {"_id": user['_id']},
            {"$set": {"last_login": datetime.now(), "updated_at": datetime.now()}}
        )

        token = create_session(db, user['_id'],
                               client_ip,
                               handler.headers.get('User-Agent'))

        print(f"[OK] Login: {email}")
        handler.send_json(200, {
            'success': True,
            'user': {
                'id': user['_id'], 'email': user['email'],
                'name': user.get('name'), 'login_method': user.get('login_method', 'email'),
                'profile_picture': user.get('profile_picture'),
                'is_admin': user.get('is_admin', False)
            },
            'session_token': token
        })
    except Exception as e:
        print(f"[ERROR] Login error: {e}")
        handler.send_json(500, {'success': False, 'error': 'Login failed'})

def handle_google(handler):
    client_ip = handler.get_client_ip()
    # Rate limit: 10 Google auth attempts per IP per 60 seconds
    if is_rate_limited(client_ip, 'google', limit=10, window=60):
        return handler.send_json(429, {'success': False, 'error': 'Too many requests. Please wait.'})

    data       = handler.read_body()
    credential = data.get('credential', '')
    google_id  = data.get('google_id', '')
    email      = data.get('email', '').strip().lower()
    name       = data.get('name', '')
    picture    = data.get('picture', '')

    # Verify the Google JWT server-side
    google_client_id = settings.GOOGLE_CLIENT_ID
    if credential and google_client_id:
        try:
            from google.oauth2 import id_token
            from google.auth.transport import requests as g_requests
            id_info = id_token.verify_oauth2_token(
                credential,
                g_requests.Request(),
                google_client_id,
                clock_skew_in_seconds=10
            )
            google_id = id_info['sub']
            email     = id_info['email'].strip().lower()
            name      = id_info.get('name', name)
            picture   = id_info.get('picture', picture)
            print(f"[OK] Google JWT verified for: {email}")
        except Exception as verify_err:
            print(f"[ERROR] Google JWT verification failed: {verify_err}")
            return handler.send_json(401, {'success': False, 'error': 'Google token verification failed. Please sign in again.'})
    elif not google_id or not email:
        return handler.send_json(400, {'success': False, 'error': 'Missing Google credential data'})
    else:
        print('[WARN] Google login: JWT not verified (GOOGLE_CLIENT_ID not set or credential not provided)')
        return handler.send_json(401, {'success': False, 'error': 'Google sign-in verification unavailable. Please try again later.'})

    # Domain restriction
    domain = email.split('@')[-1].lower() if '@' in email else ''
    if domain not in settings.ALLOWED_DOMAINS:
        log_suspicious_activity(email, "Blocked Google Auth", f"Google auth attempt from non-institutional domain from IP {client_ip}", "MEDIUM")
        print(f"[BLOCKED] Blocked Google login: {email}")
        return handler.send_json(403, {
            'success': False,
            'error': 'Access denied. Only @cutmap.ac.in and @cutm.ac.in are allowed.'
        })

    db = get_db()
    if db is None:
        return handler.send_json(500, {'success': False, 'error': 'Database unavailable'})

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
                result = db.users.insert_one({
                    "email": email,
                    "name": name,
                    "profile_picture": picture,
                    "login_method": "google",
                    "google_id": google_id,
                    "is_approved": True,
                    "token_limit": 1000000,
                    "is_active": True,
                    "is_admin": False,
                    "total_tokens_used": 0,
                    "total_messages": 0,
                    "created_at": datetime.now(),
                    "updated_at": datetime.now(),
                    "last_login": datetime.now()
                })
                user_id = result.inserted_id
                token = create_session(db, user_id, client_ip, handler.headers.get('User-Agent'))
                print(f"[OK] New Google user registered and logged in: {email}")
                return handler.send_json(200, {
                    'success': True,
                    'user': {
                        'id': user_id,
                        'email': email,
                        'name': name,
                        'login_method': 'google',
                        'profile_picture': picture,
                        'is_admin': False
                    },
                    'session_token': token,
                    'message': 'Account created successfully!'
                })

        # Update last login timestamp
        db.users.update_one(
            {"_id": user['_id']},
            {"$set": {"last_login": datetime.now(), "updated_at": datetime.now()}}
        )

        token = create_session(db, user['_id'],
                               client_ip,
                               handler.headers.get('User-Agent'))

        print(f"[OK] Google login: {email}")
        handler.send_json(200, {
            'success': True,
            'user': {
                'id': user['_id'], 'email': user['email'],
                'name': user.get('name'), 'login_method': 'google',
                'profile_picture': user.get('profile_picture'),
                'is_admin': user.get('is_admin', False)
            },
            'session_token': token
        })
    except Exception as e:
        print(f"[ERROR] Google auth error: {e}")
        handler.send_json(500, {'success': False, 'error': 'Google authentication failed'})

def handle_verify(handler):
    data  = handler.read_body()
    token = data.get('session_token', '')

    if not token:
        return handler.send_json(400, {'valid': False, 'error': 'Token required'})

    db = get_db()
    if db is None:
        return handler.send_json(500, {'valid': False, 'error': 'Database unavailable'})

    try:
        session = db.user_sessions.find_one({
            "session_token": token,
            "expires_at": {"$gt": datetime.now()}
        })
        if session:
            user = db.users.find_one({"_id": session['user_id'], "is_active": True})
            if user:
                quota = get_user_quota_info(db, user['_id'], user) or {}
                return handler.send_json(200, {
                    'valid': True,
                    'user': {
                        'id': user['_id'], 'email': user['email'],
                        'name': user.get('name'), 'login_method': user.get('login_method', 'email'),
                        'profile_picture': user.get('profile_picture'),
                        'is_admin': user.get('is_admin', False),
                        'total_tokens_used': quota.get('total_tokens_used', 0),
                        'token_limit': quota.get('token_limit', 1000000),
                        'token_balance': quota.get('token_balance', 1000000),
                        'credits_used': quota.get('credits_used', 0.0)
                    }
                })
        handler.send_json(401, {'valid': False, 'error': 'Invalid or expired session'})
    except Exception as e:
        print(f"[ERROR] Verify error: {e}")
        handler.send_json(500, {'valid': False, 'error': 'Verification failed'})

def handle_logout(handler):
    data  = handler.read_body()
    token = data.get('session_token', '')

    db = get_db()
    if db is not None and token:
        try:
            db.user_sessions.delete_one({"session_token": token})
            print(f"[OK] Logged out session: {token[:20]}...")
        except Exception as e:
            print(f"[ERROR] Logout error: {e}")

    handler.send_json(200, {'success': True})
