# HANDOFF — 세션 이관 문서

기준일: 2026-08-08

## 현재 상태 요약

```text
CST 파서 (완료) → value-kind 분류 (완료, unclassified 0)
  → 청킹 (완료, failures 0) → 파일럿 번역 (P1 확대 완료, 99.0%)
  → post 시스템 (PO1 파이프라인 통합 완료) → 번역 재사용 (다음 단계)
```

- 전체 corpus: 642 files / 16,135 passages, round-trip 0, tree invariants 0
- diagnostics: unclassified 0, unknown_macro 238 (exit 계열 미해결)
- 노출: link_label 39,157 / macro_arg 1,768 / plain_text 759,058
- 파일럿: Gemini 2.5 Flash Lite + ADC, placeholder 보존 99.0% (207/209, P1 확대),
  restore 정상. `<000000>` XML 태그 형식 (96%→100%→99.0%)
- post: `translation/post.py` 파이프라인 통합 — adhoc 잔존 0, 정적 치환 동작,
  표 외 마커는 런타임 보존. 테스트 143개 통과
- 3-match 재사용: `work/translations/ko-reuse.jsonl` 3,151건 등록 (Git 제외),
  파일럿 `--store` passage-level 재사용 실측
- unknown_macro: 238 → 6 (exit/exitAll 엔진 패치 + SC 누락 보완, baseline 갱신)
- 테스트 132개 통과, corpus_verify exit 0 (baseline matched)

## 이관 전 확인 사항 (미해결)

### 기능/조사 (해결 필요)

- [ ] **3-match 재사용** — **완료 (2026-08-08)**: R1~R4 구현,
  3,151건 등록 (`work/translations/ko-reuse.jsonl`), 파일럿 `--store`로
  passage-level 재사용 실측. 마커 있는 56%는 post 정적 치환 후 등록 예정.
  (`docs/translation-reuse-design.md`)
- [ ] **post 런타임 helper** — `{{post:...}}` 동적 마커 치환 (게임 사이드).
  설계만. 표 외 마커(이/아) 처리를 위해 `trPostsList` 전체 테이블 필요.
  (`docs/post-system-design.md` PO2)
- [ ] **exit/exitAll 매크로** — **해결 (2026-08-08)**: 엔진 패치 매크로로
  판명 (컴파일 빌드에서 `Macro.add(["exit","exitAll"])` 검증, `Wikifier.stopWikify`
  1/2 제어). grammar + audit allowlist + collect_known_macro_names 등록,
  WIDGET_NAME_RE 인용부호 없는 위젯 지원, SC leaf 매크로 7종 누락 보완.
  unknown_macro 238 → 6 (잔여는 게임 오타 1 + ModLI 미정의 5건).
  (`docs/g-l-macro-investigation.md` S2)
- [ ] **placeholder 뒤 단일 추측 조사 대응** — P1 확대에서 combat 78건,
  gwylan 110건 관찰. 프롬프트 강화 또는 검출-재시도. (`docs/archive/pilot-report.md`)
- [ ] **NPC 인명 glossary** — Gwylan 5가지 표기 비일관. 후순위.
- [ ] **시맨틱 롤 판정** — 파일럿 결과로 "불필요" 잠정 결론. 매크로 조각
  조립 사례는 수동 보정 가능 수준 (P1 수집됨). 사례 확산 시 재검토.

### 유지보수 체크 (우선순위 낮음)

- [ ] **F2/F3 회귀 fixture** — passage JSON 메타데이터, square 중첩.
  DoL 원문 0건이지만 회귀 방지용 fixture 미추가. (`docs/archive/system-review-triage.md`)
- [ ] **placeholder prefix 인플레이션** — `_merge` 충돌 시 일부 토큰만 길어짐.
  발동 확률 낮음. (`docs/archive/system-review-triage.md` F10)
- [ ] **`_merge_small_units` ancestors** — 병합 시 한쪽 경로만 남음. 낮음. (F9)
- [ ] **TextSource char 단위 encode** — 최적화 여지. 프로파일링 후 결정. (F11)

### 데이터 (후순위)

- [ ] props/색상/식물 glossary — clothing 외 분야 미구축
- [ ] glossary의 `display_ko` 변경 시 post 재계산 규칙 문서화

## 사용 방법 (빠른 참조)

```bash
uv sync --extra dev                                   # 환경
uv run python -m unittest discover -s tests           # 테스트 (132개)
uv run python -m pretranslation_cst.corpus_verify --root game   # corpus 검증
uv run python -m translation.pilot --batch --max-units 5        # 파일럿 배치
uv run python -m pretranslation_cst.macro_audit audit           # 매크로 감사
```

- 프로젝트: `adept-elevator-503122-h0`, 모델 `gemini-2.5-flash-lite`
  (`translation/client.py` 상수)
- ADC: `gcloud auth application-default login`
- 모든 산출물은 `/tmp/opencode/`에 저장 (repo Git 제외)

## 문서 구조

- **정본** (`docs/`): cst-scope, sugarcube-ground-truth, value-kind-policy,
  validation
- **현행** (`docs/`): chunking-strategy, post-system-design,
  translation-reuse-design, translation-pipeline-roadmap,
  g-l-macro-investigation, triple-match-and-post
- **아카이브** (`docs/archive/`): 완료 기록 (로드맵·워커 지시·감사·트리아지)
- **조사 자료** (`research/`): 근거·데이터셋 (Git 제외)

## 주의

- `research/`, `game/`, `ref/`, `corpus-verify-report.json`은 Git 제외.
- `config/glossary.yml` — clothing glossary (1,459 approved, post 계산됨).
- 워커 에이전트 지시문 양식은 `docs/archive/parser-followup-agent-tasks.md` 참고.