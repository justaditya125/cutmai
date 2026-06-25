"""
Artifact Detection Engine
Scans LLM responses for embeddable artifacts (HTML, SVG, React, Mermaid, Charts, Code).
Stores detected artifacts in MySQL artifacts collection.
"""
import re
import json
import hashlib
from datetime import datetime
from typing import Dict, List, Optional
from botai.config.mysql_config import get_db


# Artifact type detection patterns
ARTIFACT_PATTERNS = {
    'html':     [r'```html\n(.*?)```', r'<!DOCTYPE html', r'<html'],
    'svg':      [r'```svg\n(.*?)```', r'<svg[\s>]'],
    'mermaid':  [r'```mermaid\n(.*?)```'],
    'chart':    [r'```chart\n(.*?)```'],
    'react':    [r'```(jsx|tsx|react)\n(.*?)```', r'import React'],
    'markdown': [r'```markdown\n(.*?)```'],
    'python':   [r'```python\n(.*?)```'],
    'javascript': [r'```(javascript|js)\n(.*?)```'],
    'sql':      [r'```sql\n(.*?)```'],
    'css':      [r'```css\n(.*?)```'],
}


class ArtifactDetector:
    """Scans text content and detects embeddable artifact blocks."""

    def detect(self, text: str) -> List[Dict]:
        """Return list of detected artifacts with type, content, and position."""
        artifacts = []
        seen_contents = set()

        for artifact_type, patterns in ARTIFACT_PATTERNS.items():
            for pattern in patterns:
                matches = re.finditer(pattern, text, re.DOTALL | re.IGNORECASE)
                for match in matches:
                    # Get the last capture group (the content)
                    content = match.group(match.lastindex or 0) if match.lastindex else match.group(0)
                    content = content.strip()

                    # Deduplicate
                    content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
                    if content_hash in seen_contents or len(content) < 10:
                        continue
                    seen_contents.add(content_hash)

                    artifacts.append({
                        'type':       artifact_type,
                        'content':    content,
                        'start':      match.start(),
                        'end':        match.end(),
                        'char_count': len(content)
                    })

        # Sort by position in text
        artifacts.sort(key=lambda x: x['start'])
        return artifacts

    def has_artifacts(self, text: str) -> bool:
        return bool(self.detect(text))


class ArtifactStorage:
    """Persists and retrieves artifacts from MySQL artifacts collection."""

    def save(self, user_id: str, conversation_id: Optional[str],
             message_id: Optional[str], artifact: Dict) -> Optional[str]:
        """Save a detected artifact. Returns artifact_id."""
        try:
            db = get_db()
            if db is None:
                return None
            doc = {
                'user_id':         user_id,
                'conversation_id': conversation_id,
                'message_id':      message_id,
                'artifact_type':   artifact.get('type'),
                'content':         artifact.get('content'),
                'char_count':      artifact.get('char_count', 0),
                'version':         1,
                'created_at':      datetime.now()
            }
            result = db.artifacts.insert_one(doc)
            return str(result.inserted_id)
        except Exception as e:
            print(f"[ArtifactStorage] save error: {e}")
            return None

    def list_for_user(self, user_id: str, limit: int = 20) -> List[Dict]:
        """Return recent artifacts for a user."""
        try:
            db = get_db()
            if db is None:
                return []
            u_id = user_id
            records = list(
                db.artifacts.find({'user_id': u_id})
                .sort('created_at', -1).limit(limit)
            )
            for r in records:
                r['id'] = r.pop('_id')
                if r.get('conversation_id'):
                    r['conversation_id'] = str(r['conversation_id'])
                if r.get('message_id'):
                    r['message_id'] = str(r['message_id'])
                if isinstance(r.get('created_at'), datetime):
                    r['created_at'] = r['created_at'].isoformat()
            return records
        except Exception as e:
            print(f"[ArtifactStorage] list error: {e}")
            return []

    def get(self, artifact_id: str, user_id: str) -> Optional[Dict]:
        """Retrieve a specific artifact by ID, verifying ownership."""
        try:
            db = get_db()
            if db is None:
                return None
            record = db.artifacts.find_one({'_id': artifact_id, 'user_id': user_id})
            if not record:
                return None
            record['id'] = record.pop('_id')
            if isinstance(record.get('created_at'), datetime):
                record['created_at'] = record['created_at'].isoformat()
            return record
        except Exception as e:
            print(f"[ArtifactStorage] get error: {e}")
            return None


class ArtifactVersionManager:
    """Handles versioning of updated artifacts."""

    def create_new_version(self, artifact_id: str, user_id: str, new_content: str) -> Optional[str]:
        """Create a new version of an existing artifact."""
        try:
            db = get_db()
            if db is None:
                return None
            original = db.artifacts.find_one({'_id': artifact_id, 'user_id': user_id})
            if not original:
                return None
            new_doc = {
                k: v for k, v in original.items() if k not in ('_id', 'id')
            }
            new_doc.update({
                'content':   new_content,
                'version':   original.get('version', 1) + 1,
                'parent_id': artifact_id,
                'created_at': datetime.now()
            })
            result = db.artifacts.insert_one(new_doc)
            return str(result.inserted_id)
        except Exception as e:
            print(f"[ArtifactVersionManager] error: {e}")
            return None


# Global singletons
artifact_detector       = ArtifactDetector()
artifact_storage        = ArtifactStorage()
artifact_version_manager = ArtifactVersionManager()
