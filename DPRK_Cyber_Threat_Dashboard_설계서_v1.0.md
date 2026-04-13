# DPRK Cyber Threat Intelligence Monitoring Dashboard

## 제품 설계서 (Product Design Specification) v1.0

**작성일:** 2026년 4월 13일

**기반 논문:** *An exploratory analysis of the DPRK cyber threat landscape using publicly available reports* (Lyu et al., 2025)
International Journal of Information Security, 24:66

---

## 1. 제품 개요 (Product Overview)

### 1.1 배경 및 목적

북한 국가 후원 사이버 위협 행위자는 전 세계 63개국에 걸쳐 154건의 주요 사건을 일으킨 글로벌 위협 세력이다. Lyu et al.(2025)의 연구에 따르면 2009년부터 2024년까지 2,058건 이상의 공개 보고서가 수집되었으며, 160개의 코드명이 7개 그룹으로 클러스터링되었다. 추정 피해액은 36억 달러 이상으로, 이는 국제 금융 시스템과 글로벌 보안에 심각한 위협을 제기한다.

본 대시보드는 해당 연구의 데이터셋(actors, reports, incidents 시트)을 통합적으로 시각화하고 분석하여, 사이버 위협 인텔리전스 전문가, 보안 연구원, 정책 결정자가 북한 사이버 위협의 전체적인 그림을 신속하게 파악할 수 있도록 설계된 모니터링 제품이다.

### 1.2 대상 사용자

| 사용자 유형 | 주요 요구사항 | 핵심 기능 |
|:---:|:---|:---|
| CTI 분석가 | 위협 행위자 추적, 사건 상관관계 분석 | 코드명 네트워크, 태그 교차분석 |
| 보안 연구원 | 공격 트렌드 파악, 데이터 기반 연구 | 시계열 분석, 보고서 트렌드 |
| 정책 결정자 | 거시적 위협 현황, 브리핑용 요약 | 세계지도, KPI 카드, 요약 통계 |
| CERT/CSIRT | 최신 사건 모니터링, 실시간 알림 | 활동 피드, 핫존 알림 |

### 1.3 데이터 소스

본 대시보드는 3개의 엑셀 시트를 기반으로 한다:

| 시트명 | 컬럼 구성 | 설명 |
|:---:|:---|:---|
| Actors | Name, Named by, Associated Group, First seen, Last seen | 160개 코드명, 7개 그룹 클러스터링 정보 |
| Reports | Published, Author, Title, URL, Tags | 2,058건+ 공개 보고서, 해시태그 기반 분류 |
| Incidents | Reported, Victims, Motivations, Sectors, Countries | 154건 주요 사건, 동기/산업/국가 분류 |

---

## 2. 대시보드 레이아웃 설계 (Dashboard Layout)

### 2.1 전체 구조

대시보드는 상단 네비게이션 바, 중앙 메인 치, 하단 상세 패널의 3단 구조로 설계한다. 중앙에는 세계지도 기반 사건 시각화를 배치하고, 좌우 사이드 패널과 하단 패널에 분석 위젯을 배치한다.

### 2.2 영역별 레이아웃 그리드

| 영역 | 컴포넌트 | 비율 | 우선순위 |
|:---:|:---|:---:|:---:|
| A. 상단 바 | 타이틀, 필터, 기간 선택기, 상태 배지 | 전체 너비 100% | P0 - 필수 |
| B. KPI 카드 | 5개 핵심 지표 카드 행 | 전체 너비 100% | P0 - 필수 |
| C. 세계지도 | 인터랙티브 사건 지도 (중앙 메인) | 너비 75% / 높이 360px+ | P0 - 필수 |
| D. 우측 사이드 | 동기 분포, 타겟 섹터 차트 | 너비 25% | P0 - 필수 |
| E. 하단 패널 | 트렌드 차트, 그룹 목록, 활동 피드 | 전체 너비, 3컬럼 | P0 - 필수 |
| F. 상세 뷰 | 오버레이/모달 기반 심층 분석 | 클릭 시 확장 | P1 - 권장 |

### 2.3 ASCII 와이어프레임

```
┌──────────────────────────────────────────────────────────────────┐
│  [A] 타이틀 바 / 필터 / 기간선택 / 상태배지                        │
├──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┤
│ [B] KPI: Reports │ Actors  │ Incidents│ Est.$  │ Peak   │
├─────────────────────────────────────────────────────┬────────────────┤
│                                                     │ [D] Motivation │
│                                                     │     Donut      │
│  [C] 세계지도 (Interactive World Map)                ├────────────────┤
│      • 버블 마커 (크기=사건수)                        │ [D] Sector     │
│      • 색상 = 동기 유형                              │     Bar Chart  │
│      • 핫존 표시                                     │                │
├─────────────────┬───────────────┬────────────────────────────────┤
│ [E] Annual      │ [E] Threat    │ [E] Recent Activity            │
│ Trend Chart     │ Actor Groups  │ Feed (Timeline)                │
│ (Reports/Inc)   │ (7 clusters)  │ (Latest reports)               │
└─────────────────┴───────────────┴────────────────────────────────┘
```

---

## 3. 컴포넌트 상세 설계 (Component Specifications)

### 3.1 [A] 상단 네비게이션 바

| 항목 | 상세 설명 |
|:---:|:---|
| 타이틀 | DPRK Cyber Threat Intelligence Dashboard |
| 기간 선택기 | Date Range Picker (2009 ~ 현재). 전체/연도별/사용자 지정 기간 선택 가능. 선택 시 모든 패널이 해당 기간으로 필터링됨 |
| 그룹 필터 | 7개 그룹 멀티셀렉트: Lazarus, ScarCruft, BlueNoroff, Kimsuky, Andariel, Konni, Unclassified |
| 상태 배지 | 활성 캠페인 수(빨간), 마지막 업데이트 시간(녹색), 데이터 범위(회색) |

### 3.2 [B] KPI 카드 행

핵심 지표 5개를 가로 배치한다. 기간 필터 적용 시 실시간 재계산된다.

| KPI | 기본값 | 데이터 소스 | 부가 정보 |
|:---|:---:|:---|:---|
| Total Reports | 2,058+ | Reports 시트 행 수 카운트 | 전월 대비 증감률 표시 (▲/▼) |
| Threat Actors | 160 | Actors 시트 고유 Name 수 | 7 groups clustered 부제 |
| Notable Incidents | 154 | Incidents 시트 행 수 카운트 | 63 countries affected 부제 |
| Est. Stolen | $3.6B+ | UN 보고서 기반 추정치 | crypto + financial 분류 표시 |
| Peak Year | 2018 | Incidents 시트 연도별 집계 MAX | 33 incidents recorded |

### 3.3 [C] 세계지도 (중앙 메인)

대시보드의 핵심 컴포넌트로, Incidents 시트의 Countries 컬럼을 기반으로 전 세계 63개국의 피해 현황을 시각화한다.

| 요소 | 상세 사양 |
|:---:|:---|
| 지도 유형 | D3.js 기반 인터랙티브 코로플레스(Choropleth) 지도. 피해 빈도에 따른 색상 그라디언트 적용 |
| 버블 마커 | 국가별 사건 수에 비례한 크기의 버블 마커. KR:49, US:21, SG:10, IN:10, JP:9 등 상위 국가 강조 |
| 색상 코딩 | 빨간: Financial Gain / 파란: Espionage, Data Breach / 주황: Destruction / 보라: Supply Chain |
| 핫존 표시 | 경도/위도 기반 국가별 핫존 영역 표시. 동아시아 지역 HOTZONE 강조 박스 |
| 인터랙션 | 국가 클릭 시 해당 국가 사건 목록 툴팁 표시. 버블 클릭 시 사건 상세 모달 표시. 줌/확대 지원 |
| 애니메이션 | 시간 슬라이더 연동: 연도별 사건 발생 추이를 타임라인 애니메이션으로 시각화. 신규 사건 발생 시 펄스 이펙트 |

### 3.4 [D] 우측 사이드 패널

#### 3.4.1 공격 동기 분포 (Donut Chart)

Incidents 시트의 Motivations 컬럼을 집계하여 도넛 차트로 표시한다. 논문의 Fig.7에 해당하며, Financial Gain(65%), Data Breach(11%), Espionage(9%), Supply Chain(6%), Destruction(5%), Watering Hole(4%) 등의 비율을 시각화한다. 기간 필터 적용 시 해당 기간의 동기 비율로 재계산되어 시간에 따른 동기 변화를 확인할 수 있다.

#### 3.4.2 타겟 섹터 차트 (Horizontal Bar)

Incidents 시트의 Sectors 컬럼을 집계하여 수평 바 차트로 표시한다. 논문의 Fig.9에 해당하며, Cryptocurrency(44%), Finance(29%), Technology(6%), Defense(6%), Government(5%) 등의 비율을 표시한다. 각 바 클릭 시 해당 섹터의 사건 목록으로 드릴다운한다.

### 3.5 [E] 하단 패널 (3컬럼)

#### 3.5.1 연간 트렌드 차트

Reports 시트의 Published 컬럼과 Incidents 시트의 Reported 컬럼을 연도별로 집계하여 듀얼 바 차트로 표시한다. 논문 Fig.2와 Fig.6의 데이터를 통합한 뷰이다. 탭 전환으로 Reports/Incidents/Financial Gain 세 가지 뷰를 전환할 수 있다.

#### 3.5.2 위협 행위자 그룹 목록

Actors 시트의 Associated Group별 코드명 수를 집계하여 목록으로 표시한다. 7개 그룹(Lazarus 40, Kimsuky 32, BlueNoroff 31, ScarCruft 17, Andariel 16, Konni 8, Unclassified 16)을 색상 코드와 함께 표시한다. 그룹명 클릭 시 해당 그룹의 코드명 네트워크 다이어그램(논문 Fig.5 참조)을 모달로 표시한다.

#### 3.5.3 최신 활동 피드

Reports 시트를 Published 내림차순으로 정렬하여 최신 보고서를 타임라인 형태로 표시한다. 각 항목은 날짜, 제목, 저자, Tags를 포함하며, 클릭 시 원문 URL로 이동한다. 그룹별 색상 도트로 시각적 구분을 제공한다.

---

## 4. 분석 기능 설계 (Analysis Features)

논문의 연구 결과와 3개 시트의 데이터 구조를 기반으로 5개 분석 영역, 15개 분석 기능을 설계한다.

### 4.1 위협 행위자 분석 (Actors 시트 기반)

| ID | 분석 기능 | 상세 설명 | 사용 데이터 |
|:---:|:---|:---|:---|
| A-1 | 코드명 네트워크 그래프 | 160개 코드명 간 관계를 Force-directed graph로 시각화. 노드 크기=보고서 언급 빈도, 색상=그룹 | Actors.Name, Associated Group, Reports.Tags |
| A-2 | CTI 업체별 명명 패턴 | Named by 컬럼 기반 업체별 명명 규칙 분석. 접두/접미사 패턴, 테마(동물/기상/금속 등) 분류 | Actors.Name, Named by |
| A-3 | 활동 기간 타임라인 | First seen/Last seen 기반 간트 차트. 그룹별 평균 활동 기간, 신규 등장 코드명 추이 | Actors.First seen, Last seen, Associated Group |

### 4.2 보고서 동향 분석 (Reports 시트 기반)

| ID | 분석 기능 | 상세 설명 | 사용 데이터 |
|:---:|:---|:---|:---|
| B-1 | 발간 추이 분석 | 월별/연도별 보고서 발간량 추이. 2023년 607건 급증 현상 분석. 계절성/이벤트 연관성 파악 | Reports.Published |
| B-2 | 기여자 분석 | 300+ 발간 주체 중 상위 기여자 식별. Ahnlab(271), EST Security(168), Kaspersky(74) 등 시간별 관심 변화 | Reports.Author |
| B-3 | 태그 빈도/공출현 분석 | Tags 해시태그 파싱 후 위협 행위자별/악성코드별 언급 빈도. 태그 간 co-occurrence 패턴 분석 | Reports.Tags |

### 4.3 사건 심층 분석 (Incidents 시트 기반)

| ID | 분석 기능 | 상세 설명 | 사용 데이터 |
|:---:|:---|:---|:---|
| C-1 | 동기 변화 분석 | 2015년 기점 파괴/첩보 → 금전적 동기 전환 추이 시각화. Stacked area chart로 연도별 동기 비율 변화 표시 | Incidents.Reported, Motivations |
| C-2 | 피해 분포 분석 | 국가별(63개국) 및 산업별 피해 분포. 코로플레스 지도 + 트리맵으로 시각화 | Incidents.Countries, Sectors |
| C-3 | 시계열 패턴 분석 | 2018년 33건 피크 후 연 10건 수준 안정화 패턴 탐색. 이동평균, 추세선 분석 | Incidents.Reported |

### 4.4 교차 분석 (Cross-sheet)

| ID | 분석 기능 | 상세 설명 | 사용 데이터 |
|:---:|:---|:---|:---|
| D-1 | 보고서-사건 상관분석 | 연도별 보고서 발간량 vs 사건 수 상관계수 산출. 보고서 증가가 실제 위협 증가 반영 vs 업계 관심 증가 구분 | Reports.Published + Incidents.Reported |
| D-2 | 그룹-산업 매핑 | Actors의 Associated Group과 Incidents의 Sectors를 Tags 기반으로 조인. 그룹별 전문 공격 영역 프로파일링 | Actors.Group + Incidents.Sectors + Reports.Tags |
| D-3 | 이벤트 반응 분석 | 주요 사건 발생 후 보고서 급증 패턴과 lag time 측정. Sony Pictures, Bangladesh Bank 등 사례 분석 | Incidents.Reported + Reports.Published |

### 4.5 고급 분석 (Advanced)

| ID | 분석 기능 | 상세 설명 | 사용 데이터 |
|:---:|:---|:---|:---|
| E-1 | 지정학적 연계 분석 | UN 대북제재 결의안, 핵실험 일시 등 외부 이벤트와 사이버 공격 상관관계 분석 | 외부 데이터 + Incidents |
| E-2 | TTP 진화 분석 | Tags에서 추출한 악성코드/도구 정보를 통해 공격 기법(TTP) 변화 추적. MITRE ATT&CK 프레임워크 매핑 | Reports.Tags + MITRE ATT&CK |
| E-3 | 경제적 영향 분석 | 암호화폐 탈취 사건의 피해 금액 추정 및 시계열 분석. UN 보고서 기반 $3.6B 추정치 상세화 | Incidents + UN/Chainalysis 데이터 |
| E-4 | 예측 모델링 | 시계열 데이터 기반 미래 위협 예측. 연간 사건 수 추세, 타겟 섹터 전환 예측, 신규 코드명 등장 예측 | 전체 데이터셋 + ML 모델 |

---

## 5. 기술 스택 및 아키텍처 (Technical Architecture)

### 5.1 권장 기술 스택

| 계층 | 기술 | 선정 사유 |
|:---:|:---|:---|
| Frontend | React 18 + TypeScript | 컴포넌트 기반 UI 구성, 타입 안정성 |
| 시각화 | D3.js + Recharts | D3: 세계지도/네트워크, Recharts: 일반 차트 |
| 지도 | D3-geo + TopoJSON | 경량 지도 렌더링, 커스텀 투영법 지원 |
| 상태관리 | Zustand / React Query | 경량 전역 상태 + 데이터 페칭/캐싱 |
| 스타일링 | Tailwind CSS | 유틸리티 퍼스트 스타일링, 다크모드 지원 |
| Backend | Next.js API Routes / FastAPI | 데이터 전처리 및 API 엔드포인트 |
| 데이터베이스 | PostgreSQL + Prisma ORM | 관계형 DB로 시트 간 조인 최적화 |
| 데이터 파이프라인 | Python (pandas, openpyxl) | 엑셀 데이터 파싱 및 ETL 처리 |

### 5.2 데이터 흐름 아키텍처

```
엑셀 데이터셋(3개 시트)  →  ETL 파이프라인(Python)  →  PostgreSQL DB  →  API Layer  →  React Dashboard
```

ETL 단계에서 Tags 컬럼의 해시태그를 파싱하여 별도 태그 테이블로 정규화하고, Actors의 Associated Group과 Incidents 간의 관계를 Tags를 통해 연결하는 관계 테이블을 생성한다.

### 5.3 데이터베이스 스키마

| 테이블 | 주요 컬럼 | 설명 |
|:---:|:---|:---|
| actors | id, name, named_by, group_id, first_seen, last_seen | 160개 코드명 마스터 테이블 |
| groups | id, name, mitre_id, description, color_code | 7개 그룹 마스터 테이블 |
| reports | id, published, author, title, url | 2,058+ 보고서 마스터 테이블 |
| tags | id, name, type (actor/malware/vuln/op) | 해시태그 정규화 테이블 |
| report_tags | report_id, tag_id | N:M 관계 테이블 |
| incidents | id, reported, victims, description | 154건 주요 사건 마스터 테이블 |
| incident_motivations | incident_id, motivation | 사건별 복수 동기 매핑 |
| incident_sectors | incident_id, sector | 사건별 복수 산업 매핑 |
| incident_countries | incident_id, country_code, country_name | 사건별 복수 국가 매핑 |

### 5.4 API 엔드포인트 설계

```
GET  /api/dashboard/summary          → KPI 카드 데이터 (필터 파라미터 지원)
GET  /api/actors                     → 위협 행위자 목록 + 그룹 정보
GET  /api/actors/network             → 코드명 네트워크 그래프 데이터
GET  /api/reports                    → 보고서 목록 (페이지네이션, 태그 필터)
GET  /api/reports/trend              → 연도/월별 발간 추이 데이터
GET  /api/reports/contributors       → 기여자별 보고서 수 집계
GET  /api/incidents                  → 사건 목록 (필터: 기간, 동기, 섹터, 국가)
GET  /api/incidents/map              → 세계지도용 국가별 사건 집계 데이터
GET  /api/incidents/motivations      → 동기별 비율 데이터
GET  /api/incidents/sectors          → 섹터별 비율 데이터
GET  /api/incidents/timeline         → 시계열 분석 데이터
GET  /api/analysis/correlation       → 보고서-사건 상관분석 데이터
GET  /api/analysis/group-sector      → 그룹-산업 매핑 데이터
GET  /api/tags/cooccurrence          → 태그 공출현 분석 데이터
```

---

## 6. UX 인터랙션 설계 (Interaction Design)

### 6.1 필터링 및 연동

모든 패널은 글로벌 필터(기간, 그룹)에 연동된다. 상단 바에서 기간을 선택하면 모든 차트, 지도, 목록이 해당 기간으로 재계산된다. 이를 통해 2015년 이전과 이후의 동기 변화, 특정 연도의 집중 활동 등을 심층적으로 탐색할 수 있다.

### 6.2 클릭-스루 탐색

| 트리거 | 액션 | 결과 |
|:---|:---|:---|
| 세계지도 국가 클릭 | 툴팁: 해당 국가 사건 요약 | 클릭: 사건 목록 모달 오픈 |
| 세계지도 버블 클릭 | 사건 상세 정보 모달 | Victims, Motivations, Sectors, 관련 보고서 링크 |
| 그룹명 클릭 | 코드명 네트워크 모달 | Fig.5 스타일 네트워크 그래프 |
| 트렌드 차트 연도 클릭 | 해당 연도 전체 필터링 | 모든 패널 해당 연도로 재계산 |
| 섹터 바 클릭 | 해당 섹터 사건 목록 | 사건 테이블 필터링 드릴다운 |
| 피드 항목 클릭 | 원문 URL로 이동 | 새 탭에서 보고서 원문 열기 |

### 6.3 다크모드 및 반응형 설계

사이버 보안 SOC(Security Operations Center) 환경을 고려하여 다크모드를 기본으로 제공한다. 라이트모드 토글도 지원한다. 최소 해상도 1440x900 기준으로 설계하며, 대형 모니터(2560x1440+)에서는 지도 영역이 확장된다. 모바일 뷰는 P2 단계에서 지원하며, KPI 카드와 활동 피드 중심으로 간소화된 뷰를 제공한다.

### 6.4 상세 뷰 모달 구성

| 모달 유형 | 트리거 | 내용 |
|:---|:---|:---|
| 사건 상세 | 지도 버블 / 사건 목록 항목 클릭 | 사건 개요, 피해 국가/산업, 동기, 관련 보고서 목록, 타임라인 |
| 코드명 네트워크 | 그룹명 클릭 | Force-directed 그래프, 노드별 First/Last seen, 관련 보고서 수 |
| 보고서 상세 | 피드 항목 상세 버튼 | 보고서 메타데이터, 태그 목록, 동일 태그 보고서 추천 |
| 국가 프로필 | 지도 국가 더블클릭 | 해당 국가 전체 사건 목록, 연도별 추이, 주요 피해 산업 |

---

## 7. 개발 로드맵 (Development Roadmap)

| 단계 | 기간 | 주요 작업 | 산출물 |
|:---:|:---:|:---|:---|
| Phase 1 | 4주 | 데이터 ETL, DB 스키마, 기본 API 구축 | DB + API 엔드포인트 |
| Phase 2 | 6주 | 대시보드 UI(KPI, 지도, 차트, 피드) 구현 | 메인 대시보드 MVP |
| Phase 3 | 4주 | 교차분석(D-1~D-3), 네트워크 그래프, 심층 뷰 | 분석 기능 통합 |
| Phase 4 | 4주 | 고급 분석(E-1~E-4), 실시간 업데이트, 최적화 | 제품 정식 출시 |

### Phase 1 상세 (4주)

- Week 1-2: 엑셀 데이터 파싱 및 ETL 파이프라인 구축, Tags 정규화
- Week 3: PostgreSQL 스키마 구현, 초기 데이터 마이그레이션
- Week 4: API 엔드포인트 개발, 필터링/페이지네이션 로직

### Phase 2 상세 (6주)

- Week 1-2: 레이아웃 그리드, 상단바, KPI 카드 컴포넌트
- Week 3-4: D3.js 세계지도 구현, 버블 마커, 핫존, 인터랙션
- Week 5: 사이드 패널(도넛 차트, 바 차트), 하단 패널(트렌드, 그룹 목록)
- Week 6: 활동 피드, 글로벌 필터 연동, 다크모드 적용

### Phase 3 상세 (4주)

- Week 1-2: 코드명 네트워크 그래프(A-1), 활동 기간 타임라인(A-3)
- Week 3: 교차분석 D-1(상관분석), D-2(그룹-산업 매핑)
- Week 4: 상세 뷰 모달, 드릴다운 인터랙션, D-3(이벤트 반응 분석)

### Phase 4 상세 (4주)

- Week 1: 지정학적 연계(E-1), TTP 진화(E-2) 분석 뷰
- Week 2: 경제적 영향(E-3), 예측 모델링(E-4) 기초
- Week 3: 성능 최적화, 데이터 자동 업데이트 파이프라인
- Week 4: QA, 사용성 테스트, 배포

---

## 8. 논문 기반 핵심 인사이트 반영 (Key Insights from Paper)

본 설계서는 Lyu et al.(2025)의 연구 결과를 대시보드 설계에 직접적으로 반영하였다. 이하는 논문의 주요 Figure/Table과 대시보드 컴포넌트의 매핑이다.

| 논문 참조 | 내용 | 대시보드 반영 |
|:---:|:---|:---|
| Fig.2 | 연간 공개 보고서 수 | [E] 연간 트렌드 차트 |
| Fig.3 | 주요 기여 기관 | B-2 기여자 분석 기능 |
| Fig.5 | 코드명 네트워크 다이어그램 | A-1 네트워크 그래프 + 그룹 클릭 모달 |
| Fig.6 | 연간 사건 수 | [E] 트렌드 차트 Incidents 탭 |
| Fig.7 | 동기별 비율 | [D] 동기 분포 도넛 차트 |
| Fig.8 | 금전적 동기 연간 추이 | C-1 동기 변화 분석 기능 |
| Fig.9 | 타겟 섹터 비율 | [D] 타겟 섹터 바 차트 |
| Fig.10 | 금융/암호화폐 섹터 연간 추이 | C-2 피해 분포 분석 기능 세부 뷰 |
| Table 2 | 7개 그룹 160개 코드명 클러스터 | [E] 위협 행위자 그룹 목록 + A-1 네트워크 |
| Table 3 | 국가별 사건 빈도 | [C] 세계지도 버블 마커 크기 |

---

## 부록: 색상 코드 체계

| 용도 | 색상 | HEX 코드 | 적용 컴포넌트 |
|:---|:---|:---:|:---|
| Financial Gain | 빨강 | #E24B4A | 동기 도넛, 지도 버블, 피드 도트 |
| Espionage / Data Breach | 파랑 | #378ADD | 동기 도넛, 지도 버블, 피드 도트 |
| Destruction | 주황 | #EF9F27 | 동기 도넛, 지도 버블 |
| Supply Chain | 보라 | #7F77DD | 동기 도넛, 지도 버블 |
| Lazarus 그룹 | 빨강 | #E24B4A | 그룹 목록, 네트워크 노드 |
| Kimsuky 그룹 | 파랑 | #378ADD | 그룹 목록, 네트워크 노드 |
| BlueNoroff 그룹 | 주황 | #EF9F27 | 그룹 목록, 네트워크 노드 |
| ScarCruft 그룹 | 초록 | #1D9E75 | 그룹 목록, 네트워크 노드 |
| Andariel 그룹 | 보라 | #7F77DD | 그룹 목록, 네트워크 노드 |
| Konni 그룹 | 핑크 | #D4537E | 그룹 목록, 네트워크 노드 |
| Unclassified | 회색 | #888780 | 그룹 목록, 네트워크 노드 |

---

*End of Document*
