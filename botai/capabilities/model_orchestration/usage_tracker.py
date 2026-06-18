"""
Usage Tracker — persists per-model usage and cost to usage_logs collection.
"""
import threading
from datetime import datetime
from typing import Dict, List, Optional
from bson import ObjectId
from botai.config.mongodb_config import get_db
from botai.capabilities.model_orchestration.cost_estimator import cost_estimator


class UsageTracker:
    """Thread-safe usage tracker that persists to MongoDB usage_logs collection."""

    def __init__(self):
        self._lock = threading.Lock()

    def record(self, user_id: str, model: str, input_tokens: int,
               output_tokens: int, latency_ms: float = 0.0,
               conversation_id: Optional[str] = None):
        """
        Record a single model usage event.
        This supplements (not replaces) the existing save_token_usage in chat_routes.
        """
        try:
            cost = cost_estimator.estimate(model, input_tokens, output_tokens)
            db = get_db()
            if db is None:
                return

            doc = {
                'user_id':         ObjectId(user_id) if isinstance(user_id, str) else user_id,
                'conversation_id': ObjectId(conversation_id) if conversation_id else None,
                'model':           model,
                'input_tokens':    input_tokens,
                'output_tokens':   output_tokens,
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
            records = list(db.usage_logs.find({'created_at': {'$gte': since}}))

            by_model: Dict[str, Dict] = {}
            total_cost = 0.0
            total_tokens = 0

            for r in records:
                model = r.get('model', 'unknown')
                cost  = r.get('total_cost_usd', 0.0)
                toks  = r.get('total_tokens', 0)
                latency = r.get('latency_ms', 0.0)

                if model not in by_model:
                    by_model[model] = {
                        'requests': 0, 'total_tokens': 0,
                        'total_cost_usd': 0.0, 'avg_latency_ms': 0.0
                    }
                by_model[model]['requests']       += 1
                by_model[model]['total_tokens']   += toks
                by_model[model]['total_cost_usd'] += cost
                by_model[model]['avg_latency_ms'] += latency
                total_cost   += cost
                total_tokens += toks

            # Compute average latency
            for m in by_model:
                reqs = by_model[m]['requests']
                if reqs > 0:
                    by_model[m]['avg_latency_ms'] = round(by_model[m]['avg_latency_ms'] / reqs, 2)
                by_model[m]['total_cost_usd'] = round(by_model[m]['total_cost_usd'], 6)

            return {
                'period_days':   days,
                'total_requests': len(records),
                'total_tokens':  total_tokens,
                'total_cost_usd': round(total_cost, 6),
                'by_model':      by_model
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
            u_id = ObjectId(user_id) if isinstance(user_id, str) else user_id
            records = list(db.usage_logs.find({'user_id': u_id, 'created_at': {'$gte': since}}))
            return cost_estimator.estimate_batch(records)
        except Exception as e:
            print(f"[UsageTracker] get_user_usage error: {e}")
            return {'error': str(e)}


# Global singleton
usage_tracker = UsageTracker()
