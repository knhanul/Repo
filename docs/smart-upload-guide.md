# Smart Upload 가이드

## 기본 흐름

1. 프로젝트를 한 번 생성합니다. 프로젝트명만 필수입니다.
2. 프로젝트 상세 화면에 파일을 Drag & Drop 합니다.
3. 파일명에서 버전과 파일 유형을 자동 분석합니다.
4. 파일 크기, MIME, 업로드 시각/사용자, 저장 경로, SHA-256은 자동 기록합니다.
5. 동일 버전 파일은 하나의 Release로 묶입니다.
6. 서로 다른 버전 파일은 버전별 Release로 분리됩니다.
7. 안정 버전 중 가장 높은 버전을 Latest로 지정합니다.
8. 설치파일/APK/실행파일을 대표 다운로드로 우선 선택합니다.

## 버전 예

- `POSID-1.5.0.exe` → `1.5.0`
- `POSID-v1.5.0.exe` → `1.5.0`
- `POSID Setup 1.5.0.exe` → `1.5.0`
- `NuniTrack-v0.9.1.apk` → `0.9.1`
- `POSID-final.exe` → 자동 인식 실패, 업로드 화면에서 버전 1회 입력

## 유형 예

- setup `.exe`, `.msi` → Windows Installer
- 일반 `.exe` → Windows Executable
- `.apk` → Android App
- `.aab` → Android App Bundle
- `source/src/code`가 포함된 압축 파일 → Source Code
- `portable` 압축 파일 → Portable
- Markdown/PDF/HWPX/Office 문서 → Documentation

## 저장 구조

```text
Repo/
  POSID/
    releases/
      1.5.0/
        POSID-Setup-1.5.0.exe
        POSID-1.5.0-source.zip
    README.md
```

실제 파일명은 보존하며 DB에 별도 메타데이터를 저장합니다.
