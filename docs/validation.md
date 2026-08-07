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
- 순수 literal link label은 노출되고 동적 label은 전체 보호되는지
- `if/elseif/else`, `switch/case/default`
- nested container
- malformed close와 unterminated token
- widget definition 본문이 opaque인지
- 중첩 widget 정의에서 바깥 definition만 opaque node가 되는지
- `StoryData`/`StoryTitle`/`StoryInit`/`StoryInterface`/`StoryMenu`/`StoryShare` body가
  macro scanner를 건너뛰는지
- `[script]`와 `[stylesheet]` tag passage body가 통째로 opaque인지
- UTF-8 BOM이 파일 prefix로 유지되고 모든 offset에 3바이트가 포함되는지
- unknown/medium confidence argument가 노출되지 않는지
- `get_ancestors`와 `get_siblings`의 순서·depth

## 저장소 검증

현재 `game/` 전체 642개 Twee 파일과 16,135개 passage를 대상으로 한다.

2026-08-07 corpus inventory에서는 특수 passage가 3개(`StoryData` 1개,
`StoryTitle` 1개, `StoryInit` 1개)였고, `[script]`/`[stylesheet]` passage와
UTF-8 BOM 파일은 발견되지 않았다. 중첩 widget 정의도 현재 원문에서는 발견되지
않았지만, parser 경계 회귀를 막기 위해 단위 fixture에는 남겨 둔다.

1. 파일 splitter round-trip
2. 모든 passage의 tree span 유효성 검사
3. 특수 passage와 `[script]`/`[stylesheet]` passage가 `passage_opaque`인지 검사
4. sibling order가 원문 byte 순서와 일치하는지 검사
5. 모든 node의 parent chain이 cycle 없이 root에 도달하는지 검사
6. mask/restore byte-exact
7. 동일 입력 2회 실행 결과 JSONL byte-identical

최근 실행 결과: 642개 파일, 16,135개 passage 전체의 parse/mask/restore가
byte-exact로 통과했다. 전체 CLI 출력은 16,135행이었고, 대표 디렉터리 2회 실행의
JSONL SHA-256이 동일했다.

## unclassified 일관성 검사

JSONL의 `unclassified_argument`가 실제 schema 누락인지 확인하려면 다음 명령을
실행한다. 이 검사는 JSONL을 한 줄씩 읽고, macro 이름과 argument index가
`macro-value-kind`에 존재하면 실패한다.

```bash
python3 -m pretranslation_cst.verify /tmp/dolkr-cst-full.jsonl \
  --value-kind config/macro-value-kind.yml
```

`violations=0`이고 exit code가 0이어야 한다. `macro_missing`은 macro key 자체가
없는 경우, `argument_missing`은 macro는 있지만 해당 인자 위치가 없는 경우다.

## corpus 검증 명령

전체 corpus 검증은 한 명령으로 재현한다. `/tmp/opencode` 산출물 없이
`game/**/*.twee`를 직접 읽어 파싱·마스킹·복원하고 구조 불변식을 검사한다.

```bash
python3 -m pretranslation_cst.corpus_verify \
  --root game \
  --report corpus-verify-report.json
```

보고 항목:

- file/passage 수 (passage가 없는 빈 파일도 file 수에 포함)
- split round-trip: `split_twee` 결과의 `prefix_span` + 각 passage `source_span`
  을 재조립해 원본 파일 byte와 비교 (중간 byte 누락·중복 탐지)
- mask/restore round-trip 실패 (mask/restore byte-exact)
- tree parent/span/sibling 불변식 실패 (kind별 집계 + 샘플)
- diagnostic code별·(code, macro)별 개수
- exposed segment kind별 개수와 placeholder 개수
- passage별 protected coverage 비율과 body/protected byte 총합
- baseline과의 delta 및 회귀 여부

`--allowlist`와 `--baseline`으로 versioned allowlist와 baseline 파일 경로를
지정한다(기본값 `pretranslation_cst/data/corpus-allowlist-v1.json`,
`corpus-baseline-v1.json`). `--init-baseline`은 현재 실행 결과를 baseline으로
기록한다. JSON report는 정렬된 key와 안정된 순서만 사용하므로 동일 입력에서
두 번 실행해도 byte-identical이다.

### exit code

round-trip 실패와 구조 회귀를 bitmask로 구분한다.

| code | 의미 |
|------|------|
| 0 | 통과 |
| 1 | round-trip 실패 (decode/split/reassembly/restore) |
| 2 | 구조 회귀 (tree 불변식, 미허용 diagnostic, corpus 수치 불일치) |
| 3 | 1과 2 동시 발생 |

`corpus.file_count`, `corpus.passage_count`, `corpus.twee_byte_count`가
baseline과 다르면(감소뿐 아니라 어떤 방향이든) deviation으로 기록되고
regression으로 판정되어 exit code 2를 낸다. 파일 중간 byte 누락은
`twee_byte_count` 불일치로, passage 삭제는 `passage_count` 불일치로, 파일 삭제는
`file_count` 불일치로 잡힌다.

### versioned allowlist

원문 자체가 malformed인 사례는 parser 결함과 섞지 않고
`corpus-allowlist-v1.json`에 `path`(corpus root 기준 상대 경로), `passage`,
`code`, byte `span`으로 기록한다. diagnostic이 code/path/passage/span 모두
일치해야 allowlist에 매칭된 것으로 친다. 매칭되지 않은 구조 진단은
`unexpected`로 집계되어 exit code 2를 낸다. `unclassified_argument`는 value-kind
공백이므로 allowlist 없이 허용된다. 더 이상 발생하지 않는 allowlist 항목은
`stale_entries`로 보고한다.

### baseline

`corpus-baseline-v1.json`은 corpus, diagnostic, segment kind, 회귀 규칙을 담는다.
`corpus.file_count`/`passage_count`/`twee_byte_count` 불일치, `malformed_args`,
`mismatched_close`, `unclosed_container` 등 defect code의 증가와 `link_label`,
`macro_arg` 등 exposure kind의 감소를 증/감으로 판정하고
`baseline.regression_reasons`에 적는다. corpus 수치와 defect code·exposure
kind의 회귀는 exit code 2를 낸다.

### 현재 기대값 (2026-08-07)

- files 642 (passage 있는 파일 639, 빈 파일 3)
- passages 16,135
- restore failures 0, split failures 0
- tree invariant failures 0
- malformed_args 0, mismatched_close 0
- unclosed_container 2, invalid_macro_name 5, malformed_macro 1,
  unterminated_comment 2 (모두 allowlist 매칭)
- unclassified_argument 0
- unknown_macro 238 (statDisplay.create 405개·위젯·SC built-in 등록 후 잔여 —
  exit/exitAll 218건 정의 미발견, 별도 조사 대상) (value-kind 검수 반영, `docs/value-kind-audit-report.md`)
- segments: link_label 39,157, macro_arg 1,768, plain_text 759,058
- exposed segments 799,983, placeholders 798,038
- protected coverage 평균 0.576128

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
