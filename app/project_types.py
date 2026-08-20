from __future__ import annotations

from enum import Enum


class ProjectType(str, Enum):
    WINDOWS_APP = "WINDOWS_APP"
    WEB_APP = "WEB_APP"
    MOBILE_APP = "MOBILE_APP"
    CROSS_PLATFORM_APP = "CROSS_PLATFORM_APP"
    LIBRARY_TOOL = "LIBRARY_TOOL"
    OTHER = "OTHER"


class ResourceCategory(str, Enum):
    HELP = "HELP"
    REPORT = "REPORT"
    SAMPLE = "SAMPLE"
    DOCUMENT = "DOCUMENT"
    OTHER = "OTHER"


PROJECT_TYPE_LABELS = {
    ProjectType.WINDOWS_APP.value: "Windows 프로그램",
    ProjectType.WEB_APP.value: "웹 애플리케이션 / 웹사이트",
    ProjectType.MOBILE_APP.value: "모바일 앱",
    ProjectType.CROSS_PLATFORM_APP.value: "크로스플랫폼 앱",
    ProjectType.LIBRARY_TOOL.value: "라이브러리 / 도구",
    ProjectType.OTHER.value: "기타",
}

RESOURCE_CATEGORY_LABELS = {
    ResourceCategory.HELP.value: "도움말",
    ResourceCategory.REPORT.value: "보고서",
    ResourceCategory.SAMPLE.value: "샘플",
    ResourceCategory.DOCUMENT.value: "문서",
    ResourceCategory.OTHER.value: "기타",
}

SUPPORTED_PLATFORMS = ("Windows", "Web", "Android", "iOS", "Linux", "macOS")

LEGACY_OUTPUT_TYPE_MAP = {
    "windows_app": ProjectType.WINDOWS_APP.value,
    "smartphone_app": ProjectType.MOBILE_APP.value,
    "website": ProjectType.WEB_APP.value,
}
