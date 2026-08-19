# NUNI Repository — Smart Upload Full Source

NAS/WebDAV 파일 관리와 개발 프로그램 릴리스 관리를 하나의 웹 UI에서 제공하는 소스입니다.

## 포함 기능

- 로그인/사용자 관리
- Windows 탐색기형 파일 화면: 왼쪽 lazy-loading 폴더 트리 + 오른쪽 파일 목록
- 파일 탐색, 폴더 생성, 다중 업로드, 다운로드, 이름 변경, 삭제
- 폴더 트리 드래그 이동 / 외부 파일 폴더 직접 드롭 업로드 / 우클릭 작업
- 폴더 트리 폭 조절, 접기/펼치기, 현재 경로 자동 reveal, 불러온 폴더 검색
- Local Storage / WebDAV Storage 교체형 구조
- HTTP Digest WebDAV (`PROPFIND`, `GET`, `PUT`, `DELETE`, `MKCOL`, `MOVE`)
- 프로젝트 관리
- Smart Upload Drag & Drop
- 파일명 기반 버전 자동 추출
- 파일 유형 자동 분류
- 동일 버전 자동 Release 그룹화
- 서로 다른 버전 자동 분리
- SHA-256 자동 계산
- Latest 자동 지정 및 수동 변경
- 대표 다운로드 자동 선택 및 수동 변경
- README.md 렌더링
- 검색, 최근 업데이트
- 공유 링크
- 감사 로그
- Local SQLite 개발 / PostgreSQL 운영
- Docker Compose

## Windows 개발 PC에서 실행

### 1. 압축 해제 후 PowerShell

```powershell
cd NUNI-Repository-SmartUpload-full
Copy-Item .env.example .env
```

`.env`에서 원하는 개발 폴더를 지정합니다.

```env
STORAGE_TYPE=local
LOCAL_STORAGE_PATH=E:\NuniRepoDev
DATABASE_URL=sqlite:///./data/nuni_repository.db
```

### 2. 실행

```powershell
.\scripts\run-dev.ps1
```

또는 `scripts\run-dev-windows.bat`을 실행합니다.

브라우저:

```text
http://127.0.0.1:8090
```

기본 개발 계정:

```text
admin / admin
```

운영에서는 반드시 `.env`의 관리자 비밀번호와 `SECRET_KEY`를 변경하세요.

## 운영 WebDAV

```env
APP_ENV=production
STORAGE_TYPE=webdav
WEBDAV_URL=http://<NAS-WIREGUARD-IP>/dav/VOL1/Repo
WEBDAV_USERNAME=reposervice
WEBDAV_PASSWORD=<PASSWORD>
```

실제 NAS 주소/비밀번호를 Git에 커밋하지 마세요.

## Docker

```bash
cp .env.example .env
docker compose up -d --build
```

기본 바인딩은 `127.0.0.1:8090`입니다. 외부 공개는 Nginx/HTTPS 앞단에서 처리하는 것을 권장합니다.

## 테스트

```bash
pytest -q
```

## 주요 구조

```text
app/
  main.py
  models.py
  config.py
  security.py
  services/
    storage.py
    smart_upload.py
    project_service.py
    file_tree.py
  templates/
  static/
tests/
docs/
  folder-tree-guide.md
scripts/
```

## 주의

이 소스는 기존 NUNI Repository 소스 전체를 전달받아 패치한 것이 아니라, 이번 대화에서 확정한 요구사항을 기준으로 바로 실행 가능한 독립형 full source로 구성한 버전입니다. 기존 운영 소스와 합치려면 DB 스키마/라우트/인증 구조 비교가 필요합니다.
