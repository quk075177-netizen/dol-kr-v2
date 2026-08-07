# CST 완성 진행 계획

기준일: 2026-08-07

`docs/implementation-roadmap.md`의 1~6단계는 최초 기능 범위 구현을 [완료]했다.
그러나 해당 문서의 주석과 `docs/parser-remediation-roadmap.md`가 명시하듯, 그것은
추출 품질까지 완료되었다는 뜻이 아니다. 이 문서는 CST 완성을 위해 남은 작업과
실행 순서, 그리고 워커 에이전트에 위임 가능한 작업의 지시문 양식을 정한다.

정책의 정본은 여전히 `docs/cst-scope.md`, `docs/sugarcube-ground-truth.md`,
`docs/value-kind-policy.md`, `docs/validation.md`다. 이 문서는 실행 계획이며
정책을 대체하지 않는다.

## 현재 기준선 (2026-08-07, 직접 검증)

`python3 -m pretranslation_cst.corpus_verify --root game` 실행 결과:

- files 642 (passage 있는 파일 639, 빈 파일 3), passages 16,135,
  bytes 34,107,861
- round-trip 0 failures / 642 files, 16,135 passages (split·reassembly·restore 0)
- tree invariants 0 failures
- diagnostics 총 20,865:
  - `unclassified_argument` 20,855 (parsed positional schema gap)
  - `invalid_macro_name` 5, `malformed_macro` 1, `unclosed_container` 2,
    `unterminated_comment` 2 (전부 allowlist 매칭된 source 결함)
- segments: `link_label` 32,728, `macro_arg` 715, `plain_text` 496,421
  / exposed 529,864, placeholders 527,919
- coverage mean 0.674121, protected 22,698,784 / 33,671,688 bytes
- baseline `corpus-baseline-v1.json` 일치, 회귀 없음, exit code 0

세 완료 계약(`parser-remediation-roadmap.md` 완료 정의) 상태:

1. **Lossless** — 만족. 원본 bytes와 모든 span 보존, 2회 실행 byte-identity.
2. **Structural** — 만족. registry-driven tree, 잘못된 close/branch 0.
3. **Extraction** — 부분 만족. census 수치는 독립 inventory와 일치하지만,
   standalone `[[...]]`가 tree에 연결되지 않아 parent context를 잃는 경로가
   남아 있고, value-kind schema gap 20,855건이 residual 검토 큐로 처리되지
   않았다.

## 남은 작업

roadmap 단계 4~5의 잔여. 세 작업으로 좁혀진다. 순서는 아래 실행 순서를
따른다.

### T1. standalone markup → CST leaf 통합

roadmap 단계 4 잔여. 회귀 위험 낮고 parent context 신뢰성에 직결.

현재 `pretranslation_cst/parser.py`의 `_collect_markup`은 passage 본문의
standalone `[[...]]`/image markup을 `passage.exposed_candidates`와
`passage.protected_spans`에 직접 넣고, tree에는 반영하지 않는다. 반면 macro
인자의 square markup은 `_attach_argument_nodes`가 tree에 `protected_markup`
node로 붙인다. 결과적으로 exposure가 "tree 순회"와 "global rescan" 두 경로로
섞여, standalone link label은 parent macro/branch를 조회할 수 없다.

목표:

- standalone `[[...]]`/image markup을 `passage_root`(또는 활성
  container/branch) 아래 `protected_markup` node로 배치.
- 정적 display label이면 `link_label` `prose_text` leaf 자식을 추가.
- 동적 label(`$`, `_`, backtick, `${...}`, `+`), target, setter, image는
  leaf 없이 보호.
- macro span·definition opaque span은 ignored 영역으로 스킵(기존 동작 유지).
- exposure/protected를 tree에서 단일 파생하도록 `_collect_markup`의
  standalone-square 분기를 제거하고 `_collect_tree_exposure`가 `link_label`
  leaf를 노출.

완료 기준(`parser-remediation-roadmap.md` 단계 4 + `validation.md`):

- standalone `[[Next|Target]]`의 `Next`가 `link_label` leaf로 노출되고,
  `get_ancestors`로 `passage_root`에 도달할 수 있다.
- 동적 label은 노출되지 않는다.
- census `link_label` 32,728 / `macro_arg` 715 / `plain_text` 496,421 유지.
- overlapping span 없이 mask/restore byte-exact.
- `corpus_verify` exit code 0, baseline 일치.

영향 파일:

- `pretranslation_cst/parser.py` (`_collect_markup`, `_build_tree`,
  `_collect_tree_exposure`, `parse_passage`)
- `tests/test_pretranslation_cst.py` (standalone link parent, 동적 label,
  macro 안 link, round-trip)

이 작업은 구조 변경이고 회귀 위험이 낮으므로 직접 진행한다. 아래 워커 지시문은
참고용으로 남긴다.

### T2. value-kind schema residual 정리

roadmap 단계 5. 진단 건수 감소에 직결되지만 원문 근거 조사가 많이 필요.
워커 에이전트에 위임한다. 지시문은 `docs/parser-followup-agent-tasks.md`
Agent 1을 따르되, residual 보고서(`docs/macro-value-kind-residual-report.md`
상위 891개 macro-index rows)를 입력으로 삼는다.

완료 기준(`parser-remediation-roadmap.md` 단계 5):

- `unclassified_argument`가 parsed positional argument의 실제 schema gap만
  뜻한다.
- `set`, `run`, `print`, `if`, `elseif`, `for`, `unset`, `=`가 상위 진단에
  남지 않는다 (이미 달성).
- residual 항목은 macro/index별 검토 큐로 직접 사용할 수 있다.
- round-trip과 기존 노출 segment가 감소하지 않는다.

T1 완료 후 병렬로 시작할 수 있다.

### T3. string-form `<<link "Label" "Target">>` 노출 정책 결정

roadmap 단계 4의 명시적 결정 항목. town에 11건으로 소수지만 전 corpus 정책이므로
결정 + fixture가 필요하다. 현재 첫 인자 보호 상태. roadmap/Agent 3 지시는
"승인되지 않았다면 동작을 바꾸지 마라".

이 작업은 결정 본체이므로 워커가 아닌 설계자 결정이 필요하다. 결정 후 fixture
추가와(필요하면) config 보강은 워커에 위임 가능하다.

## 실행 순서

```
T1 진행 (직접)
  └─ 완료 후 corpus_verify exit 0 확인
        ├─ T2 워커 위임 (병렬 시작 가능)
        └─ T3 결정 요청 (설계자)
                └─ 결정 후 fixture/config 보강 워커 위임
                        └─ 전 corpus 2회 실행 byte-identity 최종 확인
```

각 단계는 round-trip 전수 검증을 통과해야 다음으로 넘어간다. 진단 감소와 번역
segment 증가는 해당 단계의 구조 assertion이 함께 통과할 때만 개선으로 인정한다.

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

| 작업 | 위임 | 근거 지시문 |
|---|---|---|
| T1 standalone markup 통합 | 직접 진행 (구조 변경, 회귀 위험 낮) | 위 양식의 "지시" 항목에 T1 세부 계획을 채우면 워커용으로 전용 가능 |
| T2 value-kind residual | 워커 위임 | `parser-followup-agent-tasks.md` Agent 1 + residual 보고서 |
| T3 정책 결정 | 설계자 결정, fixture/config 보강은 워커 위임 가능 | 위 양식에 결정된 정책을 "지시"에 명시 |

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

1. Lossless: 원본 bytes와 모든 span이 보존된다.
2. Structural: runtime macro grammar와 CST container/argument 구조가 일치한다.
3. Extraction: 노출 가능한 leaf가 독립 census와 일치하고 parent context를 가진다.

세 계약 중 하나라도 빠지면 fail-safe masking은 동작하더라도 번역 전처리
파서로는 완료된 것으로 보지 않는다.