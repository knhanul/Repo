from io import BytesIO
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Project, ProjectResource
from app.project_types import ResourceCategory
from app.services.managed_resources import is_managed_project_path, is_protected_storage_path, managed_project_for_path
from app.services.project_lifecycle import ProjectLifecycleError, delete_project_with_compensation, mark_project_deleted, restore_project_with_compensation
from app.services.project_resource_service import ProjectResourceError, ProjectResourceService
from app.services.project_service import project_storage_path
from app.services.storage import LocalStorageProvider, WebDavStorageProvider
from app.services.trash_service import move_to_trash, restore_from_trash


def test_managed_path_uses_project_path_segments(tmp_path):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    storage = LocalStorageProvider(str(tmp_path / "storage"))
    with Session(engine) as db:
        project = Project(name="Meal", slug="meal")
        db.add(project)
        db.commit()

        assert is_managed_project_path(db, "프로젝트/meal")
        assert is_managed_project_path(db, "프로젝트/meal/releases/0.5.0/app.exe")
        assert not is_managed_project_path(db, "프로젝트/meal-old/file.txt")
        assert is_protected_storage_path(db, "_trash/projects/1-meal")
        assert managed_project_for_path(db, "프로젝트/meal") is project


def test_trash_move_and_restore_preserves_project_storage_root(tmp_path):
    storage = LocalStorageProvider(str(tmp_path / "storage"))
    original = "프로젝트/meal/resources/help/manual.pdf"
    storage.write_stream(original, BytesIO(b"manual"), "application/pdf")

    trash_path = move_to_trash(storage, "프로젝트/meal", "projects", "1", "meal")

    assert not storage.exists("프로젝트/meal")
    assert storage.read_bytes(f"{trash_path}/resources/help/manual.pdf") == b"manual"
    restore_from_trash(storage, trash_path, "프로젝트/meal")
    assert storage.read_bytes(original) == b"manual"
    assert project_storage_path(Project(slug="meal")) == "프로젝트/meal"


def test_webdav_trash_move_encodes_unicode_once():
    class Response:
        def __init__(self, status_code):
            self.status_code = status_code

    class Client:
        def __init__(self):
            self.calls = []
            self.propfind_count = 0

        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            if method == "PROPFIND":
                self.propfind_count += 1
                return Response(207 if self.propfind_count == 1 else 404)
            return Response(201)

    provider = WebDavStorageProvider("http://nas/dav/VOL1/Repo", "user", "password")
    client = Client()
    provider.client = client

    trash_path = move_to_trash(provider, "프로젝트/meal/resources/help/사용자 매뉴얼.pdf", "resources", "7", "사용자 매뉴얼.pdf")

    move_call = next(call for call in client.calls if call[0] == "MOVE")
    assert "%25" not in move_call[1]
    assert "%EC%82%AC" in move_call[1]
    assert "%20" in move_call[2]["headers"]["Destination"]
    assert trash_path.startswith("_trash/resources/7-")


def test_project_delete_uses_legacy_slug_root_and_restores_it(tmp_path):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    storage = LocalStorageProvider(str(tmp_path / "storage"))
    with Session(engine) as db:
        project = Project(name="Legacy Project", slug="legacy-project")
        db.add(project)
        db.commit()
        storage.write_stream("legacy-project/README.md", BytesIO(b"legacy"), "text/markdown")

        trash_path = delete_project_with_compensation(db, project, 1, storage)
        db.refresh(project)
        assert project.is_deleted
        assert project.storage_root == "legacy-project"
        assert project.trash_path == trash_path
        assert not storage.exists("legacy-project")

        restore_project_with_compensation(db, project, 1, storage)
        db.refresh(project)
        assert not project.is_deleted
        assert project.trash_path is None
        assert storage.read_bytes("legacy-project/README.md") == b"legacy"


def test_project_delete_without_storage_root_soft_deletes_metadata_only(tmp_path):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    storage = LocalStorageProvider(str(tmp_path / "storage"))
    with Session(engine) as db:
        project = Project(name="Missing Root", slug="missing-root")
        db.add(project)
        db.commit()

        assert delete_project_with_compensation(db, project, 1, storage) is None
        db.refresh(project)
        assert project.is_deleted
        assert project.trash_path is None

        restore_project_with_compensation(db, project, 1, storage)
        db.refresh(project)
        assert not project.is_deleted


def test_project_delete_commit_failure_rolls_back_storage_and_metadata(tmp_path):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    storage = LocalStorageProvider(str(tmp_path / "storage"))
    with Session(engine) as db:
        project = Project(name="Delete Failure", slug="delete-failure")
        db.add(project)
        db.commit()
        original = project_storage_path(project)
        storage.write_stream(f"{original}/README.md", BytesIO(b"readme"), "text/markdown")

        with patch.object(Session, "commit", side_effect=RuntimeError("forced commit failure")):
            with pytest.raises(ProjectLifecycleError):
                delete_project_with_compensation(db, project, 1, storage)

        db.refresh(project)
        assert project.is_deleted is False
        assert project.trash_path is None
        assert storage.read_bytes(f"{original}/README.md") == b"readme"


def test_project_restore_commit_failure_rolls_back_to_trash(tmp_path):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    storage = LocalStorageProvider(str(tmp_path / "storage"))
    with Session(engine) as db:
        project = Project(name="Restore Failure", slug="restore-failure")
        db.add(project)
        db.commit()
        original = project_storage_path(project)
        storage.write_stream(f"{original}/README.md", BytesIO(b"readme"), "text/markdown")
        trash_path = move_to_trash(storage, original, "projects", str(project.id), project.slug)
        mark_project_deleted(project, 1, trash_path)
        db.commit()

        with patch.object(Session, "commit", side_effect=RuntimeError("forced commit failure")):
            with pytest.raises(ProjectLifecycleError):
                restore_project_with_compensation(db, project, 1, storage)

        db.refresh(project)
        assert project.is_deleted is True
        assert project.trash_path == trash_path
        assert not storage.exists(original)
        assert storage.read_bytes(f"{trash_path}/README.md") == b"readme"


def test_resource_delete_commit_failure_rolls_back_storage_and_metadata(tmp_path):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    storage = LocalStorageProvider(str(tmp_path / "storage"))
    with Session(engine) as db:
        project = Project(name="Resource Failure", slug="resource-failure")
        db.add(project)
        db.commit()
        service = ProjectResourceService(db, storage)
        resource = service.save(project, 1, ResourceCategory.HELP.value, "manual.pdf", "Manual", None, BytesIO(b"manual"), 6, "application/pdf", "a" * 64)
        db.commit()
        original = resource.storage_path

        with patch.object(Session, "commit", side_effect=RuntimeError("forced commit failure")):
            with pytest.raises(ProjectResourceError):
                service.delete_with_compensation(resource, 1)

        db.refresh(resource)
        assert resource.is_deleted is False
        assert resource.trash_path is None
        assert storage.read_bytes(original) == b"manual"


def test_webdav_move_failure_does_not_change_project_storage_or_metadata(tmp_path):
    class Client:
        def __init__(self):
            self.propfind_count = 0

        def request(self, method, url, **kwargs):
            if method == "PROPFIND":
                self.propfind_count += 1
                return type("Response", (), {"status_code": 207 if self.propfind_count == 1 else 404})()
            raise RuntimeError("forced MOVE failure")

    provider = WebDavStorageProvider("http://nas/dav/VOL1/Repo", "user", "password")
    provider.client = Client()
    with pytest.raises(RuntimeError):
        move_to_trash(provider, "프로젝트/failure", "projects", "1", "failure")
