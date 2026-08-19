# Folder Tree 구현 요약

이번 버전은 기존 Smart Upload Full Source에 파일 탐색기의 왼쪽 폴더 트리를 추가한 전체 소스다.

## 반영 사항

- `파일` 화면만 Windows 탐색기형 2-pane 구조 사용
- 왼쪽: Repository 폴더 트리
- 오른쪽: 현재 폴더 파일/폴더 목록
- WebDAV/NAS 성능을 고려한 lazy loading
- 현재 경로 자동 펼침(reveal)
- 트리 폭 드래그 조절 및 브라우저 저장
- 트리 접기/펼치기 및 상태 저장
- 불러온 폴더 검색
- 폴더 우클릭/`•••` 메뉴
  - 열기
  - 새 폴더
  - 파일 업로드
  - 새로고침
- 오른쪽 파일/폴더를 왼쪽 폴더로 Drag & Drop하여 MOVE
- Windows 탐색기 파일을 왼쪽 폴더로 Drag & Drop하여 바로 업로드
- 모바일/좁은 화면에서는 폴더 트리를 오버레이 패널로 표시
- Local Storage와 WebDAV Storage에서 동일하게 동작

## 신규 API

- `GET /api/files/tree`
- `POST /api/files/move`

## 신규 서비스

- `app/services/file_tree.py`

## 신규 테스트

- `tests/test_folder_tree.py`

전체 자동 테스트: 11개 통과.
