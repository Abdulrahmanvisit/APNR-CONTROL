from auth_security import hash_password, verify_password


def test_argon2id_hash_verifies_only_the_original_password():
    stored_hash = hash_password("A-strong-password-2026!")

    assert stored_hash.startswith("$argon2id$")
    assert verify_password(stored_hash, "A-strong-password-2026!") == (True, False)
    assert verify_password(stored_hash, "wrong-password") == (False, False)


def test_legacy_scrypt_hash_is_transitional_and_not_plaintext():
    from werkzeug.security import generate_password_hash

    stored_hash = generate_password_hash("legacy-password")

    assert verify_password(stored_hash, "legacy-password") == (True, True)
    assert verify_password(stored_hash, "legacy-password-wrong") == (False, True)
    assert verify_password("legacy-password", "legacy-password") == (False, False)