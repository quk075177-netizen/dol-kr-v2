# Value-Kind 분류 품질 검수 로드맵

기준일: 2026-08-07

## 배경

`config/macro-value-kind.yml`은 매크로 인자의 의미 종류(value-kind)를
분류한다. 현재 1,050개 매크로, 1,626개 인자 항목이 등록되어 있다.

value-kind의 원래 목적은 추후 번역 힌트로 활용하는 것이다. 예를 들어
`named_npc`면 고유명사 번역표를 적용하고, `body_part`면 신체부위 glossary를
적용하며, `prose_text`면 번역 API에 직접 넘긴다. 하지만 현재 분류가
이 목적에 맞게 잘 되어 있는지 검수가 필요하다.

## 현재 분류 현황

| kind | 항목 수 | 번역 힌트 유용성 | 비고 |
|---|---:|---|---|
| `structural` | 570 | 낮음 | 번역 안 함. 구조적 인자 |
| `arbitrary_text` | 336 | 낮음 | 번역 안 함. 임의 텍스트 |
| *(kind 없음)* | 223 | 미평가 | note만 있고 kind/evidence 없음 |
| `named_npc` | 103 | **높음** | 고유명사 — 번역표 결정 |
| `ui_icon` | 79 | 없음 | UI 아이콘 식별자 |
| `clothing` | 69 | **높음** | 의류명 — glossary 매칭 |
| `body_part` | 53 | **높음** | 신체부위 — glossary 매칭 |
| `event_key` | 40 | 없음 | 이벤트 키 |
| `location` | 39 | **높음** | 장소명 — glossary 매칭 |
| `prose_text` | 33 | **핵심** | 번역 대상 (노출) |

evidence 분포: `definition` 845, `call` 288, `llm` 189.

## I2(위젯 opaque 해제) 후 변화

I2로 위젯 본문이 스캔되면서 `unclassified_argument`가 18 → 9,072로
증가했다. 상위 매크로:

```text
numberStepper 2,396   numberslider 1,033   option[1] 303
sex[2] 280            brat 244             their 188
shopHuntActorName 204 rangeslider 186      radiovar 156
hisselect 155         actionstentacleadvcheckbox 135
case 109              combat-set-hand-target 102
money 96              shopHuntLocName 91   generateCombatAction 90
machine_damage 85     foldout 82           meek 78
```

이 residual은 `docs/worker-value-kind-audit.md`의 Part A에서 처리한다.
그 다음 P1~P5(Part B)로 이어진다.

## 검수 우선순위

### P1. kind 없는 223개 항목 정리

223개 항목이 `note`만 있고 `kind`와 `evidence`가 없다. value-kind policy에
따르면 kind가 없으면 보호 대상이므로 `unclassified` 진단이 나와야 하는데,
실제 진단은 18건뿐이다. 이 223개가 어떻게 처리되고 있는지 확인이 필요하다.

가능성:
- parser가 kind 필드가 없는 항목을 `protect` disposition으로 묵분류하고
  진단을 생략하고 있을 수 있음.
- 또는 `note`만 있는 항목이 schema에 등록된 것으로 간주되어
  `unclassified`가 아닌 `protect`로 빠지고 있을 수 있음.

확인 후, 각 항목을 다음 중 하나로 정리한다:
- `structural`로 kind 부여 (변수 할당/함수 인자인 경우)
- 실제 의미에 맞는 kind 부여
- note만으로는 분류 근거가 부족하면 항목 자체를 제거 (보호로 fallback)

### P2. `arbitrary_text` 336개 재검토

`arbitrary_text`는 "임의 텍스트"이지만, 번역 힌트로는 아무 정보도 주지
않는다. 이 항목들 중 실제로는 `prose_text`(번역 대상)이거나
`structural`(구조적)인 것이 섞여 있을 수 있다.

샘플링 검수:
- `arbitrary_text` 항목의 실제 호출부 텍스트 20개 이상 추출
- 각각이 번역 대상인지 구조적 인자인지 판정
- 분류 오류율이 높으면 전수 재검토

### P3. `prose_text` 33개 노출 검증

`prose_text`는 번역 대상으로 노출된다. LLM 근거 19개(전부
`confidence=high`), call 근거 11개, definition 근거 3개.

각 항목의 실제 노출 텍스트가 번역 대상으로 적합한지 확인:
- `macro_arg` 노출 952건 중 `prose_text` kind로 인한 노출이 얼마인지
- 노출된 텍스트가 사용자 facing 문장/구인지, 아니면 내부 식별자인지
- `swarminit[1..4]` 등 다수 인자가 동일 kind로 분류된 것이 적절한지

### P4. 시맨틱 kind(`named_npc`/`clothing`/`body_part`/`location`) 실사용 검증

이 kind값들은 번역 힌트(어순, 조사, glossary 매칭)용으로 설계되었다.
실제로 번역 파이프라인에 도움이 되려면:

- 같은 `named_npc` 항목의 실제 텍스트가 고유명사인지 확인
- `body_part` 항목이 신체부위명 glossary와 매칭되는지
- `location` 항목이 장소명 glossary와 매칭되는지
- `clothing` 항목이 의류명 glossary와 매칭되는지

현재 glossary는 `research/glossary-schema.md`에 설계만 있고 실제
데이터는 없다. 시맨틱 kind가 의미 있으려면 glossary 데이터가 먼저
구축되어야 한다.

### P5. LLM 근거 189개 재검증

LLM 분류 189개는 전부 `confidence=high`이지만, LLM 추정이므로
정확도 검증이 필요하다. 특히 `prose_text` 19개는 노출 대상이므로
오분류가 번역 품질에 직접 영향을 준다.

검증 방법:
- LLM 분류 항목의 실제 호출부 텍스트 추출
- 각 텍스트가 분류된 kind와 일치하는지 수동 확인
- 오분류율 10% 이상이면 해당 매크로 전수 재검토

## 검수 방법

각 우선순위별로 다음 절차를 따른다:

1. **추출**: 해당 kind의 모든 macro/index에 대해 실제 호출부 텍스트를
   corpus에서 추출 (passage, macro name, arg index, raw text).
2. **샘플링**: 전수가 많으면 20~50개 샘플링.
3. **판정**: 각 텍스트가 분류된 kind와 일치하는지 수동 확인.
4. **정정**: 오분류는 `config/macro-value-kind.yml`에서 kind/evidence/note
   수정.
5. **검증**: `corpus_verify` exit 0, `unittest` 113개 통과, 노출 segment
   수치 변화 확인.

## 완료 기준

- kind 없는 223개 항목이 전부 kind를 가지거나 제거됨.
- `arbitrary_text`의 오분류율이 10% 미만.
- `prose_text` 노출 항목이 전부 사용자 facing 문장/구임.
- 시맨틱 kind 4종이 glossary 데이터와 매칭 가능함.
- LLM 근거 오분류율이 10% 미만.
- `corpus_verify` exit 0, baseline 일치.