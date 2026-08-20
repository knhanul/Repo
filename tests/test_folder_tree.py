import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Project, ProjectResource
from app.project_types import ProjectType, ResourceCategory
from app.services.file_tree import move_destination, parent_repo_path
from app.services.project_service import normalize_platforms, normalize_project_type, normalize_source_url, normalize_website_url, project_release_path, project_storage_path
from app.services.storage import StorageError


def test_parent_repo_path():
    assert parent_repo_path("") == ""
    assert parent_repo_path("POSID") == ""
    assert parent_repo_path("POSID/releases/1.5.0") == "POSID/releases"


def test_project_storage_paths_are_grouped_under_projects_root():
    project = Project(slug="nuni-demo")

    assert project_storage_path(project) == "프로젝트/nuni-demo"
    assert project_release_path(project, "0.5.0", "NUNI test.exe") == "프로젝트/nuni-demo/releases/0.5.0/NUNI test.exe"


def test_project_source_url_validation():
    assert normalize_source_url(" https://github.com/nuni/repo ") == "https://github.com/nuni/repo"
    assert normalize_source_url("") is None
    with pytest.raises(ValueError):
        normalize_source_url("javascript:alert(1)")
    with pytest.raises(ValueError):
        normalize_source_url("github.com/nuni/repo")


def test_project_type_platform_and_website_validation():
    assert normalize_project_type("website") == ProjectType.WEB_APP.value
    assert normalize_project_type(ProjectType.MOBILE_APP.value) == ProjectType.MOBILE_APP.value
    assert normalize_platforms(["Windows", "Windows", "Web"]) == ["Windows", "Web"]
    assert normalize_website_url("https://nuni.co.kr/app", ProjectType.WEB_APP.value) == "https://nuni.co.kr/app"
    assert normalize_website_url("", ProjectType.WINDOWS_APP.value) is None
    with pytest.raises(ValueError):
        normalize_project_type("desktop")
    with pytest.raises(ValueError):
        normalize_platforms(["DOS"])
    with pytest.raises(ValueError):
        normalize_website_url("", ProjectType.WEB_APP.value)
    with pytest.raises(ValueError):
        normalize_website_url("javascript:alert(1)", ProjectType.WEB_APP.value)


def test_project_type_platform_and_resource_persist():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        project = Project(name="NUNI Demo", slug="nuni-demo", project_type=ProjectType.OTHER.value, platforms=["Linux"])
        db.add(project)
        db.commit()
        loaded = db.query(Project).filter_by(slug="nuni-demo").one()
        assert loaded.project_type == "OTHER"
        assert loaded.platforms == ["Linux"]

        resource = ProjectResource(
            project=loaded,
            category=ResourceCategory.DOCUMENT.value,
            title="사용자 설명서",
            original_filename="manual.pdf",
            storage_path="프로젝트/nuni-demo/resources/document/manual.pdf",
            file_size=123,
            sha256="a" * 64,
        )
        db.add(resource)
        db.commit()
        assert db.query(ProjectResource).one().project_id == loaded.id


def test_move_destination_preserves_basename():
    assert move_destination("POSID/readme.md", "docs") == "docs/readme.md"
    assert move_destination("POSID/releases", "Archive") == "Archive/releases"
    assert move_destination("a.txt", "") == "a.txt"


def test_move_directory_into_descendant_is_rejected():
    with pytest.raises(StorageError):
        move_destination("POSID", "POSID/releases")
    with pytest.raises(StorageError):
        move_destination("POSID/releases", "POSID/releases")
