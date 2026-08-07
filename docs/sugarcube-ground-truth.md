# SugarCube 대조 규칙

## 1차 사료

경계 판별과 인자 lexing은 다음 SugarCube 원본을 ground truth로 삼는다.

- `/tmp/opencode/sugarcube-2/src/markup/wikifier.js`
- `/tmp/opencode/sugarcube-2/src/markup/parserlib.js`
- `/tmp/opencode/sugarcube-2/src/lib/patterns.js`
- `/tmp/opencode/sugarcube-2/src/markup/wikifier-util.js`

TextMate grammar나 자체 정규식은 참고 자료일 뿐, 경계의 정본이 아니다.

## Macro boundary

SugarCube macro는 다음 형태다.

```text
<<(/?macroName) whitespace-protected-body>>
```

`macroName`은 `[A-Za-z][A-Za-z0-9_-]*` 또는 특수 매크로 `=`/`-`다.
body에서 `>>`가 종결이고 단일 `>`는 본문에 들어갈 수 있다.

다음 요소는 body scan 중 보호 단위다.

- `/* ... */` block comment
- `// ...\n` line comment
- backtick expression
- single/double quoted string
- regex literal
- `[[...]]` 및 image square markup
- `>` 단독 문자

이 규칙은 “매크로를 찾는 정규식”을 그대로 복사하는 대신 상태 머신으로
포팅한다. 상태 머신은 반드시 passage body end를 상한으로 받으며, 종결 실패
시 prose로 복구하지 않고 malformed diagnostic을 낸다.

## Argument lexer

`parseArgs`의 토큰 종류는 다음과 같다.

- `Bareword`
- backtick `Expression`
- single/double `String`
- nested `SquareBracket`

공백 split을 사용하지 않는다. quote escape, newline/EOF에서의 미종결,
square bracket depth, image metadata를 보존한다. 인자의 raw span과 문자열
content span을 모두 기록한다.

## Container와 branch

container stack은 같은 이름의 open/close를 중첩 추적한다. 닫기 tag에 인자가
있으면 malformed로 기록하고, 다른 이름의 `/...` 또는 `end...` 닫기는
SugarCube의 `parseBody` 규칙에 맞춰 skip/diagnostic 처리한다.

`macro.tags`에 해당하는 body tag는 별도 `macro_branch` node로 만든다. 대표
예시는 `if/elseif/else`, `switch/case/default`다. 중첩 container는 현재
container의 branch 안에 자식으로 들어간다.

모든 container registry는 SugarCube built-in 정의와 현재 game의 widget
definition header에서 얻는다. registry에 없는 macro는 leaf call로 보호하고,
닫기 구조를 임의로 추정하지 않는다.

## Link와 markup

`parseSquareBracketedMarkup`의 depth와 delimiter 규칙을 따른다.

- target/link/setter는 보호
- 순수 literal display label만 `text` 또는 `prose_text` 후보
- `$`, `_`, backtick, `${...}`, 문자열 연결이 들어간 label은 전체 보호
- HTML tag와 comment는 node로 보호하고 내부 fake macro를 재스캔하지 않음

## 최소 fixture

- `<<if $x >> 5>>`
- `<<set $x to "a >> b">>`
- ``<<print `x >> y`>>``
- `<<link [[text|target]]>>`
- `<<if>>...<<else>>...<</if>>`
- `<<= $var>>`, `<<- $var>>`
- regex argument
- malformed closing tag
- 한글 앞뒤의 macro byte span
- widget definition 안의 fake macro가 자식 node가 되지 않는지
