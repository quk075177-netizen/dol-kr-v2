# 후속 작업 제안 (2026-08-08)

기준일: 2026-08-08
상태: 1순위 완료 (2026-08-08) — 2순위 진행 예정
전제: ko-reuse 3,151 passage 어셈블 → 컴파일 → 스모크 체인이 동작함
(어셈블 1:49, 컴파일 ~2s, 스모크 ~6s — 리뷰 반영 완료, `docs/implementation-feedback.md`)

## 1순위 — 검증 파이프라인 완성 (H8 + H4, 빌드 체인 마감) — **완료**

1. **오케스트레이터 `build/verify.py`**: 어셈블 → 컴파일 → 스모크 → 레포트
   집계를 한 커맨드로. 단계 누락/스테일 산출물 혼동 방지.
   `python3 build/verify.py` (부분 실행: `--no-assemble --no-compile`).
   실측: 전체 1:56, 임계값 실패 경로 검증 완료.
2. **passage-list TSV 자동 생성**: 어셈블러 `--emit-passage-list` —
   스플라이스된 passage의 한국어 조각을 자동 추출 (수동 스크립트 제거).
   산출물: `build/browser-smoke/passage-list.tsv`.
3. **한국어 포함 비율 지표** (H4 잔여): 컴파일된 스토리(`<tw-passagedata>`
   전수)의 한국어 포함 비율을 스모크가 보고 — 실측 3,032/16,133 (18.8%,
   현재 번역 커버리지). `--min-korean-ratio` 임계값으로 "영어로 회귀" 감지
   (실측: 0.9 → fail, 0.1 → pass).

## 2순위 — Gemini 풀패시지 번역 러너 (파이프라인 본체) — **구현 완료, 검증 1 passage**

- **`translation/translate_passages.py`** (신규): 유닛 번역 → `post_process` →
  joined 복구(`repair_separator_newlines`: 모델이 버린 보호 스팬 사이 공백
  분리자 재삽입) → `restore_joined` → 보호 스팬 시그니처 검증(`_skeleton_ok`)
  → `level="passage"` 레코드 저장 (source=gemini, request_id 자동
  `req_<yyyymmdd>_<seq>` — R4 마무리)
- 실패 사유 명시: placeholder_drop / restore_failed / skeleton_mismatch
- `--file+--passage-name` 또는 `--passages-file`(JSONL)로 대상 선택,
  `--force` 재번역, 이미 저장된 passage는 skip
- **실측**: Ocean Breeze(22유닛) 번역 → 스토어 저장 → 어셈블(3,105 passage)
  → 컴파일 → 스모크 통과 (passage-list에 포함, ratio 3,032→3,033)
- **발견·수정 버그 3건**:
  1. 모델이 보호 스팬 사이 **공백/개행 분리자 드롭** → 스팬 병합 → 결정적
     복구(`repair_separator_newlines`)로 해결 (재시도는 무효 — 모델이
     반복 위반)
  2. 파서 `_consume_variable`이 `isalnum()`으로 **한글 조사(`를` 등)를
     변수명에 흡수** → ASCII 전용으로 수정 (SugarCube 스펙 일치, corpus
     영향 0 — baseline matched)
  3. gemini 레코드의 `source_path`가 `game/` 접두어 → ko_reuse 키와 불일치
     → `--game-root` 기준 상대경로 정규화
- 남은 단계: 대표 유형별 passage → 마커 있는 3-match passage → 전체
  16,135 passage (비용 큰 마지막 단계). R2 unit-level 재사용은 본번역
  배치에서 연동 예정.

## 3순위 — post 시스템 완성

- **PO2 런타임 helper** (게임 사이드): `{{post:...}}` 동적 마커 치환 +
  `trPostsList` 전체 26개 조사 테이블 (표 외 마커 `이`/`아` 처리 포함,
  `docs/post-system-design.md` PO2)
- **마커 있는 56%(4,037 passage) 3-match 등록**: `【 】`→`{{post:...}}`
  정규화 후 정적 치환분 resolve, 동적분은 런타임 대상으로 등록 →
  번역 커버리지 44% → 100%
- **단일 추측 조사 검출** (P1: combat 78건/gwylan 110건 관찰):
  placeholder 뒤 단일 조사 정규식 → 재시도 또는 리뷰 플래그

## 4순위 — 품질 인프라

- **NPC 인명 glossary**: Gwylan 5표기 비일관 — 인명 테이블 + 프롬프트 컨텍스트
- **props/색상/식물 glossary** (HANDOFF 데이터 항목): `wearProp`/`foodstuff` 계열
- **JS 문자열 번역**: 기존 KO JS 문자열 9,373건 대조 → JS 번역 레이어
  (빌드 체인에 JS 치환 단계 추가)

## 5순위 — 유지보수/정리

- H5 스모크 셀렉터 설정 분리, Q3 체크 카테고리(번역/회귀) 분리,
  Q5 store level 통일 (`docs/implementation-feedback.md` §8)
- F10 placeholder prefix 인플레이션, F9 `_merge_small_units` ancestors,
  F11 TextSource 최적화 (`docs/archive/system-review-triage.md`)

## 실행 순서 근거

1순위는 1회성(~30분)이고 체인을 "한 번에 검증"으로 바꿔 이후 모든 단계의
회귀 감지 기반이 된다. 2순위가 본체(번역 생산), 3순위는 번역 커버리지
완성(post 마커 없이 마커 있는 passage를 빌드에 넣으면 게임에 마커가
리터럴 표시됨). 2/3순위 병렬 진행 가능. 4/5순위는 품질/유지보수.
