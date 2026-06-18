"""
Capabilities Route Dispatcher
Handles all /api/capabilities/* routes without touching existing routes.
"""
import json
from botai.config import settings


def handle_post(handler):
    """Route POST requests to the correct capability handler."""
    path = handler.path

    try:
        # --- Model Orchestration ---
        if path == '/api/capabilities/models/list' and settings.ENABLE_MODEL_ORCHESTRATION:
            from botai.capabilities.model_orchestration.service import model_manager
            handler.send_json(200, model_manager.list_models())

        elif path == '/api/capabilities/models/usage' and settings.ENABLE_MODEL_ORCHESTRATION:
            data = handler.read_body()
            user = handler.get_user_from_token(data.get('session_token', ''))
            if not user or not user.get('is_admin', False):
                return handler.send_json(403, {'error': 'Admin access required'})
            from botai.capabilities.model_orchestration.usage_tracker import usage_tracker
            handler.send_json(200, usage_tracker.get_summary())

        # --- Analytics ---
        elif path == '/api/capabilities/analytics/summary' and settings.ENABLE_ANALYTICS:
            data = handler.read_body()
            user = handler.get_user_from_token(data.get('session_token', ''))
            if not user or not user.get('is_admin', False):
                return handler.send_json(403, {'error': 'Admin access required'})
            from botai.capabilities.analytics.service import analytics_manager
            handler.send_json(200, analytics_manager.get_summary())

        elif path == '/api/capabilities/analytics/latency' and settings.ENABLE_ANALYTICS:
            data = handler.read_body()
            user = handler.get_user_from_token(data.get('session_token', ''))
            if not user or not user.get('is_admin', False):
                return handler.send_json(403, {'error': 'Admin access required'})
            from botai.capabilities.analytics.performance import performance_tracker
            handler.send_json(200, performance_tracker.get_recent_latency())

        # --- Conversation Intelligence ---
        elif path == '/api/capabilities/conversation/summarize' and settings.ENABLE_CONVERSATION_INTEL:
            data = handler.read_body()
            user = handler.get_user_from_token(data.get('session_token', ''))
            if not user:
                return handler.send_json(401, {'error': 'Unauthorized'})
            from botai.capabilities.conversation_intel.service import conversation_summarizer
            result = conversation_summarizer.summarize(data.get('conversation_id'), user['id'])
            handler.send_json(200, result)

        elif path == '/api/capabilities/conversation/memory' and settings.ENABLE_CONVERSATION_INTEL:
            data = handler.read_body()
            user = handler.get_user_from_token(data.get('session_token', ''))
            if not user:
                return handler.send_json(401, {'error': 'Unauthorized'})
            from botai.capabilities.conversation_intel.memory_manager import memory_manager
            action = data.get('action', 'get')
            if action == 'store':
                memory_manager.store(user['id'], data.get('content', ''), data.get('tags', []))
                handler.send_json(200, {'success': True})
            else:
                handler.send_json(200, {'memories': memory_manager.retrieve(user['id'], data.get('query', ''))})

        # --- Web Search ---
        elif path == '/api/capabilities/search/web' and settings.ENABLE_WEB_SEARCH:
            data = handler.read_body()
            user = handler.get_user_from_token(data.get('session_token', ''))
            if not user:
                return handler.send_json(401, {'error': 'Unauthorized'})
            from botai.capabilities.web_search.service import search_manager
            result = search_manager.search(data.get('url', ''), data.get('query', ''))
            handler.send_json(200, result)

        elif path == '/api/capabilities/search/cite' and settings.ENABLE_WEB_SEARCH:
            data = handler.read_body()
            user = handler.get_user_from_token(data.get('session_token', ''))
            if not user:
                return handler.send_json(401, {'error': 'Unauthorized'})
            from botai.capabilities.web_search.citation import citation_generator
            result = citation_generator.generate(data.get('url', ''))
            handler.send_json(200, result)

        # --- Artifact Detection ---
        elif path == '/api/capabilities/artifacts/list' and settings.ENABLE_ARTIFACT_DETECTION:
            data = handler.read_body()
            user = handler.get_user_from_token(data.get('session_token', ''))
            if not user:
                return handler.send_json(401, {'error': 'Unauthorized'})
            from botai.capabilities.artifact_detection.storage import artifact_storage
            handler.send_json(200, {'artifacts': artifact_storage.list_for_user(user['id'])})

        elif path == '/api/capabilities/artifacts/download' and settings.ENABLE_ARTIFACT_DETECTION:
            data = handler.read_body()
            user = handler.get_user_from_token(data.get('session_token', ''))
            if not user:
                return handler.send_json(401, {'error': 'Unauthorized'})
            from botai.capabilities.artifact_detection.storage import artifact_storage
            artifact = artifact_storage.get(data.get('artifact_id'), user['id'])
            handler.send_json(200, artifact or {'error': 'Not found'})

        # --- Vision Intelligence ---
        elif path == '/api/capabilities/vision/analyze' and settings.ENABLE_VISION_INTELLIGENCE:
            data = handler.read_body()
            user = handler.get_user_from_token(data.get('session_token', ''))
            if not user:
                return handler.send_json(401, {'error': 'Unauthorized'})
            from botai.capabilities.vision_intelligence.service import vision_engine
            result = vision_engine.analyze(data.get('image_base64', ''), data.get('media_type', 'image/jpeg'))
            handler.send_json(200, result)

        elif path == '/api/capabilities/vision/ocr' and settings.ENABLE_VISION_INTELLIGENCE:
            data = handler.read_body()
            user = handler.get_user_from_token(data.get('session_token', ''))
            if not user:
                return handler.send_json(401, {'error': 'Unauthorized'})
            from botai.capabilities.vision_intelligence.ocr import ocr_engine
            result = ocr_engine.extract_text(data.get('image_base64', ''), data.get('media_type', 'image/jpeg'))
            handler.send_json(200, result)

        # --- Data Analysis ---
        elif path == '/api/capabilities/data/analyze' and settings.ENABLE_DATA_ANALYSIS:
            data = handler.read_body()
            user = handler.get_user_from_token(data.get('session_token', ''))
            if not user:
                return handler.send_json(401, {'error': 'Unauthorized'})
            from botai.capabilities.data_analysis.service import data_analyzer
            result = data_analyzer.analyze(data.get('file_id'), user['id'], data.get('query', ''))
            handler.send_json(200, result)

        # --- Export Engine ---
        elif path == '/api/capabilities/export/conversation/json' and settings.ENABLE_EXPORT_ENGINE:
            data = handler.read_body()
            user = handler.get_user_from_token(data.get('session_token', ''))
            if not user:
                return handler.send_json(401, {'error': 'Unauthorized'})
            from botai.capabilities.export_engine.json_exporter import json_exporter
            result = json_exporter.export_conversation(data.get('conversation_id'), user['id'])
            handler.send_json(200, result)

        elif path == '/api/capabilities/export/conversation/markdown' and settings.ENABLE_EXPORT_ENGINE:
            data = handler.read_body()
            user = handler.get_user_from_token(data.get('session_token', ''))
            if not user:
                return handler.send_json(401, {'error': 'Unauthorized'})
            from botai.capabilities.export_engine.md_exporter import md_exporter
            result = md_exporter.export_conversation(data.get('conversation_id'), user['id'])
            handler.send_json(200, result)

        # --- RAG ---
        elif path == '/api/capabilities/rag/index' and settings.ENABLE_RAG:
            data = handler.read_body()
            user = handler.get_user_from_token(data.get('session_token', ''))
            if not user:
                return handler.send_json(401, {'error': 'Unauthorized'})
            from botai.capabilities.rag.service import rag_service
            result = rag_service.index_file(data.get('file_id'), user['id'])
            handler.send_json(200, result)

        elif path == '/api/capabilities/rag/query' and settings.ENABLE_RAG:
            data = handler.read_body()
            user = handler.get_user_from_token(data.get('session_token', ''))
            if not user:
                return handler.send_json(401, {'error': 'Unauthorized'})
            from botai.capabilities.rag.service import rag_service
            result = rag_service.query(data.get('query', ''), user['id'], data.get('conversation_id'))
            handler.send_json(200, result)

        # --- Security Audit Logs (admin) ---
        elif path == '/api/capabilities/security/audit' and settings.ENABLE_SECURITY_LAYER:
            data = handler.read_body()
            user = handler.get_user_from_token(data.get('session_token', ''))
            if not user or not user.get('is_admin', False):
                return handler.send_json(403, {'error': 'Admin access required'})
            from botai.capabilities.security.audit_logger import audit_logger
            handler.send_json(200, {'logs': audit_logger.get_recent(limit=data.get('limit', 50))})

        else:
            handler.send_json(404, {'error': 'Capability endpoint not found or module disabled'})

    except Exception as e:
        print(f"[CapabilitiesRouter] Error on {path}: {e}")
        handler.send_json(500, {'error': f'Capability error: {str(e)}'})


def handle_get(handler):
    """Handle GET requests for capabilities (downloads, etc.)."""
    path = handler.path
    try:
        if path.startswith('/api/capabilities/export/download/') and settings.ENABLE_EXPORT_ENGINE:
            from botai.capabilities.export_engine.service import export_manager
            export_manager.handle_download(handler)
        else:
            handler.send_json(404, {'error': 'Not found'})
    except Exception as e:
        print(f"[CapabilitiesRouter] GET error on {path}: {e}")
        handler.send_json(500, {'error': str(e)})
