"""
Message model - MongoDB schema definition for chat messages
"""
from datetime import datetime
from typing import Optional, List
from bson import ObjectId
from pymongo import ASCENDING

class Message:
    """Message document mapping and serialization"""
    collection_name = 'messages'
    
    def __init__(self, conversation_id: ObjectId, user_id: ObjectId,
                 role: str, content: str, file_references: Optional[List[str]] = None,
                 created_at: Optional[datetime] = None, _id: Optional[ObjectId] = None):
        self._id = _id or ObjectId()
        self.conversation_id = ObjectId(conversation_id) if isinstance(conversation_id, str) else conversation_id
        self.user_id = ObjectId(user_id) if isinstance(user_id, str) else user_id
        self.role = role  # 'user' or 'assistant'
        self.content = content
        self.file_references = file_references or []
        self.created_at = created_at or datetime.utcnow()

    def to_dict(self) -> dict:
        """Serialize object to MongoDB document dictionary"""
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
        """De-serialize object from MongoDB document dictionary"""
        if not data:
            return None
        return cls(
            conversation_id=data.get('conversation_id'),
            user_id=data.get('user_id'),
            role=data.get('role', 'user'),
            content=data.get('content', ''),
            file_references=data.get('file_references', []),
            created_at=data.get('created_at'),
            _id=data.get('_id')
        )

    @staticmethod
    def create_indexes(db):
        """Build database constraints and performance search indexes"""
        db[Message.collection_name].create_index([('conversation_id', ASCENDING)])
        db[Message.collection_name].create_index([('user_id', ASCENDING)])
        db[Message.collection_name].create_index([('created_at', ASCENDING)])
