# 파일 탐색기 폴더 트리 가이드

## 목적

`파일` 화면은 Windows 탐색기와 유사하게 **왼쪽 폴더 트리 + 오른쪽 파일 목록**으로 동작한다. `프로젝트` 화면은 기존처럼 프로젝트/릴리스 중심 UI를 유지한다.

## 주요 UX

- 왼쪽 폴더 트리에서 폴더를 클릭하면 해당 폴더로 이동한다.
- 트리는 WebDAV 부담을 줄이기 위해 **하위 폴더를 펼칠 때만 조회하는 lazy loading** 방식이다.
- 현재 경로의 상위 폴더는 화면 진입 시 자동으로 펼쳐진다.
- 트리 폭은 210~440px 사이에서 드래그로 조절할 수 있고 브라우저에 저장된다.
- 트리 패널은 접고 다시 펼칠 수 있으며 상태가 브라우저에 저장된다.
- 트리의 `•••` 또는 우클릭 메뉴에서 열기, 새 폴더, 파일 업로드, 새로고침을 실행할 수 있다.
- 오른쪽 파일/폴더 행을 트리의 다른 폴더에 끌어 놓으면 MOVE로 이동한다.
- Windows 탐색기의 파일을 트리 폴더에 끌어 놓으면 해당 폴더로 업로드한다.
- 트리 검색은 현재까지 lazy loading으로 불러온 폴더를 대상으로 즉시 필터링한다.

## API

### `GET /api/files/tree?path=<repo path>`

해당 경로의 **직접 하위 폴더만** 반환한다. 전체 NAS 트리를 한 번에 스캔하지 않는다.

### `POST /api/files/move`

```json
{
  "source": "POSID/manual.pdf",
  "destination_dir": "POSID/docs"
}
```

파일명은 유지하고 대상 폴더로 이동한다. 자기 자신 또는 자신의 하위 폴더로 폴더를 이동하는 요청은 차단한다.

## Local / WebDAV

폴더 트리는 `StorageProvider.list()`와 `StorageProvider.move()`만 사용하므로 Local Storage와 WebDAV Storage 모두 같은 UI/업무 로직을 사용한다.

WebDAV에서는 각 폴더 확장 시 `PROPFIND Depth: 1`, 이동 시 `MOVE`가 사용된다.
