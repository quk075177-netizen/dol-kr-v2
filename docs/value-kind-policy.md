# value-kind와 Fail-safe 정책

## 입력 스키마

파서는 `config/macro-value-kind.yml`을 소비한다. 현재 파일은 YAML
확장자를 사용하지만 JSON 문법으로 저장되어 있다.

- key: lowercase macro name
- `name`: 실제 macro/widget 이름의 대소문자 원형
- `args[N].kind`: 인자 위치별 의미
- `evidence`: `call`, `definition`, `llm`
- `confidence`: LLM 근거의 신뢰도
- `note`: 분류 근거

macro 하나를 단일 kind로 처리하지 않는다. 반드시 argument index별로 lookup한다.

## 노출 정책

현재 전처리 레이어에서 실제로 노출하는 것은 `prose_text`뿐이다.

| kind | 처리 |
|---|---|
| `prose_text` | 확정 조건을 통과한 literal content를 leaf로 노출 |
| `named_npc` | 보호, semantic metadata만 기록 |
| `clothing` | 보호, semantic metadata만 기록 |
| `location` | 보호, semantic metadata만 기록 |
| `body_part` | 보호, semantic metadata만 기록 |
| `ui_icon` | 보호 |
| `event_key` | 보호 |
| `arbitrary_text` | 보호 |
| `structural` | 보호 |

glossary lookup과 한국어 표시명 치환은 이 레이어에서 하지 않는다.

## 허용 기준

- `definition` 또는 `call` evidence와 kind가 있으면 사용
- `llm` evidence는 `confidence=high`일 때만 사용
- `confidence=medium/low`는 보호
- macro가 schema에 없으면 전체 보호
- 해당 argument 위치가 없으면 해당 argument 보호
- string literal이 아닌 expression/bareword는 kind와 관계없이 보호
- malformed/unterminated 구조는 prose로 추정하지 않음

보호된 미분류 항목은 다음 정보를 진단 JSONL에 남긴다.

```text
source_path
passage_name
macro_name
argument_index
byte_span
reason
```

## 위젯과 중첩

위젯 정의 내부의 매크로는 분류하지 않는다. 정의 header에서 이름과
container 여부만 얻고, 일반 passage의 호출 node만 schema lookup한다.

같은 passage의 연속 호출과 같은 문자열 반복은 각각 다른 byte span과
node_id를 갖는다. 위젯 내부 구현을 호출부의 semantic child로 확장하지 않는다.
