# 검증과 완료 조건

## 불변식

모든 테스트의 최우선 기준은 byte equality다.

```text
assemble(split(file_bytes)) == file_bytes
restore(mask(passage_bytes)) == passage_bytes
```

파싱 후 재직렬화로 원본을 재생성하지 않는다. restore는 placeholder 테이블의
원본 bytes를 직접 사용한다.

## 단위 fixture

다음 fixture를 고정한다.

- UTF-8 한글 앞뒤의 byte span
- quote/backtick/regex/comment 안의 `>>`
- 단일 `>`와 종결 `>>`
- nested `[[...]]` 및 link delimiter
- `if/elseif/else`, `switch/case/default`
- nested container
- malformed close와 unterminated token
- widget definition 본문이 opaque인지
- unknown/medium confidence argument가 노출되지 않는지
- `get_ancestors`와 `get_siblings`의 순서·depth

## 저장소 검증

현재 `game/` 전체 642개 Twee 파일을 대상으로 한다.

1. 파일 splitter round-trip
2. 모든 passage의 tree span 유효성 검사
3. sibling order가 원문 byte 순서와 일치하는지 검사
4. 모든 node의 parent chain이 cycle 없이 root에 도달하는지 검사
5. mask/restore byte-exact
6. 동일 입력 2회 실행 결과 JSONL byte-identical

## Golden 데이터셋

`research/golden/`을 검증 입력으로 사용한다.

- `corpus-identical.jsonl`: 13,113 passage round-trip
- `corpus-structure-samples.jsonl`: 300개 구조 스트레스 샘플
- `corpus-triple-match.jsonl`: 구조 비교와 실제 번역 구조 사례

golden 레코드의 `source_body`는 passage body fixture로 쓰고, splitter 자체는
원본 `game/**/*.twee` 파일을 별도로 검증한다.

## 실패 보고

실패는 예외만 던지고 끝내지 않는다. source path, passage name, node_id,
macro name, byte span, diagnostic code를 함께 보여야 한다. 미분류와 malformed
구간은 fail-safe 보호 상태로 남아야 한다.

## 완료 조건

- 전체 Twee file split/assemble 성공
- golden mask/restore 성공
- 모든 node가 필수 tree metadata를 가짐
- parent/ancestor/sibling 조회가 결정적임
- 위젯 정의 본문에 자식 prose/macro node가 없음
- 미분류·저신뢰 항목이 노출되지 않음
- 2회 실행 결과가 byte-identical
