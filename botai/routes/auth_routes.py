"""
Authentication routes
"""
import json
import os
import secrets
from datetime import datetime, timedelta
from botai.config import settings
from botai.config.mysql_config import get_db
from botai.utils.auth_utils import hash_password, verify_password, needs_rehash
from botai.utils.validators import validate_email, validate_password_strength
from botai.utils.logger import log_suspicious_activity
from botai.utils.rate_limiter import is_rate_limited
from botai.routes.chat_routes import get_user_quota_info as _chat_quota_info

def create_session(db, user_id, ip=None, ua=None):
    token = secrets.token_urlsafe(32)
    expires = datetime.now() + timedelta(days=30)
    now = datetime.now()
    u_id = user_id
    try:
        db.user_sessions.insert_one({
            "user_id": u_id,
            "session_token": token,
            "expires_at": expires,
            "created_at": now,
            "last_activity": now,
            "ip_address": ip,
            "user_agent": ua
        })
        return token
    except Exception as e:
        print(f"[ERROR] Session error: {e}")
        return None


def _session_cookie(token: str, max_age_days: int = 30, secure: bool = False) -> str:
    """Build a Set-Cookie header value for the session token (HttpOnly; Secure only for HTTPS).

    Default secure=False because dev server runs on HTTP.
    Set to True in production behind TLS (nginx/Cloudflare).
    """
    max_age = max_age_days * 86400
    secure_flag = "; Secure" if secure else ""
    return (
        f"session_token={token}; "
        f"Path=/; "
        f"Max-Age={max_age}; "
        f"HttpOnly; "
        f"SameSite=Strict"
        f"{secure_flag}"
    )


def _csrf_cookie() -> str:
    """Build a Set-Cookie header value for the CSRF token (NOT HttpOnly — JS must read it)."""
    import secrets as _secrets
    token = _secrets.token_hex(32)
    max_age = 30 * 86400
    return (
        f"csrf_token={token}; "
        f"Path=/; "
        f"Max-Age={max_age}; "
        f"SameSite=Strict"
    )

# Import quota info from chat_routes to avoid duplication
get_user_quota_info = _chat_quota_info

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
    elif path == '/api/auth/change_password':
        handle_change_password(handler)
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

    if not validate_email(email):
        return handler.send_json(400, {'success': False, 'error': 'Invalid email address'})

    pw_ok, pw_err = validate_password_strength(password)
    if not pw_ok:
        return handler.send_json(400, {'success': False, 'error': pw_err})

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
        if not token:
            return handler.send_json(500, {'success': False, 'error': 'Failed to create session'})
        print(f"[OK] New user registered and logged in: {email}")
        cookie = _session_cookie(token)
        csrf = _csrf_cookie()
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
        }, set_cookie=cookie, extra_cookies=[csrf])
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

        # Rehash password if using old format
        if needs_rehash(user['password_hash']):
            new_hash = hash_password(password)
            db.users.update_one({"_id": user['_id']}, {"$set": {"password_hash": new_hash}})

        # Update last login
        db.users.update_one(
            {"_id": user['_id']},
            {"$set": {"last_login": datetime.now(), "updated_at": datetime.now()}}
        )

        token = create_session(db, user['_id'],
                               client_ip,
                               handler.headers.get('User-Agent'))
        if not token:
            return handler.send_json(500, {'success': False, 'error': 'Failed to create session'})

        print(f"[OK] Login: {email}")
        cookie = _session_cookie(token)
        csrf = _csrf_cookie()
        handler.send_json(200, {
            'success': True,
            'user': {
                'id': user['_id'], 'email': user['email'],
                'name': user.get('name'), 'login_method': user.get('login_method', 'email'),
                'profile_picture': user.get('profile_picture'),
                'is_admin': user.get('is_admin', False)
            },
            'session_token': token
        }, set_cookie=cookie, extra_cookies=[csrf])
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
        return handler.send_json(503, {'success': False, 'error': 'Google sign-in is not configured on this server.'})

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
                if not token:
                    return handler.send_json(500, {'success': False, 'error': 'Failed to create session'})
                print(f"[OK] New Google user registered and logged in: {email}")
                cookie = _session_cookie(token)
                csrf = _csrf_cookie()
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
                }, set_cookie=cookie, extra_cookies=[csrf])

        # Update last login timestamp
        db.users.update_one(
            {"_id": user['_id']},
            {"$set": {"last_login": datetime.now(), "updated_at": datetime.now()}}
        )

        token = create_session(db, user['_id'],
                               client_ip,
                               handler.headers.get('User-Agent'))
        if not token:
            return handler.send_json(500, {'success': False, 'error': 'Failed to create session'})

        print(f"[OK] Google login: {email}")
        cookie = _session_cookie(token)
        csrf = _csrf_cookie()
        handler.send_json(200, {
            'success': True,
            'user': {
                'id': user['_id'], 'email': user['email'],
                'name': user.get('name'), 'login_method': 'google',
                'profile_picture': user.get('profile_picture'),
                'is_admin': user.get('is_admin', False)
            },
            'session_token': token
        }, set_cookie=cookie, extra_cookies=[csrf])
    except Exception as e:
        print(f"[ERROR] Google auth error: {e}")
        handler.send_json(500, {'success': False, 'error': 'Google authentication failed'})

def handle_verify(handler):
    # Use get_user_from_token which reads HttpOnly cookie first (no body token needed)
    # It returns the full user document on success
    user_doc = handler.get_user_from_token('')
    if user_doc is None:
        return handler.send_json(401, {'valid': False, 'error': 'Not authenticated'})

    db = get_db()
    try:
        quota = get_user_quota_info(db, user_doc['_id'], user_doc) or {}
        return handler.send_json(200, {
            'valid': True,
            'user': {
                'id': user_doc['_id'], 'email': user_doc['email'],
                'name': user_doc.get('name'), 'login_method': user_doc.get('login_method', 'email'),
                'profile_picture': user_doc.get('profile_picture'),
                'is_admin': user_doc.get('is_admin', False),
                'total_tokens_used': quota.get('total_tokens_used', 0),
                'token_limit': quota.get('token_limit', 1000000),
                'token_balance': quota.get('token_balance', 1000000),
                'credits_used': quota.get('credits_used', 0.0)
            }
        })
    except Exception as e:
        print(f"[ERROR] Verify error: {e}")
        handler.send_json(500, {'valid': False, 'error': 'Verification failed'})

def handle_logout(handler):
    data  = handler.read_body()
    token = data.get('session_token', '') or handler.get_session_token()

    db = get_db()
    if db is not None and token:
        try:
            db.user_sessions.delete_one({"session_token": token})
            print(f"[OK] Logged out session: {token[:20]}...")
        except Exception as e:
            print(f"[ERROR] Logout error: {e}")

    # Clear the HttpOnly session cookie and the CSRF cookie
    clear_session = "session_token=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict"
    clear_csrf = "csrf_token=; Path=/; Max-Age=0; SameSite=Strict"
    handler.send_json(200, {'success': True}, set_cookie=clear_session, extra_cookies=[clear_csrf])


def handle_change_password(handler):
    data = handler.read_body()
    token = data.get('session_token', '')
    old_password = data.get('old_password', '').strip()
    new_password = data.get('new_password', '').strip()

    if not old_password or not new_password:
        return handler.send_json(400, {'success': False, 'error': 'Both old and new password required'})

    pw_ok, pw_err = validate_password_strength(new_password)
    if not pw_ok:
        return handler.send_json(400, {'success': False, 'error': pw_err})

    user = handler.get_user_from_token(token)
    if not user:
        return handler.send_json(401, {'success': False, 'error': 'Unauthorized'})

    db = get_db()
    if db is None:
        return handler.send_json(500, {'success': False, 'error': 'Database unavailable'})

    try:
        user_doc = db.users.find_one({"_id": user['_id']})
        if not user_doc or not verify_password(old_password, user_doc.get('password_hash', '')):
            return handler.send_json(401, {'success': False, 'error': 'Current password is incorrect'})

        new_hash = hash_password(new_password)
        db.users.update_one(
            {"_id": user['_id']},
            {"$set": {"password_hash": new_hash, "updated_at": datetime.now()}}
        )
        # Invalidate all other sessions for this user
        db.user_sessions.delete_many({"user_id": user['_id']})
        print(f"[OK] Password changed for: {user.get('email')}")
        handler.send_json(200, {'success': True, 'message': 'Password changed successfully'})
    except Exception as e:
        print(f"[ERROR] Password change error: {e}")
        handler.send_json(500, {'success': False, 'error': 'Password change failed'})
