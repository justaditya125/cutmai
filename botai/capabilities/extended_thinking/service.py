"""
Extended Thinking Engine
Wraps the extended thinking capability already present in chat_routes.py
with structured storage, budget tracking, and on-demand thinking requests.
"""
import json
import urllib.request
from datetime import datetime
from typing import Dict, Optional
from botai.config.mysql_config import get_db
from botai.config.database import generate_id
from botai.services.key_rotator import key_rotator


class ThinkingEngine:
    """
    Manages structured extended thinking requests.
    Supplements the existing thinking mode in chat_routes.py without modifying it.
    """

    DEFAULT_BUDGET = 8000   # tokens
    MAX_BUDGET     = 16000  # tokens

    def think(self, question: str, user_id: str, budget_tokens: int = None,
              conversation_id: str = None) -> Dict:
        """
        Run a deep thinking session for a complex question.
        Returns: thinking_content, final_answer, tokens_used.
        """
        budget = min(budget_tokens or self.DEFAULT_BUDGET, self.MAX_BUDGET)
        api_key = key_rotator.get_key()
        if not api_key:
            return {'error': 'No API key available'}

        try:
            payload = json.dumps({
                'model':      'claude-sonnet-4-5',
                'max_tokens': budget + 2000,
                'thinking': {
                    'type':         'enabled',
                    'budget_tokens': budget
                },
                'messages': [{'role': 'user', 'content': question}]
            }).encode('utf-8')

            req = urllib.request.Request(
                'https://api.anthropic.com/v1/messages',
                data=payload,
                headers={
                    'Content-Type':    'application/json',
                    'x-api-key':       api_key,
                    'anthropic-version': '2023-06-01'
                }
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())

            thinking_text = ''
            answer_text   = ''
            for block in data.get('content', []):
                if block.get('type') == 'thinking':
                    thinking_text += block.get('thinking', '')
                elif block.get('type') == 'text':
                    answer_text = block.get('text', '')

            usage = data.get('usage', {})
            result = {
                'question':       question,
                'thinking':       thinking_text,
                'answer':         answer_text,
                'budget_tokens':  budget,
                'input_tokens':   usage.get('input_tokens', 0),
                'output_tokens':  usage.get('output_tokens', 0),
                'generated_at':   datetime.now().isoformat()
            }

            # Persist thinking session for audit
            self._store(user_id, conversation_id, result)
            return result

        except Exception as e:
            print(f"[ThinkingEngine] error: {e}")
            return {'error': str(e)}

    def _store(self, user_id: str, conversation_id: Optional[str], result: Dict):
        """Store thinking session for audit/history."""
        try:
            db = get_db()
            if db is None:
                return
            db.thinking_sessions.insert_one({
                'user_id':         user_id,
                'conversation_id': conversation_id,
                'question':        result.get('question', '')[:500],
                'thinking_length': len(result.get('thinking', '')),
                'answer_length':   len(result.get('answer', '')),
                'budget_tokens':   result.get('budget_tokens', 0),
                'input_tokens':    result.get('input_tokens', 0),
                'output_tokens':   result.get('output_tokens', 0),
                'created_at':      datetime.now()
            })
        except Exception as e:
            print(f"[ThinkingEngine] store error: {e}")

    def get_history(self, user_id: str, limit: int = 10) -> list:
        """Retrieve past thinking sessions for a user."""
        try:
            db = get_db()
            if db is None:
                return []
            records = list(
                db.thinking_sessions.find({'user_id': user_id})
                .sort('created_at', -1).limit(limit)
            )
            for r in records:
                if hasattr(r.get('created_at'), 'isoformat'):
                    r['created_at'] = r['created_at'].isoformat()
            return records
        except Exception as e:
            print(f"[ThinkingEngine] get_history error: {e}")
            return []


thinking_engine = ThinkingEngine()
