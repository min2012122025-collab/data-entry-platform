import base64
import hashlib
import hmac
import os
import secrets

from cryptography.fernet import Fernet, InvalidToken

from .config import settings


HASH_NAME = "sha256"
ITERATIONS = 260000
SECRET_PREFIX = "fernet:"


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(HASH_NAME, password.encode("utf-8"), salt, ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        ITERATIONS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, iterations, salt_b64, digest_b64 = encoded.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64.encode("ascii"))
        expected = base64.b64decode(digest_b64.encode("ascii"))
        actual = hashlib.pbkdf2_hmac(HASH_NAME, password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _secret_cipher(secret_key=None):
    secret_key = secret_key or settings.secret_key
    if not secret_key:
        raise RuntimeError("缺少 ENTRY_SECRET_KEY，不能加密或解密数据连接凭据")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret_key.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    if not value or value.startswith(SECRET_PREFIX):
        return value
    return SECRET_PREFIX + _secret_cipher().encrypt(value.encode("utf-8")).decode("ascii")


def encrypt_secret_with_key(value: str, secret_key: str) -> str:
    if not value:
        return value
    return SECRET_PREFIX + _secret_cipher(secret_key).encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str) -> str:
    if not value or not value.startswith(SECRET_PREFIX):
        return value
    try:
        return _secret_cipher().decrypt(value[len(SECRET_PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("数据连接密码无法解密，请管理员重新保存密码") from exc


def decrypt_secret_with_key(value: str, secret_key: str) -> str:
    if not value or not value.startswith(SECRET_PREFIX):
        return value
    try:
        return _secret_cipher(secret_key).decrypt(value[len(SECRET_PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("数据连接密码无法使用旧密钥解密，已取消密钥轮换") from exc
