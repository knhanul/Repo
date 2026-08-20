from __future__ import annotations

import re
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..models import Project, Release, ReleaseFile
from ..project_types import LEGACY_OUTPUT_TYPE_MAP, PROJECT_TYPE_LABELS, SUPPORTED_PLATFORMS, ProjectType
from .smart_upload import choose_latest, choose_primary, is_prerelease
from .storage import normalize_repo_path


PROJECTS_ROOT = "프로젝트"


def slugify(name: str) -> str:
    value = name.strip().lower()
    value = re.sub(r"[^0-9a-zA-Z가-힣._-]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-._")
    return value or "project"


def unique_slug(db: Session, name: str) -> str:
    base = slugify(name)
    slug = base
    idx = 2
    while db.scalar(select(Project).where(Project.slug == slug)):
        slug = f"{base}-{idx}"
        idx += 1
    return slug


def normalize_project_type(value: str | None) -> str:
    project_type = (value or ProjectType.OTHER.value).strip()
    project_type = LEGACY_OUTPUT_TYPE_MAP.get(project_type, project_type)
    if project_type not in PROJECT_TYPE_LABELS:
        raise ValueError("지원하지 않는 프로젝트 유형입니다.")
    return project_type


def normalize_platforms(values: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for value in values or []:
        platform = value.strip()
        if platform not in SUPPORTED_PLATFORMS:
            raise ValueError("지원하지 않는 플랫폼입니다.")
        if platform not in normalized:
            normalized.append(platform)
    return normalized


def normalize_source_url(value: str | None) -> str | None:
    source_url = (value or "").strip()
    if not source_url:
        return None
    parsed = urlsplit(source_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Git 소스 링크는 http:// 또는 https:// URL이어야 합니다.")
    return source_url


def normalize_website_url(value: str | None, project_type: str) -> str | None:
    website_url = (value or "").strip()
    if not website_url:
        if project_type == ProjectType.WEB_APP.value:
            raise ValueError("웹사이트 프로젝트는 웹사이트 주소를 입력해야 합니다.")
        return None
    parsed = urlsplit(website_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("웹사이트 주소는 http:// 또는 https:// URL이어야 합니다.")
    return website_url


def get_active_project(db: Session, project_id: int) -> Project | None:
    return db.scalar(select(Project).where(Project.id == project_id, Project.is_deleted.is_(False)))


def project_storage_path(project: Project) -> str:
    return project.storage_root or str(PurePosixPath(PROJECTS_ROOT) / project.slug)


def resolve_project_storage_root(project: Project, storage) -> str | None:
    candidates = [project.storage_root, str(PurePosixPath(PROJECTS_ROOT) / project.slug), project.slug]
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate:
            continue
        normalized = normalize_repo_path(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        if storage.exists(normalized):
            return normalized
    return None


def project_release_path(project: Project, version: str, filename: str) -> str:
    return str(PurePosixPath(project_storage_path(project)) / "releases" / version / PurePosixPath(filename).name)


def ensure_release(db: Session, project: Project, version: str, user_id: int | None, notes: str | None = None) -> Release:
    release = db.scalar(select(Release).where(Release.project_id == project.id, Release.version == version))
    if release:
        if notes and not release.release_notes:
            release.release_notes = notes
        return release
    release = Release(
        project_id=project.id,
        version=version,
        release_notes=notes or None,
        created_by_id=user_id,
        is_prerelease=is_prerelease(version),
    )
    db.add(release)
    db.flush()
    return release


def refresh_latest_flags(db: Session, project_id: int) -> None:
    releases = list(db.scalars(select(Release).where(Release.project_id == project_id)).all())
    if not releases:
        return
    latest = choose_latest([r.version for r in releases])
    db.execute(update(Release).where(Release.project_id == project_id).values(is_latest=False))
    for r in releases:
        if r.version == latest:
            r.is_latest = True


def refresh_primary_file(release: Release) -> None:
    if not release.files:
        return
    if any(f.is_primary_download for f in release.files):
        return
    chosen = choose_primary([(f.original_filename, f.file_type) for f in release.files])
    for f in release.files:
        f.is_primary_download = (f.original_filename == chosen)
