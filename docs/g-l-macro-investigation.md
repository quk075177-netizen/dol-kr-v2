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

### S2. exit/exitAll 정의 위치

- [ ] `<<exit>>`가 전투 UI에서 어떤 동작인지 (전투 종료?)
- [ ] 정의가 어디 있는지 (다른 JS 파일, 또는 위젯 정의 형태 변형)
- [ ] 번역 관련성 (화면 텍스트 노출 여부)

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
- [ ] exit/exitAll 정의 위치 확인
- [ ] dol-kr Post 계열 대조 결과 문서화

## 참고 자료

- `game/base-system/text.js:64` — statDisplay.create 정의
- `game/base-system/translate/` (dol-kr) — Post 계열 대체 위젯
- `research/dol-kr-architecture.md` — EasyPost/trPost 구조
- `docs/post-system-design.md` — 우리 post 시스템 설계
- `docs/system-review-triage.md` — F5 적용 내역