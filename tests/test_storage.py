from io import BytesIO

import pytest

from app.services.storage import LocalStorageProvider, StorageError, normalize_repo_path


def test_local_storage_round_trip(tmp_path):
    s = LocalStorageProvider(str(tmp_path))
    s.mkdir("업무자료")
    s.write_stream("업무자료/회의자료 최종본.txt", BytesIO("hello".encode()))
    assert s.exists("업무자료/회의자료 최종본.txt")
    assert s.read_bytes("업무자료/회의자료 최종본.txt") == b"hello"
    entries = s.list("업무자료")
    assert [e.name for e in entries] == ["회의자료 최종본.txt"]
    s.move("업무자료/회의자료 최종본.txt", "업무자료/회의자료.txt")
    assert s.exists("업무자료/회의자료.txt")
    s.delete("업무자료/회의자료.txt")
    s.delete("업무자료")


def test_path_normalization():
    assert normalize_repo_path("/A\\B/file.txt") == "A/B/file.txt"
    assert normalize_repo_path("") == ""


def test_cannot_escape_root(tmp_path):
    s = LocalStorageProvider(str(tmp_path))
    # normalize_repo_path collapses traversal into the repository namespace,
    # while the final resolver additionally enforces root containment.
    with pytest.raises(StorageError):
        s._resolve("../../../../etc/passwd")
