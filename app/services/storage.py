from __future__ import annotations

import io
import mimetypes
import posixpath
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import BinaryIO
from urllib.parse import quote, unquote, urlsplit

import httpx

from ..config import settings


class StorageError(RuntimeError):
    pass


@dataclass(slots=True)
class StorageEntry:
    name: str
    path: str
    is_dir: bool
    size: int | None = None
    modified_at: datetime | None = None
    mime_type: str | None = None


class StorageProvider(ABC):
    @abstractmethod
    def list(self, path: str = "") -> list[StorageEntry]: ...

    @abstractmethod
    def exists(self, path: str) -> bool: ...

    @abstractmethod
    def mkdir(self, path: str) -> None: ...

    @abstractmethod
    def write_stream(self, path: str, stream: BinaryIO, content_type: str | None = None) -> None: ...

    @abstractmethod
    def read_bytes(self, path: str) -> bytes: ...

    @abstractmethod
    def delete(self, path: str) -> None: ...

    @abstractmethod
    def move(self, source: str, destination: str, overwrite: bool = False) -> None: ...


def _decode_path(value: str) -> str:
    decoded = value or ""
    for _ in range(3):
        next_value = unquote(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    return decoded


def normalize_repo_path(path: str) -> str:
    path = _decode_path(path).replace("\\", "/").strip()
    raw_parts = [part for part in path.split("/") if part not in ("", ".")]
    if ".." in raw_parts:
        raise StorageError("Repository root 밖의 경로는 사용할 수 없습니다.")
    while path.startswith("/"):
        path = path[1:]
    normalized = posixpath.normpath("/" + path).lstrip("/")
    if normalized in (".", ""):
        return ""
    if normalized.startswith("../") or normalized == "..":
        raise StorageError("Repository root 밖의 경로는 사용할 수 없습니다.")
    return normalized


def _href_name(href: str) -> str:
    path = _decode_path(urlsplit(href).path)
    return posixpath.basename(path.rstrip("/"))


def _parse_http_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class LocalStorageProvider(StorageProvider):
    def __init__(self, root: str):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, path: str) -> Path:
        rel = normalize_repo_path(path)
        candidate = (self.root / rel).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise StorageError("Repository root 밖의 경로는 사용할 수 없습니다.") from exc
        return candidate

    def list(self, path: str = "") -> list[StorageEntry]:
        target = self._resolve(path)
        if not target.exists():
            raise StorageError("경로가 존재하지 않습니다.")
        if not target.is_dir():
            raise StorageError("폴더가 아닙니다.")
        result: list[StorageEntry] = []
        for item in target.iterdir():
            stat = item.stat()
            rel = item.relative_to(self.root).as_posix()
            result.append(StorageEntry(
                name=item.name,
                path=rel,
                is_dir=item.is_dir(),
                size=None if item.is_dir() else stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime).astimezone(),
                mime_type=None if item.is_dir() else mimetypes.guess_type(item.name)[0],
            ))
        return sorted(result, key=lambda x: (not x.is_dir, x.name.lower()))

    def exists(self, path: str) -> bool:
        return self._resolve(path).exists()

    def mkdir(self, path: str) -> None:
        self._resolve(path).mkdir(parents=True, exist_ok=False)

    def write_stream(self, path: str, stream: BinaryIO, content_type: str | None = None) -> None:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as out:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)

    def read_bytes(self, path: str) -> bytes:
        target = self._resolve(path)
        if not target.is_file():
            raise StorageError("파일이 존재하지 않습니다.")
        return target.read_bytes()

    def delete(self, path: str) -> None:
        target = self._resolve(path)
        if not target.exists():
            raise StorageError("경로가 존재하지 않습니다.")
        if target.is_dir():
            if any(target.iterdir()):
                raise StorageError("비어 있지 않은 폴더는 삭제할 수 없습니다.")
            target.rmdir()
        else:
            target.unlink()

    def move(self, source: str, destination: str, overwrite: bool = False) -> None:
        src = self._resolve(source)
        dst = self._resolve(destination)
        if not src.exists():
            raise StorageError("원본 경로가 존재하지 않습니다.")
        if dst.exists() and not overwrite:
            raise StorageError("대상 경로가 이미 존재합니다.")
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists() and overwrite and dst.is_file():
            dst.unlink()
        src.replace(dst)


class WebDavStorageProvider(StorageProvider):
    DAV = "{DAV:}"

    def __init__(self, base_url: str, username: str, password: str, verify_ssl: bool = True, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(
            auth=httpx.DigestAuth(username, password),
            verify=verify_ssl,
            timeout=timeout,
            follow_redirects=True,
        )

    def _url(self, path: str) -> str:
        rel = normalize_repo_path(path)
        if not rel:
            return self.base_url + "/"
        return self.base_url + "/" + quote(rel, safe="/")

    def _raise(self, response: httpx.Response, allowed: tuple[int, ...] = (200, 201, 204, 207)) -> None:
        if response.status_code in allowed:
            return
        if response.status_code == 401:
            raise StorageError("WebDAV 인증에 실패했습니다.")
        if response.status_code == 403:
            raise StorageError("WebDAV 접근 권한이 없습니다.")
        if response.status_code == 404:
            raise StorageError("WebDAV 경로가 존재하지 않습니다.")
        if response.status_code == 409:
            raise StorageError("WebDAV 경로 충돌이 발생했습니다.")
        raise StorageError(f"WebDAV 오류: HTTP {response.status_code}")

    def list(self, path: str = "") -> list[StorageEntry]:
        body = """<?xml version=\"1.0\" encoding=\"utf-8\" ?>
        <d:propfind xmlns:d=\"DAV:\"><d:prop><d:displayname/><d:getcontentlength/><d:getlastmodified/><d:getcontenttype/><d:resourcetype/></d:prop></d:propfind>"""
        try:
            response = self.client.request("PROPFIND", self._url(path), headers={"Depth": "1", "Content-Type": "application/xml"}, content=body)
        except httpx.RequestError as exc:
            raise StorageError(f"WebDAV 서버에 연결할 수 없습니다: {exc}") from exc
        self._raise(response, (207,))
        root = ET.fromstring(response.content)
        entries: list[StorageEntry] = []
        base = normalize_repo_path(path)
        for idx, resp in enumerate(root.findall(f"{self.DAV}response")):
            if idx == 0:
                continue
            href = resp.findtext(f"{self.DAV}href", default="")
            props = resp.find(f".//{self.DAV}prop")
            if props is None:
                continue
            display_name = props.findtext(f"{self.DAV}displayname")
            name = _decode_path(display_name) if display_name else _href_name(href)
            rt = props.find(f"{self.DAV}resourcetype")
            is_dir = rt is not None and rt.find(f"{self.DAV}collection") is not None
            size_text = props.findtext(f"{self.DAV}getcontentlength")
            try:
                size = None if is_dir or not size_text else int(size_text)
            except ValueError:
                size = None
            child_path = normalize_repo_path(posixpath.join(base, name))
            entries.append(StorageEntry(
                name=name,
                path=child_path,
                is_dir=is_dir,
                size=size,
                modified_at=_parse_http_datetime(props.findtext(f"{self.DAV}getlastmodified")),
                mime_type=props.findtext(f"{self.DAV}getcontenttype"),
            ))
        return sorted(entries, key=lambda x: (not x.is_dir, x.name.lower()))

    def exists(self, path: str) -> bool:
        try:
            response = self.client.request("PROPFIND", self._url(path), headers={"Depth": "0"})
            return response.status_code == 207
        except httpx.RequestError:
            return False

    def mkdir(self, path: str) -> None:
        try:
            response = self.client.request("MKCOL", self._url(path))
        except httpx.RequestError as exc:
            raise StorageError(f"WebDAV 서버에 연결할 수 없습니다: {exc}") from exc
        self._raise(response, (201, 405))

    def write_stream(self, path: str, stream: BinaryIO, content_type: str | None = None) -> None:
        data = stream.read()
        try:
            response = self.client.put(self._url(path), content=data, headers={"Content-Type": content_type or "application/octet-stream"})
        except httpx.RequestError as exc:
            raise StorageError(f"WebDAV 서버에 연결할 수 없습니다: {exc}") from exc
        self._raise(response, (200, 201, 204))

    def read_bytes(self, path: str) -> bytes:
        try:
            response = self.client.get(self._url(path))
        except httpx.RequestError as exc:
            raise StorageError(f"WebDAV 서버에 연결할 수 없습니다: {exc}") from exc
        self._raise(response, (200,))
        return response.content

    def delete(self, path: str) -> None:
        try:
            response = self.client.delete(self._url(path))
        except httpx.RequestError as exc:
            raise StorageError(f"WebDAV 서버에 연결할 수 없습니다: {exc}") from exc
        self._raise(response, (200, 204))

    def move(self, source: str, destination: str, overwrite: bool = False) -> None:
        headers = {"Destination": self._url(destination), "Overwrite": "T" if overwrite else "F"}
        try:
            response = self.client.request("MOVE", self._url(source), headers=headers)
        except httpx.RequestError as exc:
            raise StorageError(f"WebDAV 서버에 연결할 수 없습니다: {exc}") from exc
        self._raise(response, (201, 204))


def get_storage() -> StorageProvider:
    if settings.storage_type.lower() == "local":
        return LocalStorageProvider(settings.local_storage_path)
    if settings.storage_type.lower() == "webdav":
        return WebDavStorageProvider(
            settings.webdav_url,
            settings.webdav_username,
            settings.webdav_password,
            verify_ssl=settings.webdav_verify_ssl,
            timeout=settings.webdav_timeout_seconds,
        )
    raise RuntimeError(f"지원하지 않는 STORAGE_TYPE: {settings.storage_type}")
