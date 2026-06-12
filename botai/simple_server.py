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

from botai.config import settings
from botai.config.mongodb_config import get_db, init_db
from botai.routes import auth_routes, chat_routes, admin_routes
from botai.services.email_service import daily_scheduler_loop, email_service

PORT = 3000

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

    def read_body(self):
        length = int(self.headers.get('Content-Length', 0))
        return json.loads(self.rfile.read(length).decode('utf-8')) if length else {}

    def send_json(self, status, data):
        try:
            body = json.dumps(data).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            print(f"[ERROR] send_json error: {e}")

    def end_headers(self):
        # Restrict CORS to our own origin - not the whole internet
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
            if self.path.startswith('/api/auth/'):
                auth_routes.handle_post(self)
            elif self.path.startswith('/api/claude') or self.path.startswith('/api/conversations/') or self.path.startswith('/api/messages/') or self.path.startswith('/api/files/'):
                chat_routes.handle_post(self)
            elif self.path.startswith('/api/admin/'):
                admin_routes.handle_post(self)
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


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    print("[START] Starting CUTM AI Chatbot Server...")

    # Test DB connection
    db_status = "Connected (MongoDB Atlas)"
    if init_db():
        try:
            db = get_db()
            db.command('ping')
            print("[DB] MongoDB database connected successfully")
        except Exception as e:
            print(f"[WARN] MongoDB connection failed: {e}")
            db_status = f"Disconnected (Error: {str(e)})"
    else:
        print("[WARN] MongoDB not connected - check credentials in MONGO_URI")
        db_status = "Disconnected (No URI)"

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
        print("[SERVER] Token usage will be tracked in MongoDB Atlas")
        print("Press Ctrl+C to stop\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[OK] Server stopped")
            httpd.shutdown()
