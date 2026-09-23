from app.core.security import (
    create_access_token,
    decode_token,
    decrypt_secret,
    encrypt_secret,
    hash_password,
    is_strong_password,
    verify_password,
)


def test_password_policy():
    assert is_strong_password("Short1!") is False
    assert is_strong_password("nouppercase1!") is False
    assert is_strong_password("NOLOWERCASE1!") is False
    assert is_strong_password("NoSpecial123") is False
    assert is_strong_password("ValidPass1!") is True
    assert is_strong_password("ПарольСильный1!") is True


def test_password_hash_roundtrip():
    hashed = hash_password("ValidPass1!")
    assert hashed != "ValidPass1!"
    assert verify_password("ValidPass1!", hashed)
    assert not verify_password("WrongPass1!", hashed)


def test_jwt_access_token():
    token = create_access_token("user-id", extra={"role": "Агроном"})
    payload = decode_token(token)
    assert payload["sub"] == "user-id"
    assert payload["type"] == "access"
    assert payload["role"] == "Агроном"


def test_aes256_encrypt_roundtrip():
    secret = "dzz-password-пример"
    encrypted = encrypt_secret(secret)
    assert encrypted != secret
    assert decrypt_secret(encrypted) == secret
