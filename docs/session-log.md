# 세션 로그

핵심 작업 기록 (이야기 로그가 길어서 찾기 어려운 문제를 위해 —
작업 완료 시 이 파일 끝에 요약을 append한다. 가장 최근이 아래).

## 2026-08-08 (저녁 세션 — 스토리지 정리·R2 재사용·검증·버그 3·4)

### 스토리지 정리 (완료)
- `ko-reuse.jsonl`(ko_reuse 7,093 전용) / `gemini-passages.jsonl`(gemini
  passage) / `ko-units.jsonl`(gemini 유닛) 파일 분리. `split_stores.py`
  멱등. 어셈블러/러너/verify는 병합 로드 (`load_translations_many`,
  뒤 파일 우선 = 기존 최신 우선 규칙 보존).
- 데드 파일(fail-demo/farmwork-rerun) → `tmp/archive/` 이동.

### R2 유닛 재사용 (완료, 실증)
- **핵심 교훈: 토큰(`<000000>`)은 passage 내 위치로 재번호되므로 토큰
  형태 저장은 재사용 불가** — 유닛 레코드는 항상 원문 바이트 복원형으로
  저장하고, 재사용 시 현재 유닛 토큰으로 재토큰화(`_retokenize`) +
  L1/L2 재검증 → API 0회. 배치 경로는 재사용 유닛을 API 배치에서 제외.
  passage 레코드 `reused_units` 필드.
- 실증: 10 passage 재실행 시 콘텐츠 유닛 121/121 전부 재사용, API 0회.

### 청킹 튜닝 (완료, 실측)
- threshold 700 (종전 1,000). 단일 유닛 passage 71% → 56%.
- **무병합 시행 → 실패 → 구조 인식 최소 병합 재도입**: 무병합 시
  "The " 같은 5자 조각 유닛이 생겨 저품질 번역·통째 삭제가 발생
  (검사도 못 잡음). F9 구조 인식 버전 (같은 ancestor 경로 안에서만
  <100자 병합, 교차 container 커플링 없음)으로 재도입:
  유닛 179,160 → 74,039, 조각 <100자 134,928 → 19,215.
- glue 유닛 (콘텐츠 없는 개행/placeholder span): verbatim 처리 —
  API 0회, 스토어 미기록. API 대상 콘텐츠 유닛 ~67,000개 (미번역분).

### 버그 3: 중첩 매크로 보호 (완료)
- 매크로 인자 내부의 `<<He>>`가 노출 segment로 남아 LLM이 `<그가>`로
  변형해도 L1/L2/시그니처 검사가 전부 못 잡던 갭.
- `masking._nested_macro_spans`: 노출 후보 내 매크로 재보호
  (quote 인식, 멀티바이트 바이트 오프셋 매핑). 실 API 재번역으로
  `<<He>>` 생존 확인.
- `register_ko_reuse --force` 추가 (마스커 변경 시 재검증·퇴출) —
  레거시 KO 44건 퇴출 (커버리지 43.5%→43.2%), corpus baseline 갱신.

### 어셈블러-러너 검증 정합 (완료 — reorder-analysis §5b 미결 해소)
- Option E 리오더가 러너 L3(캐노니컬)는 통과해도 어셈블러(원시
  비교)에서 거부되던 불일치 → **gemini 레코드는 어셈블러도 캐노니컬
  시그니처 비교** (macros_sequence 스킵), ko_reuse는 엄격 유지.
- **거부 피드백 루프**: 어셈블러 거부 레코드를
  `work/translations/assembler-rejected.jsonl`에 기록 → 러너는 해당
  해시를 "번역됨"으로 치지 않고 재번역 (조용한 영어 방치 방지).
  재검증 통과 시 엔트리 자동 정리.

### 버그 4: 콘텐츠 삭제 감지 (완료)
- placeholder 없는 유닛이 모델에 의해 통째 삭제돼도 검사가 못 잡던 갭
  (실측: "The "→"\t", "gives you a satisfied smile when "→" ").
- L2 `content_drop` 추가: 콘텐츠 유닛의 공백 전용 출력 = 실패
  (힌트 재시도 + 승격 경로 그대로).

### 시간 측정 구조 (요청 반영)
- verify.py: **단계별 경과 시간 출력 + `--no-smoke`** (개발 루프:
  유닛 테스트 + corpus_verify + assemble만. 풀 체인은 마일스톤에서만
  — 스모크가 56MB 스토리 로드로 수 분이 지배 비용). 스모크 Enter
  클릭 타임아웃 30s → 120s.

### 배치 검증 (실측)
- 10 passage: 10/10 성공 (1차), 재실행 시 전 유닛 재사용 (API 0).
- 100 passage (stage-1): 92/100 성공 + 어셈블러 거부 2건 재번역 완료.
  실패 8건 (reorder 1 + skeleton_mismatch 7 — 고난도 패턴,
  저널 `tmp/journals/req_20260808_006.jsonl` → 재던지기 대상).
  실패 유닛 76건 중 75건 flash 승격으로 회복.
- 지속 관찰: placeholder_drop이 lite에서 빈번 (중첩 매크로 보호로
  유닛당 토큰 밀도 상승) — flash 승격이 대부분 회복. 승격 모델 의존도
  높음, 비용은 유닛당 1회 추가 호출 수준.

### 스모크/검증 체인
- 223개 테스트 통과, corpus_verify baseline matched,
  어셈블 verify_failed 0 (풀 체인은 마일스톤에서 재실행 예정).
