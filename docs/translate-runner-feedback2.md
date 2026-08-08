# L2 유닛 구조 조기 검사 + 배치 관측 피드백 요청

기준일: 2026-08-08
목적: 배치 관측(2회차) 결과로 도입한 L2(유닛 단위 구조 검사) 구현의 미흡
지점을 리뷰받기 위한 문서. `docs/translate-runner-feedback.md`(러너 1차)
의 후속 — 그 문서의 H3(L2 부재), Q1(L2 보류)이 이번에 해소되었다.

## 1. 배경: 관측에서 얻은 것

대표 유형별 배치 2회 (21 passage / ~1,325 유닛, gemini-2.5-flash-lite):

| 실패 모드 | 회수 | 실측 사례 | 기존 검증에서의 위치 |
|---|---|---:|---|---|
| placeholder_drop | 12 | Sydney Chat u65·Children u4·School Detention u3 (재실행 반복) | L1에서 감지, 재시도로 불가 |
| reorder | 2 | Farm Work u92, Temple Test u3 | L1 통과, L3에서만 적발 |
| foreign_token (타 유닛 토큰 삽입) | 1 | Ocean Breeze Work u20 | L1 통과, restore에서 적발 |
| format_hallucination (자릿수 다른 토큰) | 1 | Mansion Steal Stash Calm | L1 통과, L3에서만 적발 |

- **passage 성공 2/21 (9.5%)**, 유닛 실패율 ≈1.3% — 실패 대부분이 단일
  유닛. 유닛 실패율 p≈1.3%면 100유닛 passage 성공률 ≈27%로, 유닛 1개의
  문제로 passage 전체(100유닛 번역분)가 폐기된다.
- **결정성 발견**: 3개 passage를 독립 재실행했을 때 **같은 유닛**에서
  반복 실패 (Sydney u65 ×2, Children u4 ×2, School Detention u3 ×2).
  드롭은 확률적이 아니라 유닛 특유의 고질 문제.
- 밀도 상관 없음: 실패 유닛의 placeholder 수가 평균 이하(9ph/6ph)인
  경우도 존재 — "밀집 유닛" 가설만으로는 예측 불가.

## 2. L2 구현 내용 (이번에 추가)

`translation/translate_passages.py`:

```python
L2_RETRIES = 2                                   # L2 재시도 상한

verify_unit_structure(unit, translated) -> list[str]
    # L2 검사 3종 (L1 통과 후 실행)
    # - reorder:        자기 토큰 전부 있으나 순서 다름
    # - foreign_token:  자기 토큰이 아닌 placeholder 유사 토큰
    # - format_hallucination: 자릿수가 자기 토큰과 다른 토큰 (예: 6자리
    #   <000000> vs 7자리 <0000000>) — 마스커가 본문 충돌로 prefix를
    #   키운 passage에서 발생
_l2_retry_hint(problems) -> str                 # 재시도 프롬프트 힌트
```

흐름 변화:

```text
유닛별: translate_unit (L1 재시도 내장)
  → L1 통과 시 L2 검사
  → L2 문제 있으면 힌트 포함 재번역 (최대 L2_RETRIES회)
  → 그래도 실패하면 passage 즉시 폐기, 사유 = L2 코드
      (placeholder_drop | reorder | foreign_token | format_hallucination
       | malformed_post_marker | restore_failed | skeleton_mismatch)
```

- `translate_unit`에 `hint` 파라미터 추가 (프롬프트에 구조 문제 지적 문구
  부착 — `translation/client.py`)
- foreign-token 검사 오탐 안전성: game/ corpus 본문에 `<0\d{6}>` 패턴
  **0건** 확인 (마스커의 prefix 성장 루프는 방어적 코드) — "자기 토큰이
  아닌 placeholder 유사 문자열"은 전부 모델 산출물로 판정 가능.

## 3. 핵심 인터페이스 (변경분)

```python
# translation/client.py
translate_unit(unit, index=0, total=1, max_retries=3, hint=None)
    # hint: L2 재시도용 — 모든 시도에 프롬프트로 부착

# translation/translate_passages.py
verify_unit_structure(unit, translated_text) -> list[str]
    # [] = OK, 그 외 = 문제 코드 리스트 (reorder / foreign_token / ...)
L2_RETRIES = 2
```

실패 사유 확장 (배치 관측 전 7종 → 9종):
`skipped / placeholder_drop / reorder / foreign_token / format_hallucination
/ malformed_post_marker / restore_failed / skeleton_mismatch / exception:...`

## 4. 왜 이렇게 오래 걸렸나 (시간 분석)

| 단계 | 작업 | 소요 |
|---|---|---|
| 1 | 대표 유형 배치-1 (10 passage) 설계 + 실행 + 관측 | ~50분 |
| 2 | 마커 3-match 등록 + 검증 보강 (배치와 병행) | ~40분 |
| 3 | 빌드 체인 검증 + 스토어 정리 | ~10분 |
| 4 | 배치-2 (11 passage) 실행 + 실패 모드 분류 | ~40분 |
| 5 | 결정성 재확인 (재실행 덤프 비교) | ~10분 |
| 6 | L2 구현 + 테스트 | ~20분 |

병목: (a) 배치 실행은 API 왕복(유닛당 ~1.5초)이 본체 — 병렬화하지 않아
~90분; (b) 실패 분석은 덤프 기반이라 재번역 없이 진행 가능 (H2 덤프의
효과). L2 구현 자체는 20분 — 관측이 구현을 안내한 비용.

## 4b. L2 쌍체 비교 결과 (기존 실패 passage 재실행, 5 passage)

| passage | 유닛 | L2 전 (배치 1·2) | L2 후 | 판정 |
|---|---:|---|---|---|
| Farm Work | 100 | skeleton_mismatch (u92 reorder) | **성공** | L2 재시도 회복 (또는 우연 — H7) |
| Temple Test | 38 | skeleton_mismatch | reorder | **사유 세분화 성공** (유닛 레벨 적발) |
| Mansion Steal Stash Calm | 39 | skeleton_mismatch | skeleton_mismatch | L2 통과 후 L3 실패 (다른 결함) |
| Ocean Breeze Work | 66 | restore_failed | skeleton_mismatch | 이번 실행에선 환각 미발생, 다른 결함 |
| School Detention | 53 | placeholder_drop ×2 | skeleton_mismatch | 결정성 드롭이 이번엔 미발생 — 산문 이동 케이스 노출 |

- **신규 실패 양상 발견 — 산문 이동(스팬 병합)**: School Detention에서
  `<<He>> points at the whiteboard opposite <<him>>`을 번역하며 토큰 사이
  산문을 다른 위치로 옮겨 `<0000070><0000071>`이 인접 → 파서가
  `<<He>><<him>>`을 **한 스팬으로 병합** → L3 시그니처 불일치.
  - L2 3종(순서/타 토큰/형식)은 전부 통과 — 토큰 사이에 "비공백 콘텐츠가
    사라졌는지"는 검사하지 않기 때문.
  - 보완 가능: "출력에서 인접한 두 자기 토큰의 사이가 비어 있는데
    masked 원본에서는 비공백 산문이었다" → `prose_drop` 코드로 L2 검사
    추가. 결정적 복구는 불가(산문 위치를 모름) — 재시도 힌트 대상.
  - **미구현 (H5로 병합, Q5b 참조).**
- L2의 기대 효과는 "reorder/형식/타 토큰 → 유닛 재시도로 회복" — 1/3
  회복 실측(Farm Work). 나머지 실패는 이번 실행에서 다른 결함으로
  재발하여, **유닛 단위 검사가 통과해도 L3 실패가 남는다**는 게 관측된
  한계다.

## 5. 미흡 지점 (우선순위순)

### H1. placeholder_drop(결정적)은 L2로 해결 안 됨

- 관측: 같은 유닛이 재실행에서 반복 실패. L1 재시도(3회)도 무효.
- L2는 "구조 문제"(reorder/foreign/format)만 조기 검사 — 드롭은
  "유닛 재번역으로 회복 불가능한" 클래스로 남음.
- 대안 후보: 유닛 분할(밀집 유닛 재청킹) / 프롬프트 강화 / 리뷰 플래그
  (자동 재번역 아님). **아직 결정 안 됨 — Q2 참조.**

### H2. `_PLACEHOLDER_RE`가 6자리 고정

- `_separator_gap` 등이 `r"<0\d{6}>"`로 다음 토큰을 검색 — 마스커
  prefix가 자란 passage(7자리 토큰)에서는 다음 토큰을 못 찾아 분리자
  검증이 어긋날 수 있음. Mansion Steal Stash Calm이 첫 실측 대상.
- L2의 format_hallucination이 같은 현상을 덮지만, separator 경로는
  artifact 토큰 집합 기반으로 일반화하는 게 정답.
- **미수정 (Q5 참조).**

### H3. L2 재시도의 비용 상한

- L2 문제 유닛당 최대 2회 재시도 × 각 내부 L1 재시도 3회 = 최대 9 API
  호출 + 힌트가 없을 때의 1회. 통상 1~2회로 끝나지만, 상한을 문서화하지
  않으면 비용 폭주 위험. (배치 단위 예외 격리는 있음)
- 힌트가 "문제 지적"에 불과해 모델이 반복 실패하면 9회 낭비 — 결정적
  실패(같은 유닛 반복) 관측과 함께, 재시도 상한 축소 or 1회 후 리뷰
  플래그 전환 검토.

### H4. 형식 환각의 근본 원인이 프롬프트 예시

- `SYSTEM_PROMPT`의 예시가 6자리 `<000000>` — 7자리 passage에서 모델이
  그 형식을 복사해 삽입. L2가 감지·폐기하지만, **원인 제거가 더 싸다**
  (예시를 "입력의 토큰을 그대로 복사" 문구로 교체).
- **미반영** — L2 검증을 먼저 실측하고, 프롬프트 변경은 재번역
  비용(기존 레코드 무효화 없음 — hash 기반이라 안전)과 함께 Q4에서 결정.

### H5. separator 갭 실패는 여전히 L3에서만 검증

- `repair_separator_newlines`가 결정적 복구를 하므로 실패 가능성은 낮지만,
  "갭 복구 실패"는 유닛 레벨 검사가 없어 L3(joined)에서만 드러남.
  L2가 갭까지 보려면 유닛 경계 맥락이 필요 — 범위 확대는 다음 단계.
- **쌍체 비교에서 실측 (산문 이동)**: 토큰 사이 산문이 다른 위치로
  이동해 토큰이 인접해지는 경우 — separator(공백)가 아니라 **비공백
  콘텐츠 소실**이라 복구 불가. L2에 `prose_drop`(인접 토큰 사이 빈 간격
  vs 원본 비공백 갭) 검사를 추가하면 재시도 힌트 대상이 됨. **미구현
  (Q8).**

### H6. 위젯 passage 정책 미정 (관측 사각지대)

- 561/331유닛 전투/설정 passage는 [widget] 코드 passage라 러너가 거절 —
  L2의 효과가 **가장 큰 passage에서 측정 불가**. 위젯을 옵션
  (`--allow-code`)으로 열면 L2 데이터가 그쪽에 일반화되는지 관측 가능.

### H7. 쌍체 비교의 해석 한계

- L2 유무를 같은 passage로 비교했지만, LLM 출력이 비결정적이라 "L2가
  성공시켰다"는 **한 번의 실행으로는 판정 불가** (우연 성공 가능).
- 같은 passage를 반복 실행해 L2 재시도 개입 여부와 성공률을 봐야 함.
- 보완책: 재시도 발생 횟수를 레코드/로그로 남기면 "L2 개입 → 성공"을
  추적 가능. **현재는 로그에만 존재 (Q6 참조).**

## 6. 리뷰어에게 받고 싶은 질문

1. **L2 재시도와 "자동 재번역 금지" 정책의 경계** — 1차 리뷰에서 구조
   위반 재시도는 무효라고 판정했는데(Q2), L2는 유닛 단위 국소 재시도라
   범위가 다르다고 보고 구현했다. 이 경계 판단이 타당한가?
2. **placeholder_drop(결정적)의 우선 대응** — 유닛 분할(밀집 유닛
   재청킹) / 프롬프트 강화 / 리뷰 플래그 중 무엇을 먼저?
3. **위젯 passage 정책** — `--allow-code` 옵션으로 관측을 열 것인가,
   어셈블러 정책(제외)과 일치하게 스킵할 것인가?
4. **프롬프트 예시 수정** — `<000000>` 예시를 제거/형식 고정 문구로
   바꿀지, L2 감지를 신뢰하고 둘지. (예시 수정은 기존 레코드에 영향 없음)
5. **`_PLACEHOLDER_RE` 6자리 가정 일반화** — 지금 고칠지 후순위인지.
   (현재 마스커 prefix 성장 passage는 소수 — Mansion 1건 실측)
6. **관측 지속성** — 실패 통계/재시도 횟수가 덤프 파일에만 남는다.
   스토어 레코드에 `attempts`/`l2_retries` 필드를 넣어 추적 가능하게
   할지? (스키마 확장 — 어셈블러는 무시하므로 하위 호환)
7. **L2 쌍체 비교의 회복 판정** — Farm Work 성공이 "L2 재시도 덕분"인지
   "이번 실행이 우연히 깨끗했는지"는 시도 횟수 로그 없이는 구분 불가.
   (Q6과 같은 추적 필드로 해소) L2 재시도 횟수를 로그에 남길지.
8. **`prose_drop`(산문 이동) L2 확장** — 쌍체 비교에서 실측된 스팬 병합
   케이스를 L2 코드로 추가할지. 결정적 복구는 불가, 재시도 힌트만 가능.

## 7. 재현 방법

```bash
uv run python -m unittest discover -s tests           # 185개 (L2 8개 추가)

# L2 쌍체 비교 배치 (기존 실패 passage 재실행)
uv run python -m translation.translate_passages \
  --passages-file tmp/batches/batch-l2-paired.jsonl --debug-dir tmp/debug-dumps/batch-debug

# 전체 체인 검증 (~2분)
python3 build/verify.py
```

## 8. 참고

- 관측 리포트: `tmp/reports/batch-p2-1-report.md`
- 실패 덤프: `tmp/debug-dumps/batch-debug/` (append — 재실행 비교 가능)
- 배치 로그: `tmp/batches/batch-p2-1.log`, `batch-p2-2.log`
- 선행 피드백: `docs/translate-runner-feedback.md` (H3·Q1이 이번 해소)
- 마커 3-match 등록 + macro_sequence 검증 보강은 `docs/HANDOFF.md`에 기록
