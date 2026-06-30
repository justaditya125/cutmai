import sys, os
os.chdir("D:\\botai\\botai")
sys.path.insert(0, "D:\\botai")
sys.path.insert(0, "D:\\botai\\botai")

from botai.config.database import get_db
from botai.utils.auth_utils import hash_password, verify_password
from botai.config import settings

db = get_db()

# Read admin password from .env
admin_pw = getattr(settings, 'ADMIN_PASSWORD', None) or 'M!7vQ2rL$9xT@4pK^8n'
print('Using admin password from settings')

# Check current admin
user = db.users.find_one({'email': 'secure_admin'})
if user:
    print('Current hash validation:', verify_password(admin_pw, user['password_hash']))
    if not verify_password(admin_pw, user['password_hash']):
        new_hash = hash_password(admin_pw)
        db.users.update_one({'_id': user['_id']}, {'$set': {'password_hash': new_hash}})
        print('Password reset to match .env')
        
        # Verify
        verify = verify_password(admin_pw, db.users.find_one({'email': 'secure_admin'})['password_hash'])
        print('Verification after reset:', verify)
    else:
        print('Password already matches')
else:
    print('ERROR: Admin user not found')
