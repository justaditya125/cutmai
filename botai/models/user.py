"""
User model - Schema definition for user accounts (MySQL)
"""
from datetime import datetime, timezone
from typing import Optional
from botai.config.database import generate_id


class User:
    """User document mapping and serialization"""
    collection_name = 'users'

    def __init__(self, email: str, password_hash: str = None, salt: str = None,
                 name: str = '', google_id: Optional[str] = None,
                 profile_picture: Optional[str] = None, login_method: str = 'email',
                 is_approved: bool = False, token_limit: int = 1000000,
                 is_active: bool = True, is_admin: bool = False,
                 total_tokens_used: int = 0, total_messages: int = 0,
                 created_at: Optional[datetime] = None, updated_at: Optional[datetime] = None,
                 last_login: Optional[datetime] = None, _id: Optional[str] = None):
        self._id = _id or generate_id()
        self.email = email.strip().lower()
        self.password_hash = password_hash
        self.salt = salt
        self.name = name.strip() if name else None
        self.google_id = google_id
        self.profile_picture = profile_picture
        self.login_method = login_method
        self.is_approved = is_approved
        self.token_limit = token_limit
        self.is_active = is_active
        self.is_admin = is_admin
        self.total_tokens_used = total_tokens_used
        self.total_messages = total_messages
        self.created_at = created_at or datetime.now(timezone.utc)
        self.updated_at = updated_at or datetime.now(timezone.utc)
        self.last_login = last_login

    def to_dict(self) -> dict:
        doc = {
            '_id': self._id,
            'email': self.email,
            'name': self.name,
            'login_method': self.login_method,
            'is_approved': self.is_approved,
            'token_limit': self.token_limit,
            'is_active': self.is_active,
            'is_admin': self.is_admin,
            'total_tokens_used': self.total_tokens_used,
            'total_messages': self.total_messages,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'last_login': self.last_login
        }
        if self.google_id is not None:
            doc['google_id'] = self.google_id
        if self.profile_picture is not None:
            doc['profile_picture'] = self.profile_picture
        return doc

    def to_db_dict(self) -> dict:
        doc = self.to_dict()
        doc['password_hash'] = self.password_hash
        if self.salt is not None:
            doc['salt'] = self.salt
        return doc

    @classmethod
    def from_dict(cls, data: dict) -> 'User':
        if not data:
            return None
        stored_salt = data.get('salt')
        stored_hash = data.get('password_hash')
        if stored_hash and not stored_salt and ':' in stored_hash:
            stored_salt, stored_hash = stored_hash.split(':', 1)

        return cls(
            email=data.get('email', ''),
            password_hash=stored_hash,
            salt=stored_salt,
            name=data.get('name', ''),
            google_id=data.get('google_id'),
            profile_picture=data.get('profile_picture'),
            login_method=data.get('login_method', 'email'),
            is_approved=data.get('is_approved', False),
            token_limit=data.get('token_limit', 1000000),
            is_active=data.get('is_active', True),
            is_admin=data.get('is_admin', False),
            total_tokens_used=data.get('total_tokens_used', 0),
            total_messages=data.get('total_messages', 0),
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at'),
            last_login=data.get('last_login'),
            _id=str(data.get('_id')) if data.get('_id') else None
        )

    @staticmethod
    def create_indexes(db):
        pass
