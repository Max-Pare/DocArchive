import contextlib
import os
import stat
import uuid
from pathlib import Path

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
                "python -c 'from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())'"
            )
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


def _resolve(stored_path: str) -> str:
    """Join `stored_path` onto STORAGE_DIR, refusing anything that escapes it.

    os.path.join alone is not a containment check in either direction: a ".." segment
    walks out of the root, and an ABSOLUTE right-hand operand discards the root
    entirely (os.path.join("/data/files", "/etc/passwd") == "/etc/passwd").

    Both sides go through realpath before being compared. STORAGE_DIR is a plain
    string with no normalisation applied anywhere, and on some platforms a temp
    directory is itself a symlink, so comparing unresolved paths would reject
    legitimate ones. Resolving also means a symlink *inside* the root pointing out of
    it is caught, which is the case a purely lexical check would miss.

    settings.storage_dir is read per call on purpose: the unit tests repoint it with
    monkeypatch, so a root resolved once at import time would be the wrong one.
    """
    root = Path(os.path.realpath(settings.storage_dir))
    target = Path(os.path.realpath(os.path.join(str(root), stored_path)))
    if target != root and not target.is_relative_to(root):
        raise ValueError(f"stored_path escapes the storage root: {stored_path!r}")
    return str(target)


def tighten_permissions() -> int:
    """chmod everything already under STORAGE_DIR to the modes new writes now use.

    save_encrypted() only controls files it creates, and os.makedirs(mode=...) only
    applies to directories that call actually creates. An archive written before the
    modes were tightened therefore keeps its 0644 files and 0755 directories forever,
    which is precisely the deployment that has documents worth protecting. Run once
    at startup: it is idempotent, and cheap because it only touches what is wrong.

    Returns the number of paths changed, so the caller can log something useful.
    """
    root = os.path.realpath(settings.storage_dir)
    if not os.path.isdir(root):
        return 0

    changed = 0
    if stat.S_IMODE(os.lstat(root).st_mode) != 0o700:
        os.chmod(root, 0o700)
        changed += 1
    for dirpath, dirnames, filenames in os.walk(root):
        for name in [*dirnames, *filenames]:
            path = os.path.join(dirpath, name)
            if os.path.islink(path):
                continue  # never follow a link out of the archive
            wanted = 0o700 if os.path.isdir(path) else 0o600
            try:
                if stat.S_IMODE(os.lstat(path).st_mode) != wanted:
                    os.chmod(path, wanted)
                    changed += 1
            except OSError:
                continue
    return changed


def save_encrypted(data: bytes, owner_id: int) -> tuple[str, int]:
    """Encrypt `data` and write it under storage_dir/owner_id/<uuid>.enc.

    Returns (relative_stored_path, plaintext_size).
    """
    token = _get_fernet().encrypt(data)
    rel_dir = str(owner_id)
    abs_dir = _resolve(rel_dir)
    # 0700: these are medical documents, and nothing but this process has any business
    # reading them. mode only applies to directories this call actually creates.
    os.makedirs(abs_dir, mode=0o700, exist_ok=True)
    name = f"{uuid.uuid4().hex}.enc"
    rel_path = os.path.join(rel_dir, name)
    abs_path = _resolve(rel_path)

    # Write to a temp name and rename into place. os.replace within one directory is
    # atomic, so a crash mid-write can never leave a truncated .enc that would later
    # fail to decrypt with an InvalidToken nobody can explain. O_EXCL makes a uuid4
    # collision an error instead of a silent overwrite of somebody's document.
    tmp_path = f"{abs_path}.tmp"
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(token)
        os.replace(tmp_path, abs_path)
    except BaseException:
        # Do not leave the partial temp file behind for a reaper that does not exist.
        with contextlib.suppress(FileNotFoundError):
            os.remove(tmp_path)
        raise
    return rel_path.replace("\\", "/"), len(data)


def read_decrypted(stored_path: str) -> bytes:
    with open(_resolve(stored_path), "rb") as f:
        token = f.read()
    return _get_fernet().decrypt(token)


def delete_file(stored_path: str) -> None:
    with contextlib.suppress(FileNotFoundError):
        os.remove(_resolve(stored_path))
