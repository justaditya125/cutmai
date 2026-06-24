#!/usr/bin/env python3
import sys, os
sys.path.insert(0, os.getcwd())

from botai.config.mongodb_config import get_db
from botai.utils.auth_utils import verify_password

def main():
    db = get_db()
    u = db.users.find_one({'email': 'secure_admin@cutmap.ac.in'})
    if not u:
        print('admin not found')
        return
    pw = 'M!7vQ2rL$9xT@4pK^8n'
    print('stored hash:', u['password_hash'])
    print('verify result:', verify_password(pw, u['password_hash']))

if __name__ == '__main__':
    main()
