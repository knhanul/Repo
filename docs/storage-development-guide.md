# Storage 개발/운영 가이드

## 개발 PC

`.env`:

```env
APP_ENV=development
STORAGE_TYPE=local
LOCAL_STORAGE_PATH=E:\NuniRepoDev
DATABASE_URL=sqlite:///./data/nuni_repository.db
```

NAS/WireGuard 연결 없이 파일, 프로젝트, Smart Upload, SHA-256, 릴리스/버전, README, 다운로드를 테스트할 수 있습니다.

## WebDAV 테스트/운영

```env
APP_ENV=production
STORAGE_TYPE=webdav
WEBDAV_URL=http://<NAS-WIREGUARD-IP>/dav/VOL1/Repo
WEBDAV_USERNAME=reposervice
WEBDAV_PASSWORD=<PASSWORD>
WEBDAV_VERIFY_SSL=true
DATABASE_URL=postgresql+psycopg://...
```

`WebDavStorageProvider`는 `PROPFIND`, `GET`, `PUT`, `DELETE`, `MKCOL`, `MOVE`를 사용하며 HTTP Digest 인증을 사용합니다.

실제 NAS 통합 테스트는 운영 Repository가 아니라 `Repo/_dev_test` 같은 전용 폴더에서 수행하세요.

## 환경 전환

- `STORAGE_TYPE=local`: 개발 PC 로컬 폴더
- `STORAGE_TYPE=webdav`: NAS 또는 개발용 WebDAV

업무 로직은 Storage 구현을 직접 알지 않습니다.
