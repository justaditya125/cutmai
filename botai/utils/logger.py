"""
Logging and security monitoring utility
"""
from datetime import datetime, timezone
import threading
from botai.config.MySQL_config import get_db

# Global list of suspicious activities kept in memory for backward compatibility (dashboard reports, etc.)
SUSPICIOUS_ACTIVITIES = []
_log_lock = threading.Lock()

def log_suspicious_activity(ip_or_user: str, activity_type: str, description: str, risk_level: str = "MEDIUM"):
    """Logs a security event in memory and persists it into the MySQL security_logs collection"""
    timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    event = {
        "timestamp": timestamp_str,
        "user_ip": ip_or_user,
        "type": activity_type,
        "desc": description,
        "risk": risk_level
    }
    
    # Update in-memory list thread-safely
    with _log_lock:
        SUSPICIOUS_ACTIVITIES.append(event)
        # Keep list capped at last 1000 activities to prevent memory leaks
        if len(SUSPICIOUS_ACTIVITIES) > 1000:
            SUSPICIOUS_ACTIVITIES.pop(0)
            
    # Print clean ASCII to prevent cp1252 Windows terminal crashes
    print(f"[MONITORING] Suspicious Activity: {activity_type} from {ip_or_user} - {description} ({risk_level})")
    
    # Persist to security_logs table
    try:
        db = get_db()
        if db is not None:
            db.security_logs.insert_one({
                "timestamp": datetime.now(timezone.utc),
                "user_ip": ip_or_user,
                "type": activity_type,
                "desc": description,
                "risk": risk_level
            })
    except Exception as e:
        print(f"[Logger] Failed to persist security log: {e}")

# Global API failure counter
FAILED_API_REQUESTS = 0
_failed_lock = threading.Lock()

def increment_failed_api_requests():
    global FAILED_API_REQUESTS
    with _failed_lock:
        FAILED_API_REQUESTS += 1

def get_failed_api_requests():
    global FAILED_API_REQUESTS
    return FAILED_API_REQUESTS

# Server Start Time and Uptime tracking
START_TIME = datetime.now()

def get_uptime():
    """Calculates active system uptime from START_TIME."""
    delta = datetime.now() - START_TIME
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{days}d {hours}h {minutes}m {seconds}s"


