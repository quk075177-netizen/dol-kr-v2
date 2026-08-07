# 번역 유닛 분할(청킹) 전략 초안

기준일: 2026-08-07
상태: 초안 (설계 단계, 구현 전)

## 문제

CST 추출이 완료되어 각 passage의 masked 텍스트와 placeholder 테이블이
준비되었다. 다음 단계는 이 masked 텍스트를 번역 API에 넘기는 것인데,
passage 단위가 아닌 **번역 유닛(translate unit)** 단위로 분할해야 한다.

분할이 필요한 이유:

1. **길이 제한**: 번역 API는 입력 길이에 제한이 있다. masked 텍스트
   기준으로 max 50,828자(약 25,000 토큰)인 passage가 있다.
2. **문맥 유지**: 너무 잘게 쪼개면 문맥이 끊어져 번역 품질이 떨어진다.
   "He says" 와 "Hello there" 가 서로 다른 유닛에 들어가면 조사/어순이
   틀릴 수 있다.
3. **구조 보존**: 같은 `if` branch 안의 텍스트는 하나의 유닛에
   들어가야, 조건부 대사가 문맥 없이 번역되지 않는다.

## 현재 크기 분포 (masked 텍스트 기준)

```text
passages: 16,135
masked char size:
  median=766  mean=1,257  max=50,828
  p50=766  p90=2,528  p95=3,822  p99=8,618

passages > 1,000 chars: 6,082 (38%)
passages > 2,000 chars: 2,352 (15%)
passages > 5,000 chars:   482 ( 3%)
```

대다수 passage(62%)는 masked 텍스트가 1,000자 이내라 분할 없이 번역
가능하다. 38%는 분할이 필요하다.

## 트리 기반 chunk 크기 (같은 부모 아래 텍스트 leaf 묶기)

```text
passage_root chunks:  median=2   max=1,070
macro_container chunks: median=3   max=866
macro_branch chunks:    median=13  max=581
ALL chunks:             median=4   max=1,070
chunks > 2,000 chars: 0 / 4,331
```

같은 부모의 텍스트 leaf를 묶는 단위는 매우 작다(max 1,070자). 이
단위로 분할하면 문맥이 너무 끊어진다. 더 큰 단위가 필요하다.

## 청킹 전략

### 기본 원칙

1. **passage가 1,000자 이하**면 그대로 하나의 번역 유닛.
2. **1,000자 초과**면 트리 구조를 따라 하위 분할.
3. **분할 경계 우선순위**: container 닫기 → branch 닫기 → sibling
   text/prose_text leaf 묶음.
4. **각 유닛은 ancestor/sibling 메타데이터를 부착**하여 번역 API에
   문맥을 전달.
5. **placeholder는 유닛 경계에 걸치지 않는다**: placeholder는 원본
   byte slice를 가리키므로, 유닛 경계와 placeholder 경계가 겹치면
   restore가 깨진다.

### 3단계 분할 알고리즘

```
1단계: passage 전체가 임계치(기본 1,000자) 이하 → 1개 유닛.
2단계: 초과 → passage_root의 직계 자식을 순회하며 연속된
       text/prose_text + leaf macro를 하나의 "세그먼트 그룹"으로 묶음.
       container가 나오면 그 container 전체를 하나의 세그먼트 그룹으로.
       각 세그먼트 그룹이 임계치 이하면 유닛 확정.
3단계: 세그먼트 그룹이 임계치 초과 → container 내부에서 branch 단위로
       분할. branch가 여전히 초과면 branch 내부의 직계 자식으로 다시
       묶기. leaf macro가 초과하면 더 이상 분할하지 않고 그대로
       (잘게 쪼개면 의미 단위가 깨짐).
```

### 분할 경계 우선순위

```
passage_root
  └ text ...                         ─┐
  └ macro_container(if)               ├ 세그먼트 그룹 1
  │   └ macro_branch(if)             │
  │       └ text "He says:"          │
  │       └ macro_call(speech)       │
  │           └ prose_text "Hello"   │
  │   └ macro_branch(else)           │
  │       └ text "She says:"         │
  │       └ macro_call(speech)       │
  └ text ...                         ─┘
  └ macro_container(switch)          ── 세그먼트 그룹 2
  │   └ macro_branch(case) ...
  └ text ...                         ── 세그먼트 그룹 3
```

- 세그먼트 그룹 1: `if` container 전체. branch 안의 대사가 문맥을
  유지한다. "He says:" + "Hello"가 같은 유닛에 들어간다.
- 세그먼트 그룹 2: `switch` container 전체.
- 세그먼트 그룹 3: container 뒤의 후행 text.

### 메타데이터 부착

각 번역 유닛에는 다음 메타데이터를 부착한다:

```json
{
  "unit_id": "sydney-main:Sydney Chat:0",
  "source_path": "game/overworld-town/special-sydney/main.twee",
  "passage_name": "Sydney Chat",
  "unit_index": 0,
  "unit_count": 3,
  "ancestors": [
    {"node_type": "macro_container", "name": "if", "depth": 1},
    {"node_type": "macro_branch", "name": "elseif", "depth": 2}
  ],
  "preceding_context": "He smiles and says:",
  "following_context": "You feel relieved.",
  "placeholder_count": 12,
  "char_count": 856,
  "masked_text": "He smiles and says: __DOLKR_P000000__ Hello there __DOLKR_P000001__ ..."
}
```

- `ancestors`: 이 유닛이 속한 container/branch 경로. 번역 API가
  "이 텍스트는 `if`의 `elseif` branch 안에 있다"는 것을 알 수 있다.
- `preceding_context` / `following_context`: 이웃 유닛의 첫/마지막
  1~2문장. 문맥 참고용이며 번역 대상이 아니다. 번역 API 입력에
  prefix/suffix로 포함하되 "번역하지 마라" 표시를 붙인다.
- `placeholder_count`: 이 유닛 안의 placeholder 수. restore 검증용.

### 임계치 선정

```text
기본 임계치: 1,000자 (masked 텍스트 기준)
상한: 2,000자 (절대 초과하지 않음)
하한: 200자 (이보다 작으면 이웃 유닛과 병합)
```

- 1,000자는 대다수 passage(62%)를 분할 없이 처리할 수 있는 값.
- 2,000자 상한은 번역 API 컨텍스트 윈도우 여유를 고려한 값.
- 200자 하한은 너무 잘게 쪼개진 유닛을 이웃과 합치는 기준.

임계치는 번역 API의 토큰 제한에 따라 조정한다. 현재는 번역 API를
선택하지 않았으므로 1,000자를 기본값으로 두고, API 확정 후
조정한다.

### placeholder 경계 처리

placeholder는 `__DOLKR_P000000__` 형태의 토큰이다. 분할 시:

- placeholder가 유닛 경계에 걸치면 안 된다: placeholder 토큰이
  유닛 A 끝과 유닛 B 시작에 걸쳐 있으면 restore가 깨진다.
- 해결: 분할 지점은 항상 placeholder 밖(일반 텍스트 또는 segment
  경계)으로 잡는다. masked 텍스트에서 placeholder 위치를 알고
  있으므로, 분할 지점 후보에서 placeholder 구간을 제외한다.

## 번역 유닛 인터페이스

```python
@dataclass
class TranslateUnit:
    unit_id: str
    source_path: str
    passage_name: str
    unit_index: int
    unit_count: int
    masked_text: str
    segments: list[Segment]       # 이 유닛에 속한 노출 segment
    placeholders: list[Placeholder]  # 이 유닛의 placeholder
    ancestors: list[dict]         # CST ancestor 경로
    preceding_context: str        # 앞 유닛의 마지막 문장
    following_context: str        # 뒤 유닛의 첫 문장
```

## 구현 순서

### C1. 청킹 모듈 설계

`pretranslation_cst/chunking.py` 새 모듈. `MaskArtifact`를 입력받아
`list[TranslateUnit]`을 반환. `Passage`의 tree에서 ancestor 경로를
추출.

### C2. 분할 알고리즘 구현

3단계 분할 알고리즘 구현. placeholder 경계 처리 포함.

### C3. 메타데이터 부착

ancestor 경로, preceding/following context 추출. tree의
`get_ancestors` / `get_siblings` API 활용.

### C4. 분할 검증

- 모든 유닛을 합치면 원 passage의 masked 텍스트와 정확히 일치.
- placeholder가 유닛 경계에 걸치지 않음.
- 각 유닛의 char_count가 상한(2,000자) 이하.
- 유닛 수가 passage 크기에 비례하여 합리적.

### C5. corpus 전수 분할 테스트

16,135개 passage 전체에 분할을 돌려서:
- 분할 실패 0건.
- 유닛 수 분포.
- 유닛 크기 분포 (상한 초과 0건).
- 분할 전후 masked 텍스트 일치.

### C6. 번역 API 인터페이스 설계

`TranslateUnit`을 번역 API 입력으로 변환하는 방식 설계.
`ancestors`와 `preceding/following_context`를 어떻게 system prompt에
반영할지. 이 단계는 번역 API 선택 후 진행.

## 검증 불변식

```text
join(unit.masked_text for unit in chunk(passage)) == mask_passage(passage).masked_text
all(len(unit.masked_text) <= 2000 for unit in chunk(passage))
no placeholder spans a unit boundary
restore(join(translate(unit))) == passage_body  # 번역 후 복원
```

## 고려 사항

### 문장 경계 vs 구조 경계

분할을 문장 경계(m침표/개행)로 할지, CST 구조 경계(container/branch)로
할지 선택해야 한다. 구조 경계가 번역 품질에 더 유리하다:

- 같은 `if` branch 안의 텍스트는 의미론적으로 같은 맥락.
- 문장 경계로 자르면 한 문장이 두 유닛에 걸칠 수 있음.
- 구조 경계로 자르면 branch 안의 여러 문장이 한 유닛에 들어감.

다만 구조 경계만으로 유닛이 너무 커지면, 구조 경계 1순위 + 문장 경계
2순위로 혼합할 수 있다.

### 동적 라벨과 노출 segment

`link_label`과 `macro_arg`는 노출 segment지만, 주변 placeholder와
밀접하게 연결되어 있다. 예:

```text
__DOLKR_P000000__ Next __DOLKR_P000001__
```

`Next`는 `link_label` segment이고, 앞뒤 placeholder는 매크로 구문이다.
분할 시 이 segment를 단독 유닛으로 빼면 "Next"만 번역하게 되어
문맥이 없다. 주변 text와 함께 묶는 것이 좋다.

### container 안의 빈 branch

일부 `if` branch는 텍스트가 거의 없는 경우가 있다(3자 등). 이런
branch는 이웃 branch와 병합하거나, 부모 container 단위로 유지하는
것이 좋다. 하한(200자) 기준으로 병합을 판단한다.

### widget 정의와 opaque passage

`widget_definition_opaque`와 `passage_opaque`는 노출 segment가 없다.
분할 대상이 아니다. chunking 모듈은 이 passage들을 건너뛴다.

## 완료 기준 (초안)

- 16,135개 passage 전체 분할 성공 (실패 0건).
- 모든 유닛이 2,000자 이하.
- 분할 전후 masked 텍스트 일치.
- placeholder가 유닛 경계에 걸치지 않음.
- 각 유닛이 ancestor 메타데이터를 가짐.
- `corpus_verify` exit 0 유지 (청킹은 parser/masking을 변경하지 않음).