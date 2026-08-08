# Reuse 번역본의 유닛 분할 1:1 대응 조사 레포트

기준일: 2026-08-08
대상: `tmp/stores/ko-reuse-backup-120600.jsonl` (passage-level reuse 스냅샷)
상태: **조사 완료 (코드 수정 없음)** — 조사 스크립트 `tmp/scripts/reuse_chunk_alignment.py`

## 1. 목적

파이프라인은 passage → 파서 → 마스킹 → 청킹 → 유닛 단위 번역 → 레코드 등록으로
돈다. 반면 reuse 스토어의 `ko_reuse` 레코드는 **passage 단위**로 통째로 등록되어
있다. 이 조사는

1. reuse 번역본(`translated_text`)이 현재 파서/마스커/청커로 **유닛 단위로
   재분할(자를) 수 있는가**
2. 자를 수 있다면 영어 원문(`source_text`) 유닛과 **완벽한 1:1 대응**이 되는가

를 묻는다. 어떤 기존 코드도 수정하지 않았고, 조사 결과만 보고한다.

## 2. 데이터

| 항목 | 값 |
|---|---|
| 파일 | `tmp/stores/ko-reuse-backup-120600.jsonl` |
| 레코드 수 | 3,153 (level=passage 전부) |
| 고유 hash | 3,133 (12개 hash가 중복 등록 → 여분 레코드 20) |
| `post_status` | none 3,151 / runtime_remaining 2 |
| EN 본문 길이 | mean 658 / median 496 / max 13,612 |
| KO 본문 길이 | mean 531 / median 426 / max 12,180 |

## 3. 방법

모든 레코드에 대해 양쪽을 같은 경로로 처리했다 (등록 검증 `_verify_passage`와
동일한 합성 passage 방식):

```
synthetic = ":: {passage_name}\n\n{body}"  (EN=source_text, KO=translated_text)
→ parse_file → mask_passage → chunk_passage (기본 threshold=700, max_chars=2000)
```

추가로 threshold=1로 최대 입도 구조 분해를 계산해, 길이 효과와 구조 효과를 분리했다.

비교 지표:
- 유닛 수 (`en_n700` vs `ko_n700`, `en_n1` vs `ko_n1`)
- 유닛별 placeholder 원문 시퀀스 (`ph.original_text` — 해시·구조 골격)
- 유닛별 노출 segment 수 (산문 입도 신호)

## 4. 결과

### 4.1 처리 성공률

파싱/마스킹/청킹 **실패 0건** (3,153/3,153). placeholder 개수 비교: 3,152건 동일,
1건 상이 (레거시 KO 골격 드리프트, §4.4).

### 4.2 자연 청킹(threshold=700) 분류

| 클래스 | 건수 | 비율 | 의미 |
|---|---|---|---|
| `single_single` | 2,651 | 84.1% | 양쪽 모두 1유닛 — 잘라낼 것 없음, passage=유닛 |
| `multi_1to1` | 165 | 5.2% | 양쪽 같은 N>1유닛, 유닛별 placeholder 시퀀스 **완전 일치** |
| `count_mismatch_length` | 334 | 10.6% | 구조는 1:1(threshold=1에서 완전 일치)이나 700 임계값에서 유닛 수만 다름 (KO가 짧아 자연 병합) |
| `count_mismatch_structure` | 3 | 0.1% | 최대 입도에서도 구조 분해 불일치 (레거시 KO 골격 드리프트) |

합계: 3,153건. `single_single` + `multi_1to1` = **89.3%가 자연 청킹만으로 1:1**.

### 4.3 강제 컷 검증 (EN 유닛 경계로 KO 절단)

`count_mismatch_length` 334건은 KO를 자연 청킹하면 임계값 때문에 병합되지만,
**EN의 유닛 경계(placeholder 파티션)를 그대로 KO에 적용해 잘라낼 수 있는지**가
진짜 목표다. 검증 결과:

- EN 유닛 수 > 1인 레코드 502건 중 **501건(99.8%)이 EN 유닛별 placeholder
  파티션과 KO placeholder 파티션이 완벽 일치** (유닛당 원문 시퀀스 동일).
- 1건(Hopeless Cycle Pyre)은 placeholder 총수 자체가 불일치 → 절단 불가.

절단 결과 KO 유닛 크기 분포 (EN 경계로 자른 5,624 유닛):

| 지표 | KO (절단) | EN (자연) |
|---|---|---|
| 유닛 수 | 5,624 | 5,862 |
| max | **1,232자** | 2,181자 |
| mean | 76자 | 111자 |
| p90 | 233자 | 350자 |
| p50 | 21자 | 22자 |
| > 700자 | 23건 (0.4%) | — |
| > 2,000자 | **0건** | 0건 |

→ EN 경계로 잘라도 KO 유닛은 상한 2,000자를 절대 넘지 않는다. 오히려 KO가
짧아 전반적으로 EN보다 작다.

### 4.4 예외 3건 (절단 불가/불완전)

| passage | EN/KO (n700) | n1 | 원인 |
|---|---|---|---|
| Hopeless Cycle Pyre | 6 / 1 | 38 / 38 | 유닛 26에서 EN은 인접 보호 스팬이 병합(1개 placeholder), KO는 분리(3개) — 레거시 KO에 매크로 사이 산문 차이로 골격 위치가 어긋남 |
| Ocean Breeze (2건 중복) | 153 / 170 | 470 / 469 | KO가 구조 유닛 1개 적음 (문자만 있는 leaf 그룹 차이) — placeholder 파티션은 일치 |

두 케이스 모두 **레거시 3-match KO 자체의 산문/골격 드리프트**에서 비롯되며,
파이프라인 신규 번역과 무관하다. 등록 시 `skeleton_mismatch`/`macro_sequence_mismatch`
검사가 이 3건을 잡지 못한 이유는 검사가 passage 단위 시퀀스 동일성만 보기
때문이다 (위치는 안 봄).

### 4.5 산문 입도 (유닛별 segment 수)

유닛 수가 일치하는 정렬된 유닛 쌍 5,509개 중 **99.3%(5,469)가 노출 segment 수
일치**. 40쌍은 한국어 문장 병합/분리(예: EN 8 segment → KO 6)로 산문 입도만
다르며 placeholder 정렬에는 영향 없음.

### 4.6 glue 유닛

EN 유닛 8,513개 중 38.1%(3,246)가 콘텐츠 없는 glue(개행/매크로만) — 파이프라인
러너의 identity 처리 대상과 동일한 성질이다. KO도 유사 분포.

## 5. 결론

**reuse 번역본은 현재 파서/마스커/청커만으로 유닛 단위로 자를 수 있다.**

- 전 레코드(3,153)가 기존 파이프라인 함수로 파싱·마스킹·청킹 성공.
- 84.1%는 양쪽 자연 청킹이 이미 1유닛(절단 불필요), 5.2%는 양쪽 자연 청킹
  유닛이 완전 1:1.
- 나머지 10.6%(334건)도 **EN 유닛 경계로 KO를 절단하면** 501/502건이 placeholder
  시퀀스 기준 완벽 1:1로 잘리고, 절단 유닛 크기 상한(2,000자) 초과 0건.
- 총 효과: passage 레코드 3,153건 → 유닛 레코드 약 8.5천건 (≈2.7배 세분화).
  한 줄 수정 시 재번역 범위가 passage가 아닌 유닛 단위로 좁혀진다
  (chunking-strategy의 700자 튜닝 의도와 동일한 방향).

### 구현 시 유의점 (실행은 이번 범위 아님)

1. **절단은 EN 경계 기준으로 해야 한다.** KO 자연 청킹은 KO가 짧아 더 굵게
   병합되므로, KO를 threshold=1로 최대 입도로 나눈 뒤 EN 유닛 파티션(placeholder
   index 그룹)에 맞춰 병합하면 EN과 정확히 같은 경계가 나온다.
2. **절단된 KO 유닛의 placeholder 토큰 번호는 재부여 필요.** 현재 레코드는
   passage 단위 마스킹 토큰이므로, 유닛 단위 스토어 레코드로 등록하려면 기존
   unit-level 재사용(`_reuse_unit`의 `_retokenize`)과 동일하게 유닛 기준으로
   토큰을 다시 발급해야 한다.
3. 예외 3건(0.1%)은 절단 대상에서 제외하고 passage 레코드로 남긴다.
4. 산문 경계 드리프트(0.7%)는 placeholder 정렬에는 영향이 없으나, 절단 시
   문장이 유닛 경계에 걸치는 경우가 있을 수 있다 — 프롬프트의
   `preceding/following_context`로 보완하는 기존 설계와 동일하게 처리.

## 6. 산출물

- 조사 스크립트: `tmp/scripts/reuse_chunk_alignment.py`
- 상세 통계: `tmp/reports/reuse-chunk-alignment-stats.json`
- 실행 요약: 아래 4.2~4.4 (스크립트 stdout 참조)
