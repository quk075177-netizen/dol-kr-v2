# macro grammar registry 전수 감사 (2026-08-07)

## 1. 목적

`pretranslation_cst/data/macro-grammar.json`(이하 manifest)은 SugarCube
built-in과 game JS의 매크로 정의를 반영해야 한다. 이 문서는 전수 감사 도구와
그 결과, 그리고 manifest v1 → v2 변경 근거를 기록한다.

도구: `python3 -m pretranslation_cst.macro_audit` (read-only)

```text
audit                     manifest ↔ SugarCube 스냅샷 ↔ game/**/*.js 대조
audit --sugarcube PATH    pinned 스냅샷 ↔ live SugarCube checkout drift 대조 추가
audit --corpus game/      전체 corpus 파싱 후 mismatched_close/unclosed_container 귀속 판정
extract-sugarcube         SugarCube 소스에서 스냅샷 JSON 추출 (정본 생성 명령)
```

- registry는 자동 생성하지 않는다. manifest(v2, versioned)가 정본이다.
- audit은 **읽기 전용**이며 누락/불일치를 발견하면 exit code 1로 실패한다.
- 두 번 실행하면 byte-identical한 보고서를 낸다 (`--json-out`).

## 2. 정본 소스와 추출 규칙

SugarCube ground truth는 `/tmp/opencode/sugarcube-2` (2.38.0-alpha.10)이며,
`src/macro/macros/*.js`와 `src/macro/deprecated-macros.js`의
`Macro.add(...)`를 파싱해 `pretranslation_cst/data/sugarcube-extracted.json`
스냅샷에 고정한다. game은 `game/**/*.js`를 매 실행 live 추출한다.

각 정의에서 다음을 확정한다 (SugarCube `parserlib.js` `parseBody`/`skipArgs`
규칙을 그대로 이식):

| JS 속성 | 파서 의미 | manifest 필드 |
|---|---|---|
| `tags` 프로퍼티 존재 | container (`parseBody` 호출) | `body_kind: container` |
| `tags` 배열 | branch 목록 | `tags` 키 |
| `tags: null` | container, branch 없음 | `tags` 없음 |
| `skipArgs: true` | 본인과 모든 branch raw | `arg_mode: raw` |
| `skipArgs: ['x']` | 이름에 포함된 tag만 raw | 해당 branch `raw` |
| `Macro.add(n, 'other')` | alias — target의 spec 복사 | `run`→`set`, `silently`→`silent` |
| `Macro.delete` 후 재정의 | game_override | `button`, `link` |
| `DefineMacro(S)(name, fn, tags, skipArgs)` | tags/skipArgs 매개변수 반영 | `svg` 등 |

동적 이름 정의(`DefineMacro` 본문의 `macroName`, `condition.js`의
`widgetName`, `statDisplay.create`의 `name`)는 정적으로 확정할 수 없으므로
audit 보고서의 dynamic definitions 목록에 evidence(file:line)와 함께
기록하고 검증 대상에서 제외한다.

## 3. 감사 항목

manifest의 각 entry에 대해:

1. **source 존재**: 해당 매크로가 SC 스냅샷 또는 game JS에 정의되어 있는가
   (branch tag는 부모 container의 `tags`로 해석 — `case`는 `switch`의 자식).
2. **source 종류 일치**: `sugarcube` / `sugarcube_deprecated` / `game_js` /
   `game_override` 정확 일치.
3. **body_kind**: JS의 tags 프로퍼티 존재 여부와 일치하는가.
4. **arg_mode**: skipArgs 규칙에서 유도한 값과 일치하는가.
   (`none`은 handler가 인자를 거부한다는 근거가 allowlist에 있을 때만 허용)
5. **tags**: manifest branch 키 집합과 JS tags 배열이 일치하는가.
6. **branch arg_mode**: skipArgs 배열/부울에서 유도한 branch별 raw/parsed와
   일치하는가 (`none`은 4번과 동일한 allowlist 규칙).

완전성:

7. 소스에 정의된 **모든 container**가 manifest에 있어야 한다
   (누락은 `mismatched_close` 후보).
8. `--corpus`: 전체 corpus를 파싱해 `mismatched_close`/`unclosed_container`
   를 귀속 판정한다. registry 결함(누락 container, false container)은
   error, 소스 자체 malformation은 info로 구분해 보고한다.

## 4. allowlist (정적으로 추정 불가한 의미)

`pretranslation_cst/data/macro-grammar-audit-allowlist.json` — 정규식/정적
분석으로 JS 전체 의미를 추정할 수 없는 항목만 명시적 허용 + 근거 위치.

| 키 | kind | 근거 |
|---|---|---|
| `if.else` | `handler_none_args` | `sugarcube-2/src/macro/macros/if.js:50` — "<<else>> does not accept a conditional expression" |
| `switch.default` | `handler_none_args` | `sugarcube-2/src/macro/macros/switch.js:34` — "<<default>> does not accept values" |
| `dialog.onclose` | `handler_none_args` | `game/03-JavaScript/macros/popup.js:24` — onopen/onclose의 payload 인자를 읽지 않음 |
| `dialog.onopen` | `handler_none_args` | 동일 |

## 5. manifest v2 변경 (감사 결과 반영)

| 항목 | 변경 | 근거 |
|---|---|---|
| `action` → `actions` | 이름 오류 수정 + source `sugarcube_deprecated` | SC는 `actions`(복수)만 정의 — deprecated-macros.js:20 |
| `unless` 제거 | SC 2.38에 없음(상류에서 제거), game JS에도 없음, corpus 미사용 | — |
| `style` 제거 | SC 2.38에 없음(상류에서 제거), game JS에도 없음, corpus 미사용 | — |
| `silently` source → `sugarcube_deprecated` | deprecated-macros.js:15의 alias | — |
| `radiovar` 추가 | container, parsed | `game/03-JavaScript/ui-radiovar.js:10` (`tags: null`) |
| `svg` 추가 | container, parsed | `game/03-JavaScript/base.js:577` (`DefineMacroS(..., null, false, true)`) |
| `c`/`cap`/`allCap` 추가 | container, parsed | `game/03-JavaScript/macros/capitalise.js:5` (`tags: null`) |
| `defer` 추가 | container, parsed | `game/03-JavaScript/02-Helpers/macros.js:71` (`tags: null`) |

`schema_version: 2`, `pinned_sources`, `removed`(근거 포함) 메타데이터 추가.
`grammar.py`는 `macros` 키만 읽으므로 하위 호환이다.

### corpus 영향

- radiovar/svg/c의 corpus 사용처는 전부 widget 정의(opaque) 또는 raw
  표현식/backtick/link label 안이라 파서가 스캔하지 않는다. 따라서 corpus
  진단에는 영향이 없다(아래 before/after 동일).
- 그러나 widget 밖에서 열린다면 누락 container는 `mismatched_close`를
  만들 수 있으므로 registry가 JS 정의를 정확히 반영해야 한다.

## 6. 감사 실행 결과 (전수)

- manifest entry 48개 전부 source 종류 + evidence 추적 가능
  (trace 표는 `--json-out` 보고서 참고).
- game JS에서 정의된 container 16개 전부 manifest에 존재: `addinlineevent`,
  `allCap`, `button`(override), `c`, `cap`, `compute`, `condition`, `defer`,
  `dialog`, `dynamicblock`, `foldout`, `link`(override), `radiovar`,
  `safereplace`, `svg`, `twinescript`.
- SC container 22개 전부 manifest에 존재.
- 동적 정의 5건: `macroName`(base.js DefineMacro/DefineMacroS 본문),
  `widgetName`(condition.js 조건부 매크로), `name`(statDisplay.create) —
  evidence 기록.
- drift: live `/tmp/opencode/sugarcube-2`와 pinned 스냅샷 불일치 0건.

## 7. corpus before/after (전체 game/, 642 files, 16,135 passages)

| 진단 | before | after |
|---|---:|---:|
| unclassified_argument | 23,206 | 23,161 |
| invalid_macro_name | 5 | 5 |
| malformed_macro | 1 | 1 |
| mismatched_close | 0 | 0 |
| unclosed_container | 2 (소스 자체 결함, 귀속 없음) | 2 (동일) |
| unterminated_comment | 2 | 2 |
| exposed segments (plain_text / link_label / macro_arg) | 496,421 / 32,728 / 525 | 동일 |

`unclosed_container` 2건은 `overworld-forest/loc-forestshop/gwylan-clothes.twee`
"Gwylan Talk Clothes Eden 2/Chef Cream"의 소스 결함(닫히지 않은 `<<if>>`/
`<<switch>>`)으로 registry 오류가 아니다. 감사는 이를 source-caused로
구분해 error로 세지 않는다.
