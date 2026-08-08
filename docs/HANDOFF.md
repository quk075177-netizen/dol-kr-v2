# HANDOFF — 세션 이관 문서

기준일: 2026-08-08

## 현재 상태 요약

```text
CST 파서 (완료) → value-kind (완료) → 청킹 (완료) → P1 파일럿 확대 (완료, 99.0%)
  → post PO1 (통합 완료) → 3-match 재사용 (3,151건 등록)
  → 마커 있는 3-match 등록 (완료, +3,978건 — 커버리지 43.5%)
  → 빌드/스모크 체인 (verify.py, 전 구간 통과)
  → Gemini 풀패시지 러너 (구현 + 리뷰 반영 완료, 배치 관측 2회차)
  → L2 유닛 구조 조기 검사 (구현 완료, 쌍체 비교 실측)
  → L2 2차 수정 (사유 버그/덤프 보강/토큰 일반화/프롬프트/추적 필드/
      prose_drop) + 지뢰 분석 (구조적 특징 기각)
  → 모델 티어 대조 실험 (결정적 유닛 3개: 티어 문제 1 + 승격+L2 해결 1
      + 콘텐츠 난이도 1 — 3단계 에스컬레이션 근거)
  → 리오더 원인 규명 (한국어 어순 자연화 — 표시 전용 매크로의 재배치)
  → Option E 구현 (순서 민감도 화이트리스트 — ProtectedSpan(kinds) +
      order_sensitive, L2/L3 완화, 등록/어셈블러 엄격 유지)
  → 배치 번역 + 유닛 승격 에스컬레이션 (lite 베이스 + flash 승격,
      Farm Work 100유닛 성공 실측)
  → 2티어 실패 정책 (L3 = 경계 검사로 유닛 승격, 전체 재시도 없음)
      + 스트리밍 저널 (--journal)
  → 버그 2건 수정 (repair 순서 무관화, 마커 오타 유닛 승격) — Farm
      Work 4·5차 연속 성공으로 안정성 확인
  → fail 로그 재설계 (재던지기 큐 + journal_rerun) + 유닛 스토어
      (청킹 유닛 단위 1줄씩 스트리밍) + store_view 뷰어
```

- 전체 corpus: 642 files / 16,135 passages, round-trip 0, tree invariants 0
- diagnostics: unclassified 0, unknown_macro 6 (게임 오타 1 + ModLI 미정의 5)
- 노출: link_label 39,157 / macro_arg 1,768 / plain_text 759,058
- placeholder 형식: `<000000>` XML 태그 (restore = 순서 치환, 토큰 1회 필수)
- 테스트: **213개 통과**, corpus_verify baseline matched
- 스모크 한국어 커버리지: **7,013/16,133 = 43.5%** (마커 등록 전 18.8%)

## 유닛 스토어 (추적/재사용, Git 제외)

`work/translations/ko-units.jsonl` — 청킹 유닛 단위 1줄씩 스트리밍 기록
(러너 기본, `--units-store`). passage 실패 시에도 완료 유닛 보존.
`source_text_hash` = 복원 원문 유닛 hash — R2 unit-level 재사용 키.
스키마: `docs/store-schema.md` 유닛 스토어 섹션.

## 스토어 (번역 레코드, Git 제외)

`work/translations/ko-reuse.jsonl` — **7,140 레코드** (ko_reuse 7,137
= 마커 없음 3,157 + 마커 있음 3,978 + 선존 2, gemini 3):

```json
{
  "record_id": "tr_<hash12>_ko | tr_<hash12>_gemini",
  "source_text_hash": "sha256(source_text)",
  "source_text": "<원본 passage body, 경계 개행 포함>",
  "translated_text": "<KO body — ko_reuse는 match_boundaries()로 개행 정규화됨>",
  "source_path": "game-root 상대경로 (overworld-town/..., game/ 접두어 없음)",
  "passage_name": "...", "unit_id": "...", "request_id": "req_<yyyymmdd>_<seq>",
  "model": "ko_reuse | gemini-2.5-flash-lite", "temperature": null | 0.7,
  "created_at": "KST ISO", "placeholder_ok": true,
  "post_status": "static_done | runtime_remaining | none",
  "source": "ko_reuse | gemini", "level": "passage",
  "repaired": false,          // gemini 전용: 스팬 분리자 갭 복구 여부
  "escalated": true|false,    // gemini 전용: 승격/2차 시도 사용 여부
  "escalated_units": 0,       // gemini 전용: 유닛 승격 횟수
  "tier": "base | escalated"  // gemini 전용: 최종 사용 티어
}
```

- 마커 있는 3-match 등록 (2026-08-08): 4,037 passage 중 3,978 등록
  (post_status=runtime_remaining 3,983 전체 — 레거시 마커 전량이 런타임
  값 앞, 정적 치환 0건), 퇴출: skeleton_mismatch 58 + macro_sequence_mismatch 9
- 등록 검증 보강: `macro_sequence` 검사 (링크 라벨 내부 매크로 드롭 감지 —
  파서 시그니처 검사 갭), 멱등성 (already_registered), post_status 정확화
  (마커 잔존 = runtime_remaining)
- 잔여 이슈: state=empty/excluded 595건 중 ko_body≈source_body(영어
  그대로) 90건 — find_passage_reuse 블로커. 후순위 정리.
- 스키마 정본: `docs/implementation-feedback.md` §3.1, `docs/translation-reuse-design.md`
- 어셈블러/러너/스모크는 이 파일만 읽음. **다른 소스(JS 등) 레코드는
  같은 스키마로 추가하면 자동 반영.**

## 빌드/스모크 체인

```text
work/translations/ko-reuse.jsonl → translation/assemble_game_ko.py → game_ko/
  → build/dol_build.py compile → build/dol-plus-ko.html
  → browser_smoke.py run --passage-list → build/browser-smoke/report.json
```

- **단일 커맨드**: `python3 build/verify.py` (어셈블→컴파일→스모크→레포트,
  ~2분. 옵션: --no-assemble/--no-compile/--expect-options-text/
  --min-korean-ratio)
- 어셈블러: 트리 복사 + body span 스플라이스, 드리프트 검증,
  [widget]/[script]/[stylesheet] 제외, 경계 개행 보존, 매크로 시퀀스 +
  보호 스팬 시그니처 재검증, ProcessPoolExecutor 병렬, staging 원자 스왑
- passage-list: 어셈블러 `--emit-passage-list` 자동 생성
  (`build/browser-smoke/passage-list.tsv`)
- 스모크: UI 7종 + passage-list 전수(textMatch) + 한국어 포함 비율
  (실측 7,013/16,133 = 43.5% — 번역 커버리지 반영) + pageerror/console 검사
- 실측: 3,152 passage 어셈블(1:50) → 컴파일(~2s) → 스모크(~6s) 통과
  (pageErrors 0, text mismatch 0)
- 주의: 위젯 passage는 컴파일 후 Story에 없음 (passage-list에서
  exists=False는 통과 허용)

## Gemini 풀패시지 러너

```bash
uv run python -m translation.translate_passages \
  --file game/overworld-town/loc-cafe/main.twee --passage-name "Ocean Breeze"
# 배치: --passages-file targets.jsonl  ({"source_path","passage_name"} 행,
#   source_path는 game/ 접두어 포함 — 러너가 game-root 상대경로로 저장)
# 옵션: --force 재번역, --request-id, --debug-dir 실패 덤프, --game-root
```

- 흐름: 유닛 번역(placeholder 재시도 3회 내장) → **L2 검사
  (verify_unit_structure: reorder/foreign_token/format_hallucination/
  prose_drop — 힌트 재시도 최대 2회, 실패 시 유닛 즉시 폐기)** →
  post_process → `repair_separator_newlines`(스팬 분리자 갭 결정적 복구) →
  `verify_malformed_post_markers` → restore → 시그니처 검증(L3, Option E
  완화) → 레코드 저장. L3 실패 시 `boundary_prose_drops`로 경계 유닛 쌍만
  flash 재번역 (전체 재시도 없음 — 2티어 정책, 실패 시 로그만)
- 실패 사유: skipped / placeholder_drop / reorder / foreign_token /
  format_hallucination / prose_drop / malformed_post_marker /
  restore_failed / skeleton_mismatch / exception:<...>
- `--debug-dir`: 실패 시 유닛별 masked/translated 덤프 (재번역 없이 분석)
- API 재시도 3회+backoff (client._generate), 배치 per-passage 예외 격리
- 실측: Ocean Breeze(22유닛) → 스토어 → 어셈블 → 컴파일 → 스모크 전 구간
  통과, repaired=True (갭 복구 발생)
- **배치 관측 (2026-08-08, 유니크 20 passage / 21 runs / 1,317 유닛)**:
  성공 2/21 (9.5%). 실패 모드 4종 — placeholder_drop(결정성: 같은 유닛
  재실패), reorder(skeleton_mismatch), 타 유닛 토큰 환각(restore_failed),
  placeholder 형식 환각(프롬프트 예시 `<000000>`이 7자리 토큰 passage에서
  유발). 관측 리포트: `tmp/reports/batch-p2-1-report.md`,
  덤프 `tmp/debug-dumps/batch-debug/`
- **L2 쌍체 비교 (2026-08-08)**: 기존 실패 passage 5개 재실행 — Farm
  Work(100유닛, reorder) **성공 회복**, Temple Test는 사유 세분화
  (reorder)로 유닛 레벨 적발. 신규 발견: 산문 이동(스팬 병합) — 이후
  `prose_drop`(L2) + `boundary_prose_drops`(L3 경계 승격)로 처리
- request_id 자동: `req_<yyyymmdd>_<seq>` (KST, 스토어 최대 seq + 1)

## 이관 전 확인 사항 (미해결)

### 기능 (다음 단계, docs/followup-work.md)

- [x] **유형별 배치 번역** — 2회차 관측 완료 (유니크 20, 성공 2/21,
      실패 모드 4종 분류). 전투(561유닛)·설정(331유닛)은 [widget] 코드
      passage라 러너가 거절 — 비-위젯 최대 passage로 측정.
- [x] **L2 유닛 구조 조기 검사** — 구현 완료 (verify_unit_structure:
      reorder/foreign_token/format_hallucination/prose_drop, 힌트 재시도
      2회, l2_retries/api_calls 기록). 2차 수정 반영: 재시도 사유 오염
      버그, 덤프 컨텍스트 보강, 토큰 정규식 일반화, 프롬프트 예시 제거.
      **지뢰 분석: 구조적 특징 기각** — 크기 외 예측 변수 없음 (콘텐츠
      난이도). 이후 배치+승격 에스컬레이션으로 전환.
- [x] **Option E (리오더 허용)** — 순서 민감도 화이트리스트
      (`order_sensitivity.py`): 표시 전용 매크로/변수/HTML만 무관,
      미등록은 전부 민감. 실측 5건 전부 허용 분류. 등록/어셈블러는
      엄격 유지.
- [x] **배치 번역 + 승격 에스컬레이션** — `--batch-size 16`(기본),
      L1/L2 실패 유닛 flash 승격, L3는 경계 검사로 유닛 승격.
      2티어 정책 (자동 재시도 종료). 실측: Farm Work(100유닛) 성공
      (배치 7회+승격 24회 ≈33회 호출). 버그 2건 수정 후 4·5차 연속 성공
      (repair 순서 무관화 — Option E 리오더 허용과의 상호작용 버그,
      마커 오타 유닛 승격).
- [ ] **post 런타임 helper (PO2)** — `{{post:...}}` 동적 마커 치환 (게임
  사이드). 표 외 마커(`이`/`아`/`의`/`한` 등) 처리를 위해 `trPostsList`
  전체 26개 조사 테이블 필요. (`docs/post-system-design.md` PO2)
  **주의: 마커 있는 3-match 3,978건이 runtime_remaining으로 등록됨 —
  게임에 `{{post:...}}` 리터럴 표시 중. PO2가 빌드에 들어가기 전까지
  마커 passage는 게임에서 원문 그대로 노출되는 상태.**
- [x] **마커 있는 3-match passage 등록** — 완료 (3,978건 + 검증 보강)
- [x] **ko_reuse 유닛화 — 하지 않기로 결정** (2026-08-08): ko_reuse
  (3-match)는 passage 레코드로 유지, 유닛 스토어는 gemini 전용.
  ko_reuse를 유닛으로 쪼개는 매크로 인덱스 슬라이싱은 복잡도 대비
  이득 없음 — passage 드리프트 시 hash 미스 → 통째로 재번역되며 새
  gemini passage+유닛 레코드로 자연 대체됨 (기존 레코드는 어셈블러
  최신 우선 규칙으로 superseded). 어셈블러 유닛 join 지원 불필요.
- [ ] **단일 추측 조사 검출** — placeholder 뒤 단일 조사(combat 78건/
  gwylan 110건 관찰). 검출 → 리뷰 플래그 (자동 재번역 아님).
- [ ] **R2 unit-level 재사용 연동** — 번역 배치 내 동일 문장 hash hit
  (`docs/translation-reuse-design.md`). 유닛 스토어(`ko-units.jsonl`)의
  `source_text_hash`가 키 — 문장 단위 재사용의 기반 완성

### 데이터/품질 (후순위)

- [ ] NPC 인명 glossary (Gwylan 5표기 비일관), props/색상/식물 glossary
- [ ] JS 문자열 번역 (기존 KO JS 9,373건 대조 — 빌드 체인에 JS 치환 단계)
- [ ] H5 스모크 셀렉터 분리, Q3 체크 카테고리(번역/회귀) 분리, Q5 store
  level 통일 (docs/implementation-feedback.md §8 미반영분)
- [x] `_get_model` 캐시 개선 — genai SDK 전환으로 해소 (get_client 싱글턴,
  모델은 요청별 파라미터)

### 유지보수 체크 (우선순위 낮음)

- [ ] F2/F3 회귀 fixture, F10 placeholder prefix 인플레이션, F9
  `_merge_small_units` ancestors, F11 TextSource 최적화
  (`docs/archive/system-review-triage.md`)

## 사용 방법 (빠른 참조)

```bash
uv sync --extra dev                                   # 환경
uv run python -m unittest discover -s tests           # 테스트 (213개)
uv run python -m pretranslation_cst.corpus_verify --root game   # corpus 검증
python3 build/verify.py                               # 어셈블→컴파일→스모크 (~2분)
uv run python -m translation.register_ko_reuse        # 3-match KO 재등록 (멱등, ~1.5분)
uv run python -m translation.translate_passages --file <f> --passage-name <p> [--model <m>]
uv run python -m translation.store_view --passage <p>   # 레코드 보기 (--last/--hash/--journal)
uv run python -m translation.journal_rerun --journal tmp/journals/req_xxx.jsonl --out rerun.jsonl  # 재던지기 추출
uv run python -m translation.store_view --store work/translations/ko-units.jsonl --passage <p>  # 유닛 스토어 보기
uv run python -m translation.pilot --batch --max-units 5        # 파일럿
uv run python -m pretranslation_cst.macro_audit audit           # 매크로 감사
```

- 프로젝트/인증: **Vertex 백엔드 (genai SDK, `vertexai=True`)** — ADC 사용,
  API 키 불필요. 프로젝트 `GOOGLE_CLOUD_PROJECT` (env), 리전
  `GOOGLE_CLOUD_LOCATION` 기본 **`global`** (gemini-3.x 계열은 이 리전에서만
  가용 — us-central1은 404). 모델 기본 `gemini-2.5-flash-lite` (상수),
  temperature 0.7, 안전 필터: 기본은 미설정(프로바이더 기본) — 명시 시
  `--safety-threshold block-none` 등 (`translation/client.py` SAFETY_THRESHOLDS)
- **배치 번역 (기본)**: `--batch-size 16` (1 = 유닛 단일 호출) — 한 요청에
  items 배열 + response_schema(JSON). 프로토콜 실패(JSON/requestId 불일치)는
  해당 배치 per-unit 폴백. **승격**: L1/L2 실패 유닛은 `--escalation-model`
  (기본 gemini-2.5-flash)로 단일 재시도 — lite의 결정적 드롭 해소. 레코드에
  `escalated`(bool)/`escalated_units`/`tier` 필드. **실패 정책 (2티어)**:
  1차 lite(일시 오류는 동일 티어 재시도 내장) → L1/L2 실패 유닛 flash 승격 →
  L3 skeleton_mismatch는 **경계 검사(`boundary_prose_drops`)로 해당 유닛
  쌍만 flash 재번역** (전체 passage 재시도 없음) → 또 실패 시 실패 로그만
  (자동 재시도 종료, 데이터 모아 추후 재던지기). **저널 (기본 스트리밍)**:
  fail 이벤트(유닛 실패 + 회복 여부)와 passage 결과만 기록 — 기본 경로
  `tmp/journals/req_<request_id>.jsonl`. 종결 실패는
  `journal_rerun`으로 추출해 재던지기 배치 생성. 실측:
  Farm Work(100유닛) 배치 7회+승격 24회 ≈33회 호출로 성공 (per-unit 대비
  ~3배 절감, 드롭 0 수렴)
- 설정: ADC는 `gcloud auth application-default login`
- 관측 산출물은 `tmp/` (README 참조, Git 제외). 원본 백업은 `/tmp/opencode/`

## 문서 구조

- **정본** (`docs/`): cst-scope, sugarcube-ground-truth, value-kind-policy,
  validation, translation-reuse-design (구현됨)
- **현행** (`docs/`): post-system-design, translation-pipeline-roadmap,
  g-l-macro-investigation, chunking-strategy
- **피드백/제안** (`docs/`): implementation-feedback.md (빌드 체인),
  translate-runner-feedback.md (러너 1차), translate-runner-feedback2.md
  (L2 + 배치 관측 2차), observation-analysis-plan.md (리뷰 판정 +
  지뢰 분석 + Option E/배치 승격 실행 기록), **store-schema.md (레코드
  필드 참조 정본)**
- **분석** (루트): `reorder-analysis.md` (리오더 원인 규명 + Option E 설계/실측)
- **아카이브** (`docs/archive/`): 완료 기록 (파일럿 보고, 트리아지 등)
- **조사 자료** (`research/`): 근거·데이터셋 (Git 제외)

## 주의

- Git 제외: `research/`, `game/`, `ref/`, `game_ko/`, `build/*.html`,
  `build/*.build.json`, `build/browser-smoke/`, `.cache/`, `work/`
  (레코드 스토어 포함 — 재등록/재번역으로 재생성 가능), `tmp/`
  (관측 산출물 — README 참조)
- 커밋 대상 도구: `build/dol_build.py`, `build/verify.py`,
  `build-tools.lock.json`, `browser_smoke.*`, `translation/*.py`
- `config/glossary.yml` — clothing glossary (1,459 approved, post 계산됨)
- 리뷰 반영 이력: implementation-feedback.md §8 (빌드 체인),
  translate-runner-feedback.md §9 (러너)
- 워커 에이전트 지시문 양식은 `docs/archive/parser-followup-agent-tasks.md` 참고
