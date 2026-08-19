import pytest

from app.models import Project
from app.services.file_tree import move_destination, parent_repo_path
from app.services.project_service import normalize_output_type, normalize_source_url, normalize_website_url, project_release_path, project_storage_path
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


def test_project_output_type_and_website_url_validation():
    assert normalize_output_type("website") == "website"
    assert normalize_website_url("https://nuni.co.kr/app", "website") == "https://nuni.co.kr/app"
    assert normalize_website_url("", "windows_app") is None
    with pytest.raises(ValueError):
        normalize_output_type("desktop")
    with pytest.raises(ValueError):
        normalize_website_url("", "website")
    with pytest.raises(ValueError):
        normalize_website_url("javascript:alert(1)", "website")


def test_move_destination_preserves_basename():
    assert move_destination("POSID/readme.md", "docs") == "docs/readme.md"
    assert move_destination("POSID/releases", "Archive") == "Archive/releases"
    assert move_destination("a.txt", "") == "a.txt"


def test_move_directory_into_descendant_is_rejected():
    with pytest.raises(StorageError):
        move_destination("POSID", "POSID/releases")
    with pytest.raises(StorageError):
        move_destination("POSID/releases", "POSID/releases")
