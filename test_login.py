import sys, os
os.chdir("D:\\botai\\botai")
sys.path.insert(0, "D:\\botai")
sys.path.insert(0, "D:\\botai\\botai")

from botai.config.database import get_db
from botai.utils.auth_utils import verify_password

db = get_db()
user = db.users.find_one({'email': 'secure_admin'})
print('Admin found:', user is not None)
if user:
    print('  is_active:', user.get('is_active'))
    print('  is_admin:', user.get('is_admin'))
    print('  has password_hash:', bool(user.get('password_hash')))
    
    admin_pw = 'M!7vQ2rL$9xT@4pK^8n'
    result = verify_password(admin_pw, user['password_hash'])
    print('  Password match:', result)
    
    # Also try common admin passwords
    for pw in ['admin', 'admin123', 'password', 'secure_admin']:
        r = verify_password(pw, user['password_hash'])
        if r:
            print('  FOUND! Password is:', pw)
