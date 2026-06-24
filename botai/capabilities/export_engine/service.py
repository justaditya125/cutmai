"""
Export Engine — JsonExporter, MarkdownExporter, PDFExporter (server-side), DocxExporter.
"""
import json
from datetime import datetime
from typing import Dict, List, Optional
from botai.config.MySQL_config import get_db


def _fetch_conversation(conversation_id: str, user_id: str) -> Optional[Dict]:
    """Shared helper to fetch conversation + messages from MySQL."""
    try:
        db = get_db()
        if db is None:
            return None
        conv = db.conversations.find_one({'_id': conversation_id, 'user_id': user_id})
        if not conv:
            return None
        msgs = list(db.messages.find({'conversation_id': conversation_id}).sort('created_at', 1))
        return {'conversation': conv, 'messages': msgs}
    except Exception as e:
        print(f"[ExportEngine] fetch error: {e}")
        return None


class JsonExporter:
    """Exports a full conversation as clean JSON."""

    def export_conversation(self, conversation_id: str, user_id: str) -> Dict:
        data = _fetch_conversation(conversation_id, user_id)
        if not data:
            return {'error': 'Conversation not found or access denied'}
        conv = data['conversation']
        msgs = data['messages']

        export_doc = {
            'export_type':    'conversation',
            'format':         'json',
            'exported_at':    datetime.now().isoformat(),
            'conversation': {
                'id':        conv['_id'],
                'title':     conv.get('title', 'Untitled'),
                'created_at': conv.get('created_at', '').isoformat() if hasattr(conv.get('created_at', ''), 'isoformat') else str(conv.get('created_at', '')),
            },
            'messages': [
                {
                    'role':       m.get('role'),
                    'content':    m.get('content'),
                    'created_at': m['created_at'].isoformat() if hasattr(m.get('created_at', ''), 'isoformat') else str(m.get('created_at', ''))
                }
                for m in msgs
            ],
            'message_count': len(msgs)
        }
        return {'success': True, 'data': export_doc, 'filename': f'conversation_{conversation_id[:8]}.json'}


class MarkdownExporter:
    """Exports a conversation as clean Markdown."""

    def export_conversation(self, conversation_id: str, user_id: str) -> Dict:
        data = _fetch_conversation(conversation_id, user_id)
        if not data:
            return {'error': 'Conversation not found or access denied'}
        conv = data['conversation']
        msgs = data['messages']

        lines = [
            f"# {conv.get('title', 'CUTM AI Conversation')}",
            f"\n_Exported: {datetime.now().strftime('%Y-%m-%d %H:%M')}_\n",
            "---\n"
        ]
        for m in msgs:
            role    = m.get('role', 'unknown').capitalize()
            content = m.get('content', '')
            ts      = m.get('created_at', '')
            if hasattr(ts, 'strftime'):
                ts = ts.strftime('%H:%M')
            lines.append(f"### {role} _{ts}_\n\n{content}\n\n---\n")

        md_content = '\n'.join(lines)
        return {
            'success':  True,
            'content':  md_content,
            'filename': f'conversation_{conversation_id[:8]}.md'
        }


class ExportManager:
    """Central export manager — routes export requests."""

    def handle_download(self, handler):
        """Handle GET download requests for exported files."""
        handler.send_json(200, {'message': 'Use POST endpoints to generate exports'})


export_manager  = ExportManager()
json_exporter   = JsonExporter()
md_exporter     = MarkdownExporter()
