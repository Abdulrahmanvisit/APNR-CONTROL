#!/usr/bin/env python
"""
Run this on Render to provision an admin user if auto-provisioning didn't work.

Usage on Render Dashboard:
  1. Go to Service → Shell
  2. Run: python render_provision.py

Or via CLI (if render-cli is installed):
  render run python render_provision.py --service apnr-control-center
"""
import sys
sys.path.insert(0, ".")
from main import create_connection, initialize_schema
from auth_security import hash_password
import os

username = os.getenv("ADMIN_USERNAME", "admin")
password = os.getenv("ADMIN_PASSWORD", "ChangeMe123456")

print(f"Provisioning admin user '{username}'...")

try:
    initialize_schema()
    conn = create_connection()
    cursor = conn.cursor()

    # Check if admin user exists
    cursor.execute("SELECT username FROM users WHERE username = %s", (username,))
    existing = cursor.fetchone()

    if existing:
        cursor.execute(
            "UPDATE users SET password = %s, role = 'Admin', is_active = TRUE, "
            "is_first_login = TRUE, failed_attempts = 0, locked_until = NULL "
            "WHERE username = %s",
            (hash_password(password), username)
        )
    else:
        cursor.execute(
            "INSERT INTO users (username, password, role, is_first_login) VALUES (%s, %s, 'Admin', TRUE)",
            (username, hash_password(password))
        )

    conn.commit()
    cursor.close()
    conn.close()

    print(f"Admin user provisioned: {username}")
    print(f"Password: {password}")
    print(f"Login at: https://apnr-control.onrender.com/login")
    print(f"After login -> reset password at /account/reset-password")

except Exception as e:
    print(f"Error: {e}")
    print("Check that DATABASE_URL or APNR_DB_* env vars are set in Render dashboard.")
