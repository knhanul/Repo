from __future__ import annotations

from pathlib import PurePosixPath

from .storage import StorageError, normalize_repo_path


def parent_repo_path(path: str) -> str:
    rel = normalize_repo_path(path)
    if not rel:
        return ""
    parent = PurePosixPath(rel).parent.as_posix()
    return "" if parent == "." else normalize_repo_path(parent)


def move_destination(source: str, destination_dir: str) -> str:
    """Build a safe destination path while preserving the source basename.

    This helper also blocks moving a directory into itself or into one of its
    descendants. The storage provider performs the final existence checks.
    """
    src = normalize_repo_path(source)
    dst_dir = normalize_repo_path(destination_dir)
    if not src:
        raise StorageError("Repository 루트는 이동할 수 없습니다.")

    source_name = PurePosixPath(src).name
    if dst_dir == src or (dst_dir and dst_dir.startswith(src + "/")):
        raise StorageError("폴더를 자기 자신 또는 하위 폴더로 이동할 수 없습니다.")

    destination = str(PurePosixPath(dst_dir) / source_name) if dst_dir else source_name
    return normalize_repo_path(destination)
