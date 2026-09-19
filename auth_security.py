"""Password hashing policy for the APNR authentication boundary."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from werkzeug.security import check_password_hash


PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)


def hash_password(password):
    """Create an Argon2id password hash."""
    return PASSWORD_HASHER.hash(password)


def verify_password(stored_hash, password):
    """Verify Argon2id or transitional Werkzeug hashes without plaintext fallback."""
    if str(stored_hash).startswith("$argon2id$"):
        try:
            return PASSWORD_HASHER.verify(stored_hash, password), False
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False, False
    if str(stored_hash).startswith(("pbkdf2:", "scrypt:")):
        return check_password_hash(stored_hash, password), True
    return False, False