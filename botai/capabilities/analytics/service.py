"""Analytics Engine — AnalyticsManager, MetricsCollector"""
import threading
from datetime import datetime, timedelta
from typing import Dict, Optional
from botai.config.mysql_config import get_db


class MetricsCollector:
    """Collects and persists analytics events to analytics_events collection."""

    _pool = None
    _pool_lock = threading.Lock()

    @classmethod
    def _get_pool(cls):
        if cls._pool is None:
            with cls._pool_lock:
                if cls._pool is None:
                    cls._pool = threading.local()
        return cls._pool

    def emit(self, event_type: str, user_id: Optional[str], data: dict):
        """Emit an analytics event asynchronously."""
        threading.Thread(target=self._persist, args=(event_type, user_id, data), daemon=True).start()

    def _persist(self, event_type: str, user_id: Optional[str], data: dict):
        try:
            db = get_db()
            if db is None:
                return
            uid = user_id
            doc = {
                'event_type': event_type,
                'user_id':    uid,
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

            type_results = list(db.analytics_events.aggregate([
                {'$match': {'created_at': {'$gte': since}}},
                {'$group': {'_id': '$event_type', 'count': {'$sum': 1}}}
            ]))
            by_type = {r['_id']: r['count'] for r in type_results if r['_id']}

            unique_users = len(list(db.analytics_events.aggregate([
                {'$match': {'created_at': {'$gte': since}, 'user_id': {'$ne': None}}},
                {'$group': {'_id': '$user_id'}}
            ])))

            total_tokens = db.token_usage.aggregate([
                {'$match': {'created_at': {'$gte': since}}},
                {'$group': {'_id': None, 'total': {'$sum': 'total_tokens'}}}
            ])
            total_tokens_val = total_tokens[0]['total'] if total_tokens else 0

            total_messages = db.messages.count_documents({'created_at': {'$gte': since}})

            return {
                'period_days':        days,
                'total_events':       sum(by_type.values()),
                'unique_users':       unique_users,
                'events_by_type':     by_type,
                'total_tokens':       total_tokens_val,
                'total_messages':     total_messages,
                'total_conversations': db.conversations.count_documents({'created_at': {'$gte': since}})
            }
        except Exception as e:
            print(f"[AnalyticsManager] get_summary error: {e}")
            return {'error': 'Internal error'}


# Global singletons
analytics_manager  = AnalyticsManager()
metrics_collector  = MetricsCollector()
