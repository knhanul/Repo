from __future__ import annotations

import hashlib
import mimetypes
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from packaging.version import InvalidVersion, Version


VERSION_RE = re.compile(
    r"(?<![A-Za-z0-9])v?(?P<version>\d+\.\d+(?:\.\d+){0,2}(?:[-_.]?(?:alpha|beta|rc|preview|dev)\d*)?)(?![A-Za-z0-9])",
    re.IGNORECASE,
)


@dataclass(slots=True)
class AnalyzedFile:
    filename: str
    version: str | None
    file_type: str
    mime_type: str | None
    is_primary_candidate: bool


def extract_version(filename: str) -> str | None:
    stem = Path(filename).name
    matches = list(VERSION_RE.finditer(stem))
    if not matches:
        return None
    raw = matches[-1].group("version").replace("_", "-")
    raw = re.sub(r"-(alpha|beta|rc|preview|dev)(\d*)$", lambda m: f"{m.group(1)}{m.group(2)}", raw, flags=re.IGNORECASE)
    return raw


def detect_file_type(filename: str) -> str:
    name = filename.lower()
    if any(token in name for token in ("source", "-src", "_src", "-code", "_code")) and (name.endswith(".zip") or name.endswith(".tar.gz") or name.endswith(".tgz")):
        return "Source Code"
    if name.endswith(".msi"):
        return "Windows Installer"
    if name.endswith(".exe"):
        if any(token in name for token in ("setup", "installer", "install")):
            return "Windows Installer"
        return "Windows Executable"
    if name.endswith(".apk"):
        return "Android App"
    if name.endswith(".aab"):
        return "Android App Bundle"
    if name.endswith((".zip", ".tar.gz", ".tgz", ".7z")):
        if "portable" in name:
            return "Portable"
        return "Archive"
    if name.endswith((".md", ".txt", ".pdf", ".doc", ".docx", ".hwp", ".hwpx", ".xlsx", ".pptx")):
        return "Documentation"
    return "File"


def is_primary_candidate(filename: str, file_type: str) -> bool:
    lower = filename.lower()
    if file_type in {"Windows Installer", "Android App"}:
        return True
    if file_type == "Windows Executable" and "portable" not in lower:
        return True
    if file_type == "Portable":
        return True
    return False


def analyze_filename(filename: str) -> AnalyzedFile:
    file_type = detect_file_type(filename)
    return AnalyzedFile(
        filename=filename,
        version=extract_version(filename),
        file_type=file_type,
        mime_type=mimetypes.guess_type(filename)[0],
        is_primary_candidate=is_primary_candidate(filename, file_type),
    )


def safe_version_key(value: str):
    try:
        return Version(value)
    except InvalidVersion:
        return Version("0")


def is_prerelease(value: str) -> bool:
    try:
        return Version(value).is_prerelease
    except InvalidVersion:
        return False


def choose_latest(versions: list[str]) -> str | None:
    if not versions:
        return None
    stable = [v for v in versions if not is_prerelease(v)]
    pool = stable or versions
    return max(pool, key=safe_version_key)


def choose_primary(filenames_and_types: list[tuple[str, str]]) -> str | None:
    priorities = {
        "Windows Installer": 100,
        "Android App": 95,
        "Windows Executable": 90,
        "Portable": 80,
        "Android App Bundle": 70,
        "Archive": 30,
        "Source Code": 10,
        "Documentation": 5,
        "File": 1,
    }
    if not filenames_and_types:
        return None
    return max(filenames_and_types, key=lambda item: priorities.get(item[1], 0))[0]


def hash_and_spool(stream: BinaryIO, max_bytes: int) -> tuple[tempfile.SpooledTemporaryFile, int, str]:
    temp = tempfile.SpooledTemporaryFile(max_size=min(max_bytes, 64 * 1024 * 1024), mode="w+b")
    digest = hashlib.sha256()
    size = 0
    while True:
        chunk = stream.read(1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        if size > max_bytes:
            temp.close()
            raise ValueError("업로드 허용 크기를 초과했습니다.")
        digest.update(chunk)
        temp.write(chunk)
    temp.seek(0)
    return temp, size, digest.hexdigest()
