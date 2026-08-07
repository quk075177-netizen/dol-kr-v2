# 파서 후속 에이전트 작업 지시서

기준: 핵심 parser 구조 수정 이후

아래 작업은 서로 파일 소유권이 겹치지 않도록 나눴다. 각 에이전트는 기존 사용자
변경을 되돌리지 말고, 담당 범위 밖 parser refactor를 하지 않는다.

## 공통 기준

- 정본 입력은 `game/**/*.twee`다.
- 기존 `/tmp/opencode/*.jsonl`은 덮어쓰지 않는다.
- 모든 변경은 `python3 -m unittest discover -s tests -v`를 통과해야 한다.
- parser 변경이 필요한 새 결함을 발견하면 우회 수정하지 말고 source, passage,
  macro, byte span, 최소 fixture와 함께 보고한다.
- 완료 보고에는 before/after diagnostic 및 exposed segment count를 포함한다.
- `set`, `run`, `print`, `=`, `-`, `if`, `elseif`, `for`, `unset`은 raw expression이다.
  이들의 공백 token을 value-kind positional argument로 등록하지 않는다.

## Agent 1: value-kind residual 정리

담당 파일:

- `config/macro-value-kind.yml`
- value-kind 전용 검증 fixture 또는 보고서

수정 금지:

- `pretranslation_cst/parser.py`
- `pretranslation_cst/grammar.py`
- `pretranslation_cst/data/macro-grammar.json`
- `pretranslation_cst/model.py`

지시:

```text
현재 parser로 전체 game corpus의 unclassified_argument를 macro/index별로 다시
집계하라. raw expression macro는 대상에서 제외된 상태여야 한다. residual 상위
parsed macro부터 실제 호출부와 definition/call evidence를 확인해
config/macro-value-kind.yml을 보강하라.

우선순위는 base-combat residual 13건(spray 6, moneyGain 4, beast/violence/neutral 각 1),
그 다음 overworld-town 상위 항목(pass, stress, trauma, arousal, money, neutral,
loadNPC, pain, crimeup, violence, printmoney)이다.

kind를 추정할 수 없는 인자는 보호 상태로 두고 note만으로 분류 완료 처리하지 마라.
빈 args가 실제 무인자인지 미분류인지 구분하라. 변경 후 macro/index별 before/after와
남은 residual 목록을 보고하라.
```

완료 기준:

- `unclassified_argument`가 실제 parsed positional schema gap만 의미한다.
- 추가한 모든 kind에 `call`, `definition`, 또는 high-confidence 근거가 있다.
- round-trip과 기존 노출 segment가 감소하지 않는다.

## Agent 2: macro grammar registry 전수 감사

담당 파일:

- `pretranslation_cst/data/macro-grammar.json`
- 새 registry 검증 도구와 전용 테스트

수정 금지:

- argument lexer와 tree builder 구현
- `config/macro-value-kind.yml`

지시:

```text
SugarCube source의 Macro.add 정의와 game/**/*.js의 Macro.add, Macro.delete 후 override,
DefineMacro 계열, alias를 조사해 현재 macro-grammar.json과 대조하라. 각 macro의
최종 effective body_kind, arg_mode, tags, source를 검증하라.

특히 tags:null container, skipArgs:true raw macro, skipArgs:[tag] 형태의 branch별
arg mode를 누락 없이 확인하라. condition/compute처럼 게임 JS에서 정의된 container와
button/link처럼 override된 built-in을 우선 검사하라.

registry를 자동 생성하지 말고 versioned manifest를 정본으로 유지하되, source와
manifest의 누락/불일치를 실패시키는 read-only audit command를 추가하라. 정규식으로
JS 전체 의미를 추정하기 어려운 항목은 명시적 allowlist와 근거 위치를 남겨라.
```

완료 기준:

- 전체 corpus의 valid close가 `mismatched_close`를 만들지 않는다.
- leaf macro가 `unclosed_container`를 만들지 않는다.
- registry entry마다 source 종류와 근거를 추적할 수 있다.
- audit command 결과가 결정적이며 테스트 fixture가 있다.

## Agent 3: square markup/link 의미 파서 강화

담당 파일:

- square markup 전용 새 모듈
- 해당 모듈의 fixture/tests
- 필요한 최소 parser 연결부

수정 주의:

- `parser.py` 연결부를 바꿔야 하면 `_consume_square`, `_link_label`,
  `_attach_argument_nodes` 주변으로 제한한다.
- container tree와 argument dispatch는 변경하지 않는다.

지시:

```text
현재 _link_label의 단순 delimiter find와 동적 marker heuristic을 SugarCube
parseSquareBracketedMarkup 규칙에 맞는 구조 파서로 교체하라. link/image를 구분하고
label, target, setter의 byte span을 보존하라. |, ->, <- 방향별 label/target 위치,
escape, nested markup, setter를 fixture로 고정하라.

macro argument의 <<link [[...]]>>와 standalone [[...]]가 같은 parser 결과를
사용하게 하라. 정적 label만 link_label prose leaf로 노출하고 동적 label, target,
setter는 보호하라. string-form <<link "Label" "Target">>의 노출 정책은 기존 문서와
호출부 inventory를 근거로 제안하고, 승인되지 않았다면 동작을 바꾸지 마라.
```

완료 기준:

- town의 현재 square-link `link_label` 21,569건이 근거 없이 감소하지 않는다.
- 전체 game link label census와 JSONL segment count가 일치한다.
- dynamic label false-positive fixture가 없다.
- mask/restore와 tree parent lookup이 유지된다.

## Agent 4: corpus 품질 게이트와 보고서 자동화

담당 파일:

- `pretranslation_cst/verify.py` 또는 별도 verification module
- `tests/test_verify.py`
- `docs/validation.md`

수정 금지:

- parser grammar와 exposure 정책
- value-kind 데이터

지시:

```text
현재 수동 집계를 재현하는 corpus verification command를 작성하라. file/passage 수,
split/restore failures, tree parent/span/sibling invariants, diagnostic code+macro counts,
segment kind counts, passage별 protected coverage 비율을 출력하라.

baseline과 비교해 malformed_args, mismatched_close, unclosed_container, link_label,
macro_arg의 증감을 판정할 수 있게 하라. source 자체 malformed 사례는 path, passage,
span을 가진 versioned allowlist로 분리하고 parser 결함과 섞지 마라. JSON report는
정렬된 key와 안정된 순서로 두 번 실행 시 byte-identical해야 한다.
```

완료 기준:

- 전체 corpus 검증을 한 명령으로 재현할 수 있다.
- exit code가 구조 회귀와 round-trip 실패를 구분한다.
- 기존 `/tmp/opencode` 산출물 없이도 기준선을 검증할 수 있다.
- 현재 기대값은 642 files, 16,135 passages, restore failures 0,
  tree invariant failures 0, malformed_args 0, mismatched_close 0이다.

## 실행 순서

Agent 1, 2, 4는 병렬 진행할 수 있다. Agent 3은 parser 연결부가 있으므로 Agent 2의
registry 변경과 별도 commit으로 유지하고, 병합 후 전체 corpus 검증을 다시 실행한다.
