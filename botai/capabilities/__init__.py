"""
CUTM AI Capabilities Package
Plugin-based architecture for Claude.ai-level backend capabilities.

Each module:
  - Is independently loadable
  - Has its own enable/disable feature flag
  - Fails gracefully without affecting the core chatbot
  - Follows: service -> repository -> models -> utils -> tests
"""
import importlib
from botai.config import settings


def _load_module(module_path: str, flag_name: str) -> object:
    """Safely load a capability module if its feature flag is True."""
    if not getattr(settings, flag_name, False):
        return None
    try:
        return importlib.import_module(module_path)
    except Exception as e:
        print(f"[Capabilities] Failed to load {module_path}: {e}")
        return None


# Registry of all capability modules
CAPABILITIES = {
    "model_orchestration":  "botai.capabilities.model_orchestration.service",
    "analytics":            "botai.capabilities.analytics.service",
    "security":             "botai.capabilities.security.service",
    "conversation_intel":   "botai.capabilities.conversation_intel.service",
    "file_processing":      "botai.capabilities.file_processing.service",
    "web_search":           "botai.capabilities.web_search.service",
    "artifact_detection":   "botai.capabilities.artifact_detection.service",
    "code_sandbox":         "botai.capabilities.code_sandbox.service",
    "data_analysis":        "botai.capabilities.data_analysis.service",
    "vision_intelligence":  "botai.capabilities.vision_intelligence.service",
    "export_engine":        "botai.capabilities.export_engine.service",
    "integrations":         "botai.capabilities.integrations.service",
    "rag":                  "botai.capabilities.rag.service",
    "extended_thinking":    "botai.capabilities.extended_thinking.service",
}

FLAG_MAP = {
    "model_orchestration":  "ENABLE_MODEL_ORCHESTRATION",
    "analytics":            "ENABLE_ANALYTICS",
    "security":             "ENABLE_SECURITY_LAYER",
    "conversation_intel":   "ENABLE_CONVERSATION_INTEL",
    "file_processing":      "ENABLE_ADVANCED_FILE_PROC",
    "web_search":           "ENABLE_WEB_SEARCH",
    "artifact_detection":   "ENABLE_ARTIFACT_DETECTION",
    "code_sandbox":         "ENABLE_CODE_SANDBOX",
    "data_analysis":        "ENABLE_DATA_ANALYSIS",
    "vision_intelligence":  "ENABLE_VISION_INTELLIGENCE",
    "export_engine":        "ENABLE_EXPORT_ENGINE",
    "integrations":         "ENABLE_INTEGRATIONS",
    "rag":                  "ENABLE_RAG",
    "extended_thinking":    "ENABLE_EXTENDED_THINKING",
}

_loaded = {}


def get_capability(name: str):
    """Get a loaded capability module by name. Returns None if disabled or failed."""
    if name not in _loaded:
        module_path = CAPABILITIES.get(name)
        flag = FLAG_MAP.get(name)
        if module_path and flag:
            _loaded[name] = _load_module(module_path, flag)
        else:
            _loaded[name] = None
    return _loaded[name]


def load_all():
    """Pre-load all enabled capability modules at server startup."""
    enabled = []
    disabled = []
    for name in CAPABILITIES:
        mod = get_capability(name)
        if mod is not None:
            enabled.append(name)
        else:
            disabled.append(name)
    if enabled:
        print(f"[Capabilities] Loaded: {', '.join(enabled)}")
    if disabled:
        print(f"[Capabilities] Disabled/skipped: {', '.join(disabled)}")
