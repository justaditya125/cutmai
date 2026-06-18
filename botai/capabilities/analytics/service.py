"""Analytics Engine — AnalyticsManager, MetricsCollector"""
import threading
from datetime import datetime, timedelta
from typing import Dict, Optional
from bson import ObjectId
from botai.config.mongodb_config import get_db


class MetricsCollector:
    """Collects and persists analytics events to analytics_events collection."""

    def emit(self, event_type: str, user_id: Optional[str], data: dict):
        """Emit an analytics event asynchronously."""
        threading.Thread(target=self._persist, args=(event_type, user_id, data), daemon=True).start()

    def _persist(self, event_type: str, user_id: Optional[str], data: dict):
        try:
            db = get_db()
            if db is None:
                return
            doc = {
                'event_type': event_type,
                'user_id':    ObjectId(user_id) if user_id else None,
                'data':       data,
                'created_at': datetime.now()
            }
            db.analytics_events.insert_one(doc)
        except Exception as e:
            print(f"[MetricsCollector] Failed to emit event '{event_type}': {e}")


class AnalyticsManager:
    """Aggregates analytics_events for admin reporting."""

    def get_summary(self, days: int = 7) -> Dict:
        try:
            db = get_db()
            if db is None:
                return {'error': 'Database unavailable'}
            since = datetime.now() - timedelta(days=days)
            events = list(db.analytics_events.find({'created_at': {'$gte': since}}))

            by_type: Dict[str, int] = {}
            unique_users = set()
            for e in events:
                et = e.get('event_type', 'unknown')
                by_type[et] = by_type.get(et, 0) + 1
                if e.get('user_id'):
                    unique_users.add(str(e['user_id']))

            # Aggregate from existing token_usage for backward compat
            token_records = list(db.token_usage.find({'created_at': {'$gte': since}}))
            total_tokens = sum(r.get('total_tokens', 0) for r in token_records)
            total_messages = db.messages.count_documents({'created_at': {'$gte': since}})

            return {
                'period_days':     days,
                'total_events':    len(events),
                'unique_users':    len(unique_users),
                'events_by_type':  by_type,
                'total_tokens':    total_tokens,
                'total_messages':  total_messages,
                'total_conversations': db.conversations.count_documents({'created_at': {'$gte': since}})
            }
        except Exception as e:
            print(f"[AnalyticsManager] get_summary error: {e}")
            return {'error': str(e)}


# Global singletons
analytics_manager  = AnalyticsManager()
metrics_collector  = MetricsCollector()
