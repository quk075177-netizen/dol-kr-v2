# 워커 에이전트 지시문: T2 value-kind schema residual 정리

기준: T1 standalone markup 통합 완료 (commit 8098f0c), value-kind batch 1 적용 후

## 공통 기준

- 정본 입력은 `game/**/*.twee`다.
- 기존 `/tmp/opencode/*.jsonl`은 덮어쓰지 않는다. 새 산출물은 새 경로에 생성한다.
- 모든 변경은 `python3 -m unittest discover -s tests -v`를 통과해야 한다.
- 전 corpus 검증은 `python3 -m pretranslation_cst.corpus_verify --root game
  --report <경로>`로 재현하며, exit code 0이어야 한다.
- parser 변경이 필요한 새 결함을 발견하면 우회 수정하지 말고 source, passage,
  macro, byte span, 최소 fixture와 함께 보고한다.
- 완료 보고에는 before/after diagnostic 및 exposed segment count를 포함한다.
- `set`, `run`, `print`, `=`, `-`, `if`, `elseif`, `for`, `unset`은 raw
  expression이다. 이들의 공백 token을 value-kind positional argument로
  등록하지 않는다.
- 실패하면 prose로 추정하지 않고 보호 span과 진단을 남긴다.
- 담당 범위 밖 parser refactor를 하지 않는다.
- 문서 정책(`docs/cst-scope.md`, `docs/sugarcube-ground-truth.md`,
  `docs/value-kind-policy.md`, `docs/validation.md`)과 충돌하면 문서를 우선한다.

## 담당 파일

- `config/macro-value-kind.yml`
- `docs/macro-value-kind-residual-report.md`
- `pretranslation_cst/data/corpus-baseline-v1.json`
- `docs/validation.md` (현재 기대값 갱신만)
- value-kind 전용 검증 fixture 또는 보고서

## 수정 금지

- `pretranslation_cst/parser.py`
- `pretranslation_cst/grammar.py`
- `pretranslation_cst/square_markup.py`
- `pretranslation_cst/model.py`
- `pretranslation_cst/data/macro-grammar.json`
- `pretranslation_cst/data/macro-grammar-audit-allowlist.json`
- `pretranslation_cst/data/sugarcube-extracted.json`
- `pretranslation_cst/macro_audit.py`
- `pretranslation_cst/corpus_verify.py`
- `pretranslation_cst/masking.py`
- `tests/test_pretranslation_cst.py`
- `tests/test_square_markup.py`
- `tests/test_macro_audit.py`
- `tests/test_verify.py`

## 현재 기준선 (2026-08-07, T1 + batch 1 이후)

`corpus_verify` 실행 결과:

```text
files 642 (passage 있는 파일 639, 빈 파일 3), passages 16,135, bytes 34,107,861
round-trip 0 failures, tree invariants 0 failures
diagnostics 20,865 total:
  unclassified_argument 20,855
  invalid_macro_name 5, malformed_macro 1, unclosed_container 2,
  unterminated_comment 2 (전부 allowlist 매칭된 source 결함)
segments: link_label 32,796, macro_arg 715, plain_text 496,421
  / exposed 529,932, placeholders 527,987
coverage mean 0.674121, protected 22,698,784 / 33,671,688 bytes
baseline matched=True, deviations=0, regression=False, exit code 0
```

## 지시

```text
현재 parser로 전체 game corpus의 unclassified_argument를 macro/index별로 다시
집계하라. raw expression macro(set, run, print, =, -, if, elseif, for, unset)는
대상에서 제외된 상태여야 한다. 이 집계는 config/macro-value-kind.yml에 적용된
batch 1 이후의 residual이어야 한다.

residual 상위 항목부터 실제 호출부와 definition/call evidence를 확인해
config/macro-value-kind.yml을 보강하라. 기존 residual 보고서의 상위 목록은
batch 1 이전 기준이므로, 현재 baseline(20,855)에서 다시 집계한 목록을
정본으로 사용하라.

우선순위:
1. 상위 residual 항목 중 이미 macro-grammar.json에 등록된 parsed macro부터
   처리한다.
2. kind를 추정할 수 없는 인자는 보호 상태로 두고 note만으로 분류 완료 처리하지
   마라. evidence가 call/definition/high-confidence LLM 중 하나여야 한다.
3. 빈 args가 실제 무인자인지 미분류인지 구분하라.
4. prose_text 분류는 문자열 인자(string literal)만 가능하며, bareword/
   expression은 kind와 무관하게 보호한다.

방식:
- 각 macro/index 후보에 대해 실제 호출부를 원문에서 추출해 근거로 남긴다.
- definition이 존재하면 definition의 인자 처리 방식을 근거로 삼는다.
- residual 보고서에 macro/index별 before/after residual count를 기록하라.
- corpus-baseline-v1.json의 unclassified_argument와 segments_by_kind를 갱신하고
  docs/validation.md의 현재 기대값도 같이 갱신하라.

처리하지 말 것:
- raw expression macro의 공백 token을 positional value-kind로 등록하지 마라.
- 근거 없는 note만으로 분류 완료 처리하지 마라.
- 노출 segment(link_label, plain_text)를 감소시키는 변경을 하지 마라.
- macro_arg 노출은 prose_text kind의 string literal에만 적용된다. structural
  분류는 진단만 줄이고 노출을 늘리지 않는다.
- 담당 범위 밖 parser/grammar/masking/registry 파일을 수정하지 마라.
```

## 완료 기준

- `unclassified_argument`가 parsed positional argument의 실제 schema gap만
  의미한다.
- `set`, `run`, `print`, `if`, `elseif`, `for`, `unset`, `=`가 상위 진단에
  남지 않는다 (이미 달성, 유지할 것).
- 추가한 모든 kind에 `call`, `definition`, 또는 high-confidence LLM 근거가 있다.
- residual 항목은 macro/index별 검토 큐로 직접 사용할 수 있다.
- round-trip과 기존 노출 segment(link_label 32,796, plain_text 496,421)가
  감소하지 않는다.
- `corpus_verify` exit code 0, baseline 일치.
- `python3 -m unittest discover -s tests -v` 112개 통과 유지.

## 보고 형식

```text
## before/after
- unclassified_argument: <before> -> <after>
- macro_arg: <before> -> <after>
- link_label: <before> -> <after> (유지되어야 함)
- plain_text: <before> -> <after> (유지되어야 함)
- exposed segments: <before> -> <after>
- placeholders: <before> -> <after>

## corpus_verify
- exit code: 0
- baseline matched: True
- deviations: 0
- regression: False

## residual 변화
- 처리 전 residual 항목 수: <N>
- 처리 후 residual 항목 수: <M>
- 상위 항목별 delta 표 (macro[index]: before -> after)

## 추가 분류 내역
- macro/index별 추가 kind, evidence, note

## 남은 residual
- 상위 20개 (batch 2 이후 기준)

## 새 결함 (발견 시)
- source/passage/macro/span/fixture
```