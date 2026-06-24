"""Performance Tracker — measures and stores per-request latency."""
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, List
from collections import deque


class PerformanceTracker:
    """Thread-safe in-memory ring buffer for recent request latencies."""

    MAX_ENTRIES = 1000

    def __init__(self):
        self._entries = deque(maxlen=self.MAX_ENTRIES)
        self._lock = threading.Lock()

    def record(self, model: str, latency_ms: float, tokens: int, success: bool = True):
        entry = {
            'model':      model,
            'latency_ms': round(latency_ms, 2),
            'tokens':     tokens,
            'success':    success,
            'ts':         datetime.now().isoformat()
        }
        with self._lock:
            self._entries.append(entry)

    def get_recent_latency(self, limit: int = 100) -> Dict:
        with self._lock:
            recent = list(self._entries)[-limit:]

        if not recent:
            return {'entries': [], 'avg_latency_ms': 0, 'p95_latency_ms': 0}

        latencies = sorted(e['latency_ms'] for e in recent)
        avg = sum(latencies) / len(latencies)
        p95_idx = min(int(len(latencies) * 0.95), len(latencies) - 1)
        p95 = latencies[p95_idx]

        by_model: Dict[str, List[float]] = {}
        for e in recent:
            by_model.setdefault(e['model'], []).append(e['latency_ms'])

        model_stats = {
            m: {
                'avg_ms': round(sum(vals) / len(vals), 2),
                'count': len(vals)
            }
            for m, vals in by_model.items()
        }

        return {
            'entries':        recent[-20:],
            'avg_latency_ms': round(avg, 2),
            'p95_latency_ms': round(p95, 2),
            'by_model':       model_stats
        }


performance_tracker = PerformanceTracker()
