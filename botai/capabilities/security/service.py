"""Security Manager — wraps existing rate_limiter and logger with enhanced capabilities."""
import os
import re
from datetime import datetime
from typing import Dict, Optional
from botai.utils.rate_limiter import is_rate_limited
from botai.utils.logger import log_suspicious_activity


class SecurityManager:
    """Central security orchestrator — delegates to existing security utilities."""

    def check_rate_limit(self, ip: str, endpoint: str, limit: int = 30, window: int = 60) -> bool:
        """Returns True if request is rate-limited. Delegates to existing is_rate_limited."""
        return is_rate_limited(ip, endpoint, limit=limit, window=window)

    def log_event(self, identifier: str, event_type: str, description: str, risk: str = 'MEDIUM'):
        """Delegates to existing log_suspicious_activity for backward compatibility."""
        log_suspicious_activity(identifier, event_type, description, risk)

    def validate_session(self, handler):
        """Convenience: extract and validate session from handler.
        Returns (user_doc, request_data) or (None, {})."""
        try:
            data  = handler.read_body()
            token = data.get('session_token', '')
            user = handler.get_user_from_token(token)
            return user, data
        except Exception:
            return None, {}


class ThreatDetector:
    """Detects malicious patterns in files and user inputs."""

    # Dangerous file signatures (magic bytes)
    DANGEROUS_EXTENSIONS = {'.exe', '.bat', '.cmd', '.ps1', '.sh', '.vbs', '.scr', '.com', '.pif'}

    # SQL injection patterns (more specific to reduce false positives)
    _SQL_PATTERNS = [
        r"(\bUNION\b\s+(ALL\s+)?SELECT\b)",
        r"(--\s*$|;\s*(DROP|DELETE|INSERT|UPDATE|ALTER|EXEC)\b)",
        r"(\bOR\b\s+['\"]?\w+['\"]?\s*=\s*['\"]?\w+['\"]?)",
        r"(\bAND\b\s+['\"]?\w+['\"]?\s*=\s*['\"]?\w+['\"]?)",
    ]
    _XSS_PATTERNS = [
        r"<script[^>]*>",
        r"javascript:",
        r"on\w+=",
        r"<iframe",
        r"<object",
    ]

    def scan_filename(self, filename: str) -> Dict:
        """Check if a filename has dangerous extension."""
        ext = os.path.splitext(filename.lower())[1]
        is_dangerous = ext in self.DANGEROUS_EXTENSIONS
        return {
            'filename': filename,
            'extension': ext,
            'is_dangerous': is_dangerous,
            'reason': f'Dangerous extension: {ext}' if is_dangerous else None
        }

    def scan_input(self, text: str) -> Dict:
        """Scan user input for SQL injection and XSS patterns."""
        threats = []
        for pattern in self._SQL_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                threats.append('sql_injection')
                break
        for pattern in self._XSS_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                threats.append('xss')
                break
        return {
            'is_clean': len(threats) == 0,
            'threats':  threats
        }

    def scan_file_bytes(self, file_bytes: bytes, filename: str) -> Dict:
        """Check file magic bytes for dangerous executable signatures."""
        EXECUTABLE_MAGIC = [
            b'MZ',           # Windows PE
            b'\x7fELF',      # Linux ELF
            b'#!',           # Shell script shebang
            b'PK\x03\x04',   # ZIP (also used by Office, check extension)
        ]
        ext_result = self.scan_filename(filename)
        if ext_result['is_dangerous']:
            return {'is_safe': False, 'reason': ext_result['reason']}

        for magic in EXECUTABLE_MAGIC[:3]:  # Skip ZIP check for legitimate Office files
            if file_bytes.startswith(magic):
                return {'is_safe': False, 'reason': f'Executable file signature detected: {magic!r}'}

        return {'is_safe': True, 'reason': None}


security_manager = SecurityManager()
threat_detector  = ThreatDetector()
