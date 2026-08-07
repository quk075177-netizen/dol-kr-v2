# CST 구현 로드맵

이 문서는 `docs/cst-scope.md`, `docs/sugarcube-ground-truth.md`,
`docs/value-kind-policy.md`, `docs/validation.md`를 실제 코드로 옮기는 순서다.
목표는 짧은 함수와 평범한 자료구조를 사용해, parser를 처음 보는 사람도 한 파일의
규칙을 고칠 수 있게 하는 것이다.

## 구조 원칙

- 외부 의존성 없이 Python 표준 라이브러리만 사용한다.
- 원문은 항상 `bytes`로 보관하고, 사람이 읽는 문자열은 필요한 순간에만 decode한다.
- 한 파일을 한 번만 `SourceContext`로 decode하고, 모든 span은 그 context를 공유한다.
- boundary 탐색, passage 분류, CST 조립, masking을 서로 다른 모듈에 둔다.
- 실패하면 prose로 추정하지 않고 보호 span과 진단을 남긴다.
- public API는 `parse_file`, `split_twee`, `mask_passage`, `restore_mask`와
  dataclass 모델로 제한한다.

## 단계

### 1. 기반 모델과 SourceContext `[완료]`

`Span`, `Diagnostic`, passage/node dataclass, UTF-8 문자-바이트 변환표를 만든다.
완료 기준은 한글 span과 BOM prefix의 byte equality 테스트다.

### 2. Twee splitter와 opaque passage `[완료]`

`::` header를 lossless하게 나누고 이름/tag를 읽는다. `Story*` special passage와
`[script]`/`[stylesheet]` tag는 body 하나를 `passage_opaque`로 만든다.
완료 기준은 split/assemble round-trip과 opaque body 내부 macro 미스캔 테스트다.

### 3. Macro boundary와 argument lexer `[완료]`

문자열, backtick, comment, regex, square markup을 건너뛰는 상태 기반 scanner와
raw/content span을 보존하는 lexer를 만든다. 완료 기준은 `>>` 경계 fixture와
unterminated diagnostic이다.

### 4. Widget prepass와 tree builder `[완료]`

widget depth를 먼저 계산하고 바깥 정의만 opaque로 보호한다. 그 밖의 macro를
container stack으로 `passage_root` 아래에 배치하고 parent/depth/sibling order를
결정한다. 완료 기준은 nested widget과 ancestor/sibling 조회다.

### 5. 노출 후보와 masking `[완료]`

value-kind를 fail-safe로 적용하고, literal link label/HTML/comment/variable을
보호 경계로 처리한다. 완료 기준은 prose만 노출되고 restore가 byte-exact인 것이다.

### 6. CLI와 corpus 검증 `[완료]`

JSONL CLI, fixture 모음, 전체 `game/**/*.twee` 검증 명령을 제공한다. 완료 기준은
두 번 실행한 JSONL이 동일하고 전체 파일 split/restore가 성공하는 것이다.

각 단계는 앞 단계의 테스트가 통과한 상태에서만 다음 단계로 넘어간다.

## 현재 상태

2026-08-07 기준 구현은 1~6단계까지 완료했다. `game/` 642개 파일,
16,135개 passage의 parse/mask/restore가 byte-exact로 통과했고, 전체 CLI JSONL도
16,135행을 생성했다. CLI 결정성은 대표 `game/01-config` 디렉터리를 두 번 실행해
SHA-256이 동일한 것으로 확인했다.
