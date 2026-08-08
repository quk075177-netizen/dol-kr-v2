# 리오더(reorder) 원인 분석 — placeholder 순서 교환 실측 5건

기준일: 2026-08-08
범위: 배치 관측(2회) + L2 쌍체 + 모델 티어 비교에서 실측된
`reorder` 실패 전수 (5건)

---

## 1. 리오더란 무엇인가

번역 유닛 안의 placeholder 토큰(`<0001134>` 등)은 매크로/링크/변수를
나타낸다. **원문에서의 등장 순서가 곧 게임 구조**다 — restore가 순서대로
원문을 치환하므로, 번역에서 토큰 순서가 바뀌면 치환 대상이 어긋난다.

```text
원문 순서:  <0001134> <0001135> <0001136> ...
번역 순서:  <0001134> <0001136> <0001135> ...   ← 리오더
```

- 유닛 안의 각 토큰은 1회씩 존재하므로 L1(개수 검사)은 통과
- joined 시그니처 검사(L3)에서만 발견되던 것이, L2 검사(토큰 순서)
  도입으로 **유닛 레벨에서 조기 적발**됨 (현재 실패 사유 `reorder`)

## 2. 실측 5건 (모두 2~4개 토큰의 국소 교환)

### 사례 1 — Farm Work u92 (배치-1, gemini-2.5-flash-lite)

```text
원문:  <0001134> says as <0001135> reaches for <0001136> phone.
번역:  <0001134>{{post:은는}} <0001136>{{post:을를}} 잡으려
       <0001135>{{post:이}} 말한다.
       (1135 ↔ 1136 교환)
```

"X says as Y reaches for Z's phone" → "X은 Z의 폰을 잡으려 Y이 말한다"
— **as-절의 성분이 앞으로 이동**하며 토큰이 딸려 감.

### 사례 2 — Temple Test u3 (L2 쌍체 실행, gemini-2.5-flash-lite)

```text
원문:  ... feel your <0000021> attempt to harden under <0000022> scrutiny.
번역:  ... <0000022>의 시선 아래 당신의 <0000021>가 뻣뻣해지려...
       (0021 ↔ 0022 교환)
```

"your X harden under Y's scrutiny" → "Y의 시선 아래 X가 뻣뻣해지려"
— **장소/환경구("...아래")의 문두 이동** + 관형 구조 재배열.

### 사례 3 — Sydney Chat u22 (모델 비교 2.5-flash, 토큰 2개뿐)

```text
원문:  <0000133> face drops as <0000134> flips through a...
번역:  <0000134>{{post:이}} 페이지를 넘기며 살펴보자
       <0000133>{{post:의}} 표정이 어두워진다.
       (0133 ↔ 0134 교환)
```

"X's face drops as Y flips through" → "Y이 페이지를 넘기며 … X의 표정이
어두워진다" — **as-절 앞세우기** (한국어의 전형적 어순). 토큰 2개뿐인
유닛에서도 발생 → "복잡해서"가 아니라 "어순이 달라서".

### 사례 4 — Children Activity Events u4 (모델 비교 2.5-flash)

```text
원문:  ... hold <0000044> until <0000045> calms down.
번역:  <0000045>이/가 진정될 때까지 <0000044>을/를 안아줍니다.
       (0044 ↔ 0045 교환)
```

"hold X until Y calms" → "Y이 진정될 때까지 X을 안아줍니다"
— **until-절 앞세우기**. 가장 대표적인 사례.

### 사례 5 — School Detention u1 (모델 비교 2.5-flash)

```text
원문:  <0000005> takes <0000006> seat in front of <0000007> desk...
번역:  <0000005>{{post:은는}} <0000007> 책상 앞 <0000006> 자리에 앉아...
       (0006 ↔ 0007 교환)
```

"X takes Y's seat in front of Z's desk" → "X은 Z의 책상 앞 Y의 자리에"
— **관형구(소유) 재배열**: 두 소유 성분의 순서가 뒤집힘.

## 3. 공통 메커니즘 — "한국어 어순 자연화"

5건 모두 한 문장 패턴으로 수렴한다:

```text
영어:  [주절] + 종속절/환경구 (as / until / under / of)
한국어: [종속절/환경구] + 주절      ← 한국어는 시간·조건·장소 절을 앞에 둠
```

모델은 **번역 품질(자연스러운 한국어)을 위해 문법 성분을 재배열**하고,
그 성분에 묶인 placeholder 토큰도 **함께 이동**시킨다. 토큰을 "잘못
배치"한 것이 아니라, **토큰이 가리키는 성분을 옮긴 것**이다.

- 교환 대상은 항상 **문장 성분 단위**다 (종속절 전체 / 관형구 쌍)
- 임의 스왑이 아니라 의미 보존 이동 — 예: "hold X until Y calms"에서
  X·Y가 뒤집혀도 문장 의미는 동일하게 유지됨
- 모델 티어 무관: lite·flash 모두 동일 패턴 (모델 역량 문제가 아니라
  번역 지시와 구조 계약의 **본질적 충돌**)

## 4. 왜 L2 힌트 재시도로 안 고쳐지는가

L2 재시도 힌트는 "토큰 순서를 그대로 유지하라"고 지시한다. 그러나:

```text
모델의 우선순위:  자연스러운 한국어 > 명시적 토큰 순서 지시
```

- 5건 중 4건이 L2 재시도(최대 2회, 힌트 포함)에도 동일하게 재발
- 한국어 어순 압력이 강한 절대다수 문장에서 모델은 "순서를 바꾸되
  의미는 유지"하는 출력을 반복 생성
- 이는 드롭(무작위성)과 달리 **결정적 재발** 성격이 강함 — 재시도
  자원이 아닌 "어순을 안 바꾸게 하는" 조치가 필요

## 5. 대응 옵션 (판정 완료)

| 옵션 | 내용 | 판정 |
|---|---|---|
| A. 프롬프트 강화 | 절 재배열 금지 명시 | **기각** — 어순 변경은 원하는 결과 (요구사항과 정면 충돌) |
| B. 성분 재정렬 복구 | 번역에서 성분 단위로 토큰 복원 | **폐기** — 성분 경계 판정 불안정, 결정적 복구 불가 |
| C. 유닛 분할 | 절 단위 분리 | 불필요 (E로 문제 자체 해소) |
| D. 수용 + 리뷰 플래그 | 재시도 1회 후 플래그 | 불필요 (E로 해소) |
| **E. 순서 민감도 분류** | **화이트리스트 채택 (2026-08-08)** — 표시 전용 매크로는 순서 무관, 상태/제어 매크로만 민감. **구현 완료**, 재측정 진행 중 | |

## 5b. Option E 구현 요약 (2026-08-08)

- `pretranslation_cst/model.py`: `ProtectedSpan(span, kinds)` 도입 — 파서가
  매크로 이름(`node.name`) 또는 종류(variable/expression/html/comment/
  markup/diagnostic/body)를 보호 스팬에 부여, `_merge_spans`는 kinds
  합집합 병합. `Placeholder.order_sensitive` 필드 추가
- `pretranslation_cst/order_sensitivity.py`: 화이트리스트 — 종류
  (variable/expression/html/comment) + 표시 전용 매크로 (`print`, `=`,
  대명사·이름·신체 표시 계열: he/his/him/she/childhe/childhim/.../penis/
  person1 등). **목록에 없으면 전부 민감** (보수적 기본값). 스팬은
  모든 kinds가 insensitive일 때만 순서 무관
- 러너만 완화 (등록/어셈블러는 엄격 유지):
  - L2 reorder: **이동한 토큰 중 민감 토큰이 있을 때만** 기각
  - L3 `_skeleton_ok`: `_canonical_signature` — 민감 토큰은 절대 순서
    유지, 민감 토큰 사이의 무관 토큰은 multiset(정렬) 비교
- 검증: 실측 5건 전부 "리오더 허용"으로 분류 확인, 테스트 203개 통과,
  corpus_verify baseline matched, verify.py 전 구간 통과
- **재측정**: 3 passage × 3모델 (gemini-2.5-flash / 2.5-flash-lite /
  3.5-flash-lite — **3.6-flash 제외**, 대량 호출 리스크) — 실행 중

## 5c. Option E 재측정 결과 (2026-08-08, 3 passage × 3모델)

| passage | 2.5-flash | 2.5-flash-lite | 3.5-flash-lite |
|---|---|---|---|
| Sydney Chat | skeleton_mismatch (스팬 병합) | placeholder_drop | placeholder_drop |
| Children Activity Events | reorder (u28 sensitive 스왑) | placeholder_drop | prose_drop |
| School Detention | reorder (u19 sensitive 스왑) | placeholder_drop | prose_drop |

**성공 0/9** — 단 3가지 중요한 관측:

1. **분류가 정상 작동**: 이전 지뢰 리오더(Children u4·School u1)는 허용되어
   통과 — 실패 유닛이 **진짜 sensitive 스왑**(물건↔소유격: Children
   u28, School u19)으로 이동. L2가 이동 토큰 단위로 정확히 판정
2. **passage가 다중 결함 보유**: 이 3개 passage는 리오더 외에
   드롭/스팬 병합 문제도 있어, 리오더 한 종류를 제거해도 다른 유닛에서
   실패 — "콘텐츠 난이도" 결론과 일치
3. **남는 실패 종류 3가지**: placeholder_drop(lite) / sensitive
   reorder(flash) / **스팬 병합**(flash — 유닛 경계 넘는 산문 드롭,
   L2 prose_drop은 유닛 내부만 검사)

**Option E 순효과 검증** (Farm Work + Temple Test, lite 재실행):

| passage | 이전 (리오더 원인) | 이번 실행 | 해석 |
|---|---|---|---|
| Farm Work | u92 reorder (기각) | u85 **드롭** | u92 리오더는 허용됨 — 실패가 다른 유닛의 드롭으로 이동 |
| Temple Test | u3 reorder (기각) | u4 **드롭** | u3 리오더는 허용됨 — 다른 유닛 드롭으로 이동 |

**결론**: Option E는 기계적으로 정확히 동작한다 — 지뢰 리오더(u92·u3)는
허용으로 통과하고, 실패는 다른 유닛의 독립적 결함(드롭 등)으로 이동했다.
단 이 passage들은 **다중 결함 보유**(리오더+드롭+sensitive 스왑+스팬
병합)라서, 리오더 한 종류만 제거로는 passage 성공으로 이어지지 않는다.

**실질적 다음 단계**: 유닛 단위 티어 에스컬레이션(lite 드롭 → flash
재시도, flash는 드롭 안 함) + Option E(자연 어순 허용) + L2(sensitive
스왑 재시도) 조합 — §5c의 3단계 에스컬레이션 계획과 일치.

(참고: 재측정 중 429 rate limit 발생 — 대량 배치 연속 실행 시 쿼터 주의)

## 6. 부록 — 데이터 출처

| 사례 | 덤프 |
|---|---|
| Farm Work u92 | `tmp/debug-dumps/batch-debug/Farm Work.jsonl` |
| Temple Test u3 | `tmp/debug-dumps/batch-debug/Temple Test.jsonl` (2번째 dump) |
| Sydney Chat u22 | `tmp/debug-dumps/model-cmp/gemini-2.5-flash/Sydney Chat.jsonl` |
| Children u4 | `tmp/debug-dumps/model-cmp/gemini-2.5-flash/Children Activity Events.jsonl` |
| School Detention u1 | `tmp/debug-dumps/model-cmp/gemini-2.5-flash/School Detention.jsonl` |

분석 스크립트: `tmp/scripts/reorder_analyze.py`, `reorder_analyze2.py`

## 7. 영향 범위 — 어순 변경 처리를 건드릴 경우

전제: **어순 변경(절 재배열) 자체는 원하던 번역 품질의 결과**다. 아래는
그것을 "허용하면서 구조 계약을 지키는" 방향으로 무언가를 바꿀 때
영향받는 지점만의 목록 (옵션별).

### 옵션 A — 프롬프트 변경 (절 재배열 금지 명시)

| 영향 지점 | 내용 |
|---|---|
| `translation/client.py` | `SYSTEM_PROMPT` 규칙 추가 1줄 |
| 기존 레코드 | **무영향** — 재사용은 body hash 기반이라 새 번역에만 적용 |
| 테스트 | 무영향 (프롬프트 문자열 검사 테스트 없음) |
| **모델 비교 실험** | **실험 무효화** — `model-cmp` 배치(2.5-flash/3.5-flash-lite 완료, 3.6-flash 중단)는 프롬프트 변경 전 데이터. 비교 재실행 필요 |
| 문서 | reorder-analysis.md §5, HANDOFF 관측 요약 |

### 옵션 B — 리오더 허용 + 성분 재정렬 복구 (배제된 옵션이지만 영향만 기록)

| 영향 지점 | 내용 |
|---|---|
| `translation/client.py` `restore_joined` | **순서 치환 전제가 깨짐** — 치환 순서를 토큰 ID 기반으로 바꿔야 함 |
| `translation/translate_passages.py` | L2 reorder 검사 제거/완화, 복구 실패 경로 추가 |
| `translation/assemble_game_ko.py` | 어셈블러의 시그니처 재검증(순서)과 충돌 — 검증 완화 여부 결정 필요 |
| 안전성 | 성분 경계 판정이 불안정 → 매크로 인자 순서가 실제로 어긋날 위험 |

### 옵션 C — 유닛 분할 (절 단위 청킹)

| 영향 지점 | 내용 |
|---|---|
| `pretranslation_cst/chunking.py` | 분할 경계 규칙 변경 |
| `tests/test_chunking.py` | 분할 경계 테스트 다수 — 기대값 갱신 필요 |
| `docs/chunking-strategy.md` | 분할 우선순위 문서 갱신 |
| passage 레코드 재사용 | **무영향** — passage body hash라 청킹과 무관 |
| (미래) unit-level 재사용 R2 | 유닛 hash가 바뀌어 기존 unit 레코드와 불일치 — R2 도입 시에만 |
| 러너/어셈블러/스모크 | 무영향 (유닛 수만 달라짐) |

### 옵션 D — 재시도 1회로 축소 + 리뷰 플래그

| 영향 지점 | 내용 |
|---|---|
| `translation/translate_passages.py` | L2 재시도 정책(reorder만 1회), 실패 사유/통계 |
| `translation/translate_passages.py` 실패 사유 목록 | `reorder`가 리뷰 플래그 대상으로 분류됨 |
| 관측 리포트 | 실패 분류 재집계 |

### 공통 — 옵션과 무관하게 영향받는 것

| 지점 | 내용 |
|---|---|
| 실패 덤프 포맷 | 유닛별 masked/translated — 변경 시 재생성 |
| 테스트 수/기대값 | `tests/test_translate_passages.py` (L2 관련 8개 + α) |
| `docs/HANDOFF.md` | 실패 사유 목록·관측 요약 갱신 |
| `docs/observation-analysis-plan.md` | §5c 모델 비교 결과 갱신 |

