"""
Conversation model - MongoDB schema definition for chat sessions
"""
from datetime import datetime
from typing import Optional
from bson import ObjectId
from pymongo import ASCENDING

class Conversation:
    """Conversation document mapping and serialization"""
    collection_name = 'conversations'
    
    def __init__(self, user_id: ObjectId, title: str = 'New Chat',
                 created_at: Optional[datetime] = None, updated_at: Optional[datetime] = None,
                 _id: Optional[ObjectId] = None):
        self._id = _id or ObjectId()
        self.user_id = ObjectId(user_id) if isinstance(user_id, str) else user_id
        self.title = title
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()

    def to_dict(self) -> dict:
        """Serialize object to MongoDB document dictionary"""
        return {
            '_id': self._id,
            'user_id': self.user_id,
            'title': self.title,
            'created_at': self.created_at,
            'updated_at': self.updated_at
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Conversation':
        """De-serialize object from MongoDB document dictionary"""
        if not data:
            return None
        return cls(
            user_id=data.get('user_id'),
            title=data.get('title', 'New Chat'),
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at'),
            _id=data.get('_id')
        )

    @staticmethod
    def create_indexes(db):
        """Build database constraints and performance search indexes"""
        db[Conversation.collection_name].create_index([('user_id', ASCENDING)])
        db[Conversation.collection_name].create_index([('updated_at', ASCENDING)])
