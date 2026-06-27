"""
API Key Rotator - Load balance across multiple keys thread-safely
"""
from datetime import datetime, timedelta, timezone
from typing import List
import threading
from botai.config import settings

def _mask_key(key: str) -> str:
    """Mask API key, showing only last 4 chars for identification"""
    if not key or len(key) < 8:
        return '****'
    return f'****{key[-4:]}'

class KeyRotator:
    """Rotate through API keys for load balancing with active health tracking"""
    
    def __init__(self, keys: List[str]):
        self.keys = keys
        self.current_index = 0
        self.key_health = {key: True for key in keys}
        self.unhealthy_since = {key: None for key in keys}
        self._lock = threading.Lock()
    
    def get_next_healthy_key(self) -> str:
        """Get next healthy key, skipping rate-limited ones thread-safely"""
        if not self.keys:
            return ""
            
        with self._lock:
            attempts = 0
            while attempts < len(self.keys):
                key = self.keys[self.current_index]
                self.current_index = (self.current_index + 1) % len(self.keys)
                
                # Check if key is healthy
                if self.key_health.get(key, True):
                    return key
                
                # Check if key has been unhealthy for > 1 hour (auto-recovery window)
                if self.unhealthy_since.get(key):
                    if datetime.now(timezone.utc) - self.unhealthy_since[key] > timedelta(hours=1):
                        self.key_health[key] = True
                        self.unhealthy_since[key] = None
                        print(f"[Load Balancer] Auto-recovered key ending in {_mask_key(key)}")
                        return key
                
                attempts += 1
            
            # All keys unhealthy, return None so caller can handle gracefully
            return None
            
    def get_key(self) -> str:
        """Alias for compatibility with the original server endpoints"""
        key = self.get_next_healthy_key()
        if key:
            print(f"[Load Balancer] Rotating API Key: using key ending in {_mask_key(key)}")
        return key
    
    def mark_unhealthy(self, key: str):
        """Mark key as unhealthy after rate limits or server errors"""
        if not key:
            return
        with self._lock:
            self.key_health[key] = False
            self.unhealthy_since[key] = datetime.now(timezone.utc)
            print(f"[WARNING] Key marked unhealthy: {_mask_key(key)}")
    
    def mark_healthy(self, key: str):
        """Mark key as healthy manually"""
        if not key:
            return
        with self._lock:
            self.key_health[key] = True
            self.unhealthy_since[key] = None
            print(f"Key marked healthy: {_mask_key(key)}")

# Initialize global instance
key_rotator = KeyRotator(settings.ANTHROPIC_API_KEYS)
