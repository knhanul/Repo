from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Project
from .project_service import project_storage_path, resolve_project_storage_root
from .storage import StorageProvider
from .trash_service import move_to_trash, restore_from_trash


class ProjectLifecycleError(RuntimeError):
    pass


def get_deleted_project(db: Session, project_id: int) -> Project | None:
    return db.scalar(select(Project).where(Project.id == project_id, Project.is_deleted.is_(True)))


def trash_project(project: Project, storage: StorageProvider) -> str | None:
    source = resolve_project_storage_root(project, storage)
    if not source:
        return None
    project.storage_root = source
    return move_to_trash(storage, source, "projects", str(project.id), project.slug)


def restore_project(project: Project, storage: StorageProvider) -> None:
    if not project.trash_path:
        return
    restore_from_trash(storage, project.trash_path, project_storage_path(project))


def mark_project_deleted(project: Project, user_id: int, trash_path: str) -> None:
    project.is_deleted = True
    project.deleted_at = datetime.now(timezone.utc)
    project.deleted_by_id = user_id
    project.trash_path = trash_path


def mark_project_restored(project: Project) -> None:
    project.is_deleted = False
    project.deleted_at = None
    project.deleted_by_id = None
    project.trash_path = None


def delete_project_with_compensation(
    db: Session,
    project: Project,
    user_id: int,
    storage: StorageProvider,
    audit: Callable[[], None] | None = None,
) -> str | None:
    original_path = project_storage_path(project)
    trash_path = trash_project(project, storage)
    if trash_path:
        original_path = project_storage_path(project)
    mark_project_deleted(project, user_id, trash_path)
    if audit:
        audit()
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        if trash_path:
            try:
                restore_from_trash(storage, trash_path, original_path)
            except Exception as rollback_exc:
                raise ProjectLifecycleError("프로젝트 삭제와 Storage rollback이 모두 실패했습니다.") from rollback_exc
        raise ProjectLifecycleError("프로젝트 삭제 DB commit이 실패했습니다.") from exc
    return trash_path


def restore_project_with_compensation(
    db: Session,
    project: Project,
    user_id: int,
    storage: StorageProvider,
    audit: Callable[[], None] | None = None,
) -> None:
    original_trash_path = project.trash_path
    original_path = project_storage_path(project)
    restore_project(project, storage)
    mark_project_restored(project)
    if audit:
        audit()
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        if original_trash_path:
            try:
                storage.move(original_path, original_trash_path, overwrite=False)
            except Exception as rollback_exc:
                raise ProjectLifecycleError("프로젝트 복구와 Storage rollback이 모두 실패했습니다.") from rollback_exc
        raise ProjectLifecycleError("프로젝트 복구 DB commit이 실패했습니다.") from exc
