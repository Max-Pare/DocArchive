import os
import uuid

from cryptography.fernet import Fernet

from app.config import settings

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key = settings.file_encryption_key
        if not key:
            raise RuntimeError(
                "FILE_ENCRYPTION_KEY is not set. Generate one with "
                "python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
            )
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


def save_encrypted(data: bytes, owner_id: int) -> tuple[str, int]:
    """Encrypt `data` and write it under storage_dir/owner_id/<uuid>.enc.

    Returns (relative_stored_path, plaintext_size).
    """
    token = _get_fernet().encrypt(data)
    rel_dir = str(owner_id)
    abs_dir = os.path.join(settings.storage_dir, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)
    name = f"{uuid.uuid4().hex}.enc"
    rel_path = os.path.join(rel_dir, name)
    abs_path = os.path.join(settings.storage_dir, rel_path)
    with open(abs_path, "wb") as f:
        f.write(token)
    return rel_path.replace("\\", "/"), len(data)


def read_decrypted(stored_path: str) -> bytes:
    abs_path = os.path.join(settings.storage_dir, stored_path)
    with open(abs_path, "rb") as f:
        token = f.read()
    return _get_fernet().decrypt(token)


def delete_file(stored_path: str) -> None:
    abs_path = os.path.join(settings.storage_dir, stored_path)
    try:
        os.remove(abs_path)
    except FileNotFoundError:
        pass
