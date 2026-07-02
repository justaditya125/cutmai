"""
Conversation Intelligence Service
Wraps and enhances the existing context_compactor.py with:
- On-demand conversation summarization via MySQL
- Topic extraction
- Sliding window context management
"""
import re
from datetime import datetime
from typing import Optional, Dict, List
from botai.config.mysql_config import get_db
from botai.services.context_compactor import context_compactor


class ConversationSummarizer:
    """Enhanced summarizer that operates on stored conversation history."""

    def summarize(self, conversation_id: str, user_id: str) -> Dict:
        """
        Fetch messages for a conversation from MySQL and generate a rich summary.
        Returns summary text + extracted topics.
        """
        try:
            db = get_db()
            if db is None:
                return {'error': 'Database unavailable'}

            # Verify ownership
            conv = db.conversations.find_one({'_id': conversation_id, 'user_id': user_id})
            if not conv:
                return {'error': 'Conversation not found or access denied'}

            msgs = list(db.messages.find({'conversation_id': conversation_id}).sort('created_at', 1))
            if not msgs:
                return {'summary': 'No messages found.', 'topics': [], 'message_count': 0}

            # Convert to API message format
            api_msgs = [
                {'role': m['role'], 'content': m['content']}
                for m in msgs if m.get('role') in ('user', 'assistant')
            ]

            # Use existing context_compactor for the summary call
            summary_text = context_compactor.summarize_history(api_msgs)
            topics = self._extract_topics(summary_text or '')

            return {
                'conversation_id': conversation_id,
                'message_count':   len(msgs),
                'summary':         summary_text or 'Could not generate summary.',
                'topics':          topics,
                'generated_at':    datetime.now().isoformat()
            }
        except Exception as e:
            print(f"[ConversationSummarizer] Error: {e}")
            return {'error': 'Internal error'}

    def _extract_topics(self, summary: str) -> List[str]:
        """Simple keyword extraction from summary text."""
        if not summary:
            return []
        words = re.findall(r'\b[A-Z][a-z]{4,}\b|\b[a-z]{5,}\b', summary)
        # Deduplicate and return top 5
        seen = set()
        topics = []
        for w in words:
            lw = w.lower()
            if lw not in seen and lw not in ('about', 'their', 'which', 'where', 'these', 'those'):
                seen.add(lw)
                topics.append(w)
            if len(topics) >= 5:
                break
        return topics


conversation_summarizer = ConversationSummarizer()
