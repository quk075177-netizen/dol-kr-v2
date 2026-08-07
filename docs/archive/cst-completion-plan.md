# CST 완성 진행 계획

기준일: 2026-08-07
완료일: 2026-08-07

`docs/implementation-roadmap.md`의 1~6단계는 최초 기능 범위 구현을 [완료]했다.
그러나 해당 문서의 주석과 `docs/parser-remediation-roadmap.md`가 명시하듯, 그것은
추출 품질까지 완료되었다는 뜻이 아니다. 이 문서는 CST 완성을 위해 남은 작업과
실행 순서, 그리고 워커 에이전트에 위임 가능한 작업의 지시문 양식을 정한다.

정책의 정본은 여전히 `docs/cst-scope.md`, `docs/sugarcube-ground-truth.md`,
`docs/value-kind-policy.md`, `docs/validation.md`다. 이 문서는 실행 계획이며
정책을 대체하지 않는다.

## 최종 기준선 (2026-08-07, T1+T2+T3 완료 후)

`python3 -m pretranslation_cst.corpus_verify --root game` 실행 결과:

- files 642 (passage 있는 파일 639, 빈 파일 3), passages 16,135,
  bytes 34,107,861
- round-trip 0 failures / 642 files, 16,135 passages (split·reassembly·restore 0)
- tree invariants 0 failures
- diagnostics 총 28:
  - `unclassified_argument` 18 (parsed positional schema residual)
  - `invalid_macro_name` 5, `malformed_macro` 1, `unclosed_container` 2,
    `unterminated_comment` 2 (전부 allowlist 매칭된 source 결함)
- segments: `link_label` 32,908, `macro_arg` 952, `plain_text` 496,421
  / exposed 530,281, placeholders 528,336
- coverage mean 0.674121, protected 22,698,784 / 33,671,688 bytes
- baseline `corpus-baseline-v1.json` 일치, 회귀 없음, exit code 0
- 2회 실행 JSONL byte-identity 확인 (SHA-256 동일)

세 완료 계약(`parser-remediation-roadmap.md` 완료 정의) 상태:

1. **Lossless** — 만족. 원본 bytes와 모든 span 보존, 2회 실행 byte-identity.
2. **Structural** — 만족. registry-driven tree, 잘못된 close/branch 0.
3. **Extraction** — 만족. standalone markup과 string-form link 모두 tree에
   연결되어 parent context를 가지고, value-kind residual은 18건으로
   수렴했다.

## 완료된 작업

### T1. standalone markup → CST leaf 통합 (commit 8098f0c)

passage 본문의 standalone `[[...]]`/image markup을 `passage_root`(또는 활성
container/branch) 아래 `protected_markup` node로 배치. 정적 display label이면
`link_label` `prose_text` leaf 자식을 추가. exposure/protected를 tree에서 단일
파생하도록 `_collect_markup`의 standalone-square 분기를 제거.

완료 기준:

- standalone link label이 `link_label` leaf로 노출되고 `get_ancestors`로
  parent에 도달 가능.
- 동적 label은 노출되지 않음 (false positive 0건 확인).
- `link_label` 32,728 → 32,796 (+68, container 본문 안 과소 노출 정정).

### T2. value-kind schema residual 정리 (commit b5e9da1)

891개 residual macro/index를 근거(call/definition) 기반으로 분류.
`config/macro-value-kind.yml`을 605개 → 대폭 보강해 `unclassified_argument`를
20,855 → 18로 감소(99.9%). raw expression macro는 제외. 노출은 prose_text
string literal에만 적용.

### T3. string-form `<<link "Label" "Target">>` 노출 정책 (commit b5e9da1)

정책 A 적용: `link`/`button` 첫 인자가 string literal이고 동적 마커(`$`,
`_`, backtick, `${`, `+`)가 없으면 `link_label`로 노출. 동적 8건은 보호 유지.

- `link_label` 32,796 → 32,908 (+112).
- square-form과 동일 정책으로 일관성 확보.

### 테스트 경량화 A (commit b5e9da1)

`_extract_game_js_calls_cached`(`lru_cache(maxsize=64)`)를 두어
`extract_game_specs`와 `extract_game_dynamic`이 동일 game JS 파싱 결과를 공유.
테스트 4.96s → 1.33s (73% 감소). audit·corpus_verify 영향 없음.

## 값-kind residual 최종 상태

T2 워커가 891개 residual macro/index를 근거(call/definition) 기반으로
분류했다. `unclassified_argument`는 20,855 → 18로 수렴했고, 남은 18건은
실제 parsed positional schema gap이다. `set`/`run`/`print`/`if`/`elseif`/`for`/
`unset`/`=` 등 raw expression macro는 상위 진단에 남지 않는다. residual
보고서는 `docs/macro-value-kind-residual-report.md`를 참조.

## 실행 순서 (완료)

```
T1 진행 (직접)            ✓ commit 8098f0c
  └─ corpus_verify exit 0 ✓
        ├─ T2 워커 위임   ✓ commit b5e9da1  (unclassified 20,855 → 18)
        └─ T3 결정+구현   ✓ commit b5e9da1  (link_label +112)
                └─ 전 corpus 2회 실행 byte-identity ✓  (SHA-256 동일)
```

각 단계는 round-trip 전수 검증을 통과했다. 진단 감소와 번역 segment 증가는
해당 단계의 구조 assertion이 함께 통과할 때만 개선으로 인정했다.

## 워커 에이전트 지시문 양식

워커에 위임 가능한 작업을 넘길 때는 아래 양식을 따른다. 양식은
`docs/parser-followup-agent-tasks.md`의 공통 기준과 각 Agent 지시문 구조를
합친 것이다.

```text
# 워커 에이전트 지시문: <작업 제목>

기준: <선행 작업 또는 기준일>

## 공통 기준 (아래를 생략하지 말 것)

- 정본 입력은 game/**/*.twee다.
- 기존 /tmp/opencode/*.jsonl은 덮어쓰지 않는다.
- 모든 변경은 python3 -m unittest discover -s tests -v 를 통과해야 한다.
- 전 corpus 검증은 python3 -m pretranslation_cst.corpus_verify --root game
  --report <경로> 로 재현하며, exit code 0이어야 한다.
- parser 변경이 필요한 새 결함을 발견하면 우회 수정하지 말고 source, passage,
  macro, byte span, 최소 fixture와 함께 보고한다.
- 완료 보고에는 before/after diagnostic 및 exposed segment count를 포함한다.
- set, run, print, =, -, if, elseif, for, unset은 raw expression이다.
  이들의 공백 token을 value-kind positional argument로 등록하지 않는다.
- 실패하면 prose로 추정하지 않고 보호 span과 진단을 남긴다.
- 담당 범위 밖 parser refactor를 하지 않는다.
- 문서 정책(docs/cst-scope.md, docs/sugarcube-ground-truth.md,
  docs/value-kind-policy.md, docs/validation.md)과 충돌하면 문서를 우선한다.

## 담당 파일

- <파일 경로>
- ...

## 수정 금지

- <파일 경로>
- ...

## 지시

<구체적 작업 내용. 정본 근거, 대상 범위, 우선순위, 처리하지 말 것을 명시.>

## 완료 기준

- <검증 가능한 조건. before/after 수치, assertion, exit code 등.>

## 보고 형식

- before/after diagnostic 및 exposed segment count (link_label, macro_arg,
  plain_text)
- corpus_verify exit code
- 남은 residual 목록 (해당하는 경우)
- 우회 수정하지 않은 새 결함 (발견 시 source/passage/macro/span/fixture)
```

### 위임 대상 작업 매핑

| 작업 | 상태 | 근거 지시문 |
|---|---|---|
| T1 standalone markup 통합 | 완료 (직접, 8098f0c) | 구조 변경, 회귀 위험 낮 |
| T2 value-kind residual | 완료 (워커, b5e9da1) | `parser-followup-agent-tasks.md` Agent 1 + residual 보고서; `worker-t2-value-kind-residual.md` |
| T3 정책 결정+구현 | 완료 (설계자 결정 A + 워커 구현, b5e9da1) | square-form과 동일 정책 |

## 하지 않을 수정

`parser-remediation-roadmap.md`의 "하지 않을 수정"을 그대로 따른다:

- `_lex_args` bareword loop에 quote/bracket 예외만 추가하지 않는다.
- `set`/`if`의 공백 token index를 YAML에 대량 등록하지 않는다.
- 특정 매크로 한 이름만 self-closing 예외로 두지 않는다.
- `CONTAINER_NAMES`에 발견된 이름을 계속 수동 추가하지 않는다.
- macro span 내부를 global regex로 재검색해 link label만 꺼내지 않는다.
- round-trip 통과만으로 parser 품질 완료를 선언하지 않는다.

## 완료 정의

`parser-remediation-roadmap.md` 완료 정의를 그대로 따른다. 세 계약이 동시에
성립해야 CST 완성으로 본다.

1. Lossless: 원본 bytes와 모든 span이 보존된다. — **만족** (round-trip 0, byte-identity)
2. Structural: runtime macro grammar와 CST container/argument 구조가 일치한다. — **만족** (registry-driven tree, mismatched_close 0)
3. Extraction: 노출 가능한 leaf가 독립 census와 일치하고 parent context를 가진다. — **만족** (standalone·string-form 모두 tree에 leaf로 연결, residual 18건 수렴)

세 계약이 모두 성립한다. CST 완성.