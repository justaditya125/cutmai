#!/usr/bin/env python3
import http.server
import socketserver
import json
import os
import time
import sys
import io
import threading
from datetime import datetime

# Reconfigure stdout/stderr encoding for robust terminal output on Windows
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import secrets as _secrets

from botai.config import settings
from botai.config.mysql_config import get_db, init_db, close_db
from botai.routes import auth_routes, chat_routes, admin_routes
from botai.routes import capabilities_routes
from botai.services.email_service import daily_scheduler_loop, email_service
import botai.capabilities as capabilities_pkg
from cad_tool_complete import integrate_cad_tool
import cad_tool_complete

PORT = 3000

# Paths that must never be served over HTTP
BLOCKED_PATHS = {
    '.env', 'config', 'uploads', '.git', 'node_modules',
    '__pycache__', '.env.example', 'database_setup.py',
    'requirements.txt', '.env.local', '.env.production',
}

BLOCKED_PREFIXES = ('.env', 'config/', 'uploads/', '.git', '__pycache__', 'node_modules')


class ChatbotHandler(http.server.SimpleHTTPRequestHandler):

    def log_message(self, format, *args):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {format % args}")

    def log_error(self, format, *args):
        msg = format % args
        if 'ConnectionResetError' in msg or '10054' in msg or 'BrokenPipeError' in msg:
            return
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ERROR: {msg}")

    def get_client_ip(self):
        """Extracts the true client IP from standard proxy headers, falling back to client_address."""
        for header in ['CF-Connecting-IP', 'X-Forwarded-For', 'X-Real-IP']:
            ip = self.headers.get(header)
            if ip:
                if ',' in ip:
                    return ip.split(',')[0].strip()
                return ip.strip()
        return self.client_address[0]

    def get_user_from_token(self, token):
        """Helper: get user_id from session token (checks cookie, header, or body).
        Enforces idle timeout: sessions inactive for >30 minutes are rejected."""
        # If no token passed, try to get from cookie/header
        if not token:
            token = self.get_session_token()
        if not token:
            return None
        db = get_db()
        if db is None: return None
        try:
            session = db.user_sessions.find_one({
                "session_token": token,
                "expires_at": {"$gt": datetime.now()}
            })
            if session:
                # Check idle timeout
                last_activity = session.get('last_activity') or session.get('created_at')
                if last_activity:
                    idle_seconds = (datetime.now() - last_activity).total_seconds()
                    idle_limit = settings.SESSION_IDLE_TIMEOUT_MINUTES * 60
                    if idle_seconds > idle_limit:
                        # Session idle too long — delete it
                        db.user_sessions.delete_one({"session_token": token})
                        print(f"[SESSION] Idle timeout for user {session.get('user_id')} — session deleted")
                        return None
                # Update last_activity on valid access
                db.user_sessions.update_one(
                    {"session_token": token},
                    {"$set": {"last_activity": datetime.now()}}
                )
                user = db.users.find_one({"_id": session['user_id'], "is_active": True})
                if user:
                    user['id'] = str(user['_id'])
                    return user
            return None
        except Exception as e:
            print(f"Error fetching user from session token: {e}")
            return None

    def read_body(self):
        length = int(self.headers.get('Content-Length', 0))
        if length > 10 * 1024 * 1024:  # 10MB limit
            raise ValueError('Request body too large')
        return json.loads(self.rfile.read(length).decode('utf-8')) if length else {}

    def send_json(self, status, data, set_cookie=None, extra_cookies=None):
        try:
            body = json.dumps(data).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            if set_cookie:
                self.send_header('Set-Cookie', set_cookie)
            if extra_cookies:
                for cookie in extra_cookies:
                    self.send_header('Set-Cookie', cookie)
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            print(f"[ERROR] send_json error: {e}")

    def get_session_token(self):
        """Extract session token from cookie, Authorization header, or body (read-only)."""
        # 1. HttpOnly cookie
        cookie_header = self.headers.get('Cookie', '')
        for part in cookie_header.split(';'):
            kv = part.strip().split('=', 1)
            if len(kv) == 2 and kv[0] == 'session_token':
                return kv[1]
        # 2. Authorization header
        auth = self.headers.get('Authorization', '')
        if auth.startswith('Bearer '):
            return auth[7:]
        # 3. X-Session-Token header
        return self.headers.get('X-Session-Token', '')

    def _get_cookie(self, name):
        """Extract a specific cookie value by name."""
        cookie_header = self.headers.get('Cookie', '')
        for part in cookie_header.split(';'):
            kv = part.strip().split('=', 1)
            if len(kv) == 2 and kv[0] == name:
                return kv[1]
        return ''

    def _validate_csrf(self):
        """Validate CSRF token for state-changing requests.
        Uses double-submit cookie pattern: compare X-CSRF-Token header with csrf_token cookie.
        GET and OPTIONS are always allowed. Auth endpoints (login/register) are exempt.
        """
        if self.command in ('GET', 'OPTIONS', 'HEAD'):
            return True
        path = self.path.split('?')[0]
        # Exempt auth endpoints (no session yet)
        if path.startswith('/api/auth/'):
            return True
        header_token = self.headers.get('X-CSRF-Token', '')
        cookie_token = self._get_cookie('csrf_token')
        if not header_token or not cookie_token:
            return False
        return _secrets.compare_digest(header_token, cookie_token)

    def end_headers(self):
        # Restrict CORS to our own origin - not the whole internet
        origin = self.headers.get('Origin', '')
        allowed = f'http://localhost:{PORT}'
        if origin and origin.startswith('http://localhost'):
            self.send_header('Access-Control-Allow-Origin', origin)
        else:
            self.send_header('Access-Control-Allow-Origin', allowed)
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-CSRF-Token, Authorization')
        self.send_header('Vary', 'Origin')
        # Security headers
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('X-XSS-Protection', '1; mode=block')
        self.send_header('Referrer-Policy', 'strict-origin-when-cross-origin')
        self.send_header('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
        # HSTS: only effective when behind HTTPS reverse proxy (nginx/Cloudflare)
        self.send_header('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
        # CSP: allow CDN scripts with nonce for inline, block unsafe inline
        self.send_header('Content-Security-Policy',
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://accounts.google.com https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: blob: https:; "
            "connect-src 'self' https://api.anthropic.com; "
            "frame-src https://accounts.google.com; "
            "object-src 'none'"
        )
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_POST(self):
        try:
            if not self._validate_csrf():
                self.send_json(403, {'error': 'CSRF token missing or invalid'})
                return
            if self.path.startswith('/api/auth/'):
                auth_routes.handle_post(self)
            elif self.path.startswith('/api/claude') or self.path.startswith('/api/conversations/') or self.path.startswith('/api/messages/') or self.path.startswith('/api/files/') or self.path.startswith('/api/gdrive/'):
                chat_routes.handle_post(self)
            elif self.path.startswith('/api/admin/'):
                admin_routes.handle_post(self)
            elif self.path.startswith('/api/capabilities/'):
                capabilities_routes.handle_post(self)
            elif self.path.startswith('/api/cad/'):
                cad_tool_complete.handle_post(self)
            else:
                self.send_json(404, {'error': 'Not found'})
        except Exception as e:
            print(f"[ERROR] POST error: {e}")
            self.send_json(500, {'error': 'Internal server error'})

    def do_GET(self):
        if self.path.startswith('/api/files/'):
            try:
                chat_routes.handle_get(self)
            except Exception as e:
                print(f"[ERROR] GET api error: {e}")
                self.send_json(500, {'error': 'Internal server error'})
            return

        if self.path == '/cad' or self.path == '/cad/' or self.path.startswith('/api/cad/'):
            try:
                cad_tool_complete.handle_get(self)
            except Exception as e:
                print(f"[ERROR] GET CAD error: {e}")
                self.send_json(500, {'error': 'Internal server error'})
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
            # Block sensitive files from being served over HTTP
            path = self.path.lstrip('/')
            for prefix in BLOCKED_PREFIXES:
                if path.startswith(prefix):
                    self.send_error(403, "Forbidden")
                    return
            if path in BLOCKED_PATHS or any(path.endswith(ext) for ext in ('.env', '.env.local', '.env.production')):
                self.send_error(403, "Forbidden")
                return
            try:
                super().do_GET()
            except:
                self.send_error(404, "Not found")


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    print("[START] Starting CUTM AI Chatbot Server...")
    capabilities_pkg.load_all()
    integrate_cad_tool()

    # Test DB connection
    db_status = "Connected (MySQL)"
    if init_db():
        try:
            db = get_db()
            db.command('ping')
            print("[DB] MySQL database connected successfully")
        except Exception as e:
            print(f"[WARN] MySQL connection failed: {e}")
            db_status = f"Disconnected (Error: {str(e)})"
    else:
        print("[WARN] MySQL not connected - check credentials in .env")
        db_status = "Disconnected (No connection)"

    # Send non-blocking startup alert email
    num_keys = len(settings.ANTHROPIC_API_KEYS)
    startup_subject = f"[MONITOR] CUTM AI Server Startup Alert - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    startup_body = f"""================================================================================
                    CUTM AI SERVER STARTUP NOTIFICATION
================================================================================
The CUTM AI Chatbot Server has started successfully.

Server Port          : {PORT}
Database Status      : {db_status}
Active Model Rotator : Enabled ({num_keys} keys loaded)
Email Alerts Enabled : True
Admins Notified      : kalyankv@cutmap.ac.in, aditya.sah@thegttech.com

Timestamp            : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Server               : CUTM AI Production Node
================================================================================"""
    email_service.send_email_in_background(startup_subject, startup_body)

    # Start the 3:00 AM daily status monitoring scheduler thread
    threading.Thread(target=daily_scheduler_loop, daemon=True).start()

    class ThreadedServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
        allow_reuse_address = True
        daemon_threads = True  # clean shutdown on Ctrl+C

        def handle_error(self, request, client_address):
            exc_type, exc_val, _ = sys.exc_info()
            if exc_type in (ConnectionResetError, BrokenPipeError):
                return
            if exc_type is OSError and getattr(exc_val, 'winerror', None) == 10054:
                return
            super().handle_error(request, client_address)

    with ThreadedServer(("", PORT), ChatbotHandler) as httpd:
        print(f"[SERVER] Server running at http://localhost:{PORT}")
        print("[SERVER] Token usage will be tracked in MySQL")
        print("Press Ctrl+C to stop\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[OK] Server stopped")
            httpd.shutdown()
