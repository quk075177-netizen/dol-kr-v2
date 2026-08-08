# 후속 작업 제안 (2026-08-08)

기준일: 2026-08-08
상태: 1순위 완료, 2순위 구현+리뷰 반영 완료 (실측 1 passage)

## 완료된 기반

- **빌드/스모크 체인**: `work/translations/ko-reuse.jsonl` → 어셈블러
  (병렬·원자·시그니처 검증) → tweego 컴파일 → headless 스모크.
  `python3 build/verify.py` 단일 커맨드 (~2분).
  passage-list 자동 생성, 한국어 포함 비율 지표(실측 18.8%).
- **Gemini 러너**: `translation/translate_passages.py` — 풀패시지 번역 →
  `level="passage"` 레코드 저장. 분리자 갭 결정적 복구, API 재시도,
  배치 예외 격리, post 마커 구조 검증, repaired 플래그, 실패 덤프.
  실측: Ocean Breeze(22유닛) 전 구간 통과.
- 리뷰 피드백 문서: `docs/implementation-feedback.md` (빌드 체인),
  `docs/translate-runner-feedback.md` (러너).

## 2순위 확장 — Gemini 풀패시지 번역 (진행 중)

1. **대표 유형별 배치** — `--passages-file`(JSONL)로 유형별 passage
   묶음 번역. 전투(561유닛)·설정(331유닛) 등 대형 passage의 성능·실패율
   측정 (L2 도입 판단의 관측 데이터 수집).
2. **마커 있는 3-match passage 등록** — post 정적 치환 후 등록 (3순위
   PO2와 연계). 완료 시 번역 커버리지 44% → 100%.
3. **전체 16,135 passage** — 비용 큰 마지막 단계. request_id 배치 추적,
   R2 unit-level 재사용 연동 (배치 내 동일 문장 hit).
4. **실패 관측 후 L2 결정** — `skeleton_mismatch` 사유 세분화
   (`separator_repair_failed` vs 기타) 로그 후, 잔존 실패가 실측되면
   유닛 단위 조기 검사 도입. 지금은 만들지 않음.

## 3순위 — post 시스템 완성

- **PO2 런타임 helper** (게임 사이드): `{{post:...}}` 동적 마커 치환 +
  `trPostsList` 전체 26개 조사 테이블 (표 외 마커 `이`/`아` 포함).
- **post 마커 whitelist/통계**: 세트 밖 마커 이름(`의`, `한` 등)을
  러너가 수집·보고 — PO2 테이블 확장 근거.
- **단일 추측 조사 검출**: placeholder 뒤 단일 조사(`를`, `은`) —
  P1에서 combat 78건/gwylan 110건. 검출 → 리뷰 플래그 (자동 재번역 아님).

## 4순위 — 품질 인프라

- **NPC 인명 glossary**: Gwylan 5표기 비일관. 인명 테이블 + 러너
  프롬프트 컨텍스트 주입.
- **props/색상/식물 glossary**: `wearProp`/`foodstuff` 계열.
- **JS 문자열 번역**: 기존 KO JS 문자열 9,373건 대조 → JS 번역 레이어
  (빌드 체인에 JS 치환 단계 추가).

## 5순위 — 유지보수/정리

- H5 스모크 셀렉터 설정 분리, Q3 체크 카테고리(번역/회귀) 분리,
  Q5 store level 통일.
- `_get_model` 캐시 개선 (다중 모델 혼용 시 캐시 우회).
- F10 placeholder prefix 인플레이션, F9 `_merge_small_units` ancestors,
  F11 TextSource 최적화.

## 실행 순서 근거

2순위 확장이 번역 생산의 본체 — 유형별 배치로 실패율/성능을 관측하며
단계적으로 넓힌다. 3순위는 "마커 있는 passage를 빌드에 넣을 수 있는"
전제 (PO2 없이 넣으면 `{{post:...}}`가 게임에 리터럴 표시). 4/5순위는
품질/유지보수.
