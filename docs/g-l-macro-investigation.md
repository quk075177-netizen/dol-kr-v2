# g/l 접두사 매크로 조사 계획

기준일: 2026-08-08
상태: 1차 조사 완료

## 배경

F5(unknown_macro diagnostic) 적용 후 남은 24,704건 중 상위 항목이
g/l 접두사 매크로였다 (`gstress` 2,955, `lstress` 1,837, `gtrauma` 1,403,
`garousal` 1,305 등). 이 매크로들의 정의를 조사한다.

## 1차 발견: `statDisplay.create` 동적 등록 (확정)

**결정적 발견**: `game/base-system/text.js:64-67`

```js
statDisplay.create("lstress", () => statDisplay.statChange("Stress", -1, "green"));
statDisplay.create("llstress", () => statDisplay.statChange("Stress", -2, "green"));
statDisplay.create("lllstress", () => statDisplay.statChange("Stress", -3, "green"));
statDisplay.create("gstress", () => statDisplay.statChange("Stress", 1, "red"));
```

- g/l 접두사 매크로는 **`statDisplay.create(name, fn)`**으로 동적 정의된다.
- 이름 의미: `g*` = 상태 증가(red), `l*` = 상태 감소(green),
  `gg*`/`ll*` = 증감량 2배, `ggg*`/`lll*` = 3배.
- **규모: `statDisplay.create` 405개** (g/l 계열 전체).

### 적용 결과 (S1 완료)

1. `collect_known_macro_names`에 `statDisplay.create` 패턴 추가
   → unknown_macro 24,704 → 597 (97.6% 감소)
2. 남은 597건 중 SC built-in 매크로 7개(`include`, `addclass`,
   `removeclass`, `toggleclass`, `numberbox`, `textbox`, `textarea`)를
   macro-grammar.json에 등록 (SC 스냅샷에 있던 leaf 매크로, audit가
   container만 완전성 검사해서 누락됐던 것)
   → unknown_macro 597 → **238**
3. **최종: 238건, 11종**

### 남은 unknown (238건, 11종)

| 매크로 | 수 | 상태 |
|---|---:|---|
| `exit` | 181 | 정의 미발견 — 조사 대상 |
| `exitAll` | 37 | 정의 미발견 — 조사 대상 |
| `lubePrice`/`condomsPrice` | 13 | 위젯으로 추정 (파일 밖 정의?) |
| 나머지 6종 | 7 | 1건씩, 위젯/오타 추정 |

`exit`/`exitAll`은 위젯 정의도, JS Macro.add도, statDisplay.create도
아닌데 218회 사용된다. 전투 UI(`base-combat/*.twee`)에서 집중 사용 —
별도 조사 항목으로 남긴다. 238건은 unknown_macro가 NON_STRUCTURAL이라
회귀를 트리거하지 않는다.

## 남은 조사 항목

### S2. exit/exitAll 정의 위치 — 해결 (2026-08-08)

**결론: 엔진 패치 매크로.** 게임 소스(.twee/.js)와 pinned SugarCube
2.38.0-alpha.10 어디에도 정의 없음. SugarCube 공식 문서(2.37.3)에도 없음.
하지만 컴파일된 빌드(`ref/Degrees of Lewdity_kr.html`)에서 정의 확인:

```js
Macro.add(["exit","exitAll"],{skipArgs:!0, handler(){
  // exit에 인자가 있으면 표현식 평가 → 위젯 반환값(_widgetReturn)으로 저장
  Wikifier.stopWikify = "exit" === this.name ? 1 : 2;
}})
```

- `<<exit>>` = 현재 컨테이너(위젯/switch) 조기 종료 (break/return). 인자는
  위젯 반환값 표현식 (`<<exit _text_output>>`) — **번역 대상 아님**.
- `<<exitAll>>` = 중첩 컨테이너 전체 종료.
- 빌드 시 03-Patcher 계열 툴링으로 주입되는 것으로 보임 (게임 저장소에는
  미포함). DoL은 위젯 패치(`dol-widget.js` — ref/vanila-kr-5.2.8에 잔존)와
  함께 커스텀 엔진을 쓴다.

**적용 (unknown_macro 238 → 6):**

1. `exit`/`exitAll`을 macro-grammar.json에 `arg_mode: raw, source:
   engine_patch`로 등록 — 인자는 런타임 표현식이므로 전부 보호.
2. macro-audit-allowlist에 `manifest_entry_without_source` 예외 등록
   (정의가 소스에 없어 감사 불가 — 컴파일 빌드가 근거).
3. `collect_known_macro_names`에 상수로 추가.
4. **WIDGET_NAME_RE 수정**: `<<widget lubePrice>>`처럼 인용부호 없는 위젯
   정의를 매치하지 못해 lubePrice/condomsPrice(13건)가 unknown이었던 것도
   해결 (quoted/unquoted 모두 지원).
5. **SC leaf 매크로 7종 누락 보완**: back/choice/copy/goto/redo/remove/
   return이 grammar에서 빠져 있었음 — pinned snapshot 기준 추가.

**남은 6건 (모두 NON_STRUCTURAL, 파이프라인 무해):**

| 매크로 | 위치 | 판정 |
|---|---|---|
| `actionsfencingtease` | base-combat/effects.twee | 게임 소스 오타 (정의 없음, 1회 사용) |
| `OverTopShop` | loc-adultshop/shop.twee 외 | 정의 누락 (위젯 미등록) |
| `her` | special-avery/avery steal.twee | ModLI 계열 미정의 |
| `babyIntro`, `npc_him`, `npc_Hes` | ModLI/Poppy/*.twee | ModLI 모드 매크로 (npc_*는 `nnpc_*` 오타로 추정) |

### S3. dol-kr Post 계열 대조 (조사 시스템 참고)

dol-kr `game/base-system/translate/Post/` 구조를 참고:

- **EasyPost.js/twee**: 원본 매크로 출력 뒤에 조사를 붙이는 **대체
  위젯**을 테이블+eval로 동적 등록 (305개).
  - 예: `<<HePost "을">>` = `<<He>>` 출력 + "을/를" 조사
  - `_trResult`(번역문)와 `_trPost`(조사)를 분리 저장하는 패턴
- **trPost.js**: `getPostNum` 받침 판정 + `trPostsList` 26개 조사×3형태
- 우리 post 시스템(`{{post:...}}` 마커)과의 관계:
  - 우리 방식 = LLM 출력 후처리 (번역문의 조사 마커)
  - dol-kr 방식 = 원본 매크로 호출부에서 조사 부착 (게임 런타임)
  - 3-match 재사용 시 KO 번역에 `<<XPost>>` 호출이 있으면 파서가
    처리해야 하는지 판정 필요

## 완료 기준 (갱신)

- [x] statDisplay.create 405개가 known으로 등록됨
- [x] unknown_macro 24,704 → 238 (99.0% 감소)
- [x] exit/exitAll 정의 위치 확인 (엔진 패치, 컴파일 빌드에서 검증)
- [x] unknown_macro 238 → 6 (exit/exitAll + SC 누락 7종 + 인용부호 없는 위젯)
- [ ] dol-kr Post 계열 대조 결과 문서화

## 참고 자료

- `game/base-system/text.js:64` — statDisplay.create 정의
- `game/base-system/translate/` (dol-kr) — Post 계열 대체 위젯
- `research/dol-kr-architecture.md` — EasyPost/trPost 구조
- `docs/post-system-design.md` — 우리 post 시스템 설계
- `docs/system-review-triage.md` — F5 적용 내역