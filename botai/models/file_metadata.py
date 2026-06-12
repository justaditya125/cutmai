"""
File metadata model - Track uploaded files in MongoDB
"""
from datetime import datetime
from bson import ObjectId
from pymongo import ASCENDING

class FileMetadata:
    """File document schema for MongoDB"""
    collection_name = 'files'
    
    def __init__(self, user_id: str, filename: str, file_type: str,
                 size_bytes: int, path: str, _id: ObjectId = None):
        self._id = _id or ObjectId()
        self.user_id = ObjectId(user_id) if isinstance(user_id, str) else user_id
        self.filename = filename          # Original filename: "essay.pdf"
        self.file_type = file_type        # Type: "document", "image", etc.
        self.size_bytes = size_bytes      # File size in bytes
        self.path = path                  # Where stored on disk
        self.created_at = datetime.utcnow()
    
    def to_dict(self):
        """Convert to dictionary for MongoDB"""
        return {
            '_id': self._id,
            'user_id': self.user_id,
            'filename': self.filename,
            'file_type': self.file_type,
            'size_bytes': self.size_bytes,
            'path': self.path,
            'created_at': self.created_at
        }
        
    @classmethod
    def from_dict(cls, data: dict) -> 'FileMetadata':
        """De-serialize object from MongoDB document dictionary"""
        if not data:
            return None
        inst = cls(
            user_id=data.get('user_id'),
            filename=data.get('filename', ''),
            file_type=data.get('file_type', 'unknown'),
            size_bytes=data.get('size_bytes', 0),
            path=data.get('path', ''),
            _id=data.get('_id')
        )
        if 'created_at' in data:
            inst.created_at = data['created_at']
        return inst
    
    @staticmethod
    def create_indexes(db):
        """Create MongoDB indexes for performance"""
        db[FileMetadata.collection_name].create_index([('user_id', ASCENDING)])
        db[FileMetadata.collection_name].create_index([('created_at', ASCENDING)])
