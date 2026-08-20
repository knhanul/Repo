from __future__ import annotations

from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import BinaryIO, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Project, ProjectResource
from ..project_types import RESOURCE_CATEGORY_LABELS
from .project_service import project_storage_path
from .storage import StorageError, StorageProvider, normalize_repo_path
from .trash_service import move_to_trash, restore_from_trash


class ProjectResourceError(RuntimeError):
    pass


class DuplicateProjectResourceError(ProjectResourceError):
    pass


def normalize_resource_category(category: str) -> str:
    value = (category or "").strip().upper()
    if value not in RESOURCE_CATEGORY_LABELS:
        raise ProjectResourceError("지원하지 않는 자료 분류입니다.")
    return value


def resource_storage_path(project: Project, category: str, filename: str) -> str:
    category = normalize_resource_category(category)
    safe_name = PurePosixPath((filename or "").replace("\\", "/")).name.strip()
    if not safe_name or safe_name in {".", ".."}:
        raise ProjectResourceError("잘못된 자료 파일명입니다.")
    return normalize_repo_path(str(PurePosixPath(project_storage_path(project)) / "resources" / category.lower() / safe_name))


def default_resource_title(filename: str) -> str:
    return PurePosixPath(filename).stem or filename


class ProjectResourceService:
    def __init__(self, db: Session, storage: StorageProvider):
        self.db = db
        self.storage = storage

    def list(self, project_id: int, category: str | None = None) -> list[ProjectResource]:
        statement = select(ProjectResource).where(ProjectResource.project_id == project_id, ProjectResource.is_deleted.is_(False))
        if category:
            statement = statement.where(ProjectResource.category == normalize_resource_category(category))
        statement = statement.order_by(ProjectResource.created_at.desc(), ProjectResource.id.desc())
        return list(self.db.scalars(statement).all())

    def counts(self, project_id: int) -> dict[str, int]:
        items = self.list(project_id)
        counts = {category: 0 for category in RESOURCE_CATEGORY_LABELS}
        for item in items:
            if item.category in counts:
                counts[item.category] += 1
        return counts

    def duplicates(self, project_id: int, category: str, filenames: list[str]) -> list[ProjectResource]:
        category = normalize_resource_category(category)
        if not filenames:
            return []
        return list(self.db.scalars(select(ProjectResource).where(
            ProjectResource.project_id == project_id,
            ProjectResource.category == category,
            ProjectResource.original_filename.in_(filenames),
            ProjectResource.is_deleted.is_(False),
        )).all())

    def save(
        self,
        project: Project,
        user_id: int | None,
        category: str,
        filename: str,
        title: str | None,
        description: str | None,
        stream: BinaryIO,
        file_size: int,
        mime_type: str | None,
        sha256: str,
        overwrite: bool = False,
    ) -> ProjectResource:
        category = normalize_resource_category(category)
        existing = self.db.scalar(select(ProjectResource).where(
            ProjectResource.project_id == project.id,
            ProjectResource.category == category,
            ProjectResource.original_filename == filename,
        ))
        if existing and not existing.is_deleted and not overwrite:
            raise DuplicateProjectResourceError(f"동일한 이름의 자료가 이미 존재합니다: {filename}")
        path = resource_storage_path(project, category, filename)
        old_trash_path = existing.trash_path if existing and existing.is_deleted else None
        stream.seek(0)
        self.storage.write_stream(path, stream, mime_type or "application/octet-stream")
        clean_title = (title or "").strip() or default_resource_title(filename)
        if existing:
            existing.title = clean_title[:300]
            existing.description = (description or "").strip() or None
            existing.storage_path = path
            existing.file_size = file_size
            existing.mime_type = mime_type
            existing.sha256 = sha256
            existing.created_by_id = user_id
            existing.is_deleted = False
            existing.deleted_at = None
            existing.deleted_by_id = None
            existing.trash_path = None
            resource = existing
        else:
            resource = ProjectResource(
                project_id=project.id,
                category=category,
                title=clean_title[:300],
                description=(description or "").strip() or None,
                original_filename=filename,
                storage_path=path,
                file_size=file_size,
                mime_type=mime_type,
                sha256=sha256,
                created_by_id=user_id,
            )
            self.db.add(resource)
        if old_trash_path:
            try:
                self.storage.delete(old_trash_path)
            except StorageError:
                pass
        self.db.flush()
        return resource

    def get(self, project_id: int, resource_id: int) -> ProjectResource:
        resource = self.db.scalar(select(ProjectResource).join(Project).where(
            ProjectResource.id == resource_id,
            ProjectResource.project_id == project_id,
            ProjectResource.is_deleted.is_(False),
            Project.is_deleted.is_(False),
        ))
        if not resource:
            raise ProjectResourceError("프로젝트 자료를 찾을 수 없습니다.")
        return resource

    def delete(self, resource: ProjectResource, user_id: int | None) -> tuple[str, str]:
        original_path = resource.storage_path
        trash_path = move_to_trash(self.storage, original_path, "resources", str(resource.id), resource.original_filename)
        resource.is_deleted = True
        resource.deleted_at = datetime.now(timezone.utc)
        resource.deleted_by_id = user_id
        resource.trash_path = trash_path
        self.db.flush()
        return original_path, trash_path

    def delete_with_compensation(
        self,
        resource: ProjectResource,
        user_id: int | None,
        audit: Callable[[str, str], None] | None = None,
    ) -> tuple[str, str]:
        original_path, trash_path = self.delete(resource, user_id)
        if audit:
            audit(original_path, trash_path)
        try:
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            try:
                restore_from_trash(self.storage, trash_path, original_path)
            except Exception as rollback_exc:
                raise ProjectResourceError("자료 삭제와 Storage rollback이 모두 실패했습니다.") from rollback_exc
            raise ProjectResourceError("자료 삭제 DB commit이 실패했습니다.") from exc
        return original_path, trash_path

    def get_deleted(self, project_id: int, resource_id: int) -> ProjectResource:
        resource = self.db.scalar(select(ProjectResource).where(
            ProjectResource.id == resource_id,
            ProjectResource.project_id == project_id,
            ProjectResource.is_deleted.is_(True),
        ))
        if not resource:
            raise ProjectResourceError("삭제된 프로젝트 자료를 찾을 수 없습니다.")
        return resource

    def restore(self, resource: ProjectResource) -> tuple[str, str]:
        if not resource.trash_path:
            raise ProjectResourceError("자료 Trash 경로가 없습니다.")
        original_path = resource.storage_path
        restore_from_trash(self.storage, resource.trash_path, original_path)
        trash_path = resource.trash_path
        resource.is_deleted = False
        resource.deleted_at = None
        resource.deleted_by_id = None
        resource.trash_path = None
        self.db.flush()
        return original_path, trash_path
