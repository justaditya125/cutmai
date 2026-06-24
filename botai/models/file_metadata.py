"""
File metadata model - Track uploaded files in MySQL
"""
from datetime import datetime, timezone
from botai.config.database import generate_id


class FileMetadata:
    """File document schema for MySQL"""
    collection_name = 'files'

    def __init__(self, user_id: str, filename: str, file_type: str,
                 size_bytes: int, path: str, _id: str = None):
        self._id = _id or generate_id()
        self.user_id = user_id
        self.filename = filename
        self.file_type = file_type
        self.size_bytes = size_bytes
        self.path = path
        self.created_at = datetime.now(timezone.utc)

    def to_dict(self):
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
        if not data:
            return None
        inst = cls(
            user_id=str(data.get('user_id')) if data.get('user_id') else '',
            filename=data.get('filename', ''),
            file_type=data.get('file_type', 'unknown'),
            size_bytes=data.get('size_bytes', 0),
            path=data.get('path', ''),
            _id=str(data.get('_id')) if data.get('_id') else None
        )
        if 'created_at' in data:
            inst.created_at = data['created_at']
        return inst

    @staticmethod
    def create_indexes(db):
        pass
