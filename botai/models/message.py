"""
Message model - Schema definition for chat messages (MySQL)
"""
from datetime import datetime, timezone
from typing import Optional, List
from botai.config.database import generate_id


class Message:
    """Message document mapping and serialization"""
    collection_name = 'messages'

    def __init__(self, conversation_id: str, user_id: str,
                 role: str, content: str, file_references: Optional[List[str]] = None,
                 created_at: Optional[datetime] = None, _id: Optional[str] = None):
        self._id = _id or generate_id()
        self.conversation_id = conversation_id
        self.user_id = user_id
        self.role = role
        self.content = content
        self.file_references = file_references or []
        self.created_at = created_at or datetime.now(timezone.utc)

    def to_dict(self) -> dict:
        return {
            '_id': self._id,
            'conversation_id': self.conversation_id,
            'user_id': self.user_id,
            'role': self.role,
            'content': self.content,
            'file_references': self.file_references,
            'created_at': self.created_at
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Message':
        if not data:
            return None
        return cls(
            conversation_id=str(data.get('conversation_id')) if data.get('conversation_id') else '',
            user_id=str(data.get('user_id')) if data.get('user_id') else '',
            role=data.get('role', 'user'),
            content=data.get('content', ''),
            file_references=data.get('file_references', []),
            created_at=data.get('created_at'),
            _id=str(data.get('_id')) if data.get('_id') else None
        )

    @staticmethod
    def create_indexes(db):
        pass
