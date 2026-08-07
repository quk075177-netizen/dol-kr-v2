# 워커 에이전트 지시문: value-kind 분류 품질 검수 (I2 후 재작성)

기준: I2 위젯 opaque 해제 반영 (commit 6236c66), CST 완성 후

## 공통 기준

- 정본 입력은 `game/**/*.twee`다.
- 기존 `/tmp/opencode/*.jsonl`은 덮어쓰지 않는다. 새 산출물은 새 경로에
  생성한다.
- 모든 변경은 `python3 -m unittest discover -s tests -v`를 통과해야 한다.
- 전 corpus 검증은 `python3 -m pretranslation_cst.corpus_verify --root game`
  로 재현하며, exit code 0이어야 한다. corpus_verify는 코드 변경이 없으면
  반복 실행하지 않는다 (1회만).
- parser 변경이 필요한 새 결함을 발견하면 우회 수정하지 말고 source,
  passage, macro, byte span, 최소 fixture와 함께 보고한다.
- 완료 보고에는 before/after diagnostic 및 exposed segment count를
  포함한다.
- `set`, `run`, `print`, `=`, `-`, `if`, `elseif`, `for`, `unset`은 raw
  expression이다. 이들의 공백 token을 value-kind positional argument로
  등록하지 않는다.
- 실패하면 prose로 추정하지 않고 보호 span과 진단을 남긴다.
- 담당 범위 밖 parser refactor를 하지 않는다.
- 문서 정책(`docs/cst-scope.md`, `docs/sugarcube-ground-truth.md`,
  `docs/value-kind-policy.md`, `docs/validation.md`)과 충돌하면 문서를
  우선한다.
- **corpus_verify 실행은 마지막 검증에서 1회만.** config 변경 중간마다
  돌리지 말고, 유닛 테스트만 사용해 회귀를 잡는다.

## 담당 파일

- `config/macro-value-kind.yml`
- `docs/macro-value-kind-residual-report.md`
- `pretranslation_cst/data/corpus-baseline-v1.json`
- `docs/validation.md` (현재 기대값 갱신만)
- 검수 보고서 (새 파일, `docs/value-kind-audit-report.md`)

## 수정 금지

- `pretranslation_cst/parser.py`
- `pretranslation_cst/grammar.py`
- `pretranslation_cst/square_markup.py`
- `pretranslation_cst/model.py`
- `pretranslation_cst/data/macro-grammar.json`
- `pretranslation_cst/macro_audit.py`
- `pretranslation_cst/corpus_verify.py`
- `pretranslation_cst/masking.py`
- `tests/` 하위 모든 파일

## 현재 기준선 (2026-08-07, I2 반영 후)

```text
diagnostics 9,082 total: unclassified_argument 9,072
segments: link_label 39,157, macro_arg 1,322, plain_text 759,058
  / exposed 799,537, placeholders 797,592
baseline matched=True, exit code 0
```

value-kind config 현황:

```text
1,050개 매크로, 1,626개 인자 항목
kind 분포: structural 570, arbitrary_text 336, (kind 없음) 223,
  named_npc 103, ui_icon 79, clothing 69, body_part 53,
  event_key 40, location 39, prose_text 33
```

I2(위젯 opaque 해제)로 위젯 본문이 스캔되면서 `unclassified_argument`가
18 → 9,072로 증가했다. 위젯 안 매크로 인자의 value-kind schema 누락이
주 원인이다.

## 지시

```text
이 작업은 두 부분으로 나뉜다. 순서대로 진행하라.

=== Part A: I2로 드러난 위젯 residual 정리 (최우선) ===

현재 unclassified_argument 9,072의 매크로별 분포는 다음과 같다:

  numberStepper 2,396   numberslider 1,033   option[1] 303
  sex[2] 280            brat 244             their 188
  shopHuntActorName 204 rangeslider 186      radiovar 156
  hisselect 155         actionstentacleadvcheckbox 135
  case 109              combat-set-hand-target 102
  money 96              shopHuntLocName 91   generateCombatAction 90
  machine_damage 85     foldout 82           meek 78
  tentacle_record 74    combat-reset-hand 60 bodypart_admire 57
  ...

A1. 위젯 정의부에서 등장하는 UI 매크로 분류:
  numberStepper, numberslider, rangeslider, radiovar, hisselect,
  option[1], checkbox는 UI 위젯 매크로다. 실제 호출부를 확인해
  각 인자의 의미를 분류하라.
  - numberStepper[1..N]: step 값/설정 값/라벨 등 구조적 인자일 가능성이
    높다. 정의부(game/**/*.twee의 <<widget "numberStepper">> 또는
    game/**/*.js의 Macro.add)를 확인해 인자 위치별 의미를 확정하라.
  - numberslider/rangeslider: value/name/min/max 등 구조적.
  - radiovar[0..1]: 라디오 변수명과 값. structural.
  - option[1]: cycle/listbox branch의 표시 라벨. prose_text 후보지만,
    option은 branch이므로 value-kind lookup이 어떻게 되는지 확인.

A2. 게임 위젯 매크로 분류:
  sex, brat, their, hisselect, shopHuntActorName, shopHuntLocName,
  meek, submission, machine_damage, bodypart_admire 등은 게임 정의
  위젯/매크로다. definition을 확인해 인자 의미를 분류하라.
  - sex[0..2]: 신체부위/동작/위치 등.
  - brat[0..1]: NPC 성향/동작.
  - their[0]: 소유자 NPC. named_npc 후보.
  - hisselect[0]: 선택지 라벨. prose_text 후보.
  - bodypart_admire[0]: 신체부위. body_part 후보.

A3. schema에 없는 매크로는 추가 등록하되, 근거(call/definition)를
  명시하라. kind를 추정할 수 없는 인자는 보호 상태로 두고 note만으로
  분류 완료 처리하지 마라.

=== Part B: 기존 P1~P5 검수 (A 완료 후) ===

docs/value-kind-audit-roadmap.md의 P1~P5를 순서대로 검수하라.

P1. kind 없는 223개 항목 정리:
  - config에서 kind 필드가 없는 항목을 추출해, note를 근거로 kind를
    부여하거나 항목을 제거하라.

P2. arbitrary_text 336개 재검토:
  - 30개 샘플링해 실제 호출부 텍스트가 번역 대상(prose_text)인지
    구조적(structural)인지 판정하라. 오분류율 보고.

P3. prose_text 33개 노출 검증:
  - prose_text로 노출된 macro_arg segment가 전부 사용자 facing 텍스트인지
    확인. 내부 식별자가 노출되면 강등하라.

P4. 시맨틱 kind 4종(named_npc/clothing/body_part/location) 실사용 검증:
  - 각 kind 15개씩 샘플링해 glossary 매칭 가능성 평가.

P5. LLM 근거 189개 재검증:
  - 30개 샘플링해 분류 일치 여부 확인. 오분류율 보고.

=== 공통 ===

모든 단계에서:
  - 추출은 corpus에서 직접 수행하고 source/passage/macro/arg index/raw
    text를 기록하라.
  - config 변경 후 유닛 테스트로 회귀를 잡고, 마지막에 corpus_verify를
    1회만 실행해 exit 0을 확인하라.
  - baseline 수치가 변하면 corpus-baseline-v1.json과 docs/validation.md를
    갱신하라.
  - 검수 결과를 docs/value-kind-audit-report.md에 단계별로 정리하라.
```

## 완료 기준

- Part A: 위젯 residual(9,072 중 상위 매크로)이 전부 kind를 가지거나
  명시적으로 보호로 분류됨.
- Part B: P1~P5 검수 완료, 오분류율 보고.
- `prose_text` 노출 항목이 전부 사용자 facing 텍스트임.
- `corpus_verify` exit code 0 (마지막에 1회), baseline 일치.
- `python3 -m unittest discover -s tests -v` 114개 통과 유지.
- 검수 보고서 `docs/value-kind-audit-report.md` 작성.

## 보고 형식

```text
## Part A: 위젯 residual 정리
- numberStepper: before 2,396 -> after N (kind 분류 내역)
- numberslider: before 1,033 -> after N
- 기타 상위 매크로별 delta 표
- 처리 후 unclassified_argument: 9,072 -> N

## Part B: P1~P5 검수
- P1 kind 없음: 223 -> 0 (정리 내역)
- P2 arbitrary_text: 샘플 30, 오분류 N개 (X%)
- P3 prose_text: 사용자 facing M개, 강등 K개
- P4 시맨틱 kind: kind별 오분류율
- P5 LLM: 샘플 30, 오분류 N개 (X%)

## before/after
- unclassified_argument: 9,072 -> N
- macro_arg: 1,322 -> N
- link_label: 39,157 -> N (유지되어야 함)
- plain_text: 759,058 -> N (유지되어야 함)
- corpus_verify exit code: 0 (1회 실행)

## 새 결함 (발견 시)
- source/passage/macro/span/fixture
```