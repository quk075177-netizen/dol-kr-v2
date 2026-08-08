# 관측 분석 계획 — 리뷰 판정 + 다음 단계 실행 계획

기준일: 2026-08-08
상태: 리뷰 판정 완료, 실행 대기

## 1. 리뷰 지적 판정 요약

| # | 리뷰 지적 | 판정 | 근거 |
|---|---|---|---|
| 1 | 성공률 산수 불일치 (기대 44% vs 실측 9.5%) — i.i.d. 모델 의심 | ✅ **타당 (핵심)** | p̂≈1.3%, n=63 기대 44% vs 실측 9.5%. 결정적 반복 실패 3건과 합쳐 "지뢰 유닛" 모델이 지지됨 (아래 §3) |
| 2 | 배치-2 passage 1개 누락 (439유닛뿐) | ⚠️ **부분 타당** | **누락 아님** — School Detention 재실행이 리포트 표 9행에 ✗×2로 병합돼 있어 11개 타깃이 표에 10행으로 보였음. 단 리포트의 "21 passage / ~1,325유닛" 표기는 실행 수(21)와 유니크 passage(20)를 혼동한 **표기 결함** — 정확 수치는 유니크 20 / 실행 21 / 유닛 **1,317** (§2) |
| 3 | 38~53유닛 구간 성공 0개 | ⚠️ **부분 타당** | Street Panties Photo(43u)는 **성공** (1/12). 그래도 기대 ~59% vs 실측 8% — 지적의 본질(중소형도 실패가 지배적)은 타당 |
| 4 | L2 재시도 루프가 실패 사유를 오염 | ✅ **버그 확정** | 코드 확인: 재시도 중 L1 실패(드롭) 시 `problems` 미갱신 → 루프 종료 후 옛 사유(`reorder` 등) 반환. 힌트도 옛 problems 기준 (§4-①) |
| 5 | 단일 유닛 실패 덤프가 맥락을 버림 | ✅ **타당** | placeholder_drop/L2 실패 덤프에서 성공한 앞선 유닛들의 translated_text가 전부 None — 지뢰 분석 불가능 (§4-②) |
| 6 | 지뢰 모델 — 결정성이 예외가 아니라 지배 패턴 | ✅ **타당 (수정 1건)** | 3 passage 독립 재실행에서 같은 유닛 반복 실패. 단 School Detention u3는 3번째 실행에서 **드롭이 발생하지 않음** (다른 결함으로 실패) — "거의 100%"가 아니라 **고확률 유닛**이 정확한 표현 |
| 7 | Q1~Q8 답변 | ✅ **대체로 동의** | Q3(위젯 보류), Q4(프롬프트 지금 수정), Q5(일반화 지금), Q6(추적 필드) 동의. Q1의 "과거 실패 유닛 캐시 short-circuit"은 Q6 필드와 함께 설계 (§5) |
| 8 | post.py 검토 | ✅ **수용** | resolve_static의 유닛 경계 한계는 후순위 특이점으로 기록 (§6) |

## 2. 데이터 정정 (정본 원장 — 배치 1·2, 21 runs)

| run | passage | 유닛 | 결과 | 사유 (실패 유닛) |
|---|---:|---|---|---|
| B1 | Sydney Chat | 122 | ✗ | placeholder_drop u65 (**재실행 동일 u65**) |
| B1 | Children Activity Events | 105 | ✗ | placeholder_drop u4 (**재실행 동일 u4**) |
| B1 | Farm Work | 100 | ✗ | skeleton_mismatch (u92 reorder) |
| B1 | Gwylan Ocean Breeze Watch | 100 | ✗ | placeholder_drop u29 |
| B1 | Mansion Talk Chat 2 | 95 | ✗ | placeholder_drop u7 |
| B1 | Temple Confess | 67 | ✓ | — |
| B1 | Ocean Breeze Work | 66 | ✗ | restore_failed (u20 환각 토큰) |
| B1 | Forest Shop Nowhere Talk | 65 | ✗ | placeholder_drop u58 |
| B1 | School Detention | 53 | ✗ | placeholder_drop u3 (**B2 재실행 동일 u3**) |
| B1 | Gwylan Request Clothes Complete | 52 | ✗ | placeholder_drop u28 |
| B2 | Asylum Socialise | 52 | ✗ | placeholder_drop u18 |
| B2 | Bird Tower | 51 | ✗ | placeholder_drop u6 |
| B2 | Robin Flirt Room | 50 | ✗ | placeholder_drop u31 |
| B2 | Sam Park Talk 2 | 46 | ✗ | placeholder_drop u25 |
| B2 | Street Panties Photo | 43 | ✓ | — |
| B2 | Hallways Stalker Intervention | 41 | ✗ | placeholder_drop u7 |
| B2 | Estate Cards Strip | 41 | ✗ | placeholder_drop u34 |
| B2 | Mansion Steal Stash Calm | 39 | ✗ | skeleton_mismatch (형식 환각 토큰) |
| B2 | Temple Test | 38 | ✗ | skeleton_mismatch (u3 reorder) |
| B2 | Domus Model | 38 | ✗ | placeholder_drop u34 |
| B2 | School Detention (재실행) | 53 | ✗ | placeholder_drop u3 |

- 유니크 passage **20** / 실행 **21** / 유닛 **825+492 = 1,317** / 성공 **2**
- 유닛 실패율: 드롭 12 + reorder 2 + 환각 1 + 형식 1 ≈ **16/1,317 ≈ 1.2%**
- B1의 Sydney/Children 중복 덤프는 첫 런처가 셸 타임아웃 후에도 진행된
  흔적 — **결정성 근거**로만 사용 (표본에는 미포함)

## 3. 통계 재해석 — 지뢰 모델 (이번 리뷰의 핵심 기여)

i.i.d. 모델 기대 vs 실측:

```text
기대 (p=1.2%, n=평균 63):  (0.988)^63 ≈ 45%
실측:                       2/21 ≈ 9.5%
```

지뢰 모델: 특정 특징을 가진 소수 유닛이 고확률(~수십 %)로 실패하고,
38유닛 이상 passage는 그런 유닛을 하나 이상 포함한다. 증거:

1. **결정성**: 3 passage 재실행 → 같은 유닛 반복 실패
2. **중소형 passage도 전멸**: 38~53유닛 12개 중 성공 1개 (기대 ~59%)
3. 평균 실패율(1.2%)은 "몇 %의 유닛이 지뢰인가"(실측상 거의 모든
   passage가 1개 이상 보유)를 가리는 지표

**의미**: "유닛 재시도"류 대응은 지뢰 유닛에 무효(고확률 반복 실패).
L2가 유닛 구조 문제(순서/형식)를 잡는 것과 별개로, **지뢰 유닛의 공통
특징 식별**이 성공률 개선의 실제 경로.

### 지뢰 특징 후보 (12개 드롭 유닛 masked_text 예비 관찰)

| 후보 | 관측 근거 |
|---|---|
| 연속 placeholder 실행 (공백만으로 인접한 토큰 2개 이상) | Sydney u65: `<0000399>\n\t\t<0000400>`, Children u4: `<0000033>\n\t\t<0000034>`, School u3: `<0000036>Next<0000037>` |
| 한 문장 내 placeholder 다수 (4+) | School u3: "`<0000039>` takes `<0000040>` seat... `<0000041>` desk... `<0000042>`" |
| 대화 인용부호(`"`)와 placeholder 혼재 | Sydney u65: `...as you."\n\t\t<0000398>...` |
| 줄 시작 placeholder | Sydney u65, Children u4 |

placeholder **밀도는 기각됨** (실패 유닛이 평균 이하인 사례 존재, 이미
실측). 검증은 아래 §5-③.

## 4. 수정 항목 (우선순위순)

### ① L2 재시도 사유 오염 버그 — 즉시 수정

`translate_passages.py` — 재시도마다 `problems`를 갱신하고, L1 실패 시
`placeholder_drop`으로 기록:

```python
last_reason = problems[0] if problems else "placeholder_drop"
for _ in range(L2_RETRIES):
    tu = translate_unit(unit, index, len(units), hint=_l2_retry_hint(problems))
    if verify_placeholders(unit, tu.translated_text):
        last_reason = "placeholder_drop"
        continue
    problems = verify_unit_structure(unit, tu.translated_text)
    if not problems:
        recovered = True
        break
    last_reason = problems[0]
if not recovered:
    ...
    return None, last_reason
```

- 테스트: "재시도 중 드롭 → 이유가 placeholder_drop" 케이스 추가

### ② 덤프 컨텍스트 보강 — 즉시 수정

단일 유닛 실패 덤프에 직전까지의 성공 유닛 translated_text를 포함:

```python
dump_texts = ([tu2.translated_text for tu2 in translated_units]
              + [tu.translated_text]
              + [None] * (len(units) - index - 1))
```

### ③ `_PLACEHOLDER_RE` 6자리 하드코딩 일반화 — 즉시 수정

`_separator_gap` 등이 `r"<0\d{6}>"`로 다음 토큰 검색 — 마스커 prefix가
자란 passage(7자리)에서 검증이 어긋남. **artifact 토큰 집합 기반**으로
다음 토큰을 찾도록 일반화 (Mansion Steal Stash Calm이 첫 실측 대상).

### ④ 시스템 프롬프트 예시 수정 — 다음 배치 전 반영

`SYSTEM_PROMPT`의 6자리 `<000000>` 예시가 형식 환각의 근원. 예시를
"입력의 placeholder 토큰을 그대로 복사, 새 토큰 금지" 문구로 교체.
기존 레코드 무효화 없음 (hash 기반 재사용).

### ⑤ 추적 필드 `attempts`/`l2_retries` — 다음 배치부터 기록

레코드에 `attempts`(유닛당 최대 API 시도 수)와 `l2_retries`(L2 재시도
횟수) 추가. 어셈블러는 무시하므로 하위 호환. **Q7(Farm Work 회복 판정)
의 전제 조건** — 이후 Farm Work 5회 반복 실행으로 L2 개입 효과 측정.

### ⑥ `prose_drop` L2 확장 — 재시도 전용으로 추가

School Detention L2 실행에서 실측된 스팬 병합(산문 이동): "출력에서
인접한 두 자기 토큰의 사이가 비어 있는데 masked 원본에선 비공백
산문이었다" → L2 코드 추가, **결정적 복구 없음** (재시도 힌트 전용).
L2 재시도 2회로 회복 여부를 쌍체로 측정.

## 5. 지뢰 분석 절차 (수정 ①~③ 후 실행)

1. **덤프 보강 적용 후** 기존 실패 유닛 12개의 masked_text + 문맥을
   수집 (②가 전제)
2. **특징 계산**: 연속 placeholder 최대 실행 길이 / 한 문장 내 placeholder
   수 / 인용부호-토큰 혼재 여부 / 줄 시작 placeholder 여부 — 실패 유닛
   vs 같은 passage의 성공 유닛 대조 (정밀도·재현율)
3. **지뢰 예측 실험**: 특징이 유닛을 잘 분리하면, 지뢰 의심 유닛을
   포함한 passage를 5회 반복 실행 → 지뢰 유닛만 재번역(프롬프트 강화
   또는 유닛 분할)과 전체 재번역의 성공률 비교
4. 지뢰 특징이 안 나오면 → 리뷰 플래그(수동 검수)로 전환

## 5b. 지뢰 분석 실행 결과 (2026-08-08) — 구조적 특징 기각

실패 유닛 17개 vs 동일 passage 내 성공 유닛 1,098개 대조:

| feature | 실패 평균 | 대조 평균 | 판정 |
|---|---:|---:|---|
| placeholder 수 | 16.3 | 10.9 | 약함 (분포 중첩) |
| 연속 placeholder 최대 실행 | 2.76 | **3.29** | **기각** (대조가 더 김) |
| 빈 갭 인접 토큰 | 0 | 0 | 없음 |
| 한 줄 최대 토큰 수 | 4.12 | 3.05 | 약함 (실패 100% vs 대조 81% ≥2) |
| 인용부호 수 | 4.2 | 2.9 | 약함 (71% vs 59% ≥2) |
| 줄 시작 토큰 비율 | 0.76 | 0.75 | 없음 |
| 크기 (chars) | 543 | 370 | 약함 — 유일하게 일관된 차이 |

**결론: 지뢰는 구조적 특징으로 예측 불가.** 크기(번역 분량)가 유일한
일관된 차이지만 분포가 크게 겹침. 즉 지뢰의 원인은 "밀집도/연속
토큰/마크업 패턴"이 아니라 **유닛 내용의 번역 난이도** (문맥·어휘·
화자 전환 등 시맨틱 요인)로 보임.

**전략 전환 제안**: 구조 예측을 포기하고, 실측된 사실 — "결정성은
고확률이지 100%가 아니다 (School Detention u3는 3회차에서 드롭 없음)" —
을 이용한 **실패 passage 재실행 회복 측정**으로 전환:

```text
passage 1회 실패 → 재실행 시 성공 확률 ≈ (1 - q), q = 지뢰 유닛의
단회 실패 확률 (추정 50~90%). 지뢰 유닛이 통과하면 나머지 유닛은
거의 실패하지 않으므로 passage 전체가 성공.
```

실행: 기존 실패 passage 12개를 수정된 러너(①~⑥ 반영)로 재실행 →
재실행 성공률 실측. L2 재시도 개입(l2_retries 필드)과 함께 기록하면
"재시도로 회복 가능한 실패"의 비율이 나온다. → **배치 설계에
"1회 실패 시 자동 1회 재실행" 옵션 도입 판단 데이터** (Q1과 연결).

## 5c. 모델 티어 대조 실험 (2026-08-08) — 결정적 실패 유닛 3개 × flash/lite

전제: `_get_model`의 단일 전역 캐시 버그로 다중 모델 혼용이 불가능했음
→ **(project, location, model) 키 캐시로 수정** (HANDOFF의 기존 후순위
항목 해소, 테스트 추가).

결정적 실패 유닛 3개, 유닛 단발 호출 × 3회 시도:

| 유닛 | 2.5-flash-lite (현행) | 2.5-flash | flash + L2 힌트 재시도 |
|---|---|---|---|
| Sydney Chat u65 (6ph) | **0/3** (항상 `<0000397>` 드롭) | **3/3 통과** | — |
| Children u4 (18ph) | 0/3 (드롭/중복, 유닛별 상이) | 0/3 (reorder) | **재시도 1회로 통과** |
| School Detention u3 (27ph) | 1/3 | 0/3 (reorder) | 재시도 2회에도 reorder 잔존 |

해석 (피드백의 3분기 트리):

1. **Sydney u65 = 순수 티어 문제 확정** — lite가 같은 토큰을 3/3 드롭,
   flash가 3/3 통과. 티어 승격이 완전 해결.
2. **Children u4 = 티어 승격 + L2 조합으로 해결** — flash로 승격하면
   실패 모드가 drop(무회복) → reorder(L2 재시도 회복)로 변환, 재시도 1회
   통과.
3. **School u3 = 진짜 콘텐츠 난이도** — flash+L2로도 실패. 리뷰 플래그
   대상 (단 lite 1/3 통과 — 재실행이 어느 정도 효과).

**전략 결정 근거 확보**: "lite → L1/L2 실패 시 flash 유닛 승격 재시도 →
그래도 실패면 리뷰 플래그" **3단계 에스컬레이션**이 결정적 실패 유닛
대부분을 해결하는 구조. 예상 효과: 지뢰 유닛의 실패율이 (0.7~1.0) →
(L2 재시도 포함 시 ~0.2 이하)로 하락 → passage 성공률 상승 폭 큼.

실행 로그/스크립트: `/tmp/opencode/model-tier-experiment.py`

## 6. Q1~Q8 판정 반영 요약

| Q | 판정 | 반영 |
|---|---|---|
| Q1 L2와 자동 재번역 금지 경계 | 타당 | 경계 유지 + "과거 실패 유닛 캐시" short-circuit은 ⑤ 필드가 쌓인 뒤 설계 (지금은 과잉) |
| Q2 드롭 대응 우선순위 | 원인 분석 선행 동의 | §5 절차로 결정. 프롬프트 강화는 소진 카드로 취급 (L1 힌트가 이미 그것) |
| Q3 위젯 열기 | **보류 동의** | 일반 텍스트 원인 규명 전까지 유지 |
| Q4 프롬프트 예시 | 즉시 반영 | §4-④ |
| Q5 정규식 일반화 | 즉시 반영 | §4-③ |
| Q6 추적 필드 | 추가 | §4-⑤ |
| Q7 Farm Work 판정 | l2_retries 후 5회 반복 | ⑤ 완료 후 |
| Q8 prose_drop | 재시도 전용 추가 | §4-⑥ |

후순위 특이점: `resolve_static`의 유닛 경계 한계 (post.py) — 조사 결정이
유닛 안에서만 이뤄져 경계를 넘는 조사는 동적 마커로 남음. 안전한 방향의
보수적 동작이므로 대기.

## 7. 실행 순서

```text
1. ①~③ 수정 (L2 사유 버그 / 덤프 보강 / 정규식 일반화) + 테스트  [완료]
2. ④ 프롬프트 예시 수정                                    [완료]
3. ⑤ attempts/l2_retries 필드 추가                          [완료]
4. ⑥ prose_drop L2 확장 + 테스트                            [완료]
5. 지뢰 분석 (§5-2): 실패 유닛 17개 특징 vs 성공 유닛 1,098개 대조
   → 구조적 특징 기각, 크기 외 예측 변수 없음 (§5b)            [완료]
6. 모델 티어 대조 실험 (§5c): 결정적 실패 유닛 3개 × flash/lite
   → 티어 문제 1건 확정, 승격+L2 해결 1건, 콘텐츠 난이도 1건       [완료]
7. **Option E 구현** — 리오더 원인(어순 자연화) 규명 후 순서 민감도
   화이트리스트 (ProtectedSpan(kinds)/order_sensitive, L2·L3 완화,
   등록·어셈블러 엄격 유지). 실측 5건 전부 허용 분류, 테스트 203개
   통과, corpus baseline matched                                 [완료]
8. **재측정 배치** — 3 passage × 3모델 (2.5-flash/2.5-flash-lite/
   3.5-flash-lite, 3.6 제외) — 실행 중, 결과 대기                 [진행]
9. 3단계 에스컬레이션 (lite → flash 승격 재시도 → 리뷰 플래그)     [대기]
10. Farm Work 5회 반복 (Q7)                                   [대기, API]
```

## 8. 실행 기록 (2026-08-08)

- ① L2 재시도 루프: `last_reason` 추적로 전환 — 재시도 중 드롭이면
  `placeholder_drop` 보고. 테스트 추가
- ② `_dump_texts`: 단일 유닛 실패 덤프에 직전 성공 유닛 translated_text
  포함 (실패 유닛까지, 이후 None)
- ③ `_separator_gap`/`_next_tokens` — artifact 토큰 집합 기반으로 일반화
  (`_PLACEHOLDER_RE` 6자리 하드코딩 제거). client.py `PLACEHOLDER_RE` →
  `<0[\d_]+>` (prefix 성장 토큰 대응). corpus 오탐 0건 재확인
- ④ SYSTEM_PROMPT: `<000000>` 예시 제거 → "입력의 토큰을 그대로 복사,
  새 placeholder 모양 토큰 금지" + "토큰 사이 텍스트를 옮기지 말 것"
- ⑤ 레코드에 `l2_retries` / `api_calls` 추가 (어셈블러 무시, 하위 호환)
- ⑥ `prose_drop` L2 검사 추가 (산문 이동 감지, 재시도 힌트 전용 — 결정적
  복구 없음). 테스트 6종 추가
- 테스트: 185 → **191개 통과**, verify.py 전 구간 통과 (verify_failed 0)
