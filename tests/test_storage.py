from io import BytesIO

import pytest

from app.services.storage import LocalStorageProvider, StorageError, WebDavStorageProvider, normalize_repo_path


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

    for path in ("%2e%2e/secret", "%252e%252e/secret", "../secret"):
        with pytest.raises(StorageError):
            normalize_repo_path(path)


def test_webdav_url_encodes_unicode_once():
    provider = WebDavStorageProvider("http://nas/dav/VOL1/Repo", "user", "password")

    url = provider._url("구내식당/파일 이름 (최종).zip")

    assert url == "http://nas/dav/VOL1/Repo/%EA%B5%AC%EB%82%B4%EC%8B%9D%EB%8B%B9/%ED%8C%8C%EC%9D%BC%20%EC%9D%B4%EB%A6%84%20%28%EC%B5%9C%EC%A2%85%29.zip"
    assert "%25" not in url
    assert provider._url("%EA%B5%AC%EB%82%B4%EC%8B%9D%EB%8B%B9") == provider._url("구내식당")


class _FakeResponse:
    def __init__(self, status_code=200, content=b""):
        self.status_code = status_code
        self.content = content


class _FakeWebDavClient:
    def __init__(self, response=None):
        self.calls = []
        self.response = response or _FakeResponse()

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if method in ("MKCOL", "MOVE"):
            return _FakeResponse(201)
        return self.response

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def put(self, url, **kwargs):
        return self.request("PUT", url, **kwargs)

    def delete(self, url, **kwargs):
        return self.request("DELETE", url, **kwargs)


def test_webdav_propfind_decodes_href_and_parses_metadata():
    xml = b"""<?xml version="1.0" encoding="utf-8"?>
    <d:multistatus xmlns:d="DAV:">
      <d:response><d:href>/dav/VOL1/Repo/</d:href><d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype></d:prop></d:propstat></d:response>
      <d:response><d:href>/dav/VOL1/Repo/%EA%B5%AC%EB%82%B4%EC%8B%9D%EB%8B%B9/</d:href><d:propstat><d:prop><d:displayname>%EA%B5%AC%EB%82%B4%EC%8B%9D%EB%8B%B9</d:displayname><d:resourcetype><d:collection/></d:resourcetype><d:getlastmodified>Wed, 19 Aug 2026 10:20:30 GMT</d:getlastmodified></d:prop></d:propstat></d:response>
      <d:response><d:href>/dav/VOL1/Repo/NUNI%20v0.5.0.exe</d:href><d:propstat><d:prop><d:getcontentlength>1234</d:getcontentlength><d:getlastmodified>Wed, 19 Aug 2026 10:21:30 GMT</d:getlastmodified><d:getcontenttype>application/octet-stream</d:getcontenttype><d:resourcetype/></d:prop></d:propstat></d:response>
    </d:multistatus>"""
    client = _FakeWebDavClient(_FakeResponse(207, xml))
    provider = WebDavStorageProvider("http://nas/dav/VOL1/Repo", "user", "password")
    provider.client = client

    entries = provider.list()

    assert [entry.name for entry in entries] == ["구내식당", "NUNI v0.5.0.exe"]
    assert [entry.path for entry in entries] == ["구내식당", "NUNI v0.5.0.exe"]
    assert entries[0].modified_at is not None
    assert entries[1].size == 1234
    assert entries[1].modified_at is not None
    assert client.calls[0][1] == "http://nas/dav/VOL1/Repo/"


def test_webdav_operations_share_encoded_path_boundary():
    client = _FakeWebDavClient(_FakeResponse(200, b"data"))
    provider = WebDavStorageProvider("http://nas/dav/VOL1/Repo", "user", "password")
    provider.client = client

    provider.mkdir("구내식당")
    provider.write_stream("구내식당/test file.txt", BytesIO(b"data"))
    assert provider.read_bytes("구내식당/test file.txt") == b"data"
    provider.delete("구내식당/test file.txt")
    provider.move("구내식당/old.txt", "구내식당/new file.txt")

    urls = [call[1] for call in client.calls]
    assert urls == [
        "http://nas/dav/VOL1/Repo/%EA%B5%AC%EB%82%B4%EC%8B%9D%EB%8B%B9",
        "http://nas/dav/VOL1/Repo/%EA%B5%AC%EB%82%B4%EC%8B%9D%EB%8B%B9/test%20file.txt",
        "http://nas/dav/VOL1/Repo/%EA%B5%AC%EB%82%B4%EC%8B%9D%EB%8B%B9/test%20file.txt",
        "http://nas/dav/VOL1/Repo/%EA%B5%AC%EB%82%B4%EC%8B%9D%EB%8B%B9/test%20file.txt",
        "http://nas/dav/VOL1/Repo/%EA%B5%AC%EB%82%B4%EC%8B%9D%EB%8B%B9/old.txt",
    ]
    assert client.calls[-1][2]["headers"]["Destination"] == "http://nas/dav/VOL1/Repo/%EA%B5%AC%EB%82%B4%EC%8B%9D%EB%8B%B9/new%20file.txt"
