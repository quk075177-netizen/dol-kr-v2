# 피드백 이슈 분류 및 개선 방향

기준일: 2026-08-07
작성일: 2026-08-07

## 이슈 분류

### I1. `_consume_square` opener 판별 버그 — 확정 버그, 즉시 수정

`parser.py:160`의 opener 루프가 `text[opener] in "<>IiMmGg"`로 문자
집합을 검사한다. 이는 `[img[`의 `i`, `m`, `g`를 **순서대로** 확인하는
것이 아니라, 각 문자가 `IiMmGg` 집합에 속하는지만 본다.

결과: `[Mg[src]]`, `[G[src]]`, `[Igno]]` 같은 비-markup 문자열이
image markup으로 잘못 인식된다. `[Mg[` → `M`∈집합, `g`∈집합, `[` →
opener 완성 → image markup으로 파싱.

수정: `square_markup.py`의 `_lex_left_meta`가 이미 SugarCube 규칙을
정확히 포팅하고 있으므로, `_consume_square`도 `[img[` 또는
`[<img[` / `[>img[` 패턴을 순서대로 매치해야 한다. 정규식
`\[[<>]?[Ii][Mm][Gg]\[` 또는 `_lex_left_meta` 로직 재사용.

영향: corpus에 실제 `[Mg[...]` 형태가 있는지 확인 필요. 버그가
발동하면 잘못된 image node가 만들어지고, 이후 텍스트가 markup 내부로
잘려들어간다.

### I2. 위젯 정의 opaque 처리 — 정책 변경 확정

현재 `widget_definition_opaque`는 위젯 정의 본문 전체를 자식 없이
보호한다. 본문 안의 macro, text, prose를 전혀 스캔하지 않는다.

하지만 실제 위젯 정의에는 번역 대상 prose가 있다:

- `versioninfo`: "Degrees of Lewdity Plus" 등 UI 텍스트
- `presetConfirmDetails`: "Change the below settings?" 등 대화문
- `importConfirmDetails`: "Settings import is invalid" 등 에러 메시지
- `damageClothing`: "당신의 ... 조각나 부서진다!" (ref/ 번역본에 한국어
  있음)
- `damageFaceCover`: 동일
- `animateCombat`: "Layers", "Main options", "Position:" 등 UI 라벨

corpus에서 widget 정의 약 3,030개, 그 중 prose 후보(영어 단어 3개
이상) 약 2,295개. 현재 이 텍스트는 전부 번역 파이프라인에서 빠진다.

정책 변경 방향:

1. 위젯 정의 본문을 opaque가 아닌 일반 passage body처럼 스캔.
2. 위젯 정의 header(`<<widget "name">>`)와 닫기(`<</widget>>`)는
   구조 node로 유지하되, 본문 안의 macro/text/prose를 CST 자식으로
   만든다.
3. 위젯 정의 안의 `<<set>>`, `<<if>>` 등은 이미 parser가 처리할 수
   있으므로, 본문 스캔을 활성화하면 자동으로 CST에 들어간다.
4. 위젯 안의 JS/주석/HTML은 여전히 보호 span으로 처리된다
   (기존 `_collect_markup` 경로).

주의: 위젯 안에 위젯이 중첩되는 경우, 바깥 정의만 등록하고 안쪽은
바깥의 자식으로 처리하는 기존 정책을 유지해야 한다.

영향 범위:

- `cst-scope.md`의 "위젯 정의부" 섹션 수정.
- `sugarcube-ground-truth.md`의 "Widget definition 중첩" 섹션 수정.
- `parser.py`의 `_widget_definitions`가 opaque node 대신 일반 macro
  목록을 반환하도록 변경.
- `_build_tree`의 `widget_definition_opaque` 분기 제거 또는 변경.
- 노출 segment 수치가 크게 증가할 것 (widget 안의 plain_text +
  link_label + macro_arg).
- baseline 갱신 필요.

### I3. bareword 인자는 절대 노출되지 않음 — 확인 결과: 영향 미미

`_classify_args`의 expose 조건이 `arg.lexeme_kind == "string"`을
요구하고, `_attach_argument_nodes`의 라벨 조건도 같다. 따옴표 없는
bareword 인자는 `content_span`이 `None`이라 `prose_text` kind로
분류돼도 절대 노출되지 않는다.

corpus 확인: bareword + prose_text kind 조합은 8건:

- `pluralise[1]` = `$tempRewardType` (변수, 번역 대상 아님)
- `genitalsandbreasts[0]` = `is` (be동사, 번역 대상 아님)
- `genitalsandbreasts[1]` = `are` (be동사, 번역 대상 아님)

전부 bareword가 맞고 번역 대상이 아니다. `pluralise`는 변수명이고,
`genitalsandbreasts`는 be동사이므로 보호가 맞다.

결론: 실제 번역 누락은 없다. 다만 `prose_text` kind를 bareword에
부여한 것 자체가 분류 오류이므로, `pluralise[1]`과
`genitalsandbreasts[0..1]`의 kind를 `structural`로 강등하는 것이
정확하다. 이는 value-kind 검수(P1~P5)에서 처리한다.

### I4. `_split_source`의 `splitlines()` — 수정 권장, 우선순위 낮음

`parser.py:411`이 `str.splitlines(keepends=True)`를 사용한다.
Python의 `splitlines()`는 `\n`, `\r\n` 외에도 `\v`, `\f`, `\x1c`~
`\x1e`, `\x85`, `\u2028`, `\u2029`에서도 줄을 나눈다. Twee의 `::`
header 인식은 `\n` 기준이므로, 이 문자들이 본문에 있으면 잘못된
위치에서 header를 인식할 수 있다.

corpus 확인: 642개 파일 전체에서 특수 줄바꿈 문자 0건 발견.

결론: 실전 영향은 없으나, lossless 파서의 명확성을 위해 `\n` 기준
split으로 변경을 권장. 수정 범위는 `_split_source` 한 곳.

### I5. 참고 수준 이슈들

#### I5a. 표현식 내 `>>` 조기 종료

`<<if $x >> $y>>`에서 `>>`가 표현식 안의 비교 연산자가 아니라
매크로 종결로 해석될 수 있다. SugarCube wikifier 자체도 같은
한계를 가지므로, 파서 버그가 아니라 포맷의 함정이다. 현재 parser는
SugarCube와 같은 동작을 하므로 수정하지 않는다.

#### I5b. `widget_definition_opaque`가 항상 `root.children`에 붙음

`_build_tree`가 `widget_definition_opaque`를 `stack[-1]`이 아닌
`root.children`에 직접 붙인다. 매우 드문 케이스(조건부 위젯 정의,
`<<if>><<widget>>...<</widget>><</if>>`)에서 트리 중첩 구조가 실제
문서 순서와 어긋날 수 있다. 바이트 커버리지는 깨지지 않으므로
재조립에는 영향 없다.

I2(위젯 opaque 해제)가 적용되면 이 이슈는 자연히 해소된다.
위젯 정의가 일반 macro로 처리되면 `stack[-1]`에 붙기 때문이다.

## 개선 우선순위

| 우선순위 | 이슈 | 작업 | 영향 |
|---|---|---|---|
| 1 | I1 | `_consume_square` opener 수정 | 버그 수정, 회귀 위험 낮 |
| 2 | I2 | 위젯 정의 opaque 해제 | 정책 변경, 노출 대폭 증가, baseline 갱신 |
| 3 | I3 | bareword prose_text kind 강등 | value-kind 검수에서 처리 |
| 4 | I4 | `splitlines` → `\n` split | 명확성, 실전 영향 없음 |
| — | I5a | 수정 안 함 | 포맷 함정, SugarCube 동작 일치 |
| — | I5b | I2 해결로 자연 해소 | — |

## 구현 계획

### F1. `_consume_square` opener 수정 (I1)

`_consume_square`의 opener 판별을 문자 집합 검사에서 순서 매칭으로
변경. `square_markup.py`의 `_lex_left_meta` 로직을 참조하거나, 정규식
`\[[<>]?[Ii][Mm][Gg]\[`로 교체.

검증:

- `[Mg[src]]`, `[G[src]]`가 더 이상 image markup으로 인식되지 않음.
- `[[link]]`, `[img[src]]`, `[Img[src]]`, `[>img[src]]`는 정상 작동.
- corpus_verify exit 0, baseline 일치 (또는 의도된 변화만).

### F2. 위젯 정의 opaque 해제 (I2) — 완료

정책 변경:

1. `_widget_definitions` prepass 제거. `<<widget>>`/`<</widget>>`을
   일반 container macro로 처리 (registry에 이미 container로 등록됨).
2. 위젯 본문 안의 macro/text/prose를 일반 passage body처럼 스캔.
3. 중첩 widget 정의는 container 중첩으로 바깥 위젯의 자식으로 처리.
4. `widget_definition_opaque` node type 제거.
5. `cst-scope.md`와 `sugarcube-ground-truth.md` 갱신.

부수 수정: `_standalone_markup_nodes`가 markup span이 ignored(매크로)
span을 삼키는 경우 스킵하도록 변경. 이는 cheats.twee의 `"""[[` 인용
텍스트가 매크로와 겹치던 tree invariant 실패를 해결한다.

결과:

```text
plain_text: 496,421 → 759,058  (+262,637, 위젯 본문 prose 노출)
link_label:  32,908 →  39,157  (+6,249, 위젯 안 링크 라벨)
macro_arg:      952 →   1,322  (+370, 위젯 안 매크로 prose)
unclassified_argument: 18 → 9,072 (위젯 안 매크로 인자 value-kind schema 누락)
tree invariants: 0 failures 유지
round-trip: 0 failures 유지
exit code 0
```

`unclassified_argument` 9,072 증가는 위젯 본문 안 매크로 인자가
value-kind schema에 아직 없는 것. T2 value-kind residual 정리에서
처리한다.

### F3. `splitlines` → `\n` split (I4)

`_split_source`의 `splitlines(keepends=True)`를 `\n` 기준 split으로
변경.

검증:

- corpus_verify exit 0, baseline 일치 (특수 문자가 없으므로 수치
  변화 없음).

### F4. bareword prose_text kind 강등 (I3)

`pluralise[1]`, `genitalsandbreasts[0]`, `genitalsandbreasts[1]`의
kind를 `structural`로 변경. value-kind 검수(P1~P5)에서 처리.