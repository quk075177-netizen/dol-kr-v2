# 시스템 리뷰 피드백 트리아지 (2026-08-08)

외부 시스템 리뷰 피드백을 코드/데이터로 검증한 결과. 각 항목의
타당성 판정과 조치를 기록한다.

## 확정 버그 (수정 필요)

### F1. chunking span이 placeholder를 자름 — 확정, 9,275건

**피드백**: `_merge()`가 touching span도 병합해 매크로+변수 span이 하나의
placeholder가 되면, `_split_group`의 분할점이 placeholder 중간을 자를 수
있다. `_build_units_from_spans`는 시작점 기준 배정이라 감지 못한다.

**검증**: 전체 corpus(16,132 passage)에서 span에 걸친 placeholder
**9,275건** 확인.

```text
예: minimap.twee — ph Span(6242, 6323)가 span(6242, 6269)을 넘침 (54바이트)
```

**영향**: 유닛 masked_text에는 placeholder 토큰이 온전히 포함되므로
번역/restore는 동작한다. 그러나 "유닛 = CST 경계 내 조각" 설계 의도가
깨진다 — 이웃 유닛의 실제 원문 구조가 경계와 안 맞는다. 유닛 기반
컨텍스트(LLM 프롬프트의 ancestor 정보)가 오도될 수 있다.

**조치**: `_split_group`의 분할점을 "가장 가까운 placeholder 경계"까지
확장. 우선순위 최고. (수정 전 유닛 테스트 6개 + corpus 검증으로 회귀
확인 필요)

## 타당한 지적 (수정 권장, 실전 영향 낮음)

### F2. `PASSAGE_TAG_RE` `$` 앵커 — 잠재 버그, DoL 0건

`:: Name [tag1] {"json":true}` 형태의 Twee3 JSON 메타데이터가 있으면
태그 매치가 실패해 전체가 name에 흡수된다.

**검증**: DoL 원문에서 해당 패턴 **0건**. 실전 영향 없음.
**조치**: 회귀 fixture로 고정 (수정은 선택).

### F3. `_consume_square` depth — 잠재 버그, DoL 0건

`[img[[link]]]` / `[[[img[...]]]]`처럼 link/image가 서로 중첩되면
depth 카운트가 어긋날 수 있다.

**검증**: DoL 원문에서 중첩 패턴 **0건**. 실전 영향 없음.
**조치**: 회귀 fixture로 고정 (수정은 선택).

### F4. `_classify_args` expose 조건 주석 부재

`"llm" not in evidence or confidence == "high"` 조건이 의도인지
실수인지 주석 없이 알기 어렵다.

**검증**: 조건 자체는 의도된 것 (policy: llm은 high일 때만 신뢰).
**조치**: 주석 추가.

### F5. `MacroRegistry.get()` fallback — unknown_macro 부재

미등록 매크로가 조용히 `MacroSpec(key)`(leaf/parsed)로 처리된다.
grammar.json 커버리지 누락을 삼킬 수 있다.

**조치**: `unknown_macro` diagnostic 추가 (또는 `is_known` 활용).

### F6. grammar tags 값이 dead data

`tags` dict의 arg_mode 값이 코드 어디서도 소비되지 않는다
(arg_mode는 top-level `registry.get(name)`으로만 결정).

**검증**: 피드백자가 grammar.json 확인 — 전부 top-level 엔트리와
일치하는 **의도된 이중 기재**임을 확인. 버그 아님.
**조치**: 로드 시점에 `tags[name] == registry.get(name).arg_mode`
consistency check 추가 (어긋남 조용히 무시 방지).

### F7. `_neighbour_context` 반쪽 placeholder 토큰

`masked_text[:120]` 슬라이스가 placeholder 토큰 중간을 자르면
`__DOLKR_P00000` 같은 반쪽 토큰이 LLM 프롬프트에 노출된다.

**조치**: 마지막 완전한 placeholder/segment 경계까지만 자르도록 수정.

### F8. `max_chars`가 하드 캡으로 안 쓰임

`max_chars=2000` 파라미터가 존재하지만 코드에서 강제되지 않는다
(threshold만 사용, 초과 시 leaf는 그대로).

**조치**: soft target임을 명시하거나, 초과 유닛 로그 추가.

## 참고 (우선순위 낮음)

### F9. `_merge_small_units` ancestors — 한쪽만 남음

서로 다른 container 경로 유닛이 병합되면 ancestors가 하나만 남아
메타데이터가 오도될 수 있다. LLM 프롬프트 컨텍스트용이므로 낮은
우선순위지만 기록.

### F10. placeholder prefix 인플레이션

충돌 시 `prefix + "_"`가 영구 적용되어 passage 내 placeholder 포맷이
비일관해질 수 있다. 원문에 `__DOLKR_P` 패턴이 우연히 있을 때만 발동 —
확률 낮음. 충돌 시 전체 재생성이 더 안전.

### F11. TextSource char 단위 encode

`char.encode("utf-8")`가 문자마다 호출된다. 병목은 아니지만 청크 단위
또는 codepoint 분기로 최적화 가능. 프로파일링 후 결정.

## 긍정 평가 (수정 불필요)

- lossless round-trip 전제의 stage 분리 — 합리적
- `_build_tree` stack 기반 container/branch + unclosed fallback — 안전한 실패
- opaque passage 조기 차단 — 좋음
- `restore_mask`의 `occurrences != 1` strict check — 좋은 안전장치
  (파일럿 1건 실패가 이 예외로 걸러진 것과 일치. 번역 단계 재시도
  루프는 이미 존재: `client.py` max_retries=3)
- `Passage.get_ancestors`/`get_siblings` node_index 기반 O(depth) — 문제없음
- square_markup `->`/`<-` delimiter 처리 — 맞게 구현됨

## 우선순위 요약

| 우선순위 | 항목 | 작업 | 상태 |
|---|---|---|---|
| 1 | F1 | `_split_group` 분할점을 placeholder 경계로 확장 (9,275건) | **완료** (0건) |
| 2 | F2/F3 | 회귀 fixture 추가 (수정 선택) | pending |
| 3 | F4/F5/F6/F7/F8 | 주석/diagnostic/consistency check/슬라이스 수정 | F4·F6·F7·F8 완료, F5 pending |
| 4 | F9/F10/F11 | 참고, 후순위 | pending |

## 적용 내역 (2026-08-08)

- **F1**: `_build_units_from_spans` 클램프 루프에서 span.end를 그 안에
  시작하는 placeholder의 end로 확장. corpus 재검증: 걸침 9,275 → **0**,
  join 불변식 유지, over2000 26건 (leaf 초과, 의도).
- **F4**: `_classify_args` expose 조건에 policy 주석 추가.
- **F6**: `MacroRegistry.from_payload`에 tags vs top-level arg_mode
  consistency check 추가 (불일치 시 ValueError).
- **F7**: `_neighbour_context`가 완전한 placeholder 토큰 경계까지 자름.
- **F8**: `chunk_passage` docstring에 max_chars가 soft ceiling임을 명시.
- **F5** (unknown_macro diagnostic): 미적용 — 새 diagnostic은 corpus
  수치/baseline을 바꾸므로 별도 결정 필요. `MacroRegistry.is_known`이
  이미 있어 진단 추가는 쉬움.