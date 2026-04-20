# CS2 HEATMAP

본 프로젝트는 CS2 리플레이(`.dem`) 파일을 분석하여 시각화된 전술 데이터를 제공하는 백엔드 시스템입니다. 핵심은 로우(Raw) 데이터를 사용자에게 유의미한 **팀 정보, 선수 통계, 히트맵**으로 가공하는 과정에 있습니다.

---


## 1. 프로젝트 구조 (Project Structure)

```text
cs2-heatmap/
├── main.py              # 백엔드 핵심 로직 (API 설계, 데이터 가공, 파싱)
├── templates/
│   └── index.html       # 분석 결과를 보여주는 메인 대시보드 UI
├── data/
│   ├── static/          # UI 디자인을 위한 CSS 및 JS 파일
│   ├── maps/            # 히트맵 배경으로 쓰이는 맵 오버뷰 이미지
│   └── temp/            # 업로드된 데모 파일이 잠시 머무는 임시 폴더
├── requirements.txt     # 프로젝트 구동에 필요한 라이브러리 목록
└── README.md            # 프로젝트 기술 문서
```

---

## 2. 사용 기술 및 라이브러리 (Tech Stack)

### Backend
- **Python / FastAPI**: 빠르고 효율적인 API 서버 구축.
- **Polars**: 대용량 데모 데이터를 메모리 효율적으로 처리하기 위한 데이터프레임 라이브러리.

### Parsing Tools
- **awpy (2.0)**: CS2 데이터 구조화 및 좌표 정규화의 핵심 도구.
- **demoparser2**: 팀 메타데이터 및 세부 이벤트 쿼리를 위한 고성능 Rust 기반 파서.

### Frontend
- **Vanilla JS / HTML5 Canvas**: 외부 라이브러리 없이 순수 자바스크립트와 캔버스를 이용해 히트맵 KDE(Kernel Density Estimation)와 통계 테이블 렌더링.

--- 

## 3. 상세 동작 시나리오 (Detailed Sequence of Operations)

데이터가 사용자 브라우저에서 서버를 거쳐 다시 시각화되기까지의 정밀한 흐름은 다음과 같습니다.

### 1단계: 프론트엔드 요청 (Frontend Request)
- **이벤트 발생**: 사용자가 웹 대시보드 화면에 `.dem` 파일을 드래그 앤 드롭합니다.
- **HTTP 통신**: `static/js/app.js`에서 파일을 `FormData` 객체에 담아 `POST /analyze` 엔드포인트로 비동기 `fetch` 요청을 보냅니다.
- **상태 표시**: 브라우저 UI는 분석 중임을 알리는 스피너(Spinner)를 활성화합니다.

### 2단계: 백엔드 파일 수신 및 저장 (File Ingestion)
- **FastAPI 엔트리**: `main.py`의 `@app.post("/analyze")` 함수가 `UploadFile` 객체로 데모 파일을 수신합니다.
- **임시 물리 저장**: `uuid`를 이용해 고유 파일명을 생성하고 `data/temp/temp_UUID.dem` 경로에 바이너리 형태로 저장합니다. (이는 파서가 디스크 경로를 직접 참조해야 하기 때문입니다.)

### 3단계: 파이썬 엔진 데이터 처리 (Backend Processing)
- **파서 초기화**: `awpy.Demo` 객체가 생성되고 `dem.parse()`가 호출되어 라운드, 킬, 데미지 데이터를 메모리상(Polars DataFrame)에 로드합니다.
- **팀명 및 스코어 보정**: `demoparser2` 엔진이 실행되어 `round_end` 이벤트를 쿼리합니다. 파이썬 루프를 돌며 각 라운드별 클랜 이름을 `round_team_map` 딕셔너리에 매핑합니다.
- **좌표 변환 알고리즘**: 추출된 모든 3D 좌표(x, y)는 `game_to_pct()` 함수를 거쳐 맵 이미지 비율에 맞는 0~100 사이의 상대 좌표로 변환됩니다.
- **통계 집계**: 파이썬의 `player_stats` 딕셔너리에 SteamID별로 킬, 데스, 어시스트, 데미지 데이터를 누적 집계하여 최종 `players_list`를 생성합니다.

### 4단계: 응답 및 프론트엔드 렌더링 (Response & Rendering)
- **JSON 반환**: 모든 가공이 완료되면 `JSONResponse`를 통해 맵 정보, 스코어, 통계, 히트맵 좌표를 포함한 JSON 데이터를 브라우저로 전송합니다.
- **JS 데이터 처리**: `app.js`는 수신된 JSON을 파싱하여 `renderDashboard(data)` 함수를 실행합니다.
- **시각화**: 
    - **통계표**: HTML `<table>` 요소 내에 `tr`, `td`를 동적으로 생성하여 선수 명단을 채웁니다.
    - **히트맵**: HTML5 Canvas API를 사용하여 수천 개의 좌표 지점에 커널 밀도 추정(KDE) 알고리즘을 적용, 열지도를 그립니다.

### 5단계: 자원 정리 (Cleanup)
- **자동 삭제**: 파이썬의 `finally` 구문 내에서 `del dem`, `del raw_parser`로 객체 참조를 해제한 후, `os.remove()` 명령을 통해 `data/temp/`에 저장했던 임시 파일을 즉시 삭제합니다.


---
## 4. 데이터 파싱 및 가공 프로세스

### 데이터 추출 (Parsing)
`.dem` 파일을 입력받으면 두 가지 파서를 통해 서로 다른 영역의 데이터를 추출합니다.

- **`awpy`**: 게임의 전체적인 흐름(라운드 정보, 킬 로그, 데미지 로그)을 정형화된 데이터프레임 형태로 제공합니다.
- **`demoparser2`**: 데모 파일의 원시 네트워크 메시지에 접근하여, `awpy`가 놓칠 수 있는 실제 팀 이름(Clan Name)과 정밀한 이벤트 데이터를 보완합니다.

### 데이터 활용 방식 (Data Usage)

#### ① 팀명 및 스코어 (Team & Score)
공식 데모 파일은 팀 이름이 `CT` 혹은 `TERRORIST`로만 표기되는 경우가 많습니다. 이를 해결하기 위해 다음과 같이 처리했습니다.
- **사용 데이터**: `demoparser2`의 `round_end` 이벤트 데이터
- **활용 방법**: 
    - 각 라운드가 끝날 때의 `ct_team_clan_name`과 `t_team_clan_name` 필드를 추출합니다.
    - 이 데이터를 매핑하여 화면에 'Team Vitality 13 : 6 Team Falcons'와 같이 실제 팀명이 표시되도록 구현했습니다.
    - 사이드 스왑 시에도 팀명이 섞이지 않도록 라운드별 진영 정보를 추적합니다.

#### ② 히트맵 포인트 (Heatmap Points)
좌표 데이터를 대시보드의 맵 이미지 위에 퍼센트(%) 단위로 배치하기 위해 가공합니다.
- **사용 데이터**: 
    - `kills`: `attacker_x`, `attacker_y` (킬 위치) / `victim_x`, `victim_y` (데스 위치)
    - `shots`: `player_x`, `player_y` (사격 위치)
    - `grenades`: `x`, `y`, `entity_id`, `grenade_type` (투척물 폭발 위치)
- **활용 방법**: 
    - 게임 내 좌표를 `game_to_pct` 함수를 통해 0~100 사이의 값으로 변환합니다.
    - 투척물은 수많은 이동 경로 데이터 중 `entity_id`별로 가장 마지막 위치만 남겨서 **'터진 지점'**만 정확히 표시합니다.

#### ③ 선수 통계 (Player Stats)
개별 선수의 퍼포먼스를 수치화합니다.
- **사용 데이터**: `kills_df` (K, D, A), `damage_df` (Damage)
- **활용 방법**: 
    - 각 선수의 SteamID를 키값으로 하여 킬, 데스, 어시스트를 합산합니다.
    - 총 데미지를 전체 라운드 수로 나누어 **ADR**을 구하고, 이를 기반으로 선수의 영향력인 **Rating** 지표를 산출합니다.

---

