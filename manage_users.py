"""Provision and rotate APNR operator accounts without exposing passwords in code."""

import argparse
import getpass
import sys

from main import create_connection, initialize_schema
from auth_security import hash_password


def prompt_password():
    password = getpass.getpass("Password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if not password or password != confirmation:
        raise ValueError("Passwords must be non-empty and identical.")
    if len(password) < 12:
        raise ValueError("Use a password of at least 12 characters.")
    return password


def provision_user(username, role, password):
    initialize_schema()
    connection = create_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            "INSERT INTO users (username, password, role, is_first_login) VALUES (%s, %s, %s, TRUE) "
            "ON DUPLICATE KEY UPDATE password = VALUES(password), role = VALUES(role), "
            "is_first_login = TRUE, is_active = TRUE, failed_attempts = 0, locked_until = NULL",
            (username, hash_password(password), role),
        )
        connection.commit()
    finally:
        cursor.close()
        connection.close()


def main():
    parser = argparse.ArgumentParser(description="Provision an APNR user account securely.")
    parser.add_argument("username", help="Unique account name for the operator")
    parser.add_argument("--role", choices=("Admin", "Supervisor", "Operator", "Auditor"), default="Operator")
    args = parser.parse_args()
    try:
        provision_user(args.username.strip(), args.role, prompt_password())
    except (ValueError, OSError) as error:
        print(f"User provisioning failed: {error}", file=sys.stderr)
        return 1
    print(f"Account '{args.username}' provisioned with role {args.role}.")
    print("The password was stored as a one-way hash and is not recoverable from the database.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())