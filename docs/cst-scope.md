# Twee 번역 전처리 CST 범위

결정일: 2026-08-07

## 목적

현재 Plus `game/**/*.twee`를 passage 단위로 읽고, 원문 구조를 잃지 않은
계층형 CST를 만든다. CST에서 `prose_text`만 번역 segment로 노출하고,
나머지는 placeholder로 마스킹한다. 마스킹 직후 원본 bytes로 복구하는
최소 assembler를 제공해 lossless를 검증한다.

이것은 개인 로컬 도구다. 서버, DB, 분산 실행, 플러그인, 장기 호환성 계층은
만들지 않는다. 파일 입력, JSON/JSONL 출력, 명령행 실행, 표준 라이브러리
테스트 정도로 유지한다.

## 범위

이번 단계의 입력은 `game/**/*.twee`다.

- Twee 파일 splitter
- SugarCube macro boundary와 argument lexer
- widget 정의부/호출부 구분
- container/branch를 포함한 계층형 CST
- `macro-value-kind.yml` 기반 인자 분류
- prose masking, placeholder restore, diagnostics

다음은 제외한다.

- JavaScript 문자열 추출 및 masking
- 번역 API 호출
- 번역문 삽입, QA, 최종 게임 조립·배포
- glossary 표시명 치환
- SugarCube macro 실행, DOM 생성, 게임 상태 평가

JS 파일에는 passage가 없으므로 Twee parser에 억지로 포함하지 않는다.

## Lossless 계약

원본 UTF-8 bytes가 유일한 정본이다.

- 모든 offset은 파일 기준 UTF-8 byte offset이다.
- span은 0-based 반개구간 `[start, end)`다.
- 파일 시작에 UTF-8 BOM(`EF BB BF`)이 있으면 BOM 3바이트도 파일 offset과
  `prefix_span`에 포함한다. BOM은 passage header/body에 속하지 않지만 assemble 시
  그대로 보존하며, 첫 `::` header는 BOM 뒤에서 인식한다.
- passage-local offset이나 JavaScript UTF-16 index를 공개 결과에 사용하지 않는다.
- 공백, 개행, 따옴표, escape, 대소문자, 주석을 정규화하지 않는다.
- CST에서 원문을 재직렬화해 assemble하지 않는다.
- restore는 placeholder가 가리키는 원본 byte slice를 순서대로 이어 붙인다.

불변식:

```text
assemble(split(file_bytes)) == file_bytes
restore(mask(passage_bytes)) == passage_bytes
```

파일 하나당 UTF-8 문자/byte 변환표를 하나만 만들고 모든 passage와 node가
공유한다. 매크로 boundary 함수에는 항상 현재 passage body의 끝을 명시해,
malformed 입력이 다음 passage까지 읽지 않도록 한다.

## CST 모델

결과의 기본 표현은 flat list가 아니라 tree다. passage마다 `passage_root`를
하나 둔다. root의 `parent_id`는 `null`이고, root의 직계 자식부터 실제
텍스트·매크로 구조가 시작된다.

모든 node는 다음 필드를 필수로 가진다.

```text
node_id          결정적인 고유 ID
parent_id       부모 node ID, root만 null
sibling_order    같은 부모의 children 안에서 0부터 시작하는 순서
depth            root=0
byte_span        파일 기준 [start, end)
node_type        node 종류
children[]       자식 node를 원문 순서대로 보관
```

권장 node 종류:

| node_type | 역할 |
|---|---|
| `passage_root` | passage body의 가상 root |
| `text` | 매크로 밖의 일반 텍스트 span |
| `macro_call` | 단일 매크로 호출. non-container 매크로의 부모 |
| `macro_container` | 열기부터 닫기까지의 container 매크로 |
| `macro_branch` | `else`, `elseif`, `case` 등 container 분기 |
| `prose_text` | 노출 가능한 매크로 인자 문자열 segment |
| `protected_markup` | link target, HTML, comment, variable, expression 등 |
| `passage_opaque` | 특수 passage 또는 `[script]`/`[stylesheet]` passage의 body 전체. 자식은 만들지 않음 |

위젯 정의(`<<widget>>`)는 `macro_container`로 처리되며 본문 안에
text/prose/macro 자식을 가질 수 있다.

### 부모 관계 예시

```text
passage_root
  macro_container(if)
    macro_branch(if)
      text
      macro_call
    macro_branch(else)
      text
  macro_call(wheeze)
    prose_text
```

`macro_container`와 `macro_branch`의 span은 자식 span을 포함한다. 형제 node는
같은 부모 아래에서 원문 순서를 보존해야 하며, parent container를 제외한
형제끼리는 같은 source 구간을 이중 소유하지 않는다.

`macro_call`의 `prose_text` 인자도 독립 leaf로 만든다. 따라서 해당 leaf에서
부모를 따라 매크로와 조건부 branch를 조회할 수 있다.

## node ID와 조회 API

ID는 실행마다 바뀌는 배열 인덱스가 아니라 source path, passage span, node
type, node span을 조합해 결정적으로 만든다. 같은 값이 중복되는 경우에만
preorder ordinal을 추가한다.

구현체는 tree와 함께 `node_id -> node` index를 메모리에 둔다.

```python
tree.get_ancestors(node_id)
tree.get_siblings(node_id)
```

- `get_ancestors`는 parent를 따라가며 가까운 부모부터 root 방향으로 반환한다.
- `get_siblings`는 같은 `parent_id`의 children 중 자기 자신을 제외한 node를
  `sibling_order` 순서로 반환한다.
- 없는 ID는 조용히 빈 목록을 반환하지 않고 명시적인 lookup error를 낸다.

이 API를 이용하면 청킹 단계에서 “같은 `if` branch의 텍스트만 묶기”,
“같은 container 아래 형제 segment 비교” 같은 처리를 parser 재실행 없이 할
수 있다.

## 위젯 정의부

`<<widget "name">> ... <</widget>>`은 호출이 아니라 정의지만, 정의
본문 안에는 번역 대상 prose가 있다(UI 라벨, 대사, 상태 설명 등).
따라서 위젯 정의는 opaque가 아니라 일반 `macro_container`로 처리한다.

- `<<widget>>` 열기와 `<</widget>>` 닫기는 `macro_container` node로
  기록한다.
- 정의 본문 안의 macro/text/prose는 일반 passage body처럼 스캔해
  CST 자식으로 만든다.
- `[widget]` passage tag만으로 passage 전체를 제외하지 않는다.
- 위젯 안의 JS/주석/HTML은 기존 `_collect_markup` 경로로 보호된다.
- 위젯 정의 안의 `<<set>>`, `<<if>>` 등은 일반 매크로와 동일하게
  처리된다.

위젯 정의가 본문 안에서 다시 `<<widget ...>>`를 여는 경우에는
container 중첩으로 처리한다. 바깥 위젯이 안쪽 위젯을 자식으로
포함한다. 닫기 tag를 찾지 못하면 `unclosed_container` diagnostic을
남긴다.

## 특수 passage와 코드 passage

다음 이름의 passage는 일반 SugarCube prose passage가 아니다.

```text
StoryData StoryTitle StoryInit StoryInterface StoryMenu StoryShare
```

splitter는 이 이름을 일반 passage와 똑같이 header/body span으로 보존하지만,
scanner와 CST builder는 body를 통째로 `passage_opaque`로 기록한다. `StoryData`는
JSON, 나머지는 설정·UI·초기화 코드 또는 엔진 전용 내용일 수 있으므로 이 레이어에서
JSON을 파싱하거나 SugarCube macro를 재스캔하지 않는다. body 안의 `<<...>>`, HTML,
link, 변수처럼 보이는 문자열도 모두 보호한다. opaque body 내부의 JSON·JS·CSS
문법은 검증하거나 malformed diagnostic을 만들지 않으며, UTF-8·header·body 경계
같은 splitter 수준의 문제만 진단한다. passage 이름 비교는 위 목록과의 exact match다.

passage header의 tag token이 `[script]` 또는 `[stylesheet]`인 경우에도 같은
정책을 적용한다. 이 body에는 순수 JavaScript/CSS가 올 수 있으므로 macro, link,
HTML scanner를 실행하지 않고 전체를 `passage_opaque` 보호 span으로 둔다. 현재
저장소 corpus에서는 이 두 tag가 발견되지 않았지만, 입력 glob이 `game/**/*.twee`
전체인 만큼 회귀 fixture로 고정한다. `[widget]` tag만 있는 passage는 이 규칙에
해당하지 않으며, 그 안의 일반 widget 정의 prepass 정책을 따른다.

## masking 경계

`prose_text`와 일반 `text` leaf만 노출한다.

보호 대상은 macro syntax, macro의 비-prose 인자, unknown/missing kind 인자,
변수·표현식, link target/setter, HTML tag, comment, widget definition이다.
`[[pure literal label|target]]`처럼 동적 요소가 전혀 없는 display label은
`link_label` `prose_text` 후보로 노출한다. `$`, `_`, backtick, `${...}` 또는
문자열 연결이 하나라도 있으면 label 전체와 target/setter를 함께 보호한다. 이
결정은 초기 구현의 최종 정책이며, 순수 label을 통째로 보호한다는 별도 예외는
두지 않는다.

마스킹 출력은 원문 노출 segment와 placeholder의 순서 있는 조합이다.
placeholder에는 원본 span과 복구용 원본 bytes를 연결한다. 입력 passage 안에
이미 존재하는 placeholder 문자열과 충돌하면 prefix를 바꾼다.

## 구현 순서

1. 공유 `SourceContext`와 byte span 타입
2. lossless Twee splitter
3. boundary-only event scanner
4. container/branch stack 기반 tree builder
5. 특수/tag passage opaque 분류
6. widget opaque prepass
7. value-kind fail-safe 분류
8. tree leaf 기반 masking/restore
9. fixture와 golden 검증

현재 flat-list WIP를 API만 확장해서 사용하지 않는다. tree builder와 masking을
처음부터 같은 leaf span 모델 위에 맞춘다.
