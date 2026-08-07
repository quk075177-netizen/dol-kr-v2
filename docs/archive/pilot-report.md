# 파일럿 번역 보고서 (P1)

기준일: 2026-08-08

## 실행 조건

- 모델: `gemini-2.5-flash-lite` (Vertex AI SDK, ADC 인증)
- 파이프라인: parse → mask → chunk → translate (재시도 2회) → restore
- 배치: 5개 유형 대표 passage, 각 5유닛 (총 25유닛)
- 산출물: `/tmp/opencode/pilot-batch.jsonl`

## 결과 요약

| 유형 | passage | 유닛 | placeholder 성공 | 비고 |
|---|---|---:|---:|---|
| 대화 | Ocean Breeze | 5 | 5/5 | 우수 |
| 전투 | Widgets Combat Man-Combat | 5 | 5/5 | **조사 마커 자동 생성 발견** |
| UI | Widgets Version Info | 5 | 5/5 | 우수 |
| 설정 | Widgets Settings | 5 | 5/5 | placeholder 위주 유닛 |
| 성인 | Gwylan Ocean Breeze Watch | 5 | 4/5 | placeholder 드롭 1건 |

**합계: 24/25 (96%), 실패 1건은 재시도 2회 후에도 placeholder 드롭**

## 핵심 발견 1: LLM이 조사 마커를 자동 생성함 (post 시스템 필요성 근거)

전투 passage에서 다음 번역이 나왔다:

```text
원문: <<npc>> 패들로 당신의 <<bodypart>> 치려고 하지만
번역: __DOLKR_P000051__이(가) __DOLKR_P000052__ 당신의 __DOLKR_P000053__을(를)
      __DOLKR_P000054__으로(로) 치려고 하지만
```

- 원문에는 조사가 없는데, LLM이 **런타임 값(매크로 출력) 뒤의 조사를
  `이(가)`, `을(를)`, `으로(로)` 형태로 표기**했다.
- 받침을 모르는 값이므로 쌍으로 표기한 것이다 — KO HTML의 `【 】` 마커와
  같은 원리 (ko-marker-analysis.md).
- **이 마커는 게임에 그대로 표시되면 안 된다.** post 시스템(정적/동적 치환)
  이 없으면 번역 결과가 게임에서 깨진다.

→ **P2(post 시스템) 필요성 확정.** LLM은 조사 선택(이/가 vs 을/를)을
문맥으로 올바르게 처리하므로(시맨틱 롤 추론 능력), 우리가 할 일은
LLM이 만든 `이(가)` 표기를 표준 post 마커로 후처리하는 것이다.

## 핵심 발견 2: 시맨틱 롤은 여전히 불필요

- LLM이 `이(가)`(주어) vs `을(를)`(목적어) vs `으로(로)`(도구)를 문맥에서
  정확히 선택했다 — 시맨틱 롤 정보 없이.
- 시맨틱 롤 계층이 필요한 상황은 발견되지 않았다. LLM이 조사 선택까지
  처리하고, post 시스템이 "받침 결정"만 보완하면 된다.

## 핵심 발견 3: placeholder 드롭 실패 사례 (성인 passage)

```text
원문: __DOLKR_P000030__ and Robin__DOLKR_P000031__, __DOLKR_P000032__.
      "Robin, would you be a dear..."
번역: __DOLKR_P000030__와 로빈__DOLKR_P000031__, __DOLKR_P000032__.
      "로빈, 잠깐 나와..."  ← P38, P39 드롭, P51 중복
```

- placeholder가 많은 유닛에서 모델이 문장을 압축하면서 placeholder를
  드롭/중복했다.
- 재시도 2회로도 해결 안 됨 → 이 유형(placeholder 밀집)은 재시도
  상한을 늘리거나, 프롬프트 강화 필요.
- 드롭된 placeholder는 원본 매크로가 누락된 것으로, restore 단계에서
  ValueError로 잡힌다 (조용히 넘어가지 않음 — fail-safe 유지).

## 품질 샘플

### 대화 (Ocean Breeze)
```text
"결정했어요." 그가 말합니다. "빵을 저렴하게 유지하고 싶었지만,
이미 많은 관심을 받고 있어요."
```

### UI (Widgets Version Info)
```text
공식 바닐라 웹사이트 / 바닐라 변경 로그 / DoLP 변경사항 및 릴리즈
바닐라 위키 / DoLP 개발 지원
```
- URL(vrelnir.com, fanbox)은 placeholder로 보호됨. 버튼 라벨은 짧고
  자연스러운 한국어.

### 전투 (Widgets Combat Man-Combat)
```text
__DOLKR_P000051__이(가) __DOLKR_P000052__ 당신의 __DOLKR_P000053__을(를)
__DOLKR_P000054__으로(로) 치려고 하지만
__DOLKR_P000055__
  회전하며 상대의 옆구리에 발차기를 합니다.
```
- 런타임 값 뒤 조사가 `이(가)` 형태로 표기됨 (post 시스템 필요).

## 후속 작업

1. **P2 진행**: post 시스템 설계 문서 작성. LLM이 생성하는 `이(가)`/`을(를)`/
   `으로(로)` 표기를 표준 post 마커로 변환하는 규칙 포함.
2. **placeholder 드롭 대응**: placeholder 밀집 유닛의 재시도 상한 증가
   (3~4회) 또는 프롬프트에 "placeholder 수 N개를 정확히 보존" 명시.
3. **P4 판정**: 시맨틱 롤은 불필요로 확정 (LLM이 조사 선택 처리).
   post 시스템에서 받침만 보완.

## 참고

- 이전 단일 파일럿 (Ocean Breeze 전체 28유닛): placeholder 28/28,
  restore 정상.
- `이(가)` 표기는 LLM 출력의 비정형 마커이므로, 번역 후처리에서
  `【 】` 표준 마커 또는 post 필드로 정규화해야 한다.