from __future__ import annotations

import re
from pathlib import PurePosixPath

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..models import Project, Release, ReleaseFile
from .smart_upload import choose_latest, choose_primary, is_prerelease


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


def project_release_path(project: Project, version: str, filename: str) -> str:
    return str(PurePosixPath(project.slug) / "releases" / version / PurePosixPath(filename).name)


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
