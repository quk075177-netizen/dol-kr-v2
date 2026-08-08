# HANDOFF — 세션 이관 문서

기준일: 2026-08-08

## 현재 상태 요약

```text
CST 파서 (완료) → value-kind (완료) → 청킹 (완료) → P1 파일럿 확대 (완료, 99.0%)
  → post PO1 (통합 완료) → 3-match 재사용 (3,151건 등록)
  → 빌드/스모크 체인 (verify.py, 전 구간 통과)
  → Gemini 풀패시지 러너 (구현 + 리뷰 반영 완료, 실측 1 passage)
```

- 전체 corpus: 642 files / 16,135 passages, round-trip 0, tree invariants 0
- diagnostics: unclassified 0, unknown_macro 6 (게임 오타 1 + ModLI 미정의 5)
- 노출: link_label 39,157 / macro_arg 1,768 / plain_text 759,058
- placeholder 형식: `<000000>` XML 태그 (restore = 순서 치환, 토큰 1회 필수)
- 테스트: **167개 통과**, corpus_verify baseline matched

## 스토어 (번역 레코드, Git 제외)

`work/translations/ko-reuse.jsonl` — 3,152 레코드 (ko_reuse 3,151 + gemini 1):

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
  "repaired": false          // gemini 전용: 스팬 분리자 갭 복구 여부
}
```

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
  (실측 3,033/16,133 = 18.8% — 번역 커버리지 반영) + pageerror/console 검사
- 실측: 3,152 passage 어셈블(1:50) → 컴파일(~2s) → 스모크(~6s) 통과
  (pageErrors 0, text mismatch 0)
- 주의: 위젯 passage는 컴파일 후 Story에 없음 (passage-list에서
  exists=False는 통과 허용)

## Gemini 풀패시지 러너

```bash
uv run python -m translation.translate_passages \
  --file game/overworld-town/loc-cafe/main.twee --passage-name "Ocean Breeze"
# 배치: --passages-file targets.jsonl  ({"source_path","passage_name"} 행)
# 옵션: --force 재번역, --request-id, --debug-dir 실패 덤프, --game-root
```

- 흐름: 유닛 번역(placeholder 재시도 3회 내장) → post_process →
  `repair_separator_newlines`(스팬 분리자 갭 결정적 복구) →
  `verify_malformed_post_markers` → restore → 시그니처 검증 → 레코드 저장
- 실패 사유: skipped / placeholder_drop / malformed_post_marker /
  restore_failed / skeleton_mismatch / exception:<...>
- `--debug-dir`: 실패 시 유닛별 masked/translated 덤프 (재번역 없이 분석)
- API 재시도 3회+backoff (client._generate), 배치 per-passage 예외 격리
- 실측: Ocean Breeze(22유닛) → 스토어 → 어셈블 → 컴파일 → 스모크 전 구간
  통과, repaired=True (갭 복구 발생)
- request_id 자동: `req_<yyyymmdd>_<seq>` (KST, 스토어 최대 seq + 1)

## 이관 전 확인 사항 (미해결)

### 기능 (다음 단계, docs/followup-work.md)

- [ ] **유형별 배치 번역** — `--passages-file`로 대표 passage 묶음.
  전투(561유닛)·설정(331유닛) 대형 passage 성능/실패율 관측 (L2 도입 판단
  데이터). 마커 있는 56% 등록 → 전체 corpus 순으로 확장.
- [ ] **post 런타임 helper (PO2)** — `{{post:...}}` 동적 마커 치환 (게임
  사이드). 표 외 마커(`이`/`아`/`의`/`한` 등) 처리를 위해 `trPostsList`
  전체 26개 조사 테이블 필요. (`docs/post-system-design.md` PO2)
- [ ] **마커 있는 3-match 4,037 passage 등록** — `【 】`→`{{post:...}}`
  정규화 후 정적 치환분 resolve, 동적분은 런타임 대상으로 등록
- [ ] **단일 추측 조사 검출** — placeholder 뒤 단일 조사(combat 78건/
  gwylan 110건 관찰). 검출 → 리뷰 플래그 (자동 재번역 아님).
- [ ] **R2 unit-level 재사용 연동** — 번역 배치 내 동일 문장 hash hit
  (`docs/translation-reuse-design.md`)

### 데이터/품질 (후순위)

- [ ] NPC 인명 glossary (Gwylan 5표기 비일관), props/색상/식물 glossary
- [ ] JS 문자열 번역 (기존 KO JS 9,373건 대조 — 빌드 체인에 JS 치환 단계)
- [ ] H5 스모크 셀렉터 분리, Q3 체크 카테고리(번역/회귀) 분리, Q5 store
  level 통일 (docs/implementation-feedback.md §8 미반영분)
- [ ] `_get_model` 캐시 개선 (다중 모델 혼용 시) (docs/translate-runner-feedback.md §9)

### 유지보수 체크 (우선순위 낮음)

- [ ] F2/F3 회귀 fixture, F10 placeholder prefix 인플레이션, F9
  `_merge_small_units` ancestors, F11 TextSource 최적화
  (`docs/archive/system-review-triage.md`)

## 사용 방법 (빠른 참조)

```bash
uv sync --extra dev                                   # 환경
uv run python -m unittest discover -s tests           # 테스트 (167개)
uv run python -m pretranslation_cst.corpus_verify --root game   # corpus 검증
python3 build/verify.py                               # 어셈블→컴파일→스모크 (~2분)
uv run python -m translation.register_ko_reuse        # 3-match KO 재등록 (43s)
uv run python -m translation.translate_passages --file <f> --passage-name <p>
uv run python -m translation.pilot --batch --max-units 5        # 파일럿
uv run python -m pretranslation_cst.macro_audit audit           # 매크로 감사
```

- 프로젝트: `adept-elevator-503122-h0`, 모델 `gemini-2.5-flash-lite`
  (`translation/client.py` 상수)
- ADC: `gcloud auth application-default login`
- 모든 산출물은 `/tmp/opencode/`에 저장 (repo Git 제외)

## 문서 구조

- **정본** (`docs/`): cst-scope, sugarcube-ground-truth, value-kind-policy,
  validation, translation-reuse-design (구현됨)
- **현행** (`docs/`): post-system-design, translation-pipeline-roadmap,
  g-l-macro-investigation, chunking-strategy
- **피드백/제안** (`docs/`): implementation-feedback.md (빌드 체인),
  translate-runner-feedback.md (러너), followup-work.md (후속 제안)
- **아카이브** (`docs/archive/`): 완료 기록 (파일럿 보고, 트리아지 등)
- **조사 자료** (`research/`): 근거·데이터셋 (Git 제외)

## 주의

- Git 제외: `research/`, `game/`, `ref/`, `game_ko/`, `build/*.html`,
  `build/*.build.json`, `build/browser-smoke/`, `.cache/`, `work/`
  (레코드 스토어 포함 — 재등록/재번역으로 재생성 가능)
- 커밋 대상 도구: `build/dol_build.py`, `build/verify.py`,
  `build-tools.lock.json`, `browser_smoke.*`, `translation/*.py`
- `config/glossary.yml` — clothing glossary (1,459 approved, post 계산됨)
- 리뷰 반영 이력: implementation-feedback.md §8 (빌드 체인),
  translate-runner-feedback.md §9 (러너)
- 워커 에이전트 지시문 양식은 `docs/archive/parser-followup-agent-tasks.md` 참고
