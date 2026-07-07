"""
Chat and conversation routes
"""
import re
import json
import os
import socket
import urllib.request
import urllib.error
from datetime import datetime
from botai.config import settings
from botai.config.mysql_config import get_db
from botai.utils.logger import log_suspicious_activity, increment_failed_api_requests
from botai.utils.rate_limiter import is_rate_limited
from botai.services.key_rotator import key_rotator
from botai.services.context_compactor import context_compactor
from botai.services.file_handler import FileHandler


from botai.utils.validators import sanitize_input


def _is_safe_url(url: str) -> bool:
    """Check if a URL points to a public (non-private) IP address. Returns False if unsafe (SSRF protection)."""
    from urllib.parse import urlparse
    import socket
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            return False

        blocked_hosts = {'localhost', '127.0.0.1', '0.0.0.0', '::1', '169.254.169.254'}
        if hostname.lower() in blocked_hosts:
            return False

        ips = socket.getaddrinfo(hostname, None)
        for family, _, _, _, sockaddr in ips:
            ip = sockaddr[0]
            if family == socket.AF_INET:
                parts = ip.split('.')
                if parts[0] == '10':
                    return False
                if parts[0] == '172' and 16 <= int(parts[1]) <= 31:
                    return False
                if parts[0] == '192' and parts[1] == '168':
                    return False
                if parts[0] == '127':
                    return False
                if parts[0] == '0':
                    return False
                if parts[0] == '169' and parts[1] == '254':
                    return False
            elif family == socket.AF_INET6:
                if ip in ('::1',) or ip.startswith('fc') or ip.startswith('fd'):
                    return False
        return True
    except Exception:
        return False


def save_token_usage(db, user_id, input_tokens, output_tokens, model='claude-haiku-4-5',
                     cache_creation_tokens=0, cache_read_tokens=0):
    """Save token usage to database and print detailed log"""
    total = input_tokens + output_tokens
    u_id = user_id
    try:
        # Insert token usage record
        db.token_usage.insert_one({
            "user_id": u_id,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_creation_input_tokens": cache_creation_tokens,
            "cache_read_input_tokens": cache_read_tokens,
            "total_tokens": total,
            "model": model,
            "created_at": datetime.now()
        })

        # Update user total tokens
        db.users.update_one(
            {"_id": u_id},
            {
                "$inc": {"total_tokens_used": total, "total_messages": 1},
                "$set": {"updated_at": datetime.now()}
            }
        )

        # Fetch updated user stats for logging
        user = db.users.find_one({"_id": u_id})
        if not user:
            return

        # Real-time console log (safe ascii prints)
        print("\n" + "="*55)
        print("  TOKEN USAGE LOG")
        print("="*55)
        print(f"  User     : {user['email']}")
        print(f"  Input    : {input_tokens} tokens")
        print(f"  Output   : {output_tokens} tokens")
        print(f"  This msg : {total} tokens")
        print(f"  Total    : {user['total_tokens_used']} tokens (lifetime)")
        print(f"  Messages : {user['total_messages']} total")
        print("="*55 + "\n")

    except Exception as e:
        print(f"[ERROR] Token save error: {e}")

def get_user_quota_info(db, user_id, user_doc=None):
    """Calculates and returns user's token usage, limit, balance, and credits consumed."""
    from botai.capabilities.model_orchestration.cost_estimator import cost_estimator
    if user_doc is None:
        user_doc = db.users.find_one({"_id": user_id})
    if not user_doc:
        return None
    
    # Calculate user credits
    credits = 0.0
    try:
        user_tokens = list(db.token_usage.find({"user_id": user_id}))
        for r in user_tokens:
            m = r.get("model", "")
            in_t = r.get("input_tokens", 0)
            out_t = r.get("output_tokens", 0)
            c_write = r.get("cache_creation_input_tokens", 0)
            c_read = r.get("cache_read_input_tokens", 0)
            
            est = cost_estimator.estimate(m, in_t, out_t, c_write, c_read)
            credits += est['total_cost']
    except Exception as ex:
        print(f"Error calculating credits for user {user_id}: {ex}")

    total_tokens = user_doc.get("total_tokens_used") or 0
    limit = user_doc.get("token_limit") or 1000000
    balance = max(0, limit - total_tokens)
    
    return {
        'total_tokens_used': total_tokens,
        'token_limit': limit,
        'token_balance': balance,
        'credits_used': credits
    }

def trim_messages(messages_list, max_messages=6):
    """Trims message history to optimize tokens. Ensures alternating user/assistant roles."""
    if not messages_list:
        return []
    if len(messages_list) <= max_messages:
        return messages_list
    trimmed = messages_list[-max_messages:]
    if trimmed and trimmed[0].get('role') == 'assistant':
        trimmed = trimmed[1:]
    return trimmed

def handle_post(handler):
    path = handler.path
    if path == '/api/claude':
        handle_claude(handler)
    elif path == '/api/claude/stream':
        handle_claude_stream(handler)
    elif path == '/api/claude/vision':
        handle_claude_vision(handler)
    elif path == '/api/local/stream':
        handle_local_stream(handler)
    elif path == '/api/local':
        handle_local(handler)
    elif path == '/api/local/status':
        handle_local_status(handler)
    elif path == '/api/groq/stream':
        handle_groq_stream(handler)
    elif path == '/api/groq':
        handle_groq(handler)
    elif path == '/api/zen/stream':
        handle_zen_stream(handler)
    elif path == '/api/zen':
        handle_zen(handler)
    elif path == '/api/files/generate':
        handle_file_generate(handler)
    elif path == '/api/conversations/new':
        handle_new_conversation(handler)
    elif path == '/api/conversations/list':
        handle_list_conversations(handler)
    elif path == '/api/conversations/messages':
        handle_get_messages(handler)
    elif path == '/api/conversations/delete':
        handle_delete_conversation(handler)
    elif path == '/api/conversations/rename':
        handle_rename_conversation(handler)
    elif path == '/api/messages/feedback':
        handle_message_feedback(handler)
    elif path == '/api/messages/edit':
        handle_edit_message(handler)
    elif path == '/api/files/upload':
        handle_file_upload(handler)
    elif path == '/api/files/delete':
        handle_file_delete(handler)
    elif path == '/api/gdrive/load':
        handle_gdrive_load(handler)
    elif path == '/api/gdrive/clear':
        handle_gdrive_clear(handler)
    else:
        if hasattr(handler, 'send_json'):
            handler.send_json(404, {'error': 'Not found'})
        else:
            send_json_response(handler, 404, {'error': 'Not found'})

def handle_gdrive_load(handler):
    """
    POST /api/gdrive/load
    Load a public Google Drive folder or file as a conversation knowledge base.
    Saves the fetched document text into the conversation document in MySQL.
    Request:  { session_token, conversation_id, gdrive_url }
    Response: { success, files_loaded, file_names, total_chars, preview, conversation_id }
    """
    data          = handler.read_body()
    token         = data.get('session_token', '')
    conv_id       = data.get('conversation_id')
    gdrive_url    = data.get('gdrive_url', '').strip()
    user          = handler.get_user_from_token(token)

    if not user:
        return handler.send_json(401, {'error': 'Unauthorized'})
    if not gdrive_url:
        return handler.send_json(400, {'error': 'gdrive_url is required'})

    db = get_db()
    if db is None:
        return handler.send_json(500, {'error': 'Database unavailable'})

    # Auto-create conversation if not provided
    if not conv_id:
        try:
            res = db.conversations.insert_one({
                'user_id': user['_id'],
                'title': 'Drive Knowledge Base',
                'created_at': datetime.now(),
                'updated_at': datetime.now()
            })
            conv_id = res.inserted_id
        except Exception as e:
            return handler.send_json(500, {'error': 'Failed to create conversation'})

    # Verify ownership
    try:
        conv = db.conversations.find_one({'_id': conv_id, 'user_id': user['_id']})
        if not conv:
            return handler.send_json(403, {'error': 'Forbidden — conversation not found or not yours'})
    except Exception as e:
        return handler.send_json(400, {'error': f'Invalid conversation_id: {e}'})

    print(f"[Drive KB] User {user['email']} loading Drive URL: {gdrive_url}")

    # Fetch documents — this may take several seconds for large folders
    result = FileHandler.fetch_gdrive_documents(gdrive_url)

    if result.get('error'):
        return handler.send_json(400, {'success': False, 'error': result['error']})

    if not result['files']:
        return handler.send_json(400, {
            'success': False,
            'error': 'No readable documents found. Make sure the Drive is shared as "Anyone with the link" and contains supported file types (PDF, DOCX, XLSX, TXT, etc.).'
        })

    # Build the combined context text
    context_parts = []
    file_names = []
    for f in result['files']:
        if f.get('text') and f['text'].strip():
            context_parts.append(f"=== {f['name']} ===\n{f['text'].strip()}")
            file_names.append(f['name'])

    gdrive_context = "\n\n".join(context_parts)
    preview = gdrive_context[:300] + '...' if len(gdrive_context) > 300 else gdrive_context

    # Persist to MySQL conversation document
    try:
        db.conversations.update_one(
            {'_id': conv_id},
            {'$set': {
                'gdrive_url':        gdrive_url,
                'gdrive_context':    gdrive_context,
                'gdrive_file_names': file_names,
                'gdrive_loaded_at':  datetime.now(),
                'updated_at':        datetime.now()
            }}
        )
    except Exception as e:
        return handler.send_json(500, {'error': 'Failed to save Drive context'})

    print(f"[Drive KB] Loaded {result['files_loaded']} docs ({result['total_chars']:,} chars) for conversation {conv_id}")

    handler.send_json(200, {
        'success':       True,
        'conversation_id': conv_id,
        'files_loaded':  result['files_loaded'],
        'files_skipped': result['files_skipped'],
        'file_names':    file_names,
        'total_chars':   result['total_chars'],
        'preview':       preview
    })


def handle_gdrive_clear(handler):
    """
    POST /api/gdrive/clear
    Remove the Google Drive knowledge base from a conversation.
    Request:  { session_token, conversation_id }
    Response: { success }
    """
    data    = handler.read_body()
    token   = data.get('session_token', '')
    conv_id = data.get('conversation_id')
    user    = handler.get_user_from_token(token)

    if not user:
        return handler.send_json(401, {'error': 'Unauthorized'})

    db = get_db()
    if db is None:
        return handler.send_json(500, {'error': 'Database unavailable'})

    try:
        db.conversations.update_one(
            {'_id': conv_id, 'user_id': user['_id']},
            {'$unset': {'gdrive_url': '', 'gdrive_context': '', 'gdrive_file_names': '', 'gdrive_loaded_at': ''}}
        )
        handler.send_json(200, {'success': True})
    except Exception as e:
        handler.send_json(500, {'error': 'Internal server error'})


def handle_new_conversation(handler):
    data  = handler.read_body()
    token = data.get('session_token', '')
    title = (sanitize_input(data.get('title') or '') or 'New Chat')[:200]  # Max 200 chars
    user  = handler.get_user_from_token(token)
    if not user:
        return handler.send_json(401, {'error': 'Unauthorized'})
    db = get_db()
    if db is None: return handler.send_json(500, {'error': 'DB error'})
    try:
        conv_doc = {
            "user_id": user['_id'],
            "title": title,
            "created_at": datetime.now(),
            "updated_at": datetime.now()
        }
        res = db.conversations.insert_one(conv_doc)
        conv_id = res.inserted_id
        handler.send_json(200, {'success': True, 'conversation_id': conv_id, 'title': title})
    except Exception as e:
        handler.send_json(500, {'error': 'Internal server error'})

def handle_list_conversations(handler):
    data  = handler.read_body()
    token = data.get('session_token', '')
    user  = handler.get_user_from_token(token)
    if not user:
        return handler.send_json(401, {'error': 'Unauthorized'})
    db = get_db()
    if db is None: return handler.send_json(500, {'error': 'DB error'})
    try:
        convs = list(db.conversations.find({"user_id": user['_id']}).sort("updated_at", -1))
        conv_list = []
        for c in convs:
            msg_count = db.messages.count_documents({"conversation_id": c['_id']})
            c_created = c.get("created_at")
            c_updated = c.get("updated_at")
            conv_list.append({
                "id": c['_id'],
                "title": c.get("title", "New Conversation"),
                "created_at": c_created.strftime('%Y-%m-%d %H:%M:%S') if isinstance(c_created, datetime) else str(c_created),
                "updated_at": c_updated.strftime('%Y-%m-%d %H:%M:%S') if isinstance(c_updated, datetime) else str(c_updated),
                "message_count": msg_count,
                "gdrive_file_names": c.get("gdrive_file_names", []),
                "has_drive_kb": bool(c.get("gdrive_context"))
            })
        handler.send_json(200, {'conversations': conv_list})
    except Exception as e:
        handler.send_json(500, {'error': 'Internal server error'})

def handle_get_messages(handler):
    data    = handler.read_body()
    token   = data.get('session_token', '')
    conv_id = data.get('conversation_id')
    user    = handler.get_user_from_token(token)
    if not user:
        return handler.send_json(401, {'error': 'Unauthorized'})
    db = get_db()
    if db is None: return handler.send_json(500, {'error': 'DB error'})
    try:
        c_id = conv_id
        # Verify ownership
        conv = db.conversations.find_one({"_id": c_id, "user_id": user['_id']})
        if not conv:
            return handler.send_json(403, {'error': 'Forbidden'})
            
        msgs = list(db.messages.find({"conversation_id": c_id}).sort("created_at", 1))
        msg_list = []
        for m in msgs:
            m_created = m.get("created_at")
            msg_list.append({
                "id": m["_id"],
                "role": m.get("role"),
                "content": m.get("content"),
                "feedback": m.get("feedback", "none"),
                "created_at": m_created.strftime('%Y-%m-%d %H:%M:%S') if isinstance(m_created, datetime) else str(m_created)
            })
        handler.send_json(200, {
            'messages': msg_list,
            'gdrive_file_names': conv.get('gdrive_file_names', []),
            'gdrive_url': conv.get('gdrive_url', '')
        })
    except Exception as e:
        handler.send_json(500, {'error': 'Internal server error'})

def handle_delete_conversation(handler):
    data    = handler.read_body()
    token   = data.get('session_token', '')
    conv_id = data.get('conversation_id')
    user    = handler.get_user_from_token(token)
    if not user:
        return handler.send_json(401, {'error': 'Unauthorized'})
    db = get_db()
    if db is None: return handler.send_json(500, {'error': 'DB error'})
    try:
        c_id = conv_id
        
        # Verify ownership and delete conversation
        res = db.conversations.delete_one({"_id": c_id, "user_id": user['_id']})
        if res.deleted_count > 0:
            db.messages.delete_many({"conversation_id": c_id})
            
        handler.send_json(200, {'success': True})
    except Exception as e:
        handler.send_json(500, {'error': 'Internal server error'})

def handle_rename_conversation(handler):
    data    = handler.read_body()
    token   = data.get('session_token', '')
    conv_id = data.get('conversation_id')
    title   = (sanitize_input(data.get('title') or '') or 'New Chat')[:200]
    user    = handler.get_user_from_token(token)
    if not user:
        return handler.send_json(401, {'error': 'Unauthorized'})
    db = get_db()
    if db is None: return handler.send_json(500, {'error': 'DB error'})
    try:
        c_id = conv_id
        db.conversations.update_one(
            {"_id": c_id, "user_id": user['_id']},
            {"$set": {"title": title, "updated_at": datetime.now()}}
        )
        handler.send_json(200, {'success': True})
    except Exception as e:
        handler.send_json(500, {'error': 'Internal server error'})

def handle_message_feedback(handler):
    data       = handler.read_body()
    token      = data.get('session_token', '')
    message_id = data.get('message_id')
    feedback   = data.get('feedback', 'none')  # 'like' | 'dislike' | 'none'
    user = handler.get_user_from_token(token)
    if not user:
        return handler.send_json(401, {'error': 'Unauthorized'})
    if feedback not in ('like', 'dislike', 'none'):
        return handler.send_json(400, {'error': 'Invalid feedback value'})
    db = get_db()
    if db is None: return handler.send_json(500, {'error': 'DB error'})
    try:
        m_id = message_id
        msg  = db.messages.find_one({'_id': m_id})
        if not msg:
            return handler.send_json(404, {'error': 'Message not found'})
        conv = db.conversations.find_one({'_id': msg['conversation_id'], 'user_id': user['_id']})
        if not conv:
            return handler.send_json(403, {'error': 'Forbidden'})
        db.messages.update_one({'_id': m_id}, {'$set': {'feedback': feedback}})
        handler.send_json(200, {'success': True})
    except Exception as e:
        handler.send_json(500, {'error': 'Internal server error'})

def handle_edit_message(handler):
    data        = handler.read_body()
    token       = data.get('session_token', '')
    message_id  = data.get('message_id')
    new_content = (data.get('new_content', '') or '')[:50000]  # Max 50k chars per message
    user = handler.get_user_from_token(token)
    if not user:
        return handler.send_json(401, {'error': 'Unauthorized'})
    if not new_content.strip():
        return handler.send_json(400, {'error': 'Content cannot be empty'})
    db = get_db()
    if db is None: return handler.send_json(500, {'error': 'DB error'})
    try:
        m_id = message_id
        msg  = db.messages.find_one({'_id': m_id})
        if not msg:
            return handler.send_json(404, {'error': 'Message not found'})
        conv = db.conversations.find_one({'_id': msg['conversation_id'], 'user_id': user['_id']})
        if not conv:
            return handler.send_json(403, {'error': 'Forbidden'})
        msg_created_at = msg.get('created_at')
        db.messages.delete_many({
            'conversation_id': msg['conversation_id'],
            'created_at': {'$gt': msg_created_at}
        })
        db.messages.update_one({'_id': m_id}, {'$set': {'content': new_content.strip(), 'edited': True}})
        db.conversations.update_one({'_id': msg['conversation_id']}, {'$set': {'updated_at': datetime.now()}})
        handler.send_json(200, {'success': True})
    except Exception as e:
        handler.send_json(500, {'error': 'Internal server error'})

def handle_claude_stream(handler):
    """Stream Claude's response using Server-Sent Events (SSE)."""
    client_ip = handler.get_client_ip()
    if is_rate_limited(client_ip, 'claude', limit=30, window=60):
        handler.send_response(429)
        handler.send_header('Content-Type', 'text/event-stream')
        handler.end_headers()
        handler.wfile.write(b'data: {"error": "Rate limited"}\n\n')
        return

    data = handler.read_body()
    session_token = data.get('session_token', '')
    conv_id       = data.get('conversation_id')
    user_message  = data.get('user_message', '')
    user_info     = handler.get_user_from_token(session_token)
    if not user_info:
        handler.send_response(401)
        handler.send_header('Content-Type', 'text/event-stream')
        handler.end_headers()
        handler.wfile.write(b'data: {"error": "Unauthorized"}\n\n')
        return

    db = get_db()
    if db is None:
        handler.send_response(503)
        handler.send_header('Content-Type', 'text/event-stream')
        handler.end_headers()
        handler.wfile.write(b'data: {"error": "Database unavailable"}\n\n')
        return

    total_tokens_used = user_info.get('total_tokens_used', 0)
    token_limit = user_info.get('token_limit', 1000000)
    if total_tokens_used >= token_limit:
        handler.send_response(403)
        handler.send_header('Content-Type', 'text/event-stream')
        handler.end_headers()
        handler.wfile.write(b'data: {"error": "Token limit exceeded"}\n\n')
        return

    user_id = user_info['_id']

    # Auto-create conversation
    if db is not None and user_id and not conv_id:
        try:
            title = (user_message[:40] + '...') if len(user_message) > 40 else user_message
            result = db.conversations.insert_one({
                "user_id": user_id, "title": title or "New Chat",
                "created_at": datetime.now(), "updated_at": datetime.now()
            })
            conv_id = str(result.inserted_id)
        except Exception as e:
            print(f"[ERROR] Conv create error: {e}")

    # Fetch URL/Drive content
    urls = re.findall(r'(https?://[^\s]+)', user_message)
    fetched_contents = ""
    GDRIVE_PATTERNS = ['drive.google.com/file/', 'drive.google.com/open', 'drive.google.com/uc',
                       'drive.google.com/drive/', 'docs.google.com/document/',
                       'docs.google.com/spreadsheets/', 'docs.google.com/presentation/']
    for url in urls:
        clean_url = url.rstrip(').,!]')
        if not _is_safe_url(clean_url):
            print(f"[SSRF] Blocked unsafe URL: {clean_url}")
            continue
        if any(p in clean_url for p in GDRIVE_PATTERNS):
            url_text = FileHandler.fetch_gdrive_text(clean_url)
            fetched_contents += f"\n\n[Google Drive File Content from {clean_url}]\n-----------------------------\n{url_text}\n-----------------------------\n"
        else:
            url_text = FileHandler.fetch_url_text(clean_url)
            fetched_contents += f"\n\n[Webpage Content from {clean_url}]\n-----------------------------\n{url_text}\n-----------------------------\n"

    messages = data.get('messages', [])
    if fetched_contents:
        if messages and messages[-1].get('role') == 'user':
            messages[-1]['content'] = fetched_contents + "\nUser query: " + messages[-1]['content']
            user_message = messages[-1]['content']

    messages = trim_messages(messages, max_messages=6)

    chosen_model = data.get('model', 'claude-haiku-4-5')
    if chosen_model not in ['claude-haiku-4-5', 'claude-sonnet-4-5', 'claude-opus-4-5']:
        chosen_model = 'claude-haiku-4-5'

    system_instructions = (
        "You are CUTM AI, an AI assistant for Centurion University (CUTM). Use markdown.\n"
        "When generating code, prefix with filename tag: [filename=\"file.ext\"] inside code blocks."
    )

    # Inject Google Drive Knowledge Base context if loaded for this conversation
    if db is not None and conv_id:
        try:
            c_id_lookup = conv_id
            conv_doc = db.conversations.find_one({'_id': c_id_lookup}, {'gdrive_context': 1, 'gdrive_file_names': 1})
            if conv_doc and conv_doc.get('gdrive_context'):
                file_names_str = ', '.join(conv_doc.get('gdrive_file_names', []))
                system_instructions += (
                    f"\n\n====================================================\n"
                    f"KNOWLEDGE BASE (loaded from Google Drive)\n"
                    f"Files: {file_names_str}\n"
                    f"====================================================\n"
                    f"{conv_doc['gdrive_context']}\n"
                    f"====================================================\n"
                    "Use the above knowledge base documents to answer the user's questions accurately. "
                    "If the answer is in the documents, cite which document it is from."
                )
                print(f"[Drive KB] Injecting {len(conv_doc['gdrive_context'])} chars of Drive context into stream prompt")
        except Exception as kb_err:
            print(f"[Drive KB] Could not load KB context: {kb_err}")

    active_key = key_rotator.get_key()
    if not active_key:
        handler.send_response(500)
        handler.send_header('Content-Type', 'text/event-stream')
        handler.end_headers()
        handler.wfile.write(b'data: {"error": "No API key"}\n\n')
        return

    thinking_enabled = data.get('thinking_enabled', False)
    payload_dict = {
        'model': chosen_model,
        'max_tokens': min(data.get('max_tokens', 4000), 4000),
        'system': system_instructions,
        'messages': messages,
        'stream': True
    }
    if thinking_enabled:
        payload_dict['thinking'] = {
            'type': 'enabled',
            'budget_tokens': 1024
        }
    claude_payload = json.dumps(payload_dict).encode('utf-8')

    # Validate user_message size
    if len(user_message) > 50000:
        handler.send_response(400)
        handler.send_header('Content-Type', 'text/event-stream')
        handler.end_headers()
        handler.wfile.write(b'data: {"error": "Message too long (max 50KB)"}\n\n')
        return

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
    input_tokens = 0
    output_tokens = 0
    cache_creation_tokens = 0
    cache_read_tokens = 0
    db_saved = False

    try:
        # Send start event immediately with conversation_id
        if conv_id:
            start_msg = json.dumps({'type': 'start', 'conversation_id': conv_id})
            handler.wfile.write(f'data: {start_msg}\n\n'.encode('utf-8'))
            handler.wfile.flush()

        req = urllib.request.Request(
            'https://api.anthropic.com/v1/messages',
            data=claude_payload,
            headers={
                'Content-Type': 'application/json',
                'x-api-key': active_key,
                'anthropic-version': '2023-06-01'
            }
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            for raw_line in resp:
                line = raw_line.decode('utf-8').strip()
                if not line or not line.startswith('data:'):
                    continue
                payload_str = line[5:].strip()
                if payload_str == '[DONE]':
                    break
                try:
                    chunk = json.loads(payload_str)
                    event_type = chunk.get('type', '')
                    if event_type == 'content_block_delta':
                        delta = chunk.get('delta', {})
                        delta_type = delta.get('type', '')
                        if delta_type == 'thinking_delta':
                            delta_thinking = delta.get('thinking', '')
                            if delta_thinking:
                                msg_out = json.dumps({'type': 'thinking', 'text': delta_thinking})
                                handler.wfile.write(f'data: {msg_out}\n\n'.encode('utf-8'))
                                handler.wfile.flush()
                        else:
                            delta_text = delta.get('text', '')
                            if delta_text:
                                full_response += delta_text
                                msg_out = json.dumps({'type': 'delta', 'text': delta_text})
                                handler.wfile.write(f'data: {msg_out}\n\n'.encode('utf-8'))
                                handler.wfile.flush()
                    elif event_type == 'message_delta':
                        usage = chunk.get('usage', {})
                        output_tokens = usage.get('output_tokens', 0)
                    elif event_type == 'message_start':
                        usage = chunk.get('message', {}).get('usage', {})
                        input_tokens = usage.get('input_tokens', 0)
                        cache_creation_tokens = usage.get('cache_creation_input_tokens', 0)
                        cache_read_tokens = usage.get('cache_read_input_tokens', 0)
                except Exception:
                    continue

        # Save to DB after stream completes
        user_msg_id = None
        asst_msg_id = None
        if db is not None and user_id and conv_id and user_message and not db_saved:
            try:
                c_id = conv_id
                user_res = db.messages.insert_one({"conversation_id": c_id, "user_id": user_id, "role": 'user', "content": user_message, "created_at": datetime.now(), "feedback": "none"})
                user_msg_id = user_res.inserted_id
                if full_response:
                    asst_res = db.messages.insert_one({"conversation_id": c_id, "user_id": user_id, "role": 'assistant', "content": full_response, "created_at": datetime.now(), "feedback": "none"})
                    asst_msg_id = asst_res.inserted_id
                db.conversations.update_one({"_id": c_id}, {"$set": {"updated_at": datetime.now()}})
                if input_tokens or output_tokens:
                    save_token_usage(
                        db, user_id, input_tokens, output_tokens, chosen_model,
                        cache_creation_tokens, cache_read_tokens
                    )
                db_saved = True
            except Exception as e:
                print(f"[ERROR] Stream DB save error: {e}")

        # Send final done event with metadata including message IDs
        done_msg = json.dumps({'type': 'done', 'conversation_id': conv_id, 'input_tokens': input_tokens, 'output_tokens': output_tokens, 'user_message_id': user_msg_id, 'assistant_message_id': asst_msg_id})
        handler.wfile.write(f'data: {done_msg}\n\n'.encode('utf-8'))
        handler.wfile.flush()

    except Exception as e:
        increment_failed_api_requests()
        print(f"[ERROR] Stream error: {e}")
        # Save whatever partial progress we made to the DB
        if db is not None and user_id and conv_id and user_message and not db_saved:
            try:
                c_id = conv_id
                db.messages.insert_one({"conversation_id": c_id, "user_id": user_id, "role": 'user', "content": user_message, "created_at": datetime.now(), "feedback": "none"})
                if full_response:
                    db.messages.insert_one({"conversation_id": c_id, "user_id": user_id, "role": 'assistant', "content": full_response, "created_at": datetime.now(), "feedback": "none"})
                db.conversations.update_one({"_id": c_id}, {"$set": {"updated_at": datetime.now()}})
                if input_tokens or output_tokens:
                    save_token_usage(
                        db, user_id, input_tokens, output_tokens, chosen_model,
                        cache_creation_tokens, cache_read_tokens
                    )
                db_saved = True
            except Exception as db_err:
                print(f"[ERROR] Interrupted stream DB save error: {db_err}")
        err_msg = json.dumps({'type': 'error', 'message': 'Internal server error'})
        try:
            handler.wfile.write(f'data: {err_msg}\n\n'.encode('utf-8'))
            handler.wfile.flush()
        except Exception:
            pass

def handle_claude_vision(handler):
    """Accept base64 image + text, send to Claude vision, return response."""
    client_ip = handler.get_client_ip()
    if is_rate_limited(client_ip, 'claude', limit=30, window=60):
        return handler.send_json(429, {'error': 'Rate limit reached. Please slow down.'})

    data = handler.read_body()
    session_token = data.get('session_token', '')
    user_info = handler.get_user_from_token(session_token)
    if not user_info:
        return handler.send_json(401, {'error': 'Unauthorized'})

    image_b64   = data.get('image_base64', '')   # base64 string without prefix
    media_type  = data.get('media_type', 'image/jpeg')  # e.g. image/png
    user_text   = data.get('text', 'What is in this image?')
    chosen_model = data.get('model', 'claude-haiku-4-5')
    if chosen_model not in ['claude-haiku-4-5', 'claude-sonnet-4-5', 'claude-opus-4-5']:
        chosen_model = 'claude-haiku-4-5'

    if len(image_b64) > 10 * 1024 * 1024:
        return handler.send_json(400, {'error': 'Image too large (max 10MB)'})
    if len(user_text) > 50000:
        return handler.send_json(400, {'error': 'Text too long (max 50KB)'})

    if not image_b64:
        return handler.send_json(400, {'error': 'No image provided'})

    active_key = key_rotator.get_key()
    if not active_key:
        return handler.send_json(500, {'error': 'No API key'})

    payload = json.dumps({
        'model': chosen_model,
        'max_tokens': 2048,
        'messages': [{
            'role': 'user',
            'content': [
                {'type': 'image', 'source': {'type': 'base64', 'media_type': media_type, 'data': image_b64}},
                {'type': 'text', 'text': user_text}
            ]
        }]
    }).encode('utf-8')

    try:
        req = urllib.request.Request(
            'https://api.anthropic.com/v1/messages',
            data=payload,
            headers={'Content-Type': 'application/json', 'x-api-key': active_key, 'anthropic-version': '2023-06-01'}
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            response_json = json.loads(resp.read())
            handler.send_response(200)
            handler.send_header('Content-Type', 'application/json')
            handler.end_headers()
            handler.wfile.write(json.dumps(response_json).encode('utf-8'))
    except Exception as e:
        increment_failed_api_requests()
        print(f"[ERROR] Vision error: {e}")
        handler.send_json(500, {'error': 'Internal server error'})

def handle_claude(handler):
    client_ip = handler.get_client_ip()
    if is_rate_limited(client_ip, 'claude', limit=30, window=60):
        return handler.send_json(429, {'error': 'Rate limit reached. Please slow down.'})

    data = handler.read_body()
    session_token = data.get('session_token', '')
    conv_id       = data.get('conversation_id')
    user_message  = data.get('user_message', '')
    user_info     = handler.get_user_from_token(session_token)
    if not user_info:
        return handler.send_json(401, {'error': 'Unauthorized'})

    if len(user_message) > 50000:
        return handler.send_json(400, {'error': 'Message too long (max 50KB)'})

    db = get_db()
    if db is None:
        return handler.send_json(503, {'error': 'Database unavailable'})

    total_tokens_used = user_info.get('total_tokens_used', 0)
    token_limit = user_info.get('token_limit', 1000000)
    if total_tokens_used >= token_limit:
        return handler.send_json(403, {'error': 'You have exceeded your allocated token limit. Please contact the administrator.'})

    user_id = user_info['_id']

    # Auto-create conversation if none provided
    if db is not None and user_id and not conv_id:
        try:
            title = (user_message[:40] + '...') if len(user_message) > 40 else user_message or 'New Chat'
            conv_doc = {
                "user_id": user_id,
                "title": title,
                "created_at": datetime.now(),
                "updated_at": datetime.now()
            }
            res = db.conversations.insert_one(conv_doc)
            conv_id = res.inserted_id
        except Exception as e:
            print(f"Auto-conversation creation failed: {e}")

    # Enforce data visualization and editable document guidelines
    system_instructions = (
        "You are CUTM AI, an AI assistant for Centurion University (CUTM). Use markdown. Image generation is disabled.\n\n"
        "INSTRUCTIONS FOR DATA VISUALIZATION:\n"
        "If the user requests data analytics, sales reports, tables, trends, or any data comparative views, perform thorough calculations/analyses and present interactive charts using the following JSON schema wrapped in a ```chart code block (e.g., ```chart\\n{...}\\n```):\n"
        "{\n"
        "  \"type\": \"bar\", // or \"line\", \"pie\", \"doughnut\", \"radar\"\n"
        "  \"title\": \"Title of Chart\",\n"
        "  \"labels\": [\"Label1\", \"Label2\", ...],\n"
        "  \"datasets\": [\n"
        "    {\n"
        "      \"label\": \"Dataset Label\",\n"
        "      \"data\": [value1, value2, ...]\n"
        "    }\n"
        "  ]\n"
        "}\n\n"
        "INSTRUCTIONS FOR EDITABLE DOCUMENTS & ARTIFACT FILENAMES:\n"
        "When generating structured reports, tables, code scripts, or documents that the user might want to edit, modify, or download, prefix the code block with a filename tag format: [filename=\"filename.ext\"] on the very first line inside the fenced code block (e.g., ```markdown\\n[filename=\"report.md\"]\\n...\\n``` or ```text\\n[filename=\"document.txt\"]\\n...\\n```). Ensure files representing Microsoft Word documents have a `.doc` or `.docx` extension. When the user uploads a document (PDF or Word) and asks for modifications, read the provided text context, perform modifications, and provide the modified version in a fenced code block with a filename tag on the first line."
    )

    # Inject Google Drive Knowledge Base context if loaded for this conversation
    if db is not None and conv_id:
        try:
            c_id_lookup = conv_id
            conv_doc = db.conversations.find_one({'_id': c_id_lookup}, {'gdrive_context': 1, 'gdrive_file_names': 1})
            if conv_doc and conv_doc.get('gdrive_context'):
                file_names_str = ', '.join(conv_doc.get('gdrive_file_names', []))
                system_instructions += (
                    f"\n\n====================================================\n"
                    f"KNOWLEDGE BASE (loaded from Google Drive)\n"
                    f"Files: {file_names_str}\n"
                    f"====================================================\n"
                    f"{conv_doc['gdrive_context']}\n"
                    f"====================================================\n"
                    "Use the above knowledge base documents to answer the user's questions accurately. "
                    "If the answer is in the documents, cite which document it is from."
                )
                print(f"[Drive KB] Injecting {len(conv_doc['gdrive_context'])} chars of Drive context into non-stream prompt")
        except Exception as kb_err:
            print(f"[Drive KB] Could not load KB context: {kb_err}")

    messages = data.get('messages', [])


    # Scan for URLs in user_message and fetch content dynamically
    urls = re.findall(r'(https?://[^\s]+)', user_message)
    fetched_contents = ""
    GDRIVE_PATTERNS = [
        'drive.google.com/file/',
        'drive.google.com/open',
        'drive.google.com/uc',
        'drive.google.com/drive/',
        'docs.google.com/document/',
        'docs.google.com/spreadsheets/',
        'docs.google.com/presentation/',
    ]
    for url in urls:
        clean_url = url.rstrip(').,!]')
        if not _is_safe_url(clean_url):
            print(f"[SSRF] Blocked unsafe URL: {clean_url}")
            continue
        is_gdrive = any(p in clean_url for p in GDRIVE_PATTERNS)
        if is_gdrive:
            print(f"[Drive Fetcher] Detected Google Drive URL: {clean_url}")
            url_text = FileHandler.fetch_gdrive_text(clean_url)
            fetched_contents += f"\n\n[Google Drive File Content from {clean_url}]\n-----------------------------\n{url_text}\n-----------------------------\n"
        else:
            print(f"[Web Fetcher] Detected URL: {clean_url}")
            url_text = FileHandler.fetch_url_text(clean_url)
            fetched_contents += f"\n\n[Webpage Content from {clean_url}]\n-----------------------------\n{url_text}\n-----------------------------\n"

    if fetched_contents:
        user_message = fetched_contents + "\nUser query: " + user_message
        if messages and messages[-1].get('role') == 'user':
            messages[-1]['content'] = fetched_contents + "\nUser query: " + messages[-1]['content']
    
    # Apply Smart Summarization & Context Trimming
    if len(messages) > 12:
        messages_to_summarize = messages[:-6]
        recent_messages = messages[-6:]
        if recent_messages and recent_messages[0].get('role') == 'assistant':
            recent_messages = recent_messages[1:]
        try:
            summary = context_compactor.summarize_history(messages_to_summarize)
            if summary:
                system_instructions += f"\n\nHere is a summary of the earlier part of the conversation for your context:\n{summary}"
        except Exception as sum_err:
            print(f"[WARN] Context summarization failed, using raw messages: {sum_err}")
        messages = recent_messages
    else:
        messages = trim_messages(messages, max_messages=6)

    # Ensure the chosen model is one of the supported ones
    chosen_model = data.get('model', 'claude-haiku-4-5')
    if chosen_model not in ['claude-haiku-4-5', 'claude-sonnet-4-5', 'claude-opus-4-5']:
        chosen_model = 'claude-haiku-4-5'

    thinking_enabled = data.get('thinking_enabled', False)
    payload_dict = {
        'model': chosen_model,
        'max_tokens': min(data.get('max_tokens', 4000), 4000),
        'system': system_instructions,
        'messages': messages
    }
    if thinking_enabled:
        payload_dict['thinking'] = {
            'type': 'enabled',
            'budget_tokens': 1024
        }
    claude_payload = json.dumps(payload_dict).encode('utf-8')

    active_key = key_rotator.get_key()
    if not active_key:
        return handler.send_json(500, {'error': 'No API keys configured'})

    try:
        req = urllib.request.Request(
            'https://api.anthropic.com/v1/messages',
            data=claude_payload,
            headers={
                'Content-Type': 'application/json',
                'x-api-key': active_key,
                'anthropic-version': '2023-06-01'
            }
        )

        with urllib.request.urlopen(req, timeout=120) as resp:
            response_data = resp.read()
            response_json = json.loads(response_data)

            assistant_text = ''
            if response_json.get('content'):
                parts = []
                for block in response_json['content']:
                    if block.get('type') == 'text':
                        parts.append(block.get('text', ''))
                assistant_text = '\n'.join(parts)

            # Save messages to DB
            if db is not None and user_id and conv_id and user_message:
                try:
                    c_id = conv_id
                    # Save user message
                    db.messages.insert_one({
                        "conversation_id": c_id,
                        "user_id": user_id,
                        "role": 'user',
                        "content": user_message,
                        "created_at": datetime.now()
                    })
                    # Save assistant response
                    if assistant_text:
                        db.messages.insert_one({
                            "conversation_id": c_id,
                            "user_id": user_id,
                            "role": 'assistant',
                            "content": assistant_text,
                            "created_at": datetime.now()
                        })
                    # Update conversation timestamp
                    db.conversations.update_one(
                        {"_id": c_id},
                        {"$set": {"updated_at": datetime.now()}}
                    )

                    # Save token usage
                    usage = response_json.get('usage', {})
                    save_token_usage(
                        db, user_id, 
                        usage.get('input_tokens', 0), 
                        usage.get('output_tokens', 0), 
                        chosen_model,
                        usage.get('cache_creation_input_tokens', 0),
                        usage.get('cache_read_input_tokens', 0)
                    )
                except Exception as e:
                    print(f"[ERROR] Message save error: {e}")

            # Add conversation_id to response
            response_json['conversation_id'] = conv_id

            # Fetch and add user quota/credit details
            if db is not None:
                response_json['user_quota'] = get_user_quota_info(db, user_id)

            handler.send_response(200)
            handler.send_header('Content-Type', 'application/json')
            handler.end_headers()
            handler.wfile.write(json.dumps(response_json).encode('utf-8'))

    except urllib.error.HTTPError as e:
        increment_failed_api_requests()
        err = e.read().decode('utf-8')
        print(f"[ERROR] Claude API error: {e.code} - {err}")
        client_ip = handler.get_client_ip()
        log_suspicious_activity(user_info.get('email', client_ip) if user_info else client_ip, "Claude API HTTP Error", f"HTTP {e.code} error received: {err[:60]}", "MEDIUM")
        handler.send_response(e.code)
        handler.send_header('Content-Type', 'application/json')
        handler.end_headers()
        # Sanitize: never send raw API errors to client
        safe_errors = {400: 'Bad request', 401: 'Invalid API key', 403: 'Access denied',
                       429: 'Rate limited by Claude', 500: 'Claude service error',
                       529: 'Claude API overloaded'}
        msg = safe_errors.get(e.code, 'Claude API error')
        handler.wfile.write(json.dumps({'error': msg}).encode('utf-8'))

    except Exception as e:
        increment_failed_api_requests()
        print(f"[ERROR] Claude error: {e}")
        handler.send_json(500, {'error': 'Internal server error'})


# ============================================
# LOCAL LLM (OLLAMA) HANDLERS
# ============================================

def _ollama_chat(messages, model=None, stream=True):
    """Send chat request to Ollama API. Returns streaming response or full response."""
    import urllib.request
    import urllib.error
    model = model or settings.OLLAMA_MODEL
    url = f"{settings.OLLAMA_BASE_URL}/api/chat"
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "stream": stream
    }).encode('utf-8')
    req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'})
    return urllib.request.urlopen(req, timeout=120)


def handle_local_status(handler):
    """POST /api/local/status — check if Ollama is running and model is loaded."""
    try:
        req = urllib.request.Request(f"{settings.OLLAMA_BASE_URL}/api/tags")
        resp = urllib.request.urlopen(req, timeout=5)
        data = json.loads(resp.read())
        models = [m['name'] for m in data.get('models', [])]
        handler.send_json(200, {
            'available': settings.ENABLE_LOCAL_LLM,
            'ollama_running': True,
            'model': settings.OLLAMA_MODEL,
            'models_loaded': models,
            'model_ready': settings.OLLAMA_MODEL in models
        })
    except Exception:
        handler.send_json(200, {
            'available': settings.ENABLE_LOCAL_LLM,
            'ollama_running': False,
            'model': settings.OLLAMA_MODEL,
            'models_loaded': [],
            'model_ready': False
        })


def handle_local(handler):
    """POST /api/local — non-streaming local LLM chat."""
    data = handler.read_body()
    session_token = data.get('session_token', '')
    conv_id = data.get('conversation_id')
    user_message = data.get('user_message', '')
    user_info = handler.get_user_from_token(session_token)
    if not user_info:
        return handler.send_json(401, {'error': 'Unauthorized'})

    if len(user_message) > 50000:
        return handler.send_json(400, {'error': 'Message too long (max 50KB)'})

    if not settings.ENABLE_LOCAL_LLM:
        return handler.send_json(503, {'error': 'Local LLM is disabled'})

    db = get_db()

    # Auto-create conversation
    if db is not None and conv_id is None:
        try:
            title = (user_message[:40] + '...') if len(user_message) > 40 else user_message or 'New Chat'
            res = db.conversations.insert_one({
                "user_id": user_info['_id'], "title": title,
                "created_at": datetime.now(), "updated_at": datetime.now()
            })
            conv_id = res.inserted_id
        except Exception as e:
            print(f"[ERROR] Conv create error: {e}")

    # Build message history
    messages = data.get('messages', [])
    if not messages:
        messages = [{"role": "user", "content": user_message}]

    system_prompt = """You are CUTM AI, an AI assistant for Centurion University (CUTM). Use markdown for formatting.

CRITICAL RULE - FILE GENERATION:
When a user asks you to CREATE, GENERATE, or MAKE any file (Word, PDF, Excel, PowerPoint, CSV, code file, etc.), you MUST:

1. DO NOT write Python code or explain how to create the file
2. DO NOT use pip install or import statements
3. INSTEAD: Output the actual FILE CONTENT inside a code block with the correct language tag

The system will automatically convert your output into a real downloadable file.

FORMAT: ```<language>
[filename="desired-filename.ext"]
<file content here>
```

EXAMPLES:

User: "Create a PDF with meeting notes"
You respond:
```pdf
[filename="meeting_notes.pdf"]
# Meeting Notes - June 2026

## Attendees
- Alice (Project Manager)
- Bob (Developer)

## Action Items
- Review project budget by Friday

## Decisions
- Approved Q3 budget of $50,000
```

User: "Generate a Word document with my resume"
You respond:
```docx
[filename="resume.docx"]
# John Doe

## Contact
- Email: john@example.com
- Phone: +91-9876543210

## Education
- B.Tech Computer Science, CUTM (2022-2026)

## Skills
- Python, JavaScript, SQL
```

User: "Make an Excel sheet with student data"
You respond:
```csv
[filename="students.csv"]
Name,Roll,Department,GPA
Alice,21CS001,CSE,8.5
Bob,21CS002,CSE,7.8
```

SUPPORTED FILE TYPES:
- docx → Word document (provide formatted text with # headings, - bullet points)
- pdf → PDF document (provide formatted text with # headings, - bullet points)
- xlsx → Excel spreadsheet (provide comma-separated or pipe-separated table data)
- csv → CSV data (provide comma-separated or pipe-separated table data)
- pptx → PowerPoint (provide # slide titles and - bullet points)
- html, css, javascript/js, python/py, java, c, cpp, sql, bash, md, json, xml

RULES:
- ALWAYS use ```language code blocks (never plain text for files)
- ALWAYS put [filename="name.ext"] as the first line inside the code block
- Put the actual CONTENT of the file, not code to generate it
- For documents (pdf, docx, pptx), use markdown-style formatting: # for titles, - for lists
- For spreadsheets (xlsx, csv), use comma-separated or pipe-separated values with a header row"""
    ollama_messages = [{"role": "system", "content": system_prompt}] + messages[-8:]

    try:
        resp = _ollama_chat(ollama_messages, stream=False)
        result = json.loads(resp.read())
        assistant_text = result.get('message', {}).get('content', '')

        # Save to DB
        if db is not None and user_info['_id'] and conv_id and user_message:
            try:
                db.messages.insert_one({
                    "conversation_id": conv_id, "user_id": user_info['_id'],
                    "role": "user", "content": user_message, "created_at": datetime.now(), "feedback": "none"
                })
                if assistant_text:
                    db.messages.insert_one({
                        "conversation_id": conv_id, "user_id": user_info['_id'],
                        "role": "assistant", "content": assistant_text, "created_at": datetime.now(), "feedback": "none"
                    })
                db.conversations.update_one({"_id": conv_id}, {"$set": {"updated_at": datetime.now()}})
            except Exception as e:
                print(f"[ERROR] Local LLM DB save error: {e}")

        handler.send_json(200, {
            'content': [{'type': 'text', 'text': assistant_text}],
            'conversation_id': conv_id,
            'model': settings.OLLAMA_MODEL,
            'usage': {'input_tokens': result.get('prompt_eval_count', 0), 'output_tokens': result.get('eval_count', 0)}
        })
    except Exception as e:
        print(f"[ERROR] Local LLM error: {e}")
        handler.send_json(500, {'error': 'Local LLM request failed'})


def handle_local_stream(handler):
    """POST /api/local/stream — streaming local LLM chat via SSE."""
    client_ip = handler.get_client_ip()
    if is_rate_limited(client_ip, 'local', limit=20, window=60):
        handler.send_response(429)
        handler.send_header('Content-Type', 'text/event-stream')
        handler.end_headers()
        handler.wfile.write(b'data: {"error": "Rate limited"}\n\n')
        return

    data = handler.read_body()
    session_token = data.get('session_token', '')
    conv_id = data.get('conversation_id')
    user_message = data.get('user_message', '')
    user_info = handler.get_user_from_token(session_token)

    if not user_info:
        handler.send_response(401)
        handler.send_header('Content-Type', 'text/event-stream')
        handler.end_headers()
        handler.wfile.write(b'data: {"error": "Unauthorized"}\n\n')
        return

    if not settings.ENABLE_LOCAL_LLM:
        handler.send_response(503)
        handler.send_header('Content-Type', 'text/event-stream')
        handler.end_headers()
        handler.wfile.write(b'data: {"error": "Local LLM is disabled"}\n\n')
        return

    db = get_db()

    # Auto-create conversation
    if db is not None and conv_id is None:
        try:
            title = (user_message[:40] + '...') if len(user_message) > 40 else user_message or 'New Chat'
            res = db.conversations.insert_one({
                "user_id": user_info['_id'], "title": title,
                "created_at": datetime.now(), "updated_at": datetime.now()
            })
            conv_id = str(res.inserted_id)
        except Exception as e:
            print(f"[ERROR] Conv create error: {e}")

    messages = data.get('messages', [])
    if not messages:
        messages = [{"role": "user", "content": user_message}]

    system_prompt = """You are CUTM AI, an AI assistant for Centurion University (CUTM). Use markdown for formatting.

CRITICAL RULE - FILE GENERATION:
When a user asks you to CREATE, GENERATE, or MAKE any file (Word, PDF, Excel, PowerPoint, CSV, code file, etc.), you MUST:

1. DO NOT write Python code or explain how to create the file
2. DO NOT use pip install or import statements
3. INSTEAD: Output the actual FILE CONTENT inside a code block with the correct language tag

The system will automatically convert your output into a real downloadable file.

FORMAT: ```<language>
[filename="desired-filename.ext"]
<file content here>
```

EXAMPLES:

User: "Create a PDF with meeting notes"
You respond:
```pdf
[filename="meeting_notes.pdf"]
# Meeting Notes - June 2026

## Attendees
- Alice (Project Manager)
- Bob (Developer)

## Action Items
- Review project budget by Friday
- Schedule follow-up meeting

## Decisions
- Approved Q3 budget of $50,000
- New deadline: July 15, 2026
```

User: "Generate a Word document with my resume"
You respond:
```docx
[filename="resume.docx"]
# John Doe

## Contact
- Email: john@example.com
- Phone: +91-9876543210

## Education
- B.Tech Computer Science, CUTM (2022-2026)

## Skills
- Python, JavaScript, SQL
- Machine Learning, Data Analysis
```

User: "Make an Excel sheet with student data"
You respond:
```csv
[filename="students.csv"]
Name,Roll,Department,GPA
Alice,21CS001,CSE,8.5
Bob,21CS002,CSE,7.8
Charlie,21EE001,EEE,9.1
```

User: "Create a Python calculator"
You respond:
```python
[filename="calculator.py"]
def add(a, b):
    return a + b

def subtract(a, b):
    return a - b

if __name__ == "__main__":
    print(add(5, 3))
    print(subtract(10, 4))
```

SUPPORTED FILE TYPES:
- docx → Word document (provide formatted text with # headings, - bullet points)
- pdf → PDF document (provide formatted text with # headings, - bullet points)
- xlsx → Excel spreadsheet (provide comma-separated or pipe-separated table data)
- csv → CSV data (provide comma-separated or pipe-separated table data)
- pptx → PowerPoint (provide # slide titles and - bullet points)
- html, css, javascript/js, python/py, java, c, cpp, sql, bash, md, json, xml

RULES:
- ALWAYS use ```language code blocks (never plain text for files)
- ALWAYS put [filename="name.ext"] as the first line inside the code block
- Put the actual CONTENT of the file, not code to generate it
- For documents (pdf, docx, pptx), use markdown-style formatting: # for titles, - for lists, ## for subtitles
- For spreadsheets (xlsx, csv), use comma-separated or pipe-separated values with a header row"""
    ollama_messages = [{"role": "system", "content": system_prompt}] + messages[-8:]

    # Validate user_message size
    if len(user_message) > 50000:
        handler.send_response(400)
        handler.send_header('Content-Type', 'text/event-stream')
        handler.end_headers()
        handler.wfile.write(b'data: {"error": "Message too long (max 50KB)"}\n\n')
        return

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
        # Send start event
        if conv_id:
            start_msg = json.dumps({'type': 'start', 'conversation_id': conv_id})
            handler.wfile.write(f'data: {start_msg}\n\n'.encode('utf-8'))
            handler.wfile.flush()

        resp = _ollama_chat(ollama_messages, stream=True)

        for line in resp:
            line = line.decode('utf-8').strip()
            if not line:
                continue
            try:
                chunk = json.loads(line)
                token = chunk.get('message', {}).get('content', '')
                if token:
                    full_response += token
                    msg_out = json.dumps({'type': 'delta', 'text': token})
                    handler.wfile.write(f'data: {msg_out}\n\n'.encode('utf-8'))
                    handler.wfile.flush()
                if chunk.get('done'):
                    break
            except json.JSONDecodeError:
                continue

        # Save to DB
        user_msg_id = None
        asst_msg_id = None
        if db is not None and user_info['_id'] and conv_id and user_message:
            try:
                user_res = db.messages.insert_one({
                    "conversation_id": conv_id, "user_id": user_info['_id'],
                    "role": "user", "content": user_message, "created_at": datetime.now(), "feedback": "none"
                })
                user_msg_id = user_res.inserted_id
                if full_response:
                    asst_res = db.messages.insert_one({
                        "conversation_id": conv_id, "user_id": user_info['_id'],
                        "role": "assistant", "content": full_response, "created_at": datetime.now(), "feedback": "none"
                    })
                    asst_msg_id = asst_res.inserted_id
                db.conversations.update_one({"_id": conv_id}, {"$set": {"updated_at": datetime.now()}})
            except Exception as e:
                print(f"[ERROR] Local stream DB save error: {e}")

        done_msg = json.dumps({
            'type': 'done', 'conversation_id': conv_id,
            'user_message_id': user_msg_id, 'assistant_message_id': asst_msg_id
        })
        handler.wfile.write(f'data: {done_msg}\n\n'.encode('utf-8'))
        handler.wfile.flush()

    except Exception as e:
        print(f"[ERROR] Local stream error: {e}")
        err_msg = json.dumps({'type': 'error', 'message': 'Local LLM request failed'})
        try:
            handler.wfile.write(f'data: {err_msg}\n\n'.encode('utf-8'))
            handler.wfile.flush()
        except Exception:
            pass


def handle_file_generate(handler):
    """POST /api/files/generate — Generate a downloadable file from content."""
    from botai.services.file_generator import generate_file, get_download_url
    data = handler.read_body()
    session_token = data.get('session_token', '')
    user_info = handler.get_user_from_token(session_token)
    if not user_info:
        return handler.send_json(401, {'error': 'Unauthorized'})

    filename = data.get('filename', 'output.txt')
    content = data.get('content', '')
    file_type = data.get('file_type', '')

    if not content:
        return handler.send_json(400, {'error': 'No content provided'})

    result = generate_file(filename, content, file_type)
    if result['success']:
        download_url = get_download_url(result['filename'])
        handler.send_json(200, {
            'success': True,
            'filename': result['filename'],
            'original_name': filename,
            'download_url': download_url,
            'size': result['size']
        })
    else:
        handler.send_json(500, {'error': f"File generation failed: {result['error']}"})


def handle_file_download(handler):
    """GET /api/files/download/{filename} — Serve a generated file for download."""
    import mimetypes
    filename = handler.path.split('/api/files/download/')[-1]
    if not filename or '/' in filename or '\\' in filename or '..' in filename:
        return handler.send_json(400, {'error': 'Invalid filename'})

    from botai.services.file_generator import GENERATED_DIR
    filepath = os.path.join(GENERATED_DIR, filename)

    if not os.path.exists(filepath):
        return handler.send_json(404, {'error': 'File not found'})

    mime_type, _ = mimetypes.guess_type(filepath)
    if not mime_type:
        mime_type = 'application/octet-stream'

    try:
        with open(filepath, 'rb') as f:
            file_data = f.read()
        handler.send_response(200)
        handler.send_header('Content-Type', mime_type)
        handler.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        handler.send_header('Content-Length', str(len(file_data)))
        handler.send_header('Cache-Control', 'no-cache')
        handler.end_headers()
        handler.wfile.write(file_data)
        handler.wfile.flush()
    except Exception as e:
        print(f"[FileDownload] Error: {e}")
        try:
            handler.send_json(500, {'error': 'Download failed'})
        except Exception:
            pass


def handle_get(request_handler):
    """Route GET requests"""
    path = request_handler.path.split('?')[0]
    if path == '/api/files/list':
        handle_file_list(request_handler)
    elif path.startswith('/api/files/download/'):
        handle_file_download(request_handler)
    else:
        if hasattr(request_handler, 'send_json'):
            request_handler.send_json(404, {'error': 'Not found'})
        else:
            send_json_response(request_handler, 404, {'error': 'Not found'})

# ============================================
# FILE UPLOAD ENDPOINT
# ============================================

def handle_file_upload(handler):
    """
    POST /api/files/upload
    Upload file to server
    
    Expects: Base64 encoded file or binary in JSON
    
    Response: {
        "file_id": "...",
        "filename": "essay.pdf",
        "file_type": "document",
        "size_mb": 2.5
    }
    """
    client_ip = handler.get_client_ip() if hasattr(handler, 'get_client_ip') else ''
    if client_ip and is_rate_limited(client_ip, 'file_upload', limit=10, window=60):
        if hasattr(handler, 'send_json'):
            handler.send_json(429, {'error': 'File upload rate limit reached (10/min). Please wait.'})
        else:
            send_json_response(handler, 429, {'error': 'File upload rate limit reached (10/min). Please wait.'})
        return
    try:
        db = get_db()
        data = get_json_body(handler)
        
        token = data.get('session_token', '')
        user = handler.get_user_from_token(token) if hasattr(handler, 'get_user_from_token') else None
        if not user:
            if hasattr(handler, 'send_json'):
                handler.send_json(401, {'error': 'Unauthorized'})
            else:
                send_json_response(handler, 401, {'error': 'Unauthorized'})
            return
        user_id = user['id']
            
        filename = data.get('filename', '')
        file_data_b64 = data.get('file_data_b64', '')
        
        if not filename or not file_data_b64:
            if hasattr(handler, 'send_json'):
                handler.send_json(400, {'error': 'Filename and file_data_b64 required'})
            else:
                send_json_response(handler, 400, {'error': 'Filename and file_data_b64 required'})
            return
            
        # Decode base64
        import base64
        try:
            file_data = base64.b64decode(file_data_b64)
        except Exception as e:
            if hasattr(handler, 'send_json'):
                handler.send_json(400, {'error': f'Invalid base64 encoding: {e}'})
            else:
                send_json_response(handler, 400, {'error': f'Invalid base64 encoding: {e}'})
            return
            
        # Save file
        success, result = FileHandler.save_file(file_data, filename, user_id, db)
        
        if success:
            file_id = result
            file_doc = db.files.find_one({'_id': file_id})
            res_data = {
                'file_id': file_doc['_id'],
                'filename': file_doc['filename'],
                'file_type': file_doc['file_type'],
                'size_mb': round(file_doc['size_bytes'] / (1024*1024), 2),
                'created_at': file_doc['created_at'].isoformat()
            }
            if hasattr(handler, 'send_json'):
                handler.send_json(200, res_data)
            else:
                send_json_response(handler, 200, res_data)
        else:
            if hasattr(handler, 'send_json'):
                handler.send_json(400, {'error': result})
            else:
                send_json_response(handler, 400, {'error': result})
                
    except Exception as e:
        print(f"[ERROR] uploading file: {e}")
        if hasattr(handler, 'send_json'):
            handler.send_json(500, {'error': 'Internal server error'})
        else:
            send_json_response(handler, 500, {'error': 'Internal server error'})

# ============================================
# FILE LIST ENDPOINT
# ============================================

def handle_file_list(handler):
    """
    GET /api/files/list
    Get all files uploaded by user
    
    Response: {
        "files": [
            {
                "file_id": "...",
                "filename": "essay.pdf",
                "file_type": "document",
                "size_mb": 2.5,
                "created_at": "2024-06-10T..."
            }
        ]
    }
    """
    try:
        from urllib.parse import parse_qs, urlparse
        db = get_db()
        token = ''
        if '?' in handler.path:
            parsed_url = urlparse(handler.path)
            query_params = parse_qs(parsed_url.query)
            token = query_params.get('session_token', [''])[0]
        if not token:
            token = handler.headers.get('Authorization', '')
            if token.startswith('Bearer '):
                token = token[7:]
            else:
                token = handler.headers.get('X-Session-Token', '')
                
        user = handler.get_user_from_token(token) if hasattr(handler, 'get_user_from_token') else None
        if not user:
            if hasattr(handler, 'send_json'):
                handler.send_json(401, {'error': 'Unauthorized'})
            else:
                send_json_response(handler, 401, {'error': 'Unauthorized'})
            return
        user_id = user['id']
            
        files = FileHandler.list_user_files(user_id, db)
        if hasattr(handler, 'send_json'):
            handler.send_json(200, {'files': files})
        else:
            send_json_response(handler, 200, {'files': files})
            
    except Exception as e:
        if hasattr(handler, 'send_json'):
            handler.send_json(500, {'error': 'Internal server error'})
        else:
            send_json_response(handler, 500, {'error': 'Internal server error'})

# ============================================
# FILE DELETE ENDPOINT
# ============================================

def handle_file_delete(handler):
    """
    POST /api/files/delete
    Delete file
    
    Request: {"file_id": "..."}
    Response: {"message": "File deleted"}
    """
    try:
        data = get_json_body(handler)
        token = data.get('session_token', '')
        user = handler.get_user_from_token(token) if hasattr(handler, 'get_user_from_token') else None
        if not user:
            if hasattr(handler, 'send_json'):
                handler.send_json(401, {'error': 'Unauthorized'})
            else:
                send_json_response(handler, 401, {'error': 'Unauthorized'})
            return
        user_id = user['id']
            
        file_id = data.get('file_id')
        if not file_id:
            if hasattr(handler, 'send_json'):
                handler.send_json(400, {'error': 'file_id required'})
            else:
                send_json_response(handler, 400, {'error': 'file_id required'})
            return
            
        db = get_db()
        success, message = FileHandler.delete_file(file_id, user_id, db)
        
        if success:
            res_data = {'message': message}
            if hasattr(handler, 'send_json'):
                handler.send_json(200, res_data)
            else:
                send_json_response(handler, 200, res_data)
        else:
            if hasattr(handler, 'send_json'):
                handler.send_json(400, {'error': message})
            else:
                send_json_response(handler, 400, {'error': message})
                
    except Exception as e:
        if hasattr(handler, 'send_json'):
            handler.send_json(500, {'error': 'Internal server error'})
        else:
            send_json_response(handler, 500, {'error': 'Internal server error'})

# ============================================
# HELPER FUNCTIONS
# ============================================

# ══════════════════════════════════════════════════════════════════════════════
# GROQ API HANDLERS (Free, zero-cost OpenAI-compatible)
# ══════════════════════════════════════════════════════════════════════════════

_CUTM_SYSTEM_PROMPT = """You are CUTM AI, an AI assistant for Centurion University (CUTM). Use markdown for formatting.

CRITICAL RULE - FILE GENERATION:
When a user asks you to CREATE, GENERATE, or MAKE any file (Word, PDF, Excel, PowerPoint, CSV, code file, etc.), you MUST:

1. DO NOT write Python code or explain how to create the file
2. DO NOT use pip install or import statements
3. INSTEAD: Output the actual FILE CONTENT inside a code block with the correct language tag

The system will automatically convert your output into a real downloadable file.

FORMAT: ```<language>
[filename="desired-filename.ext"]
<file content here>
```

SUPPORTED FILE TYPES:
- docx, pdf, xlsx, csv, pptx, html, css, javascript/js, python/py, java, c, cpp, sql, bash, md, json, xml

RULES:
- ALWAYS use ```language code blocks (never plain text for files)
- ALWAYS put [filename="name.ext"] as the first line inside the code block
- Put the actual CONTENT of the file, not code to generate it"""

def _groq_chat(messages, model='llama-3.3-70b-versatile', stream=False, max_tokens=2000):
    """Call Groq OpenAI-compatible API."""
    api_key = settings.GROQ_API_KEY
    base_url = settings.GROQ_API_URL
    if not api_key:
        raise ValueError('GROQ_API_KEY not configured')

    payload = {
        'model': model,
        'messages': messages,
        'max_tokens': max_tokens,
        'temperature': 0.7,
        'stream': stream,
    }
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        f'{base_url}/chat/completions',
        data=data,
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
        },
        method='POST'
    )
    return urllib.request.urlopen(req, timeout=120)


def handle_groq(handler):
    """POST /api/groq — non-streaming Groq chat."""
    client_ip = handler.get_client_ip()
    if is_rate_limited(client_ip, 'groq', limit=30, window=60):
        return handler.send_json(429, {'error': 'Rate limited. Please wait.'})

    data = handler.read_body()
    session_token = data.get('session_token', '')
    conv_id = data.get('conversation_id')
    user_message = data.get('user_message', '')
    user_info = handler.get_user_from_token(session_token)
    if not user_info:
        return handler.send_json(401, {'error': 'Unauthorized'})

    if len(user_message) > 50000:
        return handler.send_json(400, {'error': 'Message too long (max 50KB)'})

    total_tokens_used = user_info.get('total_tokens_used', 0)
    token_limit = user_info.get('token_limit', 1000000)
    if total_tokens_used >= token_limit:
        return handler.send_json(403, {'error': 'Token limit exceeded'})

    db = get_db()

    if db is not None and conv_id is None:
        try:
            title = (user_message[:40] + '...') if len(user_message) > 40 else user_message or 'New Chat'
            res = db.conversations.insert_one({
                "user_id": user_info['_id'], "title": title,
                "created_at": datetime.now(), "updated_at": datetime.now()
            })
            conv_id = res.inserted_id
        except Exception as e:
            print(f"[ERROR] Conv create error: {e}")

    messages = data.get('messages', [])
    if not messages:
        messages = [{"role": "user", "content": user_message}]

    api_messages = [{"role": "system", "content": _CUTM_SYSTEM_PROMPT}] + messages[-10:]
    model_key = data.get('model', 'llama-3.3-70b-versatile')
    groq_model = settings.MODEL_REGISTRY.get(model_key, {}).get('id', model_key)

    try:
        resp = _groq_chat(api_messages, model=groq_model, stream=False, max_tokens=4096)
        result = json.loads(resp.read().decode('utf-8'))
        assistant_text = result['choices'][0]['message']['content']
        usage = result.get('usage', {})
    except Exception as e:
        print(f"[ERROR] Groq API error: {e}")
        return handler.send_json(502, {'error': 'Groq API error'})

    user_msg_id = asst_msg_id = None
    if db is not None and user_info['_id'] and conv_id and user_message:
        try:
            ures = db.messages.insert_one({
                "conversation_id": conv_id, "user_id": user_info['_id'],
                "role": "user", "content": user_message, "created_at": datetime.now(), "feedback": "none"
            })
            user_msg_id = ures.inserted_id
            ares = db.messages.insert_one({
                "conversation_id": conv_id, "user_id": user_info['_id'],
                "role": "assistant", "content": assistant_text, "created_at": datetime.now(), "feedback": "none"
            })
            asst_msg_id = ares.inserted_id
            db.conversations.update_one({"_id": conv_id}, {"$set": {"updated_at": datetime.now()}})
        except Exception as e:
            print(f"[ERROR] Groq DB save error: {e}")

    if db is not None and user_info['_id']:
        try:
            save_token_usage(db, user_info['_id'],
                             usage.get('prompt_tokens', 0), usage.get('completion_tokens', 0),
                             model=groq_model)
        except Exception as token_err:
            print(f"[ERROR] Groq token usage save error: {token_err}")

    handler.send_json(200, {
        'response': assistant_text,
        'conversation_id': conv_id,
        'user_message_id': user_msg_id,
        'assistant_message_id': asst_msg_id,
        'model': groq_model
    })


def handle_groq_stream(handler):
    """POST /api/groq/stream — streaming Groq chat via SSE."""
    client_ip = handler.get_client_ip()
    if is_rate_limited(client_ip, 'groq', limit=30, window=60):
        handler.send_response(429)
        handler.send_header('Content-Type', 'text/event-stream')
        handler.end_headers()
        handler.wfile.write(b'data: {"error": "Rate limited"}\n\n')
        return

    data = handler.read_body()
    session_token = data.get('session_token', '')
    conv_id = data.get('conversation_id')
    user_message = data.get('user_message', '')
    user_info = handler.get_user_from_token(session_token)

    if not user_info:
        handler.send_response(401)
        handler.send_header('Content-Type', 'text/event-stream')
        handler.end_headers()
        handler.wfile.write(b'data: {"error": "Unauthorized"}\n\n')
        return

    if len(user_message) > 50000:
        handler.send_response(400)
        handler.send_header('Content-Type', 'text/event-stream')
        handler.end_headers()
        handler.wfile.write(b'data: {"error": "Message too long (max 50KB)"}\n\n')
        return

    total_tokens_used = user_info.get('total_tokens_used', 0)
    token_limit = user_info.get('token_limit', 1000000)
    if total_tokens_used >= token_limit:
        handler.send_response(403)
        handler.send_header('Content-Type', 'text/event-stream')
        handler.end_headers()
        handler.wfile.write(b'data: {"error": "Token limit exceeded"}\n\n')
        return

    db = get_db()

    if db is not None and conv_id is None:
        try:
            title = (user_message[:40] + '...') if len(user_message) > 40 else user_message or 'New Chat'
            res = db.conversations.insert_one({
                "user_id": user_info['_id'], "title": title,
                "created_at": datetime.now(), "updated_at": datetime.now()
            })
            conv_id = str(res.inserted_id)
        except Exception as e:
            print(f"[ERROR] Conv create error: {e}")

    messages = data.get('messages', [])
    if not messages:
        messages = [{"role": "user", "content": user_message}]

    api_messages = [{"role": "system", "content": _CUTM_SYSTEM_PROMPT}] + messages[-10:]
    model_key = data.get('model', 'llama-3.3-70b-versatile')
    groq_model = settings.MODEL_REGISTRY.get(model_key, {}).get('id', model_key)

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
        if conv_id:
            start_msg = json.dumps({'type': 'start', 'conversation_id': conv_id})
            handler.wfile.write(f'data: {start_msg}\n\n'.encode('utf-8'))
            handler.wfile.flush()

        resp = _groq_chat(api_messages, model=groq_model, stream=True, max_tokens=4096)
    
        for line in resp:
            line = line.decode('utf-8').strip()
            if not line or not line.startswith('data: '):
                continue
            payload_str = line[6:]
            if payload_str == '[DONE]':
                break
            try:
                chunk = json.loads(payload_str)
                delta = chunk.get('choices', [{}])[0].get('delta', {})
                token = delta.get('content', '')
                if token:
                    full_response += token
                    msg_out = json.dumps({'type': 'delta', 'text': token})
                    handler.wfile.write(f'data: {msg_out}\n\n'.encode('utf-8'))
                    handler.wfile.flush()
            except json.JSONDecodeError:
                continue

        user_msg_id = asst_msg_id = None
        if db is not None and user_info['_id'] and conv_id and user_message:
            try:
                ures = db.messages.insert_one({
                    "conversation_id": conv_id, "user_id": user_info['_id'],
                    "role": "user", "content": user_message, "created_at": datetime.now(), "feedback": "none"
                })
                user_msg_id = ures.inserted_id
                if full_response:
                    ares = db.messages.insert_one({
                        "conversation_id": conv_id, "user_id": user_info['_id'],
                        "role": "assistant", "content": full_response, "created_at": datetime.now(), "feedback": "none"
                    })
                    asst_msg_id = ares.inserted_id
                db.conversations.update_one({"_id": conv_id}, {"$set": {"updated_at": datetime.now()}})
            except Exception as e:
                print(f"[ERROR] Groq stream DB save error: {e}")

        done_msg = json.dumps({
            'type': 'done', 'conversation_id': conv_id,
            'user_message_id': user_msg_id, 'assistant_message_id': asst_msg_id
        })
        handler.wfile.write(f'data: {done_msg}\n\n'.encode('utf-8'))
        handler.wfile.flush()

    except Exception as e:
        print(f"[ERROR] Groq stream error: {e}")
        err_msg = json.dumps({'type': 'error', 'error': 'Groq streaming error'})
        try:
            handler.wfile.write(f'data: {err_msg}\n\n'.encode('utf-8'))
            handler.wfile.flush()
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# ZEN OpenCode API HANDLERS (Free, zero-cost OpenAI-compatible)
# ══════════════════════════════════════════════════════════════════════════════

def _zen_chat(messages, model='deepseek-v4-flash-free', stream=False, max_tokens=2000):
    """Call Zen OpenCode OpenAI-compatible API."""
    api_key = settings.ZEN_API_KEY
    base_url = settings.ZEN_API_URL
    if not api_key:
        raise ValueError('ZEN_API_KEY not configured')

    payload = {
        'model': model,
        'messages': messages,
        'max_tokens': max_tokens,
        'temperature': 0.7,
        'stream': stream,
    }
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        f'{base_url}/chat/completions',
        data=data,
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
        },
        method='POST'
    )
    return urllib.request.urlopen(req, timeout=120)


def handle_zen(handler):
    """POST /api/zen — non-streaming Zen chat."""
    client_ip = handler.get_client_ip()
    if is_rate_limited(client_ip, 'zen', limit=30, window=60):
        return handler.send_json(429, {'error': 'Rate limited. Please wait.'})

    data = handler.read_body()
    session_token = data.get('session_token', '')
    conv_id = data.get('conversation_id')
    user_message = data.get('user_message', '')
    user_info = handler.get_user_from_token(session_token)
    if not user_info:
        return handler.send_json(401, {'error': 'Unauthorized'})

    if len(user_message) > 50000:
        return handler.send_json(400, {'error': 'Message too long (max 50KB)'})

    total_tokens_used = user_info.get('total_tokens_used', 0)
    token_limit = user_info.get('token_limit', 1000000)
    if total_tokens_used >= token_limit:
        return handler.send_json(403, {'error': 'Token limit exceeded'})

    db = get_db()

    if db is not None and conv_id is None:
        try:
            title = (user_message[:40] + '...') if len(user_message) > 40 else user_message or 'New Chat'
            res = db.conversations.insert_one({
                "user_id": user_info['_id'], "title": title,
                "created_at": datetime.now(), "updated_at": datetime.now()
            })
            conv_id = res.inserted_id
        except Exception as e:
            print(f"[ERROR] Conv create error: {e}")

    messages = data.get('messages', [])
    if not messages:
        messages = [{"role": "user", "content": user_message}]

    api_messages = [{"role": "system", "content": _CUTM_SYSTEM_PROMPT}] + messages[-10:]
    model_key = data.get('model', 'deepseek-v4-flash-free')
    zen_model = settings.MODEL_REGISTRY.get(model_key, {}).get('id', model_key)

    try:
        resp = _zen_chat(api_messages, model=zen_model, stream=False, max_tokens=4096)
        result = json.loads(resp.read().decode('utf-8'))
        choice = result['choices'][0]
        msg = choice.get('message', {})
        assistant_text = msg.get('content') or msg.get('reasoning_content') or choice.get('text') or ''
        usage = result.get('usage', {})
    except Exception as e:
        print(f"[ERROR] Zen API error: {e}")
        return handler.send_json(502, {'error': 'Zen API error'})

    user_msg_id = asst_msg_id = None
    if db is not None and user_info['_id'] and conv_id and user_message:
        try:
            ures = db.messages.insert_one({
                "conversation_id": conv_id, "user_id": user_info['_id'],
                "role": "user", "content": user_message, "created_at": datetime.now(), "feedback": "none"
            })
            user_msg_id = ures.inserted_id
            ares = db.messages.insert_one({
                "conversation_id": conv_id, "user_id": user_info['_id'],
                "role": "assistant", "content": assistant_text, "created_at": datetime.now(), "feedback": "none"
            })
            asst_msg_id = ares.inserted_id
            db.conversations.update_one({"_id": conv_id}, {"$set": {"updated_at": datetime.now()}})
        except Exception as e:
            print(f"[ERROR] Zen DB save error: {e}")

    if db is not None and user_info['_id']:
        try:
            save_token_usage(db, user_info['_id'],
                             usage.get('prompt_tokens', 0), usage.get('completion_tokens', 0),
                             model=zen_model)
        except Exception as token_err:
            print(f"[ERROR] Zen token usage save error: {token_err}")

    handler.send_json(200, {
        'response': assistant_text,
        'conversation_id': conv_id,
        'user_message_id': user_msg_id,
        'assistant_message_id': asst_msg_id,
        'model': zen_model
    })


def handle_zen_stream(handler):
    """POST /api/zen/stream — streaming Zen chat via SSE."""
    client_ip = handler.get_client_ip()
    if is_rate_limited(client_ip, 'zen', limit=30, window=60):
        handler.send_response(429)
        handler.send_header('Content-Type', 'text/event-stream')
        handler.end_headers()
        handler.wfile.write(b'data: {"error": "Rate limited"}\n\n')
        return

    data = handler.read_body()
    session_token = data.get('session_token', '')
    conv_id = data.get('conversation_id')
    user_message = data.get('user_message', '')
    user_info = handler.get_user_from_token(session_token)

    if not user_info:
        handler.send_response(401)
        handler.send_header('Content-Type', 'text/event-stream')
        handler.end_headers()
        handler.wfile.write(b'data: {"error": "Unauthorized"}\n\n')
        return

    if len(user_message) > 50000:
        handler.send_response(400)
        handler.send_header('Content-Type', 'text/event-stream')
        handler.end_headers()
        handler.wfile.write(b'data: {"error": "Message too long (max 50KB)"}\n\n')
        return

    total_tokens_used = user_info.get('total_tokens_used', 0)
    token_limit = user_info.get('token_limit', 1000000)
    if total_tokens_used >= token_limit:
        handler.send_response(403)
        handler.send_header('Content-Type', 'text/event-stream')
        handler.end_headers()
        handler.wfile.write(b'data: {"error": "Token limit exceeded"}\n\n')
        return

    db = get_db()

    if db is not None and conv_id is None:
        try:
            title = (user_message[:40] + '...') if len(user_message) > 40 else user_message or 'New Chat'
            res = db.conversations.insert_one({
                "user_id": user_info['_id'], "title": title,
                "created_at": datetime.now(), "updated_at": datetime.now()
            })
            conv_id = str(res.inserted_id)
        except Exception as e:
            print(f"[ERROR] Conv create error: {e}")

    messages = data.get('messages', [])
    if not messages:
        messages = [{"role": "user", "content": user_message}]

    api_messages = [{"role": "system", "content": _CUTM_SYSTEM_PROMPT}] + messages[-10:]
    model_key = data.get('model', 'deepseek-v4-flash-free')
    zen_model = settings.MODEL_REGISTRY.get(model_key, {}).get('id', model_key)

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
        if conv_id:
            start_msg = json.dumps({'type': 'start', 'conversation_id': conv_id})
            handler.wfile.write(f'data: {start_msg}\n\n'.encode('utf-8'))
            handler.wfile.flush()

        resp = _zen_chat(api_messages, model=zen_model, stream=True, max_tokens=4096)
    
        for line in resp:
            line = line.decode('utf-8').strip()
            if not line or not line.startswith('data: '):
                continue
            payload_str = line[6:]
            if payload_str == '[DONE]':
                break
            try:
                chunk = json.loads(payload_str)
                choice = chunk.get('choices', [{}])[0]
                delta = choice.get('delta', {})
                token = delta.get('content') or delta.get('reasoning_content') or ''
                if token:
                    full_response += token
                    msg_out = json.dumps({'type': 'delta', 'text': token})
                    handler.wfile.write(f'data: {msg_out}\n\n'.encode('utf-8'))
                    handler.wfile.flush()
            except json.JSONDecodeError:
                continue

        user_msg_id = asst_msg_id = None
        if db is not None and user_info['_id'] and conv_id and user_message:
            try:
                ures = db.messages.insert_one({
                    "conversation_id": conv_id, "user_id": user_info['_id'],
                    "role": "user", "content": user_message, "created_at": datetime.now(), "feedback": "none"
                })
                user_msg_id = ures.inserted_id
                if full_response:
                    ares = db.messages.insert_one({
                        "conversation_id": conv_id, "user_id": user_info['_id'],
                        "role": "assistant", "content": full_response, "created_at": datetime.now(), "feedback": "none"
                    })
                    asst_msg_id = ares.inserted_id
                db.conversations.update_one({"_id": conv_id}, {"$set": {"updated_at": datetime.now()}})
            except Exception as e:
                print(f"[ERROR] Zen stream DB save error: {e}")

        done_msg = json.dumps({
            'type': 'done', 'conversation_id': conv_id,
            'user_message_id': user_msg_id, 'assistant_message_id': asst_msg_id
        })
        handler.wfile.write(f'data: {done_msg}\n\n'.encode('utf-8'))
        handler.wfile.flush()

    except Exception as e:
        print(f"[ERROR] Zen stream error: {e}")
        err_msg = json.dumps({'type': 'error', 'error': 'Zen streaming error'})
        try:
            handler.wfile.write(f'data: {err_msg}\n\n'.encode('utf-8'))
            handler.wfile.flush()
        except Exception:
            pass


def send_json_response(request_handler, status_code: int, data: dict):
    """Send JSON response"""
    if hasattr(request_handler, 'send_json'):
        request_handler.send_json(status_code, data)
        return
    request_handler.send_response(status_code)
    request_handler.send_header('Content-type', 'application/json')
    origin = request_handler.headers.get('Origin', '')
    if origin in settings.CORS_ORIGINS:
        request_handler.send_header('Access-Control-Allow-Origin', origin)
    request_handler.end_headers()
    
    response = json.dumps(data).encode('utf-8')
    request_handler.wfile.write(response)

def get_json_body(request_handler) -> dict:
    """Read JSON body from request"""
    if hasattr(request_handler, 'read_body'):
        return request_handler.read_body()
    content_length = int(request_handler.headers.get('Content-Length', 0))
    return json.loads(request_handler.rfile.read(content_length))

