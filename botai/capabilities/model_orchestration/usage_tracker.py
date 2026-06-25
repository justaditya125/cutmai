"""
Usage Tracker — persists per-model usage and cost to usage_logs collection.
"""
import threading
from datetime import datetime
from typing import Dict, List, Optional
from botai.config.mysql_config import get_db
from botai.capabilities.model_orchestration.cost_estimator import cost_estimator


class UsageTracker:
    """Thread-safe usage tracker that persists to MySQL usage_logs collection."""

    def __init__(self):
        self._lock = threading.Lock()

    def record(self, user_id: str, model: str, input_tokens: int,
               output_tokens: int, latency_ms: float = 0.0,
               conversation_id: Optional[str] = None,
               cache_creation_tokens: int = 0, cache_read_tokens: int = 0):
        """
        Record a single model usage event.
        This supplements (not replaces) the existing save_token_usage in chat_routes.
        """
        try:
            cost = cost_estimator.estimate(model, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens)
            db = get_db()
            if db is None:
                return

            doc = {
                'user_id':         user_id,
                'conversation_id': conversation_id,
                'model':           model,
                'input_tokens':    input_tokens,
                'output_tokens':   output_tokens,
                'cache_creation_input_tokens': cache_creation_tokens,
                'cache_read_input_tokens': cache_read_tokens,
                'total_tokens':    input_tokens + output_tokens,
                'total_cost_usd':  cost['total_cost'],
                'latency_ms':      latency_ms,
                'created_at':      datetime.now()
            }
            db.usage_logs.insert_one(doc)
        except Exception as e:
            print(f"[UsageTracker] Failed to record usage: {e}")

    def record_async(self, *args, **kwargs):
        """Record usage in a background thread to never block the response."""
        import threading
        threading.Thread(target=self.record, args=args, kwargs=kwargs, daemon=True).start()

    def get_summary(self, days: int = 30) -> Dict:
        """Return aggregated usage summary for admin dashboard."""
        try:
            db = get_db()
            if db is None:
                return {'error': 'Database unavailable'}

            from datetime import timedelta
            since = datetime.now() - timedelta(days=days)

            pipeline = [
                {'$match': {'created_at': {'$gte': since}}},
                {'$group': {
                    '_id': '$model',
                    'requests': {'$sum': 1},
                    'total_tokens': {'$sum': '$total_tokens'},
                    'total_cost_usd': {'$sum': '$total_cost_usd'},
                    'avg_latency_ms': {'$avg': '$latency_ms'}
                }}
            ]
            results = db.usage_logs.aggregate(pipeline)

            by_model = {}
            total_cost = 0.0
            total_tokens = 0
            total_requests = 0

            for r in results:
                model = r['_id'] or 'unknown'
                by_model[model] = {
                    'requests': r['requests'],
                    'total_tokens': r['total_tokens'],
                    'total_cost_usd': round(r['total_cost_usd'], 6),
                    'avg_latency_ms': round(r.get('avg_latency_ms', 0), 2)
                }
                total_cost += r['total_cost_usd']
                total_tokens += r['total_tokens']
                total_requests += r['requests']

            return {
                'period_days':    days,
                'total_requests': total_requests,
                'total_tokens':   total_tokens,
                'total_cost_usd': round(total_cost, 6),
                'by_model':       by_model
            }
        except Exception as e:
            print(f"[UsageTracker] get_summary error: {e}")
            return {'error': str(e)}

    def get_user_usage(self, user_id: str, days: int = 30) -> Dict:
        """Get usage breakdown for a specific user."""
        try:
            db = get_db()
            if db is None:
                return {'error': 'Database unavailable'}
            from datetime import timedelta
            since = datetime.now() - timedelta(days=days)
            records = list(db.usage_logs.find({'user_id': user_id, 'created_at': {'$gte': since}}))
            return cost_estimator.estimate_batch(records)
        except Exception as e:
            print(f"[UsageTracker] get_user_usage error: {e}")
            return {'error': str(e)}


# Global singleton
usage_tracker = UsageTracker()
