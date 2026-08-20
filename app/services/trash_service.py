from __future__ import annotations

from datetime import datetime, timezone
from pathlib import PurePosixPath

from .storage import StorageError, StorageProvider, normalize_repo_path


TRASH_ROOT = "_trash"


def _ensure_directory(storage: StorageProvider, path: str) -> None:
    current = ""
    for part in normalize_repo_path(path).split("/"):
        current = f"{current}/{part}".strip("/")
        if not storage.exists(current):
            try:
                storage.mkdir(current)
            except StorageError:
                if not storage.exists(current):
                    raise


def _safe_label(label: str) -> str:
    value = PurePosixPath((label or "item").replace("\\", "/")).name.strip()
    return value if value not in {"", ".", ".."} else "item"


def move_to_trash(storage: StorageProvider, source: str, kind: str, identifier: str, label: str) -> str:
    source = normalize_repo_path(source)
    if not source or not storage.exists(source):
        raise StorageError("이동할 Storage 경로가 존재하지 않습니다.")
    parent = normalize_repo_path(f"{TRASH_ROOT}/{kind}")
    _ensure_directory(storage, parent)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    base = f"{identifier}-{_safe_label(label)}-{timestamp}"
    destination = normalize_repo_path(f"{parent}/{base}")
    suffix = 2
    while storage.exists(destination):
        destination = normalize_repo_path(f"{parent}/{base}-{suffix}")
        suffix += 1
    storage.move(source, destination, overwrite=False)
    return destination


def restore_from_trash(storage: StorageProvider, trash_path: str, destination: str) -> None:
    trash_path = normalize_repo_path(trash_path)
    destination = normalize_repo_path(destination)
    if not trash_path or not storage.exists(trash_path):
        raise StorageError("Trash 경로가 존재하지 않습니다.")
    if storage.exists(destination):
        raise StorageError("원래 프로젝트 경로가 이미 존재하여 복구할 수 없습니다.")
    _ensure_directory(storage, str(PurePosixPath(destination).parent))
    storage.move(trash_path, destination, overwrite=False)
