# Value-Kind 분류 품질 검수 보고서

기준일: 2026-08-07 (I2 위젯 opaque 해제 반영, commit 6236c66 이후)

## Part A: 위젯 residual 정리

I2로 위젯 본문이 스캔되면서 `unclassified_argument`가 18 → 9,072로 증가했다.
본 검수에서 corpus(`game/**/*.twee`, 642 files / 16,135 passages)를 직접
파싱해 진단 9,072건 전부에 대해 source/passage/macro/argument index/raw
text를 수집하고, 정의부(위젯 body, JS `Macro.add`/`DefineMacroS` signature,
SugarCube 소스)를 확인해 인자 위치별 kind를 확정했다.

### A1. UI 위젯 매크로

| macro | before | 분류 내역 |
|---|---:|---|
| `numberStepper` | 2,396 | `[0]` title → **prose_text** (정의: titlebox에 `Wikifier.wikifyEval(title)` 표시; 기존 body_part은 오분류였음). `[1]` initialValue, `[2]` setter 변수명, `[3]` options 객체 → **structural**. `[4..64]` → **structural** (options 객체/함수 literal token; 정의는 args 0-3만 소비) |
| `numberslider` | 1,033 | `[0..4]` 변수명/기본값/min/max/step → **structural**. `[5..144]` → **structural** (callbacks 객체 literal token; settings.twee의 대형 객체 리터럴 785행) |
| `rangeslider` | 186 | `[0..8]` 변수명/수치/options/callbacks → **structural**. `[9..46]` → **structural** (literal fragment) |
| `radiovar` | 156 | `[0]` 상태 변수명, `[1]` 설정값 → **structural**. `[2]` 선택지 라벨 → **prose_text** (정의: `$("<label>").append(args[2])`) |
| `option` | 311 | **지시문 가정과 다른 결론**: SugarCube cycle/listbox에서 `<<option label value [selected]>>`이므로 `[0]`이 표시 라벨(정의: `.text(opt.label)`), `[1]`이 저장 값, `[2]`가 `"selected"` 플래그다. `[0]` → **prose_text**, `[1]` → **arbitrary_text**(저장 값), `[2]` → **structural** |
| `checkbox` | 51 | `[0..3]` 변수명/체크·언체크 값/옵션 → **structural**. `[4..21]` → **structural** (옵션 객체 literal fragment) |
| `case` | 109 | `[9..51]` 추가 switch case 값 → **structural** (정의: SugarCube switch는 무제한 값) |

### A2. 게임 위젯 매크로

| macro | before | 분류 내역 |
|---|---:|---|
| `sex` | 280 | `[2]` → **structural** (정의: `$NPCList[_args[2]]` — double penetration NPC index) |
| `brat` | 244 | `[0]` → **structural** (stress amount, 정의: `stress _args[0] …`, `def _args[0]/4`). `[1]` → **structural** (call: `$*target` NPC index vars, 정의에서 미사용 dead arg). `[2]` → **structural** |
| `their` | 188 | `[0]` → **structural** (NPC index, 정의: `hisselect $_target`) |
| `hisselect` | 155 | `[0]` → **structural** (NPC index 0-5, 정의 주석) |
| `shopHuntActorName` | 204 | `[0]` → **named_npc** (정의: `$shopHunt.actors[key].name` 출력). `[1..2]` → **arbitrary_text** (`"cap"`/`"trueName"` 플래그) |
| `shopHuntLocName` | 91 | `[0]` → **location** (정의: location key → prose 표시명). `[1]` → **arbitrary_text** (`"simple"`/`"sound"`/`"cap"`) |
| `generateCombatAction` | 90 | `[0]` → **structural** (options table). `[1..2]` → **arbitrary_text** (action/combat type key) |
| `machine_damage` | 85 | `[0]` → **structural** (`$machine[key].health`) |
| `foldout` | 82 | `[0]` → **structural** (초기 열림 플래그), `[1]` → **structural** (상태 변수명) |
| `meek` | 78 | `[0]` → **structural** (meek value), `[1]` → **structural** (NPC index, 미사용) |
| `tentacle_record` | 74 | `[0]` 기존 body_part **오분류 수정** → **arbitrary_text** (정의: `$combat_tentacle_record[key]` — arousal/fluid/damage 등 기록 key). `[1]` → **structural** (amount). `[2..15]` → **structural** (수식 literal fragment) |
| `combat-set-hand-target` | 102 | `[0]` → **arbitrary_text** (hand key), `[1]` → **arbitrary_text** (target key — 신체/의복/성도구 혼합) |
| `combat-reset-hand` | 60 | `[0]` → **arbitrary_text** (hand key) |
| `bodypart_admire` | 57 | `[0]` → **body_part** (정의: `$skin[key]`), `[1]` → **arbitrary_text** (mode key) |
| `submission` | 54 | `[1]` → **structural** (NPC index, 미사용) |
| `characteristic-box` | 54 | `[0]` → **structural** (config 객체) |
| `struggle_appendage` | 53 | `[0]` → **structural** (`$struggle[key].creature`) |
| `shopHuntStun` | 51 | `[0..3]` → **structural** (actor id/turns/array/flag) |
| `bodywriting_finalisation` | 49 | `[0]` → **body_part**, `[1]` → **arbitrary_text** (`"machine"`) |
| `toggleclass` | 48 | `[0]` → **structural** (CSS selector), `[1]` → **structural** (class name) |
| `actionstentacleadvcheckbox` | 135 | `[0]` → **arbitrary_text** (disposition key), `[1]` → **prose_text** (표시 라벨), `[2..4]` → **structural** (radiobutton 변수명/값/체크값) |

### A3. 기타 등록

- 위 표 이외 5xx개 매크로(합계 1,393행)도 동일한 근거로 등록했다. 정의부
  위젯 body의 `_args[N]` 사용처와 call-site raw value를 근거로:
  - `$*target`/`_n`/`$_i` 등 NPC index → structural
  - body-part literal key (mouth/vagina/anus/forehead/...) → body_part
  - `$NPCList[_n]`/`$NPCName[_i]`/`fullDescription` → named_npc
  - slot/hand/색상/flags 키 → arbitrary_text
  - 수치·객체·플래그 → structural
- 근거가 불충분한 항목은 없었다(전 항목에 정의부 또는 call 값 근거 존재).
- **수정 금지 파일(parser/grammar/model 등)은 변경하지 않았다.** 객체
  리터럴이 positional arg로 토큰 분해되는 것은 parser 동작이며, 이에 대한
  수정은 범위 밖으로 보고에만 기록한다.

### Part A 결과

```text
unclassified_argument: 9,072 -> 0
```

## Part B: P1~P5 검수

### P1. kind 없는 항목 정리 (223 → 0)

검수 전 config의 kind 없는 항목 223개(전부 note만 보유)를 추출했다. Part A
등록 과정에서 10개가 kind를 얻었고, 나머지 213개는 note와 실제 call-site
string literal 값을 추출해 근거를 확정했다. 최종적으로 kind 없는 항목은
0개다(제거한 항목 없음 — 전 항목에 근거 존재).

주요 패턴:

- `*wear[1]/[2]/[3]`, `*send[1]/[2]/[4]` (색상/액세서리 색상/전달 인자) →
  arbitrary_text (call)
- `passed to >generalUndress()/generalWear()/generalSend()` 계열 →
  arbitrary_text (전달되는 slot/key)
- `assigned to $…` 변수 의미별 분류 (NPC index → structural, key → arbitrary_text)
- prose 표시가 확정된 것만 prose_text 부여: `dolpSettingsTabButton[0]`,
  `startOptionsComplexityButton[0]`, `earSlimeCafeLinks[0]`,
  `earSlimePoundLinks[0]`, `birthCradle[0]`, `whitneyRoofRuleBreak[0]`

### P2. arbitrary_text 재검토 (샘플 30)

전체 871개 항목(검수 전 336 + Part A 추가 535)에서 무작위 30개를 추출해
실제 호출부 값과 정의부를 확인했다. **오분류 0개 (0%)**. 샘플 값 전부
key/플래그/색상/슬롯 식별자로 번역 대상이 아니었다. 임계 10% 미만으로
전수 재검토 불필요.

### P3. prose_text 노출 검증

prose_text 항목 43개 중 string literal이 실제로 노출된 것은 32개
매크로/인덱스, 노출 segment는 **1,768**개(전체 macro_arg). 전 노출 값을
검토한 결과:

- **강등 1개**: `avery_mansion_party_speech[1]` (llm high) — 값이
  `"caught_warned"`, `"movies_insult"`, `"bribe_large"`, `"fox_demand"` 등
  **내부 speech key** (정의: `$avery_party.speech_*`에 push 후
  `current_speech is "intro"` 비교). → arbitrary_text로 강등.
- 그 외 전부 사용자 facing 텍스트 확인:
  - UI 라벨: `option[0]` ("Hide"/"Default"/"Front"...), `numberStepper[0]`
    ("Lust"/"Deviancy"/"Pregnancy progress"...), 설정 탭 버튼
  - 표시 문장: `insufficientStat[1]`, `hypnosisText[0]`, `gagged_speech[0]`,
    `gwylanCommand[0]`, `swarminit[1..4]`, `wheeze[0]` 등
  - 표시 단어: `pluralise[1..2]`, `possessedWord[0]`, `pull_leash[0]`
- **알려진 edge case** (사용자 facing이나 마크업/템플릿 포함, index 단위
  분류 한계로 잔존):
  - `actionstentacleadvcheckbox[1]` 중 `"Kick _the _tentacle.fullDesc"`류
    템플릿 문자열 9/45행 (렌더 시 "the tentacle" 표시)
  - `add_link[0]`/`fadeText[0..1]`의 `<<link [[...]]>>` 포함 마크업 문자열
  - `numberStepper[0]`의 `"_title"` 템플릿 변수명 1행
  - `pluralise[1]`의 빈 문자열 1행 (마스킹 단계에서 무해)

### P4. 시맨틱 kind 4종 실사용 검증

각 kind에서 15개씩 샘플링해 실제 값이 kind와 일치하고 glossary 매칭이
가능한지 확인했다.

| kind | 항목 수 | 샘플 오분류 | 수정 내역 |
|---|---:|---:|---|
| `named_npc` | 132 | 2 | `loadnpc[1]`(save key), `enableschoolrescue[0]`(조건 key 혼합) → arbitrary_text |
| `clothing` | 47 | 7 | 슬롯/재료 key 계열 7개(`generalSend[1]`, `generalSend[2]`, `oldWardrobeList[0]`, `feetUndress[0]`, `showLayer[0]`, `leash[0]`, `ingredientsSupplied[0]`) → arbitrary_text |
| `body_part` | 108 | 3 | `npcVirginityWarning[0]`(NPC명) → named_npc, `cheatVirginityToggle[0]`/`recordVaginalSperm[0]` → arbitrary_text/named_npc |
| `location` | 46 | 2 | `handsUndress[0]`(이벤트 context) → arbitrary_text, `underLowerUndress[0]`/`underUpperUndress[0]` 값이 위치("exec room") → location 확정 |

- 오분류의 공통 원인: "slots/식별자를 clothing으로", "virginity act type을
  body_part으로" 판정한 llm/call 추정.
- `location`/`body_part`/`named_npc`/`clothing`은 전부 glossary 매칭 가능한
  값(위치 key, 신체부위 key, NPC명, 의복명)으로 확인. glossary 데이터는
  `research/glossary-schema.md` 설계만 존재해 실제 매칭은 데이터 구축 후
  가능.

### P5. LLM 근거 재검증 (176개 전수)

샘플 30개 검토에서 오분류 6개(20%)를 발견해, 임계 10% 초과로 **전수
검토**를 수행했다(모든 llm 항목의 call-site 값과 정의부 대조).

- 총 176개 중 **37개 수정 (21.0%)**:
  - clothing → arbitrary_text 18개 (슬롯 key: `generalOn[0]`,
    `generalSteal[0]`, `generalStrip[0]`, `generalUndress[1]`, `has[0]`,
    `it[0]`, `itis[0]`, `plural[0]`, `pushClothingCaption[0]`,
    `shredderActions[0]`, `cardClothesLost[0]`, `storeLoad[0..1]`; food
    key: `tending_give[0]`, `foodstuffReport[0]`, `saveFavoriteFood[1]`,
    `ingredientsSuppliesSteal[0]`; 혼합: `storeActions[0]`)
  - clothing → body_part 1개 (`that[0]` — hands/legs/feet/genitals)
  - body_part → arbitrary_text 6개 (`combatRequestRefused[0]`,
    `creampie[0]`, `cumSwallow[0]`, `gwylanHypnoNote[0]`,
    `selectNpcWithPartInPositionAnus[0]`, `npcVirginityTakenByOther[1]`)
  - location → arbitrary_text 4개 (`handheldUndress[0]`, `legsUndress[0]`,
    `undressMid[0]`, `shopHuntIcon[0]`)
  - location → body_part 1개 (`portalPantiesClear[0]` — anus/vagina/mouth)
  - named_npc → arbitrary_text 5개 (`bodywriting_npc_normal[1]`,
    `avery_mansion_party_speech[0]`, `pregnancyBabyText[0]`,
    `temple_title[0]`, `saveFavoriteFood[0]` 유지·검토) + P3 강등 1개
  - named_npc → structural 2개 (`combatRequestRefused[1]`, `condomDesc[0]`
    — NPC index/키)
- 수정 근거는 전부 call/definition evidence로 교체했고 confidence 필드는
  제거했다.
- 나머지 139개(79.0%)는 분류 일치 확인. 주요 불일치 원인은 슬롯/식별자와
  의복명, act type과 body_part의 혼동이었다.

## before/after

```text
unclassified_argument: 9,072 -> 0
macro_arg:             1,322 -> 1,768  (+446: option[0] ~303, numberStepper[0] ~200,
                                       actionstentacleadvcheckbox[1] ~45,
                                       -avery_mansion_party_speech[1] ~99)
link_label:           39,157 -> 39,157 (유지)
plain_text:          759,058 -> 759,058 (유지)
exposed segments:    799,537 -> 799,983
placeholders:        797,592 -> 798,038
protected coverage:   0.576128 (I2 이후 값; 문서의 0.674121은 I2 이전 stale 값)
```

config 현황: 매크로 1,050 → 1,586, 인자 항목 1,626 → 2,722.
kind 분포: structural 1,358, arbitrary_text 871, named_npc 132,
body_part 108, ui_icon 79, clothing 47, location 46, prose_text 42,
event_key 39. evidence: definition 1,824, call 758, llm 140.

## 검증

- `python3 -m unittest discover -s tests -v`: **120개 OK** (기존 114개
  추적 테스트 포함)
- `python3 -m pretranslation_cst.corpus_verify --root game`: **exit code 0**,
  baseline matched=True, round-trip/tree invariant 실패 0, allowlist
  unexpected 0
- baseline `pretranslation_cst/data/corpus-baseline-v1.json`과
  `docs/validation.md` 기대값을 위 수치로 갱신

## 새 결함 (발견 없음)

parser/grammar/masking 변경이 필요한 새 결함은 발견되지 않았다. 위젯 정의부
본문이 스캔되면서 객체/함수 리터럴이 positional arg로 토큰화되어 인덱스가
140까지 늘어나는 현상(numberStepper[4..64], numberslider[5..144])은 parser
동작 특성이며, value-kind schema로 전부 structural 처리해 진단을 정리했다.
