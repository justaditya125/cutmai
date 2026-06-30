"""
Rate limiter - IP-based and endpoint-based request limiting
"""
from datetime import datetime, timedelta, timezone
import threading
import time as _time
from botai.config import settings

class RateLimiter:
    """IP-based and endpoint-based rate limiting utility"""
    
    def __init__(self):
        self.requests = {}  # Store: {ip: {endpoint: [timestamps]}}
        self._lock = threading.Lock()
        self._last_cleanup = _time.monotonic()
    
    def _cleanup_stale_entries(self):
        """Remove entries for IPs that have no recent activity (older than 1 hour)."""
        now = _time.monotonic()
        if now - self._last_cleanup < 300:  # Only cleanup every 5 minutes
            return
        self._last_cleanup = now
        with self._lock:
            stale_ips = []
            for ip, endpoints in self.requests.items():
                for endpoint, timestamps in list(endpoints.items()):
                    fresh = [ts for ts in timestamps if now - ts < 3600]
                    if fresh:
                        endpoints[endpoint] = fresh
                    else:
                        del endpoints[endpoint]
                if not endpoints:
                    stale_ips.append(ip)
            for ip in stale_ips:
                del self.requests[ip]
    
    def is_allowed(self, ip: str, endpoint: str) -> bool:
        """Check if request is allowed for this IP thread-safely"""
        # Periodically prune stale entries
        self._cleanup_stale_entries()

        # Determine specific limits based on endpoint prefixes
        if '/api/auth/login' in endpoint:
            limit = settings.RATE_LIMIT_LOGIN_PER_MIN
            window = timedelta(minutes=1)
        elif '/api/auth/signup' in endpoint:
            limit = settings.RATE_LIMIT_SIGNUP_PER_10MIN
            window = timedelta(minutes=10)
        else:
            limit = settings.RATE_LIMIT_API_PER_MIN
            window = timedelta(minutes=1)
        
        with self._lock:
            # Initialize IP if not exists
            if ip not in self.requests:
                self.requests[ip] = {}
            
            if endpoint not in self.requests[ip]:
                self.requests[ip][endpoint] = []
            
            # Remove expired timestamps outside the time window
            now = datetime.now(timezone.utc)
            self.requests[ip][endpoint] = [
                ts for ts in self.requests[ip][endpoint]
                if now - ts < window
            ]
            
            # Prune empty entries to prevent memory leak
            if not self.requests[ip][endpoint]:
                del self.requests[ip][endpoint]
            if not self.requests[ip]:
                del self.requests[ip]
            
            # Check limit violation
            if len(self.requests[ip][endpoint]) >= limit:
                return False
            
            # Record current request
            self.requests[ip][endpoint].append(now)
            return True
    
    def get_remaining(self, ip: str, endpoint: str) -> int:
        """Get remaining allowed requests count for this IP"""
        if '/api/auth/login' in endpoint:
            limit = settings.RATE_LIMIT_LOGIN_PER_MIN
        elif '/api/auth/signup' in endpoint:
            limit = settings.RATE_LIMIT_SIGNUP_PER_10MIN
        else:
            limit = settings.RATE_LIMIT_API_PER_MIN

        with self._lock:
            if ip not in self.requests or endpoint not in self.requests[ip]:
                return limit
            # Prune expired timestamps before counting
            now = datetime.now(timezone.utc)
            window = timedelta(seconds=60)
            self.requests[ip][endpoint] = [
                ts for ts in self.requests[ip][endpoint]
                if now - ts < window
            ]
            return max(0, limit - len(self.requests[ip][endpoint]))

# Global singleton instance
rate_limiter = RateLimiter()

# Backward compatibility layer
import time
from collections import defaultdict
from botai.utils.logger import log_suspicious_activity

_rate_store = defaultdict(list)
_rate_lock = threading.Lock()

def is_rate_limited(ip: str, endpoint: str, limit: int = 10, window: int = 60) -> bool:
    """
    Returns True if `ip` has exceeded `limit` calls to `endpoint` in the last
    `window` seconds. Automatically prunes stale entries.
    """
    key = f"{ip}:{endpoint}"
    now = time.monotonic()
    with _rate_lock:
        _rate_store[key] = [t for t in _rate_store[key] if now - t < window]
        if len(_rate_store[key]) >= limit:
            log_suspicious_activity(ip, "Rate Limit Triggered", f"Exceeded limits ({limit} per {window}s) on endpoint: {endpoint}", "LOW")
            return True
        _rate_store[key].append(now)
        if not _rate_store[key]:
            del _rate_store[key]
        return False

