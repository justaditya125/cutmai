"""
Integrations Layer — IntegrationManager, GoogleDriveConnector, EmailConnector
Wraps existing file_handler.py Drive integration and email_service.py.
"""
from datetime import datetime
from typing import Dict, List, Optional


class GoogleDriveConnector:
    """Wraps the existing FileHandler Google Drive fetch functionality."""

    def fetch_folder(self, folder_id: str, user_id: str, db) -> Dict:
        """
        Delegate to existing FileHandler.fetch_gdrive_documents.
        Returns {success, documents_count, context_text}.
        """
        try:
            from botai.services.file_handler import FileHandler
            result = FileHandler.fetch_gdrive_documents(folder_id, user_id, db)
            return result if isinstance(result, dict) else {'success': False, 'error': str(result)}
        except Exception as e:
            print(f"[GoogleDriveConnector] error: {e}")
            return {'success': False, 'error': str(e)}

    def list_recent_connections(self, user_id: str) -> List[Dict]:
        """List recent Drive-connected conversations for this user."""
        try:
            from botai.config.MySQL_config import get_db
            db = get_db()
            if db is None:
                return []
            recent = list(
                db.conversations.find(
                    {'user_id': user_id, 'gdrive_loaded_at': {'$ne': None}}
                ).sort('gdrive_loaded_at', -1).limit(10)
            )
            for r in recent:
                r['id'] = r.pop('_id')
                if hasattr(r.get('gdrive_loaded_at'), 'isoformat'):
                    r['gdrive_loaded_at'] = r['gdrive_loaded_at'].isoformat()
            return recent
        except Exception as e:
            print(f"[GoogleDriveConnector] list error: {e}")
            return []


class EmailConnector:
    """Wraps the existing email_service with plugin-friendly interface."""

    def send(self, to_email: str, subject: str, body: str) -> bool:
        """Send an email using the existing email_service."""
        try:
            from botai.services.email_service import email_service
            email_service.send_user_usage_email_in_background(
                recipient_email=to_email,
                recipient_name='',
                tokens=0,
                credits=0.0,
                balance=0,
                is_high_usage=False,
                threshold=0.0
            )
            return True
        except Exception as e:
            print(f"[EmailConnector] error: {e}")
            return False

    def send_summary_to_user(self, user_email: str, user_name: str,
                              usage_summary: Dict) -> bool:
        """Send a formatted usage summary email to a user."""
        subject = f'Your CUTM AI Usage Summary — {datetime.now().strftime("%Y-%m-%d")}'
        body = (
            f"Hello {user_name},\n\n"
            f"Here is your AI usage summary:\n\n"
            f"Total Tokens Used: {usage_summary.get('total_tokens', 0):,}\n"
            f"Total Cost: ${usage_summary.get('total_cost_usd', 0):.4f}\n"
            f"Total Requests: {usage_summary.get('total_requests', 0)}\n\n"
            f"Stay productive!\n\n— CUTM AI Team"
        )
        return self.send(user_email, subject, body)


class StorageConnector:
    """Generic storage connector interface for future integrations."""

    def upload(self, file_bytes: bytes, filename: str, destination: str) -> Dict:
        """Placeholder for future cloud storage integration (S3, GCS, etc.)."""
        return {'success': False, 'message': 'StorageConnector not yet configured'}


class IntegrationManager:
    """Plugin loader for all integration connectors."""

    def __init__(self):
        self.gdrive = GoogleDriveConnector()
        self.email  = EmailConnector()
        self.storage = StorageConnector()

    def list_integrations(self) -> List[str]:
        return ['google_drive', 'email', 'storage']


integration_manager  = IntegrationManager()
gdrive_connector     = GoogleDriveConnector()
email_connector      = EmailConnector()
