# 파서 구조 개선 로드맵

기준일: 2026-08-07

이 문서는 현재 파서의 byte-exact round-trip 성질을 유지하면서 CST 정확도와
번역 대상 추출 품질을 복구하기 위한 작업 순서를 정한다. 진단 건수를 줄이기 위한
매크로별 예외 추가가 아니라, `boundary scan -> grammar dispatch -> CST -> exposure`
계약을 다시 세우는 것이 목표다.

## 구현 상태

2026-08-07 현재 핵심 parser 작업은 다음까지 반영됐다.

- versioned `MacroSpec` registry와 `raw | parsed | none` argument dispatch
- registry 기반 container/branch tree
- `set/run/print/if/elseif/for/unset` 계열 raw expression 처리
- `addinlineevent`, `foldout`, `linkreplace` container 처리
- `checkbox`, `radiobutton` leaf 처리
- macro 내부 square-link label의 CST leaf 및 masking 노출
- division과 regex literal의 macro boundary 구분

전체 `game/**/*.twee` 642개 파일, 16,135개 passage에서 restore 실패 0,
tree invariant 실패 0, `malformed_args` 0, `mismatched_close` 0을 확인했다.
`unclosed_container` 2건은
`game/overworld-forest/loc-forestshop/gwylan-clothes.twee`의 malformed `case`
인자가 뒤 구조를 닫지 못하게 만드는 동일 source 결함에서 발생한다.

남은 병렬 작업은 [parser-followup-agent-tasks.md](parser-followup-agent-tasks.md)에
분리했다.

## 결론

현재 splitter와 원본 byte/span 보존 계층은 유지할 수 있다. 구조적으로 다시
설계해야 하는 범위는 macro boundary 이후부터 masking 이전까지다.

핵심 문제는 다음 네 가지다.

1. 모든 매크로 본문을 동일한 positional argument lexer로 처리한다.
2. 매크로 문법 정보와 argument value-kind 정보가 분리되어 있지 않다.
3. container 여부와 branch tag가 코드 상수에 하드코딩되어 있다.
4. CST와 번역 후보가 서로 다른 경로에서 만들어져, tree에 들어간 markup을
   exposure 단계가 다시 찾지 못한다.

따라서 우선순위는 단순히 `_lex_args`를 고치는 순서가 아니다. 먼저 매크로별
문법 registry를 만들고, 그 registry가 argument mode와 container 구조를 모두
결정하게 해야 한다.

## 현재 기준선

기존 `/tmp/opencode/combat.jsonl`과 `/tmp/opencode/town.jsonl`을 다시 집계한
결과다. 산출물은 수정하지 않는다.

| 항목 | base-combat | overworld-town |
|---|---:|---:|
| rows | 101 | 10,752 |
| `unclassified_argument` | 222 | 226,186 |
| `malformed_args` | 36 | 100 |
| `mismatched_close` | 0 | 503 |
| `unclosed_container` | 0 | 50 |
| `macro_arg` segment | 0 | 318 |
| `link_label` segment | 0 | 0 |

town의 `unclosed_container`는 `radiobutton` 35건과 `checkbox` 15건이다.
`mismatched_close`는 `/addinlineevent` 502건과 `/linkreplace` 1건이다.

현재 town 원문에서 `<<link [[label|target]]>>` 형태의 정적 square-link label은
약 21,569건, string literal 첫 인자는 11건이다. 새 square markup parser로 다시
확정해야 하지만, 링크 라벨 누락이 소수 예외가 아니라는 기준선으로 사용한다.

## 구조적 원인

### 1. boundary scan과 argument 해석이 결합되어 있다

`_parse_macro()`는 macro boundary를 찾은 직후 모든 raw body를 `_lex_args()`에
넘긴다. 그러나 SugarCube는 매크로 정의의 `skipArgs`에 따라 두 경로를 사용한다.

- 일반 매크로: `parseArgs`로 `Bareword`, `String`, `Expression`,
  `SquareBracket`를 만든다.
- `set`, `run`, `print`, `=`, `-`, `if`, `elseif`, `for`, `unset` 등:
  positional argument를 만들지 않고 전체 raw expression을 사용한다.

따라서 다음 입력은 bareword 안의 quote를 더 잘 소비해야 하는 사례가 아니다.

```text
<<set _anusaction["Straddle " + $NPCList[...].penisdesc] to "anustopenisdouble">>
<<print _full.join(" and ")>>
```

두 매크로 모두 raw expression mode로 처리되어야 한다. generic bareword scanner를
quote-aware하게 바꾸면 SugarCube의 일반 `parseArgs`와 다른 문법이 된다.

### 2. grammar schema와 value-kind schema의 책임이 섞여 있다

`macro-value-kind.yml`은 번역 의미를 분류하는 데이터다. 다음 정보까지 이 파일의
존재 여부로 추론하면 안 된다.

- leaf/container 여부
- branch tag 목록
- positional args/raw expression/no args 구분
- branch별 argument mode
- nested square markup 허용 여부

현재 `set`과 `run`에 positional index를 대량 추가하는 방식은 표현식의 단어와
연산자를 가짜 argument로 굳힌다. `$a and $b`의 `and`가 arg1로 진단되는 현상도
같은 모델 오류다.

### 3. container registry가 런타임 정의와 분리되어 있다

`CONTAINER_NAMES`는 실제 SugarCube와 게임의 macro 정의를 반영하지 못한다.

- `checkbox`, `radiobutton`은 leaf인데 container로 등록되어 있다.
- built-in `linkreplace`는 `tags: null`인 container인데 빠져 있다.
- 게임 JS의 `addinlineevent`, `foldout`도 `tags: null`인 container인데 빠져 있다.
- branch 이름은 어느 container에 속하는지 확인하지 않고 전역 집합으로 처리한다.

문서에는 built-in 정의와 게임 registry를 사용한다고 되어 있지만 구현은 정적 이름
집합만 사용한다. 이 차이가 passage 끝까지의 과보호와 잘못된 parent 관계를 만든다.

### 4. CST와 masking이 같은 leaf 모델을 사용하지 않는다

현재 macro span 전체가 `_collect_markup()`의 ignored range가 된다. 따라서
`<<link [[Next|Target]]>>`의 `SquareBracket` argument는 CST argument에는 있어도
markup collector에는 보이지 않는다.

또한 `protected_spans`와 `exposed_candidates`가 tree와 별도로 누적된다. 이 구조에서는
tree가 맞아도 추출이 틀릴 수 있고, 추출 후보가 있어도 어느 macro/branch의 자식인지
보장할 수 없다. 문서의 `prose_text` leaf 모델과 실제 masking 구현이 갈라진 상태다.

### 5. 현재 진단 단위가 의미 있는 결함 수가 아니다

raw expression을 공백으로 쪼갠 뒤 각 token을 `unclassified_argument`로 세기 때문에
226,186건은 schema gap과 parser dispatch 오류가 섞인 숫자다. 이 상태에서 YAML
항목을 추가하면 진단은 줄어도 CST 품질이 좋아졌다고 볼 수 없다.

## 목표 파이프라인

```text
source bytes
  -> passage splitter
  -> boundary-only macro events
  -> MacroSpec registry lookup
  -> grammar-aware argument decoding
  -> nested markup nodes
  -> registry-driven container tree
  -> value-kind/exposure policy on CST leaves
  -> masking and byte restore
```

각 단계는 원본 byte span만 전달한다. 실패 시 보호하는 정책은 유지하되, 실패 범위는
해당 token 또는 구조적으로 열린 container까지만 명시적으로 계산한다.

## 목표 데이터 모델

### MacroSpec registry

parser 문법용 registry를 value-kind와 별도 파일 및 타입으로 둔다. 최소 필드는
다음과 같다.

```text
name
body_kind       leaf | container
tags            branch 이름 목록
arg_mode        parsed | raw | none
tag_arg_modes   branch별 parsed | raw | none
source          sugarcube | game_js | widget | override
```

예시는 다음과 같다.

| macro | body_kind | arg_mode | tags |
|---|---|---|---|
| `set`, `run`, `print`, `=` | leaf | raw | 없음 |
| `if` | container | raw | `elseif`, `else` |
| `for` | container | raw | 없음 |
| `link`, `linkreplace` | container | parsed | 없음 |
| `addinlineevent`, `foldout` | container | parsed | 없음 |
| `checkbox`, `radiobutton` | leaf | parsed | 없음 |
| `cycle`, `listbox` | container | parsed | `option`, `optionsfrom` |

registry는 SugarCube built-in snapshot, 게임의 `Macro.add()` 정의, container widget
header, 게임 override의 최종 정의를 반영해야 한다. 첫 구현에서는 검토 가능한
versioned JSON을 정본으로 두고, source scan은 누락/불일치를 검증하는 도구로 두는
편이 안전하다.

### Argument node

`CstNode`는 `arg_mode`를 기록한다.

- `parsed`: 기존 `ArgNode[]`를 생성한다.
- `raw`: 전체 `raw_args_span`을 하나의 structural expression node로 기록하고
  positional index를 만들지 않는다.
- `none`: 공백 외 내용이 있으면 별도 diagnostic을 남긴다.

`SquareBracket` argument는 opaque string이 아니라 link/image 하위 node를 가질 수
있어야 한다. link node는 최소한 label, target, setter span을 분리한다.

### 의미 분류

`macro-value-kind.yml`은 `arg_mode=parsed`인 positional argument에만 적용한다.
raw expression macro는 macro grammar에서 이미 structural로 보호되므로
`unclassified_argument`를 만들지 않는다.

## 단계별 실행 계획

### 0. 기준선과 회귀 fixture 고정

코드를 바꾸기 전에 현재 JSONL 진단 집계와 영향 passage 목록을 재생성 가능한
검증 명령으로 만든다.

- 보고서의 두 expression 사례를 fixture로 추가한다.
- `addinlineevent`, `foldout`, `linkreplace`, `checkbox`, `radiobutton` fixture를
  추가한다.
- square-link literal/dynamic label fixture를 추가한다.
- passage 끝까지 protected가 확장된 5개 이상 실제 사례를 corpus fixture로 고정한다.
- round-trip, tree invariants, exposed segment census를 서로 다른 검증 항목으로 둔다.

완료 기준:

- 수정 전 기준선이 위 집계와 일치한다.
- 각 실패가 source path, passage, macro, span으로 재현된다.

### 1. MacroSpec registry 도입

`CONTAINER_NAMES`와 `BRANCH_NAMES`를 바로 늘리지 않고 문법 registry를 먼저 만든다.

- SugarCube built-in macro의 `tags`와 `skipArgs`를 versioned registry로 옮긴다.
- 게임 JS의 `Macro.add()` 중 parser 구조에 필요한 항목을 등록한다.
- override 이후 최종 정의가 무엇인지 기록한다.
- widget prepass가 container widget metadata를 registry에 합칠 수 있게 한다.
- unknown macro는 leaf + parsed fail-closed를 기본값으로 하되 diagnostic으로 구분한다.

완료 기준:

- `checkbox`와 `radiobutton`은 leaf로 조회된다.
- `addinlineevent`, `foldout`, `linkreplace`는 container로 조회된다.
- `if`, `switch`, `cycle/listbox`의 branch 소유 관계가 registry에 표현된다.
- registry source와 현재 JS 정의의 불일치를 찾는 검증이 있다.

### 2. boundary event와 argument decoder 분리

boundary scanner는 name, closing 여부, raw args span, 전체 macro span만 만든다.
argument decoder는 registry의 `arg_mode`를 보고 별도로 실행한다.

- `raw` macro는 내부 quote, bracket, whitespace와 무관하게 전체 expression span을
  유지한다.
- `parsed` macro만 SugarCube `parseArgs` 호환 lexer를 사용한다.
- bareword 동작은 SugarCube와 같게 유지하고, raw expression 보정을 섞지 않는다.
- closing macro의 args와 `arg_mode=none` 위반은 별도 diagnostic으로 만든다.

완료 기준:

- 두 보고 사례가 `malformed_args` 없이 하나의 raw expression으로 기록된다.
- `set/run/print/=/if/elseif/for/unset` token에서
  `unclassified_argument`가 생성되지 않는다.
- 일반 positional macro의 기존 string/content span 동작은 유지된다.
- 모든 byte span과 round-trip이 기존과 동일하게 통과한다.

### 3. registry 기반 tree builder 전환

tree builder는 이름 집합이 아니라 `MacroSpec`만 사용한다.

- container open/close는 `body_kind`로 판정한다.
- branch는 현재 열린 container의 `tags`에 속할 때만 branch가 된다.
- 잘못된 branch, close args, 교차 close를 서로 다른 diagnostic으로 분리한다.
- leaf macro는 닫힘을 기다리지 않으며 passage 끝 보호를 만들지 않는다.
- unknown closing tag는 root-level text 구조를 오염시키지 않고 해당 close만 보호한다.

완료 기준:

- town의 `/addinlineevent` 502건과 `/linkreplace` 1건 mismatch가 해소된다.
- `foldout`을 포함한 전체 corpus에서 알려진 container pair가 올바른 parent를 가진다.
- `checkbox` 15건과 `radiobutton` 35건의 unclosed 및 passage-tail 과보호가 사라진다.
- residual mismatch/unclosed는 모두 실제 malformed source 또는 명시적 registry 누락으로
  분류된다.

### 4. nested markup과 exposure를 CST leaf로 통합

global markup rescan에 의존하지 않고 argument decoder가 만든 nested node를 tree에
연결한다.

- `SquareBracket` argument 아래에 link/image node를 만든다.
- link label, target, setter span을 분리한다.
- literal label은 `link_label` leaf로 노출하고 target/setter는 보호한다.
- `$`, `_`, backtick, `${...}`, macro markup 등 동적 label은 정책에 따라 전체 보호한다.
- string-form `<<link "Label" "Target">>`의 첫 인자 노출 정책도 같은 단계에서
  명시적으로 결정하고 fixture를 둔다.
- masking은 CST의 exposed/protected leaf를 순회해 span을 만들고, 별도 후보 목록을
  정본으로 사용하지 않는다.

완료 기준:

- `<<link [[Next|Tutorial Finish]]>>`에서 `Next`가 `link_label`로 노출된다.
- 동적 label은 노출되지 않는다.
- town의 square-link label census와 JSONL `link_label` 수가 일치한다.
- 각 exposed segment에서 parent macro와 branch를 조회할 수 있다.
- overlapping span 없이 mask/restore가 byte-exact다.

### 5. value-kind schema 재정비

parser 구조가 안정된 뒤에만 의미 schema를 보강한다.

- raw expression macro를 positional value-kind 대상에서 제거한다.
- parsed macro의 실제 argument index만 inventory한다.
- `spray`, `moneyGain` 등 residual 상위 항목을 호출부 근거로 분류한다.
- macro 누락과 argument index 누락을 별도 집계한다.
- 빈 `args`가 "인자 없음", "아직 미분류", "raw mode라 비대상" 중 무엇인지
  구분한다.

완료 기준:

- `unclassified_argument`는 parsed positional argument의 실제 schema gap만 뜻한다.
- `set`, `run`, `print`, `if`, `elseif`, `for`, `unset`, `=`가 상위 진단에 남지 않는다.
- residual 항목은 macro/index별 검토 큐로 직접 사용할 수 있다.

### 6. 전체 corpus 검증과 rollout

마지막에 base-combat, overworld-town, 전체 `game/**/*.twee` 순서로 넓힌다.

- split/assemble와 mask/restore를 전수 실행한다.
- diagnostic code/macro별 before-after를 저장한다.
- exposed segment를 kind별로 집계한다.
- passage별 protected coverage 비율을 계산해 비정상 급증을 탐지한다.
- 2회 실행 JSONL byte identity를 확인한다.
- 기존 `/tmp/opencode/*.jsonl`은 덮어쓰지 않고 새 경로에 생성한다.

완료 기준:

- round-trip은 계속 100%, 0 failures다.
- 알려진 valid fixture의 `malformed_args`, `mismatched_close`,
  `unclosed_container`는 0이다.
- residual 구조 진단은 source 결함 또는 registry gap으로 전부 설명 가능하다.
- link label과 macro prose의 추출 census가 독립 inventory와 일치한다.
- passage-tail 과보호가 known leaf macro 때문에 발생하지 않는다.

## 작업 분할 권장안

구현 commit은 다음 경계로 나누는 것이 좋다.

1. baseline reporter와 regression fixtures
2. `MacroSpec` 타입과 versioned grammar registry
3. boundary-only scanner와 grammar-aware argument decoder
4. registry-driven tree builder
5. nested square markup node와 CST leaf masking
6. value-kind migration과 corpus verification report

각 commit은 round-trip 전수 검증을 통과해야 한다. 진단 감소와 번역 segment 증가는
해당 단계의 구조 assertion이 함께 통과할 때만 개선으로 인정한다.

## 하지 않을 수정

- `_lex_args` bareword loop에 quote/bracket 예외만 추가하지 않는다.
- `set`과 `if`의 공백 token index를 YAML에 대량 등록하지 않는다.
- `radiobutton` 한 이름만 self-closing 예외로 두지 않는다.
- `CONTAINER_NAMES`에 발견된 이름을 계속 수동 추가하지 않는다.
- macro span 내부를 global regex로 재검색해 link label만 꺼내지 않는다.
- round-trip 통과만으로 parser 품질 완료를 선언하지 않는다.

## 완료 정의

이 개선의 완료는 diagnostic 숫자가 작아지는 것이 아니다. 다음 세 계약이 동시에
성립해야 한다.

1. Lossless: 원본 bytes와 모든 span이 보존된다.
2. Structural: runtime macro grammar와 CST container/argument 구조가 일치한다.
3. Extraction: 노출 가능한 leaf가 독립 census와 일치하고 parent context를 가진다.

세 계약 중 하나라도 빠지면 fail-safe masking은 동작하더라도 번역 전처리 파서로는
완료된 것으로 보지 않는다.
