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

## 2순위 — Gemini 풀패시지 번역 러너 (파이프라인 본체)

- 청킹 기반 유닛 번역 → passage 레코드로 스토어 저장 (`level="passage"`,
  `request_id` 자동 발급 — `docs/translation-reuse-design.md` R2/R4 마무리)
- **단계적 실행**: 대표 유형별 passage → 마커 있는 3-match passage →
  전체 16,135 passage (비용 큰 마지막 단계)
- 재시도/드롭 대응은 기존 로직(P1 검증, `docs/archive/pilot-report.md`) 재사용,
  passage 단위 구조 검증은 어셈블러 시그니처 검사가 커버

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
