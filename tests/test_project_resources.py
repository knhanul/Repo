from io import BytesIO

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Project
from app.project_types import ResourceCategory
from app.services.project_resource_service import DuplicateProjectResourceError, ProjectResourceError, ProjectResourceService, resource_storage_path
from app.services.storage import LocalStorageProvider, WebDavStorageProvider


def test_project_resource_local_round_trip_and_filter(tmp_path):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    storage = LocalStorageProvider(str(tmp_path / "storage"))
    with Session(engine) as db:
        project = Project(name="자료 프로젝트", slug="resource-project")
        db.add(project)
        db.commit()
        service = ProjectResourceService(db, storage)

        resource = service.save(
            project,
            None,
            ResourceCategory.HELP.value,
            "사용자 매뉴얼 (최종).pdf",
            "사용자 매뉴얼",
            "설치 및 기본 사용 방법",
            BytesIO("도움말 내용".encode()),
            19,
            "application/pdf",
            "a" * 64,
        )
        db.commit()

        assert resource.storage_path == "프로젝트/resource-project/resources/help/사용자 매뉴얼 (최종).pdf"
        assert storage.read_bytes(resource.storage_path) == "도움말 내용".encode()
        assert [item.id for item in service.list(project.id, "HELP")] == [resource.id]
        assert service.counts(project.id)[ResourceCategory.HELP.value] == 1
        assert service.list(project.id, "REPORT") == []


def test_project_resource_duplicate_requires_explicit_replace(tmp_path):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    storage = LocalStorageProvider(str(tmp_path / "storage"))
    with Session(engine) as db:
        project = Project(name="Duplicate Project", slug="duplicate-project")
        db.add(project)
        db.commit()
        service = ProjectResourceService(db, storage)
        kwargs = dict(
            project=project,
            user_id=None,
            category=ResourceCategory.REPORT.value,
            filename="report.xlsx",
            title="보고서",
            description=None,
            file_size=3,
            mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            sha256="b" * 64,
        )
        service.save(stream=BytesIO(b"old"), overwrite=False, **kwargs)
        db.commit()
        with pytest.raises(DuplicateProjectResourceError):
            service.save(stream=BytesIO(b"new"), overwrite=False, **kwargs)
        replacement_kwargs = {**kwargs, "sha256": "c" * 64}
        replacement = service.save(stream=BytesIO(b"new"), overwrite=True, **replacement_kwargs)
        db.commit()

        assert replacement.sha256 == "c" * 64
        assert storage.read_bytes(replacement.storage_path) == b"new"


def test_deleted_project_resources_are_not_accessible(tmp_path):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    storage = LocalStorageProvider(str(tmp_path / "storage"))
    with Session(engine) as db:
        project = Project(name="Deleted Parent", slug="deleted-parent", is_deleted=True)
        db.add(project)
        db.flush()
        service = ProjectResourceService(db, storage)
        resource = service.save(project, None, ResourceCategory.HELP.value, "manual.pdf", "Manual", None, BytesIO(b"manual"), 6, "application/pdf", "a" * 64)
        db.commit()
        with pytest.raises(ProjectResourceError):
            service.get(project.id, resource.id)


def test_deleted_resource_can_be_reused_without_duplicate_conflict(tmp_path):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    storage = LocalStorageProvider(str(tmp_path / "storage"))
    with Session(engine) as db:
        project = Project(name="Reuse Project", slug="reuse-project")
        db.add(project)
        db.commit()
        service = ProjectResourceService(db, storage)
        resource = service.save(project, None, ResourceCategory.HELP.value, "manual.pdf", "Manual", None, BytesIO(b"old"), 3, "application/pdf", "a" * 64)
        db.commit()
        service.delete(resource, None)
        db.commit()

        replacement = service.save(project, None, ResourceCategory.HELP.value, "manual.pdf", "New Manual", None, BytesIO(b"new"), 3, "application/pdf", "b" * 64)
        db.commit()

        assert replacement.id == resource.id
        assert not replacement.is_deleted
        assert replacement.trash_path is None
        assert storage.read_bytes(replacement.storage_path) == b"new"
        assert len(service.list(project.id)) == 1


def test_project_resource_delete_removes_storage_and_metadata(tmp_path):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    storage = LocalStorageProvider(str(tmp_path / "storage"))
    with Session(engine) as db:
        project = Project(name="Delete Project", slug="delete-project")
        db.add(project)
        db.commit()
        service = ProjectResourceService(db, storage)
        resource = service.save(project, None, ResourceCategory.SAMPLE.value, "sample.txt", None, None, BytesIO(b"sample"), 6, "text/plain", "d" * 64)
        db.commit()
        path = resource.storage_path
        original, trash_path = service.delete(resource, None)
        db.commit()

        assert original == path
        assert resource.is_deleted
        assert resource.trash_path == trash_path
        assert not storage.exists(path)
        assert storage.exists(trash_path)
        assert service.list(project.id) == []


def test_resource_path_is_encoded_once_for_webdav():
    path = resource_storage_path(Project(slug="resource-project"), ResourceCategory.HELP.value, "식단 샘플 (최종).xlsx")
    provider = WebDavStorageProvider("http://nas/dav/VOL1/Repo", "user", "password")

    url = provider._url(path)

    assert "%25" not in url
    assert "%EC%8B%9D" in url
    assert "%20" in url
    assert "%28" in url
