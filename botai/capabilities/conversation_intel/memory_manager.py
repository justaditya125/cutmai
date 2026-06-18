"""
Memory Manager — persistent per-user memory stored in conversation_memory collection.
"""
import threading
from datetime import datetime
from typing import List, Dict, Optional
from bson import ObjectId
from botai.config.mongodb_config import get_db


class MemoryManager:
    """Stores and retrieves user memory snippets from MongoDB."""

    MAX_MEMORIES_PER_USER = 100

    def store(self, user_id: str, content: str, tags: List[str] = None) -> bool:
        """Store a memory snippet for a user."""
        try:
            db = get_db()
            if db is None:
                return False
            u_id = ObjectId(user_id) if isinstance(user_id, str) else user_id

            # Enforce per-user cap
            count = db.conversation_memory.count_documents({'user_id': u_id})
            if count >= self.MAX_MEMORIES_PER_USER:
                # Remove oldest
                oldest = db.conversation_memory.find_one({'user_id': u_id}, sort=[('created_at', 1)])
                if oldest:
                    db.conversation_memory.delete_one({'_id': oldest['_id']})

            db.conversation_memory.insert_one({
                'user_id':    u_id,
                'content':    content.strip(),
                'tags':       tags or [],
                'created_at': datetime.now()
            })
            return True
        except Exception as e:
            print(f"[MemoryManager] store error: {e}")
            return False

    def retrieve(self, user_id: str, query: str = '', limit: int = 10) -> List[Dict]:
        """Retrieve memory snippets for a user, optionally filtered by query keywords."""
        try:
            db = get_db()
            if db is None:
                return []
            u_id = ObjectId(user_id) if isinstance(user_id, str) else user_id

            filter_query: Dict = {'user_id': u_id}
            if query:
                # Simple text search in content
                import re
                filter_query['content'] = {'$regex': re.escape(query), '$options': 'i'}

            records = list(
                db.conversation_memory.find(filter_query, {'_id': 0, 'user_id': 0})
                .sort('created_at', -1)
                .limit(limit)
            )
            for r in records:
                if isinstance(r.get('created_at'), datetime):
                    r['created_at'] = r['created_at'].isoformat()
            return records
        except Exception as e:
            print(f"[MemoryManager] retrieve error: {e}")
            return []

    def delete_all(self, user_id: str) -> int:
        """Delete all memories for a user."""
        try:
            db = get_db()
            if db is None:
                return 0
            u_id = ObjectId(user_id) if isinstance(user_id, str) else user_id
            result = db.conversation_memory.delete_many({'user_id': u_id})
            return result.deleted_count
        except Exception as e:
            print(f"[MemoryManager] delete_all error: {e}")
            return 0


class ContextManager:
    """Sliding window context manager for conversations."""

    def __init__(self, window_size: int = 6, threshold: int = 12):
        self.window_size = window_size
        self.threshold   = threshold

    def apply_sliding_window(self, messages: List[Dict]) -> Dict:
        """
        Apply sliding window to a messages list.
        Wraps existing context_compactor logic with tracking metadata.
        """
        from botai.services.context_compactor import context_compactor
        original_count = len(messages)
        compacted, summary = context_compactor.compact_messages(
            messages, threshold=self.threshold, keep_count=self.window_size
        )
        return {
            'messages':       compacted,
            'summary':        summary,
            'original_count': original_count,
            'compacted_count': len(compacted),
            'was_compacted':  original_count > self.threshold
        }


memory_manager  = MemoryManager()
context_manager = ContextManager()
