#!/usr/bin/env python3
"""
Utility to create or update an admin user in the application's MongoDB.

Usage:
  python scripts/create_admin.py EMAIL PASSWORD [NAME]

If EMAIL does not contain an '@', the script will append '@cutmap.ac.in'.
"""
import sys
from datetime import datetime

from botai.config.mongodb_config import get_db, init_db
from botai.utils.auth_utils import hash_password


def upsert_admin(email: str, password: str, name: str = 'Administrator') -> None:
    if '@' not in email:
        email = f"{email}@cutmap.ac.in"

    db = get_db()
    try:
        init_db()
    except Exception:
        pass

    hashed = hash_password(password)

    existing = db.users.find_one({"email": email})
    now = datetime.now()
    if existing:
        db.users.update_one(
            {"_id": existing['_id']},
            {"$set": {
                "password_hash": hashed,
                "is_admin": True,
                "is_active": True,
                "is_approved": True,
                "name": name,
                "updated_at": now
            }}
        )
        print(f"Updated admin user: {email}")
    else:
        res = db.users.insert_one({
            "email": email,
            "password_hash": hashed,
            "name": name,
            "profile_picture": None,
            "login_method": "email",
            "is_approved": True,
            "token_limit": 1000000,
            "is_active": True,
            "is_admin": True,
            "total_tokens_used": 0,
            "total_messages": 0,
            "created_at": now,
            "updated_at": now,
            "last_login": now
        })
        print(f"Created admin user: {email} (id: {res.inserted_id})")


def main(argv):
    if len(argv) < 3:
        print("Usage: python scripts/create_admin.py EMAIL PASSWORD [NAME]")
        sys.exit(1)
    email = argv[1]
    password = argv[2]
    name = argv[3] if len(argv) > 3 else 'Administrator'
    upsert_admin(email, password, name)


if __name__ == '__main__':
    main(sys.argv)
