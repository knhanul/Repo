import pytest

from app.services.file_tree import move_destination, parent_repo_path
from app.services.storage import StorageError


def test_parent_repo_path():
    assert parent_repo_path("") == ""
    assert parent_repo_path("POSID") == ""
    assert parent_repo_path("POSID/releases/1.5.0") == "POSID/releases"


def test_move_destination_preserves_basename():
    assert move_destination("POSID/readme.md", "docs") == "docs/readme.md"
    assert move_destination("POSID/releases", "Archive") == "Archive/releases"
    assert move_destination("a.txt", "") == "a.txt"


def test_move_directory_into_descendant_is_rejected():
    with pytest.raises(StorageError):
        move_destination("POSID", "POSID/releases")
    with pytest.raises(StorageError):
        move_destination("POSID/releases", "POSID/releases")
