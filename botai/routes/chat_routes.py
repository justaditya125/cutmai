"""
Chat and conversation routes
"""
import re
import json
import urllib.request
import urllib.error
from datetime import datetime
from bson import ObjectId
from botai.config import settings
from botai.config.mongodb_config import get_db
from botai.utils.logger import log_suspicious_activity, increment_failed_api_requests
from botai.utils.rate_limiter import is_rate_limited
from botai.services.key_rotator import key_rotator
from botai.services.context_compactor import context_compactor
from botai.services.file_handler import FileHandler

def save_token_usage(db, user_id, input_tokens, output_tokens, model='claude-haiku-4-5'):
    """Save token usage to database and print detailed log"""
    total = input_tokens + output_tokens
    u_id = ObjectId(user_id) if isinstance(user_id, (str, bytes)) else user_id
    try:
        # Insert token usage record
        db.token_usage.insert_one({
            "user_id": u_id,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total,
            "model": model,
            "created_at": datetime.now()
        })

        # Update user total tokens
        db.users.update_one(
            {"_id": u_id},
            {
                "$inc": {
                    "total_tokens_used": total,
                    "total_messages": 1
                },
                "$set": {
                    "updated_at": datetime.now()
                }
            }
        )

        # Fetch updated user stats for logging
        user = db.users.find_one({"_id": u_id})

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
    if user_doc is None:
        user_doc = db.users.find_one({"_id": user_id})
    if not user_doc:
        return None
    
    # Calculate user credits
    credits = 0.0
    try:
        user_tokens = list(db.token_usage.find({"user_id": user_id}))
        for r in user_tokens:
            m = r.get("model", "").lower()
            in_t = r.get("input_tokens", 0)
            out_t = r.get("output_tokens", 0)
            if "sonnet" in m:
                credits += (in_t * 3.0 + out_t * 15.0) / 1_000_000
            elif "haiku" in m:
                credits += (in_t * 0.25 + out_t * 1.25) / 1_000_000
            elif "opus" in m:
                credits += (in_t * 15.0 + out_t * 75.0) / 1_000_000
            else:
                credits += (in_t * 3.0 + out_t * 15.0) / 1_000_000
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
    else:
        if hasattr(handler, 'send_json'):
            handler.send_json(404, {'error': 'Not found'})
        else:
            send_json_response(handler, 404, {'error': 'Not found'})

def handle_new_conversation(handler):
    data  = handler.read_body()
    token = data.get('session_token', '')
    title = data.get('title', 'New Chat')
    user  = handler.get_user_from_token(token)
    if not user:
        return handler.send_json(401, {'error': 'Unauthorized'})
    db = get_db()
    if db is None: return handler.send_json(500, {'error': 'DB error'})
    try:
        conv_doc = {
            "user_id": ObjectId(user['id']),
            "title": title,
            "created_at": datetime.now(),
            "updated_at": datetime.now()
        }
        res = db.conversations.insert_one(conv_doc)
        conv_id = str(res.inserted_id)
        handler.send_json(200, {'success': True, 'conversation_id': conv_id, 'title': title})
    except Exception as e:
        handler.send_json(500, {'error': str(e)})

def handle_list_conversations(handler):
    data  = handler.read_body()
    token = data.get('session_token', '')
    user  = handler.get_user_from_token(token)
    if not user:
        return handler.send_json(401, {'error': 'Unauthorized'})
    db = get_db()
    if db is None: return handler.send_json(500, {'error': 'DB error'})
    try:
        convs = list(db.conversations.find({"user_id": ObjectId(user['id'])}).sort("updated_at", -1))
        conv_list = []
        for c in convs:
            msg_count = db.messages.count_documents({"conversation_id": c['_id']})
            c_created = c.get("created_at")
            c_updated = c.get("updated_at")
            conv_list.append({
                "id": str(c['_id']),
                "title": c.get("title", "New Conversation"),
                "created_at": c_created.strftime('%Y-%m-%d %H:%M:%S') if isinstance(c_created, datetime) else str(c_created),
                "updated_at": c_updated.strftime('%Y-%m-%d %H:%M:%S') if isinstance(c_updated, datetime) else str(c_updated),
                "message_count": msg_count
            })
        handler.send_json(200, {'conversations': conv_list})
    except Exception as e:
        handler.send_json(500, {'error': str(e)})

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
        c_id = ObjectId(conv_id) if isinstance(conv_id, str) else conv_id
        # Verify ownership
        conv = db.conversations.find_one({"_id": c_id, "user_id": ObjectId(user['id'])})
        if not conv:
            return handler.send_json(403, {'error': 'Forbidden'})
            
        msgs = list(db.messages.find({"conversation_id": c_id}).sort("created_at", 1))
        msg_list = []
        for m in msgs:
            m_created = m.get("created_at")
            msg_list.append({
                "id": str(m.get("_id")),
                "role": m.get("role"),
                "content": m.get("content"),
                "feedback": m.get("feedback", "none"),
                "created_at": m_created.strftime('%Y-%m-%d %H:%M:%S') if isinstance(m_created, datetime) else str(m_created)
            })
        handler.send_json(200, {'messages': msg_list})
    except Exception as e:
        handler.send_json(500, {'error': str(e)})

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
        c_id = ObjectId(conv_id) if isinstance(conv_id, str) else conv_id
        
        # Verify ownership and delete conversation
        res = db.conversations.delete_one({"_id": c_id, "user_id": ObjectId(user['id'])})
        if res.deleted_count > 0:
            db.messages.delete_many({"conversation_id": c_id})
            
        handler.send_json(200, {'success': True})
    except Exception as e:
        handler.send_json(500, {'error': str(e)})

def handle_rename_conversation(handler):
    data    = handler.read_body()
    token   = data.get('session_token', '')
    conv_id = data.get('conversation_id')
    title   = data.get('title', 'New Chat')
    user    = handler.get_user_from_token(token)
    if not user:
        return handler.send_json(401, {'error': 'Unauthorized'})
    db = get_db()
    if db is None: return handler.send_json(500, {'error': 'DB error'})
    try:
        c_id = ObjectId(conv_id) if isinstance(conv_id, str) else conv_id
        db.conversations.update_one(
            {"_id": c_id, "user_id": ObjectId(user['id'])},
            {"$set": {"title": title, "updated_at": datetime.now()}}
        )
        handler.send_json(200, {'success': True})
    except Exception as e:
        handler.send_json(500, {'error': str(e)})

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
        m_id = ObjectId(message_id)
        msg  = db.messages.find_one({'_id': m_id})
        if not msg:
            return handler.send_json(404, {'error': 'Message not found'})
        conv = db.conversations.find_one({'_id': msg['conversation_id'], 'user_id': ObjectId(user['id'])})
        if not conv:
            return handler.send_json(403, {'error': 'Forbidden'})
        db.messages.update_one({'_id': m_id}, {'$set': {'feedback': feedback}})
        handler.send_json(200, {'success': True})
    except Exception as e:
        handler.send_json(500, {'error': str(e)})

def handle_edit_message(handler):
    data        = handler.read_body()
    token       = data.get('session_token', '')
    message_id  = data.get('message_id')
    new_content = data.get('new_content', '')
    user = handler.get_user_from_token(token)
    if not user:
        return handler.send_json(401, {'error': 'Unauthorized'})
    if not new_content.strip():
        return handler.send_json(400, {'error': 'Content cannot be empty'})
    db = get_db()
    if db is None: return handler.send_json(500, {'error': 'DB error'})
    try:
        m_id = ObjectId(message_id)
        msg  = db.messages.find_one({'_id': m_id})
        if not msg:
            return handler.send_json(404, {'error': 'Message not found'})
        conv = db.conversations.find_one({'_id': msg['conversation_id'], 'user_id': ObjectId(user['id'])})
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
        handler.send_json(500, {'error': str(e)})

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

    total_tokens_used = user_info.get('total_tokens_used', 0)
    token_limit = user_info.get('token_limit', 1000000)
    if total_tokens_used >= token_limit:
        handler.send_response(403)
        handler.send_header('Content-Type', 'text/event-stream')
        handler.end_headers()
        handler.wfile.write(b'data: {"error": "Token limit exceeded"}\n\n')
        return

    user_id = ObjectId(user_info['id'])
    db = get_db()

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

    messages = trim_messages(messages, max_messages=6)

    chosen_model = data.get('model', 'claude-haiku-4-5')
    if not user_info.get('is_admin', False):
        chosen_model = 'claude-haiku-4-5'
    elif chosen_model not in ['claude-haiku-4-5', 'claude-sonnet-4-5', 'claude-opus-4-5']:
        chosen_model = 'claude-haiku-4-5'

    system_instructions = (
        "You are CUTM AI, an AI assistant for Centurion University (CUTM). Use markdown.\n"
        "When generating code, prefix with filename tag: [filename=\"file.ext\"] inside code blocks."
    )

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

    # Send SSE headers
    handler.send_response(200)
    handler.send_header('Content-Type', 'text/event-stream')
    handler.send_header('Cache-Control', 'no-cache')
    handler.send_header('X-Accel-Buffering', 'no')
    handler.send_header('Access-Control-Allow-Origin', '*')
    handler.end_headers()

    full_response = ""
    input_tokens = 0
    output_tokens = 0
    db_saved = False

    try:
        # Send start event immediately with conversation_id
        if conv_id:
            start_msg = json.dumps({'type': 'start', 'conversation_id': str(conv_id)})
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
                except Exception:
                    continue

        # Save to DB after stream completes
        user_msg_id = None
        asst_msg_id = None
        if db is not None and user_id and conv_id and user_message and not db_saved:
            try:
                c_id = ObjectId(conv_id) if isinstance(conv_id, str) else conv_id
                user_res = db.messages.insert_one({"conversation_id": c_id, "user_id": user_id, "role": 'user', "content": user_message, "created_at": datetime.now(), "feedback": "none"})
                user_msg_id = str(user_res.inserted_id)
                if full_response:
                    asst_res = db.messages.insert_one({"conversation_id": c_id, "user_id": user_id, "role": 'assistant', "content": full_response, "created_at": datetime.now(), "feedback": "none"})
                    asst_msg_id = str(asst_res.inserted_id)
                db.conversations.update_one({"_id": c_id}, {"$set": {"updated_at": datetime.now()}})
                if input_tokens or output_tokens:
                    save_token_usage(db, user_id, input_tokens, output_tokens, chosen_model)
                db_saved = True
            except Exception as e:
                print(f"[ERROR] Stream DB save error: {e}")

        # Send final done event with metadata including message IDs
        done_msg = json.dumps({'type': 'done', 'conversation_id': str(conv_id), 'input_tokens': input_tokens, 'output_tokens': output_tokens, 'user_message_id': user_msg_id, 'assistant_message_id': asst_msg_id})
        handler.wfile.write(f'data: {done_msg}\n\n'.encode('utf-8'))
        handler.wfile.flush()

    except Exception as e:
        increment_failed_api_requests()
        print(f"[ERROR] Stream error: {e}")
        # Save whatever partial progress we made to the DB
        if db is not None and user_id and conv_id and user_message and not db_saved:
            try:
                c_id = ObjectId(conv_id) if isinstance(conv_id, str) else conv_id
                db.messages.insert_one({"conversation_id": c_id, "user_id": user_id, "role": 'user', "content": user_message, "created_at": datetime.now(), "feedback": "none"})
                if full_response:
                    db.messages.insert_one({"conversation_id": c_id, "user_id": user_id, "role": 'assistant', "content": full_response, "created_at": datetime.now(), "feedback": "none"})
                db.conversations.update_one({"_id": c_id}, {"$set": {"updated_at": datetime.now()}})
                if input_tokens or output_tokens:
                    save_token_usage(db, user_id, input_tokens, output_tokens, chosen_model)
                db_saved = True
            except Exception as db_err:
                print(f"[ERROR] Interrupted stream DB save error: {db_err}")
        err_msg = json.dumps({'type': 'error', 'message': str(e)})
        try:
            handler.wfile.write(f'data: {err_msg}\n\n'.encode('utf-8'))
            handler.wfile.flush()
        except Exception:
            pass

def handle_claude_vision(handler):
    """Accept base64 image + text, send to Claude vision, return response."""
    data = handler.read_body()
    session_token = data.get('session_token', '')
    user_info = handler.get_user_from_token(session_token)
    if not user_info:
        return handler.send_json(401, {'error': 'Unauthorized'})

    image_b64   = data.get('image_base64', '')   # base64 string without prefix
    media_type  = data.get('media_type', 'image/jpeg')  # e.g. image/png
    user_text   = data.get('text', 'What is in this image?')
    chosen_model = data.get('model', 'claude-haiku-4-5')
    if not user_info.get('is_admin', False):
        chosen_model = 'claude-haiku-4-5'
    elif chosen_model not in ['claude-haiku-4-5', 'claude-sonnet-4-5', 'claude-opus-4-5']:
        chosen_model = 'claude-haiku-4-5'

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
        with urllib.request.urlopen(req) as resp:
            response_json = json.loads(resp.read())
            handler.send_response(200)
            handler.send_header('Content-Type', 'application/json')
            handler.end_headers()
            handler.wfile.write(json.dumps(response_json).encode('utf-8'))
    except Exception as e:
        increment_failed_api_requests()
        print(f"[ERROR] Vision error: {e}")
        handler.send_json(500, {'error': str(e)})

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

    total_tokens_used = user_info.get('total_tokens_used', 0)
    token_limit = user_info.get('token_limit', 1000000)
    if total_tokens_used >= token_limit:
        return handler.send_json(403, {'error': 'You have exceeded your allocated token limit. Please contact the administrator.'})

    user_id = ObjectId(user_info['id'])
    db = get_db()

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
            conv_id = str(res.inserted_id)
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
            
        summary = context_compactor.summarize_history(messages_to_summarize)
        if summary:
            system_instructions += f"\n\nHere is a summary of the earlier part of the conversation for your context:\n{summary}"
        messages = recent_messages
    else:
        messages = trim_messages(messages, max_messages=6)

    # Enforce Haiku-fallback constraint on regular users
    chosen_model = data.get('model', 'claude-haiku-4-5')
    if not user_info.get('is_admin', False):
        chosen_model = 'claude-haiku-4-5'
    elif chosen_model not in ['claude-haiku-4-5', 'claude-sonnet-4-5', 'claude-opus-4-5']:
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

        with urllib.request.urlopen(req) as resp:
            response_data = resp.read()
            response_json = json.loads(response_data)

            assistant_text = ''
            if response_json.get('content'):
                assistant_text = response_json['content'][0].get('text', '')

            # Save messages to DB
            if db is not None and user_id and conv_id and user_message:
                try:
                    c_id = ObjectId(conv_id) if isinstance(conv_id, str) else conv_id
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
                    save_token_usage(db, user_id, usage.get('input_tokens', 0), usage.get('output_tokens', 0), chosen_model)
                except Exception as e:
                    print(f"[ERROR] Message save error: {e}")

            # Add conversation_id to response
            response_json['conversation_id'] = str(conv_id)

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
        handler.wfile.write(err.encode('utf-8'))

    except Exception as e:
        increment_failed_api_requests()
        print(f"[ERROR] Claude error: {e}")
        handler.send_json(500, {'error': str(e)})

def handle_get(request_handler):
    """Route GET requests"""
    path = request_handler.path.split('?')[0]
    if path == '/api/files/list':
        handle_file_list(request_handler)
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
    try:
        db = get_db()
        data = get_json_body(handler)
        
        token = data.get('session_token', '')
        user = handler.get_user_from_token(token) if hasattr(handler, 'get_user_from_token') else None
        if user:
            user_id = user['id']
        else:
            user_id = "test_user_123"
            
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
            file_doc = db.files.find_one({'_id': ObjectId(file_id)})
            res_data = {
                'file_id': str(file_doc['_id']),
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
            handler.send_json(500, {'error': str(e)})
        else:
            send_json_response(handler, 500, {'error': str(e)})

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
        if user:
            user_id = user['id']
        else:
            user_id = "test_user_123"
            
        files = FileHandler.list_user_files(user_id, db)
        if hasattr(handler, 'send_json'):
            handler.send_json(200, {'files': files})
        else:
            send_json_response(handler, 200, {'files': files})
            
    except Exception as e:
        if hasattr(handler, 'send_json'):
            handler.send_json(500, {'error': str(e)})
        else:
            send_json_response(handler, 500, {'error': str(e)})

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
        if user:
            user_id = user['id']
        else:
            user_id = "test_user_123"
            
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
            handler.send_json(500, {'error': str(e)})
        else:
            send_json_response(handler, 500, {'error': str(e)})

# ============================================
# HELPER FUNCTIONS
# ============================================

def send_json_response(request_handler, status_code: int, data: dict):
    """Send JSON response"""
    if hasattr(request_handler, 'send_json'):
        request_handler.send_json(status_code, data)
        return
    request_handler.send_response(status_code)
    request_handler.send_header('Content-type', 'application/json')
    request_handler.send_header('Access-Control-Allow-Origin', '*')
    request_handler.end_headers()
    
    response = json.dumps(data).encode('utf-8')
    request_handler.wfile.write(response)

def get_json_body(request_handler) -> dict:
    """Read JSON body from request"""
    if hasattr(request_handler, 'read_body'):
        return request_handler.read_body()
    content_length = int(request_handler.headers.get('Content-Length', 0))
    return json.loads(request_handler.rfile.read(content_length))

