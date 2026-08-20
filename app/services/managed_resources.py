from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Project
from .project_service import project_storage_path
from .storage import normalize_repo_path


def managed_project_roots(db: Session) -> dict[str, Project]:
    projects = db.scalars(select(Project).where(Project.is_deleted.is_(False))).all()
    roots: dict[str, Project] = {}
    for project in projects:
        roots[project_storage_path(project)] = project
        if project.storage_root is None:
            roots[project.slug] = project
    return roots


def managed_project_for_path(db: Session, path: str) -> Project | None:
    normalized = normalize_repo_path(path)
    if not normalized:
        return None
    for root, project in managed_project_roots(db).items():
        if normalized == root or normalized.startswith(root + "/"):
            return project
    return None


def is_managed_path_from_roots(path: str, roots: dict[str, Project]) -> bool:
    normalized = normalize_repo_path(path)
    return any(normalized == root or normalized.startswith(root + "/") for root in roots)


def is_managed_project_path(db: Session, path: str) -> bool:
    return managed_project_for_path(db, path) is not None


def is_trash_path(path: str) -> bool:
    normalized = normalize_repo_path(path)
    return normalized == "_trash" or normalized.startswith("_trash/")


def is_protected_storage_path(db: Session, path: str) -> bool:
    return is_trash_path(path) or is_managed_project_path(db, path)
