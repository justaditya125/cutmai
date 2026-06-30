from botai.config.database import get_db
from botai.utils.auth_utils import hash_password, verify_password
from botai.config import settings

db = get_db()
admin_pw = getattr(settings, 'ADMIN_PASSWORD', None) or 'M!7vQ2rL$9xT@4pK^8n'
new_hash = hash_password(admin_pw)
db.users.update_one({'email': 'secure_admin'}, {'$set': {'password_hash': new_hash}})
print('Admin password reset')

# Verify
user = db.users.find_one({'email': 'secure_admin'})
print('Verification:', verify_password(admin_pw, user['password_hash']))