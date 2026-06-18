"""
AuditLogger — enhances existing logger.py with structured audit trails.
Does NOT modify logger.py — wraps it.
"""
from datetime import datetime, timedelta
from typing import List, Dict
from botai.utils.logger import log_suspicious_activity, SUSPICIOUS_ACTIVITIES  # reuse existing
from botai.config.mongodb_config import get_db


class AuditLogger:
    """Structured audit logging on top of existing security infrastructure."""

    def log(self, actor: str, action: str, resource: str,
            outcome: str = 'SUCCESS', metadata: dict = None, risk: str = 'LOW'):
        """
        Log a structured audit event.
        Persists to existing security_logs collection for backward compatibility.
        """
        description = f"Action={action} Resource={resource} Outcome={outcome}"
        if metadata:
            description += f" Meta={metadata}"
        log_suspicious_activity(actor, action, description, risk)

        # Also store in dedicated audit_logs collection if available
        try:
            db = get_db()
            if db is not None:
                db.audit_logs.insert_one({
                    'actor':    actor,
                    'action':   action,
                    'resource': resource,
                    'outcome':  outcome,
                    'metadata': metadata or {},
                    'risk':     risk,
                    'ts':       datetime.now()
                })
        except Exception as e:
            print(f"[AuditLogger] Failed to persist to audit_logs: {e}")

    def get_recent(self, limit: int = 50) -> List[Dict]:
        """Return recent audit events. Falls back to in-memory SUSPICIOUS_ACTIVITIES."""
        try:
            db = get_db()
            if db is not None:
                records = list(
                    db.audit_logs.find({}, {'_id': 0}).sort('ts', -1).limit(limit)
                )
                if records:
                    return records
        except Exception:
            pass
        # Fallback to in-memory list
        return list(reversed(SUSPICIOUS_ACTIVITIES[-limit:]))


class InputSanitizer:
    """Sanitizes and cleans user inputs."""

    def sanitize(self, text: str, strip_html: bool = True) -> str:
        """Remove dangerous HTML and script tags from user input."""
        import re
        if strip_html:
            text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<[^>]+>', '', text)
        # Normalize whitespace
        text = ' '.join(text.split())
        return text.strip()

    def truncate(self, text: str, max_chars: int = 50000) -> str:
        """Truncate oversized inputs to prevent token bombs."""
        if len(text) > max_chars:
            print(f"[InputSanitizer] Input truncated from {len(text)} to {max_chars} chars")
            return text[:max_chars] + '\n[Content truncated by safety filter]'
        return text


audit_logger    = AuditLogger()
input_sanitizer = InputSanitizer()
