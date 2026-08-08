# 후속 작업 제안 (2026-08-08)

기준일: 2026-08-08
상태: 1순위 완료, 2순위-1~2 완료, L2/Option E/배치+승격 완료,
      2순위-3(전체 corpus) 대기, 3순위(PO2) 대기

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

1. **대표 유형별 배치** — 실행 완료 (2026-08-08, 2회차 관측).
   `--passages-file`로 대화/이벤트/성인 유니크 20 passage (21 runs,
   1,317 유닛) 배치: 성공 2/21 (9.5%), 유닛 실패율 ≈1.2%. 관측 리포트:
   `tmp/reports/batch-p2-1-report.md`, 실패 덤프
   `tmp/debug-dumps/batch-debug/`. **실패 모드 4종**: placeholder_drop
   (결정적 — 같은 유닛 재실패), reorder(skeleton_mismatch), 타 유닛
   토큰 환각(restore_failed), **placeholder 형식 환각**(7자리 토큰
   passage에서 프롬프트 예시의 6자리 `<000000>` 삽입 — skeleton_mismatch).
   전투(561유닛)·설정(331유닛)은 [widget] 코드 passage라 러너가 거절 —
   비-위젯 최대 passage(38~122유닛)로 측정.
2. **마커 있는 3-match passage 등록** — **완료** (2026-08-08). 마커 있는
   4,037 passage 중 3,978건 등록 (post_status=runtime_remaining 3,983 전체),
   레거시 【 】→{{post:...}} 전량 매핑, 정적 치환 0건 (전 마커가 런타임 값 앞 —
   문서의 91.8%보다 높음). 등록 검증 보강 3건:
   - `macro_sequence` 검사 추가 — 링크 라벨 내부 매크로 드롭(레거시 KO
     결함)이 파서 시그니처 검사로 안 잡히는 갭 해결 (8건 퇴출 → 재등록
     자동 스킵, 어셈블 verify_failed 0)
   - 등록 멱등성: 이미 있는 hash는 `already_registered`로 스킵
   - `post_status` 정확화: 마커 잔존 = `runtime_remaining` (기존
     `static_done` 오분류 수정)
   완료 시 번역 커버리지 18.8% → 43.5% (7,011/16,133 passage, 스모크 실측).
   잔여: state=empty/excluded 595건 중 ko_body≈source_body(영어 그대로)
   90건은 find_passage_reuse 블로커 — 후순위 정리 대상.
3. **전체 16,135 passage** — 비용 큰 마지막 단계. request_id 배치 추적,
   R2 unit-level 재사용 연동 (배치 내 동일 문장 hit).
4. **실패 관측 후 L2 결정 — 완료 (구현)**: 관측 데이터 확보 후 유닛
   단위 조기 검사(L2) + Option E(리오더 허용) + 배치/승격 에스컬레이션
   구현. placeholder_drop은 결정적(같은 유닛 재실패) — **lite의 지뢰
   유닛은 flash 승격으로 해소** (Farm Work 100유닛 성공 실측). 잔여
   실패는 실패 로그로 수집 후 추후 재던지기 전략.

## 2.5순위 — 구현 완료 요약 (2026-08-08)

- **L2 유닛 구조 검사**: reorder/foreign_token/format_hallucination/
  prose_drop + 힌트 재시도 2회. 재시도 사유 오염 버그·덤프 컨텍스트·
  토큰 정규식 일반화·프롬프트 예시 제거 반영. `l2_retries`/`api_calls`/
  `escalated`(bool)/`escalated_units`/`tier` 레코드 필드.
- **Option E**: 리오더 원인 = 한국어 어순 자연화 (표시 전용 매크로
  재배치). `ProtectedSpan(kinds)` + `order_sensitivity.py` 화이트리스트 —
  표시 전용만 순서 무관, 미등록은 전부 민감. L2/L3 완화, 등록/어셈블러
  엄격 유지. 분석: 루트 `reorder-analysis.md`.
- **배치 번역 + 승격**: `--batch-size 16` (items 배열 + response_schema),
  L1/L2 실패 유닛 `--escalation-model`(flash) 승격, L3는
  `boundary_prose_drops` 경계 검사로 유닛 승격. **2티어 정책** — 자동
  재시도 종료, 실패 로그만. `--journal` 스트리밍 저장. 실측: Farm Work
  성공 (배치 7회+승격 24회 ≈33회 호출, per-unit 대비 ~3배 절감).
- 관측 산출물: `tmp/` (batches/debug-dumps/reports/stores/scripts).

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
