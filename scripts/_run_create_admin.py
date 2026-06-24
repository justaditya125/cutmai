#!/usr/bin/env python3
import os
import sys

# Ensure project root is importable
sys.path.insert(0, os.getcwd())

from scripts.create_admin import upsert_admin

if __name__ == '__main__':
    upsert_admin('secure_admin@cutmap.ac.in', 'M!7vQ2rL$9xT@4pK^8n', 'Secure Admin')
