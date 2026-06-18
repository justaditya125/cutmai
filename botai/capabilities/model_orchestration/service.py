"""
Model Orchestration Service
Wraps and extends the existing KeyRotator with full model management capabilities:
ModelManager, ModelRouter, FallbackManager — all backward-compatible with key_rotator.
"""
import json
import time
import threading
import urllib.request
import urllib.error
from datetime import datetime
from typing import Optional, Dict, List
from botai.config import settings
from botai.services.key_rotator import key_rotator   # reuse existing rotator


class ModelManager:
    """
    Central registry and router for all available models.
    Extends the existing key_rotator without replacing it.
    """

    def __init__(self):
        self._registry: Dict[str, Dict] = dict(settings.MODEL_REGISTRY)
        self._health: Dict[str, bool] = {m: True for m in self._registry}
        self._lock = threading.Lock()
        print("[ModelManager] Initialized with models:", list(self._registry.keys()))

    # ── Registry ───────────────────────────────────────────────────────────────

    def list_models(self) -> Dict:
        """Return all registered models with health status."""
        with self._lock:
            models = []
            for model_id, config in self._registry.items():
                models.append({
                    **config,
                    'healthy': self._health.get(model_id, True)
                })
        return {'models': models, 'count': len(models)}

    def get_model_config(self, model_id: str) -> Optional[Dict]:
        """Retrieve config dict for a model by ID."""
        return self._registry.get(model_id)

    def register_model(self, model_id: str, config: Dict) -> bool:
        """Dynamically register a new model (plugin-friendly)."""
        with self._lock:
            self._registry[model_id] = config
            self._health[model_id] = True
        print(f"[ModelManager] Registered model: {model_id}")
        return True

    # ── Health tracking ────────────────────────────────────────────────────────

    def mark_unhealthy(self, model_id: str):
        with self._lock:
            self._health[model_id] = False
        print(f"[ModelManager] Marked unhealthy: {model_id}")

    def mark_healthy(self, model_id: str):
        with self._lock:
            self._health[model_id] = True

    # ── Routing ────────────────────────────────────────────────────────────────

    def route(self, requested_model: str, is_admin: bool = False) -> str:
        """
        Return the model ID to use for a request.
        Falls back to Haiku if requested model is unhealthy.
        """
        valid_ids = list(self._registry.keys())
        if requested_model not in valid_ids:
            requested_model = 'claude-haiku-4-5'

        if self._health.get(requested_model, True):
            return requested_model

        # Fallback chain
        fallback = self._fallback(requested_model)
        print(f"[ModelRouter] {requested_model} unhealthy → falling back to {fallback}")
        return fallback

    def _fallback(self, failed_model: str) -> str:
        """Return the next best healthy model."""
        fallback_chain = ['claude-haiku-4-5', 'claude-sonnet-4-5', 'claude-opus-4-5']
        for candidate in fallback_chain:
            if candidate != failed_model and self._health.get(candidate, True):
                return candidate
        return 'claude-haiku-4-5'

    # ── API key passthrough (reuses existing rotator) ──────────────────────────

    def get_api_key(self) -> str:
        """Get next healthy API key — delegates to existing key_rotator."""
        return key_rotator.get_key()

    def report_key_error(self, key: str):
        """Report API key failure to existing rotator."""
        key_rotator.mark_unhealthy(key)


class FallbackManager:
    """Manages automatic fallback when a model fails mid-request."""

    def __init__(self, model_manager: ModelManager):
        self._mm = model_manager
        self._fallback_counts: Dict[str, int] = {}
        self._lock = threading.Lock()

    def handle_error(self, model_id: str, error_code: int) -> str:
        """
        Handle a model error and return the fallback model to use.
        error_code 429 = rate limited, 401/403 = auth error, 500 = server error.
        """
        with self._lock:
            self._fallback_counts[model_id] = self._fallback_counts.get(model_id, 0) + 1

        if error_code in (429, 401, 403, 500):
            self._mm.mark_unhealthy(model_id)
            fallback = self._mm._fallback(model_id)
            print(f"[FallbackManager] HTTP {error_code} on {model_id} → switching to {fallback}")
            return fallback
        return model_id


# ── Global singletons ──────────────────────────────────────────────────────────
model_manager = ModelManager()
fallback_manager = FallbackManager(model_manager)
