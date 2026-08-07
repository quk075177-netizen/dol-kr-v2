# 시스템 점검 요약 (DoL 한국어 번역 파이프라인)

기준일: 2026-08-08

## 프로젝트

Degrees of Lewdity(DoL) Plus 게임의 영어 Twee 원문(`game/**/*.twee`,
642파일/16,135 passage)을 안전하게 분해해 한국어로 번역하는 파이프라인.
Python + uv 환경.

## 현재 상태 (완료)

1. **CST 파서** (`pretranslation_cst/`) — SugarCube 매크로를 lossless로
   분해, 계층형 트리 구축, byte-exact round-trip 검증(실패 0).
2. **마스킹** — 번역 대상 prose만 노출, 매크로/링크/변수는 placeholder
   토큰(`__DOLKR_P000000__`)으로 보호, 즉시 복원 가능.
3. **value-kind 분류** — 매크로 인자 2,722개를 9개 의미 카테고리로 분류.
   미분류(unclassified) 0건. prose_text만 노출.
4. **청킹** — passage를 트리 경계 기준으로 1,000자 이하 유닛으로 분할.
   join 불변식 실패 0, 결정성(2회 실행 byte-identical) 유지.
5. **번역 파일럿** — Vertex AI Gemini 2.5 Flash Lite + ADC 인증.
   placeholder 보존 96%(25유닛 중 24), restore 정상.

## 핵심 발견

- **SOV/SVO 어순 변환은 LLM이 처리** (시맨틱 롤 불필요 확인).
- LLM이 런타임 값 뒤에 조사 마커(`이(가)`, `을(를)`)를 자동 생성 →
  post 시스템(getPostNum 받침 판정 + 정적/동적 치환) 설계·초기 구현.
- 3-match(KO 기존 번역, 7,206 passage) 재사용은 post 처리 후 가능.
  마커 없는 44%는 즉시 가능.

## 남은 작업

- 번역 재사용 저장소 구현 (원문 hash 키)
- 3-match 재사용 파이프라인
- post 런타임 helper (게임 사이드)
- 검수 워크플로우

## 검토 받고 싶은 부분

1. 청킹 전략 (트리 경계 vs 문장 경계, 1,000자 임계치) 적절성
2. placeholder 토큰 기반 번역 방식의 한계
3. post 마커 정규화/치환 설계의 결함
4. 재사용 hash 키 설계 (완전 hash vs 일반화 hash)
5. 전반적 아키텍처 병목/리스크