"""
Conversation model - Schema definition for chat sessions (MySQL)
"""
from datetime import datetime, timezone
from typing import Optional
from botai.config.database import generate_id


class Conversation:
    """Conversation document mapping and serialization"""
    collection_name = 'conversations'

    def __init__(self, user_id: str, title: str = 'New Chat',
                 created_at: Optional[datetime] = None, updated_at: Optional[datetime] = None,
                 _id: Optional[str] = None):
        self._id = _id or generate_id()
        self.user_id = user_id
        self.title = title
        self.created_at = created_at or datetime.now(timezone.utc)
        self.updated_at = updated_at or datetime.now(timezone.utc)

    def to_dict(self) -> dict:
        return {
            '_id': self._id,
            'user_id': self.user_id,
            'title': self.title,
            'created_at': self.created_at,
            'updated_at': self.updated_at
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Conversation':
        if not data:
            return None
        return cls(
            user_id=str(data.get('user_id')) if data.get('user_id') else '',
            title=data.get('title', 'New Chat'),
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at'),
            _id=str(data.get('_id')) if data.get('_id') else None
        )

    @staticmethod
    def create_indexes(db):
        pass
