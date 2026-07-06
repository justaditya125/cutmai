"""
External API routes for CampusOne LMS integration.
Provides API key-authenticated endpoints that CampusOne can call
to get AI responses from the chatbot.

Authentication: X-API-Key header or api_key in body.
No session/CSRF required — API key is the auth mechanism.
"""
import json
import os
import re
import urllib.request
import urllib.error
from datetime import datetime
from botai.config import settings
from botai.config.mysql_config import get_db
from botai.utils.rate_limiter import is_rate_limited


# ── System prompt for CampusOne AI Tutor ──
_CAMPUSONE_SYSTEM_PROMPT = """You are CUTM AI Tutor, an AI assistant for Centurion University of Technology and Management (CUTM).

ROLE: You are an AI tutor integrated into the CampusOne LMS. You help students and faculty with academic questions, course content, assignments, and learning.

BEHAVIOR:
- Answer questions clearly, accurately, and concisely
- Use markdown formatting for readability (headers, lists, code blocks)
- When explaining concepts, provide examples
- For code questions, include working code examples
- If you're unsure, say so honestly
- Be encouraging and supportive in tone
- For assignment-related questions, guide the student to understand the concept rather than just giving the answer

CONTEXT: You are serving CUTM students and faculty through the CampusOne learning management system. Your responses will be displayed in the CampusOne AI Tutor interface.

FILE GENERATION:
When a user asks you to CREATE, GENERATE, or MAKE any file, output the actual FILE CONTENT inside a code block with the correct language tag and a filename tag on the first line:
```language
[filename="filename.ext"]
<file content here>
```
Supported: docx, pdf, xlsx, csv, pptx, html, css, javascript, python, java, c, cpp, sql, bash, md, json, xml"""


def _get_api_key(handler):
    """Extract API key from X-API-Key header or request body."""
    # Try header first
    api_key = handler.headers.get('X-API-Key', '').strip()
    if api_key:
        return api_key

    # Try body
    try:
        data = handler.read_body()
        return (data.get('api_key') or '').strip()
    except Exception:
        return ''


def _validate_api_key(api_key):
    """Validate the API key against configured CampusOne keys."""
    if not api_key:
        return False
    valid_keys = [k.strip() for k in settings.CAMPUSONE_API_KEYS if k.strip()]
    if not valid_keys:
        return False
    import secrets
    return any(secrets.compare_digest(api_key, valid_key) for valid_key in valid_keys)


def _groq_chat_external(messages, model='llama-3.3-70b-versatile', max_tokens=2000):
    """Call Groq OpenAI-compatible API for external requests."""
    api_key = settings.GROQ_API_KEY
    base_url = settings.GROQ_API_URL
    if not api_key:
        raise ValueError('GROQ_API_KEY not configured')

    payload = {
        'model': model,
        'messages': messages,
        'max_tokens': max_tokens,
        'temperature': 0.7,
        'stream': False,
    }
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        f'{base_url}/chat/completions',
        data=data,
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}',
            'User-Agent': 'CUTM-AI-CampusOne/1.0',
            'Accept': 'application/json',
        },
        method='POST'
    )
    return urllib.request.urlopen(req, timeout=120)


def _ollama_chat_external(messages, model=None):
    """Call Ollama local LLM for external requests."""
    model = model or settings.OLLAMA_MODEL
    url = f"{settings.OLLAMA_BASE_URL}/api/chat"
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "stream": False
    }).encode('utf-8')
    req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'})
    return urllib.request.urlopen(req, timeout=120)


def handle_post(handler):
    """Route POST requests for /api/external/*"""
    path = handler.path
    if path == '/api/external/chat':
        handle_chat(handler)
    elif path == '/api/external/chat/stream':
        handle_chat_stream(handler)
    else:
        handler.send_json(404, {'error': 'Not found'})


def handle_get(handler):
    """Route GET requests for /api/external/*"""
    path = handler.path.split('?')[0]
    if path == '/api/external/health':
        handle_health(handler)
    elif path == '/api/external/docs':
        handle_docs(handler)
    else:
        handler.send_json(404, {'error': 'Not found'})


def handle_health(handler):
    """GET /api/external/health — Public health check (no auth needed)."""
    groq_ok = bool(settings.GROQ_API_KEY)
    zen_ok = bool(settings.ZEN_API_KEY)
    ollama_ok = settings.ENABLE_LOCAL_LLM
    handler.send_json(200, {
        'status': 'healthy',
        'service': 'CUTM AI Chatbot - CampusOne API',
        'version': '1.0.0',
        'providers': {
            'groq': 'available' if groq_ok else 'not_configured',
            'zen': 'available' if zen_ok else 'not_configured',
            'ollama': 'available' if ollama_ok else 'disabled'
        }
    })


def handle_docs(handler):
    """GET /api/external/docs — API documentation."""
    docs = {
        'service': 'CUTM AI Chatbot - CampusOne Integration API',
        'version': '1.0.0',
        'authentication': {
            'method': 'API Key',
            'header': 'X-API-Key: <your-api-key>',
            'or_body': '"api_key": "<your-api-key>"',
            'note': 'Obtain your API key from the CUTM AI admin.'
        },
        'endpoints': {
            'POST /api/external/chat': {
                'description': 'Send a message and get an AI response (non-streaming)',
                'request': {
                    'message': '(required) The user question or prompt',
                    'api_key': '(required unless X-API-Key header) Your API key',
                    'model': '(optional) Model to use. Default: groq-llama-3.3-70b. Options: groq-llama-3.3-70b, groq-llama-3.1-8b, local',
                    'context': '(optional) Additional context (e.g. course name, topic)',
                    'user_id': '(optional) CampusOne user ID for tracking'
                },
                'response': {
                    'success': True,
                    'response': 'AI response text',
                    'model': 'model ID used',
                    'usage': {'input_tokens': 0, 'output_tokens': 0}
                },
                'example_curl': 'curl -X POST https://sathi.cutm.ac.in/api/external/chat -H "Content-Type: application/json" -H "X-API-Key: YOUR_KEY" -d \'{"message": "What is machine learning?"}\''
            },
            'POST /api/external/chat/stream': {
                'description': 'Send a message and get an AI response via Server-Sent Events (SSE)',
                'request': 'Same as /api/external/chat',
                'response': 'SSE stream with data: {"type": "delta", "text": "..."} events'
            },
            'GET /api/external/health': {
                'description': 'Health check (no auth required)',
                'response': {'status': 'healthy', 'service': '...', 'providers': {...}}
            }
        },
        'rate_limits': {
            'chat': '30 requests per minute per API key',
            'chat_stream': '30 requests per minute per API key'
        },
        'supported_models': [
            {'key': 'groq-llama-3.3-70b', 'name': 'Llama 3.3 70B (Groq)', 'cost': 'free'},
            {'key': 'groq-llama-3.1-8b', 'name': 'Llama 3.1 8B (Groq)', 'cost': 'free'},
            {'key': 'local', 'name': 'Llama 3.1 8B (Ollama)', 'cost': 'free'}
        ]
    }
    handler.send_json(200, docs)


def handle_chat(handler):
    """
    POST /api/external/chat
    Non-streaming AI chat for CampusOne integration.

    Request:  { message, api_key, model?, context?, user_id? }
    Response: { success, response, model, usage }
    """
    # 1. Authenticate via API key
    api_key = _get_api_key(handler)
    if not _validate_api_key(api_key):
        return handler.send_json(401, {'success': False, 'error': 'Invalid or missing API key'})

    # 2. Rate limit
    client_ip = handler.get_client_ip()
    if is_rate_limited(client_ip, 'external_chat', limit=30, window=60):
        return handler.send_json(429, {'success': False, 'error': 'Rate limit exceeded (30/min). Please wait.'})

    # 3. Read request
    try:
        data = handler.read_body()
    except Exception:
        return handler.send_json(400, {'success': False, 'error': 'Invalid JSON body'})

    user_message = (data.get('message') or '').strip()
    if not user_message:
        return handler.send_json(400, {'success': False, 'error': 'Message is required'})

    if len(user_message) > 50000:
        return handler.send_json(400, {'success': False, 'error': 'Message too long (max 50KB)'})

    model_key = data.get('model', settings.EXTERNAL_DEFAULT_MODEL)
    context = (data.get('context') or '').strip()
    campus_user_id = (data.get('user_id') or '').strip()

    # 4. Build messages
    system_prompt = _CAMPUSONE_SYSTEM_PROMPT
    if context:
        system_prompt += f"\n\nAdditional context from CampusOne: {context}"

    messages = [{"role": "system", "content": system_prompt}]
    messages.append({"role": "user", "content": user_message})

    # 5. Route to provider
    model_info = settings.MODEL_REGISTRY.get(model_key, {})
    provider = model_info.get('provider', 'groq')
    actual_model_id = model_info.get('id', model_key)

    try:
        if provider == 'ollama' and settings.ENABLE_LOCAL_LLM:
            resp = _ollama_chat_external(messages, model=actual_model_id)
            result = json.loads(resp.read())
            assistant_text = result.get('message', {}).get('content', '')
            usage = {
                'input_tokens': result.get('prompt_eval_count', 0),
                'output_tokens': result.get('eval_count', 0)
            }
        elif provider == 'groq' and settings.GROQ_API_KEY:
            resp = _groq_chat_external(messages, model=actual_model_id, max_tokens=2000)
            result = json.loads(resp.read().decode('utf-8'))
            assistant_text = result['choices'][0]['message']['content']
            usage = result.get('usage', {})
        elif provider == 'zen' and settings.ZEN_API_KEY:
            # Zen uses same OpenAI-compatible API
            from botai.routes.chat_routes import _zen_chat
            resp = _zen_chat(messages, model=actual_model_id, stream=False, max_tokens=2000)
            result = json.loads(resp.read().decode('utf-8'))
            choice = result['choices'][0]
            msg = choice.get('message', {})
            assistant_text = msg.get('content') or msg.get('reasoning_content') or choice.get('text') or ''
            usage = result.get('usage', {})
        else:
            return handler.send_json(503, {
                'success': False,
                'error': f'Model provider "{provider}" is not configured or available'
            })
    except ValueError as ve:
        return handler.send_json(503, {'success': False, 'error': str(ve)})
    except urllib.error.HTTPError as e:
        print(f"[External API] Provider HTTP error: {e.code}")
        return handler.send_json(502, {'success': False, 'error': 'AI provider returned an error'})
    except Exception as e:
        print(f"[External API] Provider error: {type(e).__name__}: {e}")
        return handler.send_json(502, {'success': False, 'error': 'AI provider request failed'})

    # 6. Log usage
    if campus_user_id:
        try:
            db = get_db()
            if db is not None:
                db.token_usage.insert_one({
                    "user_id": f"campusone:{campus_user_id}",
                    "input_tokens": usage.get('input_tokens', usage.get('prompt_tokens', 0)),
                    "output_tokens": usage.get('output_tokens', usage.get('completion_tokens', 0)),
                    "total_tokens": usage.get('input_tokens', usage.get('prompt_tokens', 0)) + usage.get('output_tokens', usage.get('completion_tokens', 0)),
                    "model": actual_model_id,
                    "source": "campusone",
                    "created_at": datetime.now()
                })
        except Exception as log_err:
            print(f"[External API] Usage logging error: {log_err}")

    # 7. Return response
    input_tokens = usage.get('input_tokens', usage.get('prompt_tokens', 0))
    output_tokens = usage.get('output_tokens', usage.get('completion_tokens', 0))

    handler.send_json(200, {
        'success': True,
        'response': assistant_text,
        'model': actual_model_id,
        'provider': provider,
        'usage': {
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'total_tokens': input_tokens + output_tokens
        }
    })


def handle_chat_stream(handler):
    """
    POST /api/external/chat/stream
    Streaming AI chat for CampusOne integration (SSE).

    Request:  { message, api_key, model?, context?, user_id? }
    Response: SSE stream with data: {"type": "delta", "text": "..."} events
    """
    # 1. Authenticate via API key
    api_key = _get_api_key(handler)
    if not _validate_api_key(api_key):
        handler.send_response(401)
        handler.send_header('Content-Type', 'text/event-stream')
        handler.end_headers()
        handler.wfile.write(b'data: {"type": "error", "message": "Invalid or missing API key"}\n\n')
        return

    # 2. Rate limit
    client_ip = handler.get_client_ip()
    if is_rate_limited(client_ip, 'external_chat', limit=30, window=60):
        handler.send_response(429)
        handler.send_header('Content-Type', 'text/event-stream')
        handler.end_headers()
        handler.wfile.write(b'data: {"type": "error", "message": "Rate limit exceeded"}\n\n')
        return

    # 3. Read request
    try:
        data = handler.read_body()
    except Exception:
        handler.send_response(400)
        handler.send_header('Content-Type', 'text/event-stream')
        handler.end_headers()
        handler.wfile.write(b'data: {"type": "error", "message": "Invalid JSON body"}\n\n')
        return

    user_message = (data.get('message') or '').strip()
    if not user_message:
        handler.send_response(400)
        handler.send_header('Content-Type', 'text/event-stream')
        handler.end_headers()
        handler.wfile.write(b'data: {"type": "error", "message": "Message is required"}\n\n')
        return

    if len(user_message) > 50000:
        handler.send_response(400)
        handler.send_header('Content-Type', 'text/event-stream')
        handler.end_headers()
        handler.wfile.write(b'data: {"type": "error", "message": "Message too long (max 50KB)"}\n\n')
        return

    model_key = data.get('model', settings.EXTERNAL_DEFAULT_MODEL)
    context = (data.get('context') or '').strip()
    campus_user_id = (data.get('user_id') or '').strip()

    # 4. Build messages
    system_prompt = _CAMPUSONE_SYSTEM_PROMPT
    if context:
        system_prompt += f"\n\nAdditional context from CampusOne: {context}"

    messages = [{"role": "system", "content": system_prompt}]
    messages.append({"role": "user", "content": user_message})

    # 5. Route to provider (streaming)
    model_info = settings.MODEL_REGISTRY.get(model_key, {})
    provider = model_info.get('provider', 'groq')
    actual_model_id = model_info.get('id', model_key)

    # Send SSE headers
    handler.send_response(200)
    handler.send_header('Content-Type', 'text/event-stream')
    handler.send_header('Cache-Control', 'no-cache')
    handler.send_header('X-Accel-Buffering', 'no')
    origin = handler.headers.get('Origin', '')
    if origin in settings.CORS_ORIGINS:
        handler.send_header('Access-Control-Allow-Origin', origin)
    handler.end_headers()

    full_response = ""

    try:
        if provider == 'ollama' and settings.ENABLE_LOCAL_LLM:
            import json as _json
            payload = _json.dumps({
                "model": actual_model_id,
                "messages": messages,
                "stream": True
            }).encode('utf-8')
            req = urllib.request.Request(
                f"{settings.OLLAMA_BASE_URL}/api/chat",
                data=payload,
                headers={'Content-Type': 'application/json'}
            )
            resp = urllib.request.urlopen(req, timeout=120)
            for line in resp:
                line = line.decode('utf-8').strip()
                if not line:
                    continue
                try:
                    chunk = _json.loads(line)
                    token = chunk.get('message', {}).get('content', '')
                    if token:
                        full_response += token
                        msg_out = _json.dumps({'type': 'delta', 'text': token})
                        handler.wfile.write(f'data: {msg_out}\n\n'.encode('utf-8'))
                        handler.wfile.flush()
                    if chunk.get('done'):
                        break
                except _json.JSONDecodeError:
                    continue

        elif provider == 'groq' and settings.GROQ_API_KEY:
            import json as _json
            payload = _json.dumps({
                'model': actual_model_id,
                'messages': messages,
                'max_tokens': 2000,
                'temperature': 0.7,
                'stream': True,
            }).encode('utf-8')
            req = urllib.request.Request(
                f'{settings.GROQ_API_URL}/chat/completions',
                data=payload,
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {settings.GROQ_API_KEY}',
                    'User-Agent': 'CUTM-AI-CampusOne/1.0',
                    'Accept': 'application/json',
                },
                method='POST'
            )
            resp = urllib.request.urlopen(req, timeout=120)
            for line in resp:
                line = line.decode('utf-8').strip()
                if not line or not line.startswith('data: '):
                    continue
                payload_str = line[6:]
                if payload_str == '[DONE]':
                    break
                try:
                    chunk = _json.loads(payload_str)
                    delta = chunk.get('choices', [{}])[0].get('delta', {})
                    token = delta.get('content', '')
                    if token:
                        full_response += token
                        msg_out = _json.dumps({'type': 'delta', 'text': token})
                        handler.wfile.write(f'data: {msg_out}\n\n'.encode('utf-8'))
                        handler.wfile.flush()
                except _json.JSONDecodeError:
                    continue

        elif provider == 'zen' and settings.ZEN_API_KEY:
            import json as _json
            payload = _json.dumps({
                'model': actual_model_id,
                'messages': messages,
                'max_tokens': 2000,
                'temperature': 0.7,
                'stream': True,
            }).encode('utf-8')
            req = urllib.request.Request(
                f'{settings.ZEN_API_URL}/chat/completions',
                data=payload,
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {settings.ZEN_API_KEY}',
                    'User-Agent': 'CUTM-AI-CampusOne/1.0',
                    'Accept': 'application/json',
                },
                method='POST'
            )
            resp = urllib.request.urlopen(req, timeout=120)
            for line in resp:
                line = line.decode('utf-8').strip()
                if not line or not line.startswith('data: '):
                    continue
                payload_str = line[6:]
                if payload_str == '[DONE]':
                    break
                try:
                    chunk = _json.loads(payload_str)
                    choice = chunk.get('choices', [{}])[0]
                    delta = choice.get('delta', {})
                    token = delta.get('content') or delta.get('reasoning_content') or ''
                    if token:
                        full_response += token
                        msg_out = _json.dumps({'type': 'delta', 'text': token})
                        handler.wfile.write(f'data: {msg_out}\n\n'.encode('utf-8'))
                        handler.wfile.flush()
                except _json.JSONDecodeError:
                    continue
        else:
            err_msg = json.dumps({'type': 'error', 'message': f'Model provider "{provider}" is not available'})
            handler.wfile.write(f'data: {err_msg}\n\n'.encode('utf-8'))
            handler.wfile.flush()

        # Send done event
        done_msg = json.dumps({
            'type': 'done',
            'model': actual_model_id,
            'provider': provider,
            'response_length': len(full_response)
        })
        handler.wfile.write(f'data: {done_msg}\n\n'.encode('utf-8'))
        handler.wfile.flush()

    except Exception as e:
        print(f"[External API] Stream error: {type(e).__name__}: {e}")
        err_msg = json.dumps({'type': 'error', 'message': 'AI provider request failed'})
        try:
            handler.wfile.write(f'data: {err_msg}\n\n'.encode('utf-8'))
            handler.wfile.flush()
        except Exception:
            pass

    # Log usage after stream completes
    if campus_user_id and full_response:
        try:
            db = get_db()
            if db is not None:
                db.token_usage.insert_one({
                    "user_id": f"campusone:{campus_user_id}",
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "model": actual_model_id,
                    "source": "campusone",
                    "created_at": datetime.now()
                })
        except Exception:
            pass
