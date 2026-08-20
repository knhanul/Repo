# 프로젝트 관리 구조 분석 (Phase 1)

## 1. 현재 데이터 흐름

### Project

`Project`는 PostgreSQL/SQLite 공통 SQLAlchemy 모델인 `projects` 테이블에 저장된다.

- 기본 정보: `name`, `slug`, `storage_root`, `description`
- 프로젝트 메타데이터: `project_type`, `platforms`
- 관련 링크: `source_url`, `website_url`
- 관리 파일 경로: `icon_path`, `readme_path`
- lifecycle 정보: `is_deleted`, `deleted_at`, `deleted_by_id`, `trash_path`
- 감사/생성 정보: `created_by_id`, `created_at`, `updated_at`

프로젝트 폴더는 `프로젝트/<slug>`를 루트로 사용한다.

### Release / ReleaseFile

- `Release`: 프로젝트에 속한 버전과 릴리스 메모리
- `ReleaseFile`: 릴리스에 속한 실제 배포 파일의 `storage_path`, 크기, MIME, SHA-256, 다운로드 통계
- 프로젝트 삭제 시 Release/ReleaseFile metadata는 유지되며 Project soft delete와 Storage Trash lifecycle로 함께 복구할 수 있다.

릴리스 파일 경로는 다음과 같다.

```text
프로젝트/<project-slug>/releases/<version>/<filename>
```

### README / Icon / Git / Website

- README와 아이콘은 Storage에 저장하고, Project에는 상대 `storage_path`만 저장한다.
- Git URL과 Website URL은 Project metadata에 저장한다.
- URL은 `http` 또는 `https`만 허용하는 service helper를 통과한다.

### Smart Upload

Smart Upload가 파일명을 분석하여 Release를 만들고, `project_release_path()`로 경로를 생성한 뒤 Local/WebDAV Storage abstraction의 `write_stream()`을 호출한다. DB의 `ReleaseFile.storage_path`는 실제 Storage 경로와 동일한 내부 Unicode 경로를 사용한다.

### File Explorer / Folder Tree

File Explorer는 Storage의 `list()`가 반환하는 `StorageEntry`를 사용한다. Folder Tree는 `/api/files/tree`에서 폴더 목록을 읽는다. 일반 File Explorer와 Project 관리 데이터는 현재 별도 계층이며, Phase 4에서 Managed Resource backend 보호를 연결할 수 있도록 판별 helper를 추가했다.

### User / Admin / Audit

- 로그인 사용자는 `User.is_admin`으로 admin 여부를 판단한다.
- `require_admin()`은 프로젝트 삭제 같은 위험 작업에 사용할 수 있는 공통 guard다.
- 변경 작업은 `add_audit()`으로 감사 로그를 남긴다.

## 2. ProjectType 설계

ProjectType은 문자열 Enum으로 정의했다. PostgreSQL native enum을 사용하지 않아 SQLite와 기존 운영 DB migration을 단순하게 유지한다.

```text
WINDOWS_APP
WEB_APP
MOBILE_APP
CROSS_PLATFORM_APP
LIBRARY_TOOL
OTHER
```

화면 표시명은 `PROJECT_TYPE_LABELS`에서 관리한다. 기존에 사용하던 `windows_app`, `smartphone_app`, `website` 값은 migration/normalizer에서 각각 `WINDOWS_APP`, `MOBILE_APP`, `WEB_APP`으로 변환한다.

## 3. Platform 설계

플랫폼은 Project에 JSON 배열로 저장한다. 현재 지원 값은 다음과 같다.

```text
Windows, Web, Android, iOS, Linux, macOS
```

플랫폼은 복수 선택 가능하며 `normalize_platforms()`가 허용 목록 검증, 중복 제거, 입력 순서 보존을 담당한다. 플랫폼별 검색/집계 요구가 생기기 전까지는 별도 join table보다 현재 모델과 호환성이 좋은 JSON 배열을 사용한다.

## 4. ProjectResource foundation

Release 실행파일과 프로젝트 자료를 분리하기 위해 `project_resources` 테이블과 `ProjectResource` 모델을 추가했다.

지원 category:

```text
HELP, REPORT, SAMPLE, DOCUMENT, OTHER
```

모델에는 제목, 설명, 원본 파일명, Storage 경로, 크기, MIME, SHA-256, 생성자, 생성일을 저장한다. 이번 Phase에서는 업로드 API/UI를 추가하지 않고, Phase 3에서 사용할 DB 및 relationship foundation만 만든다.

예상 Storage 구조:

```text
프로젝트/<project-slug>/resources/<category>/<filename>
```

## 5. Managed Resource 판별 전략

별도 ManagedResource 테이블을 추가하지 않았다. 현재 Project, ReleaseFile, ProjectResource, README/icon 경로 및 프로젝트 Storage root가 authoritative metadata다.

`app/services/managed_resources.py`의 `managed_project_for_path()`는 DB의 Project slug에서 `프로젝트/<slug>` root를 계산하고, 요청 경로가 해당 root 또는 하위인지 비교한다. 따라서 단순 폴더명 일치가 아니라 DB에 등록된 Project를 기준으로 판단한다.

Phase 4에서 delete/move/rename backend API가 이 helper를 호출하여 Project 관리 경로를 보호한다. 현재 Phase에서는 helper만 제공하며 일반 File Explorer 동작은 변경하지 않는다.

## 6. Migration

앱 startup의 `ensure_schema_compatibility()`가 기존 `projects` 및 `project_resources` 테이블에 다음 nullable-compatible 컬럼을 추가한다.

```text
storage_root VARCHAR(1000)
project_type VARCHAR(40)
platforms JSON
website_url VARCHAR(1000)
source_url VARCHAR(1000)
is_deleted BOOLEAN
deleted_at TIMESTAMP
deleted_by_id INTEGER
trash_path VARCHAR(1000)
```

`project_resources`에도 동일한 soft-delete metadata가 추가된다. 기존 자료는 `is_deleted = false`로 backfill된다.

기존 `output_type` 컬럼이 있는 DB에서는 다음과 같이 project type을 backfill한다.

```text
windows_app    -> WINDOWS_APP
smartphone_app -> MOBILE_APP
website        -> WEB_APP
기타           -> OTHER
```

기존 Project, Release, ReleaseFile, User, AuditLog 및 Storage 파일은 삭제하거나 재생성하지 않는다. `project_resources` 테이블은 `Base.metadata.create_all()`에 의해 신규 생성된다.

운영 DB migration은 애플리케이션 startup compatibility 처리로만 준비했으며, 이번 작업에서 운영 서버에는 접속하지 않았다.

## 7. Phase 1 범위

- 현재 Project/Release/Storage/User/Audit 구조 분석
- ProjectType 및 플랫폼 foundation
- 기존 output_type 호환 migration
- ProjectResource DB 모델 및 category foundation
- Managed Resource 판별 helper
- 기존 URL/프로젝트 기능 회귀 테스트 보강

## 8. Phase 4.1 삭제/복구 lifecycle

Project는 soft delete를 사용한다.

```text
프로젝트/<slug>
↓ Storage MOVE
_trash/projects/<project-id>-<slug>-<timestamp>
↓ DB commit
Project.is_deleted = true
Project.trash_path = ...
```

Project 전체 삭제와 개별 ProjectResource 삭제는 서로 독립적인 lifecycle이다.

### Project 전체 삭제 시 존재하는 Resource

Project Root 안에 있으므로 Project Root와 함께 `_trash/projects`로 이동한다. Project Restore 시 함께 원래 위치로 돌아온다.

### Project 삭제 전에 개별 삭제된 Resource

이미 `_trash/resources`로 이동되고 Resource row는 유지된다. Project Root 밖에 있으므로 Project Restore만으로 자동 복구되지 않는다.

ProjectResource는 soft delete metadata를 유지한다.

```text
is_deleted
deleted_at
deleted_by_id
trash_path
```

개별 Resource를 다시 업로드할 때는 `is_deleted = false`인 자료만 중복 판정 대상이며, 삭제된 동일 파일은 기존 row를 재활성화할 수 있다.

Storage MOVE 후 DB commit 실패 시 원래 경로로 rollback을 시도한다. Restore 중 DB commit이 실패하면 다시 Trash로 rollback한다.

File Explorer에서는 DB Project slug 기준 managed path 및 `_trash` 영역의 구조 변경을 backend에서 차단한다.
