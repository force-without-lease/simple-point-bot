# Simple Point Bot

채팅과 통화로 경험치를 쌓고, 레벨이 오르면 포인트와 보상 역할을 받는 디스코드 봇입니다.

## 기능

- 채팅·통화 경험치와 MEE6 방식의 레벨 계산
- 레벨업 보상 포인트와 멤버 간 송금
- 레벨별 보상 역할 지급
- 랭크 카드 이미지와 레벨·포인트 순위표
- 서버별 알림, 배율, 경험치 제외 대상 설정

## 요구 사항

- Python 3.10 이상
- 디스코드 봇 토큰 ([Discord Developer Portal](https://discord.com/developers/applications)에서 발급)

## 설치

```sh
git clone https://github.com/force-without-lease/simple-point-bot.git
cd simple-point-bot
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 실행

봇은 환경 변수에서 설정을 읽습니다.

| 변수 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `DISCORD_TOKEN` | 예 | | 봇 토큰 |
| `DB_PATH` | 아니요 | `points.db` | SQLite 데이터베이스 파일 경로 |

```sh
DISCORD_TOKEN=봇토큰 .venv/bin/python bot.py
```

`.env` 파일에 토큰을 적어 두었다면 다음처럼 실행할 수 있습니다.

```sh
set -a; . ./.env; set +a
.venv/bin/python bot.py
```

## 봇 초대 권한

- 역할 관리, 메시지 보내기, 링크 첨부, 파일 첨부
- 보상 역할을 주려면 서버 설정의 역할 목록에서 봇 역할이 보상 역할보다 위에 있어야 합니다.
- 특수 권한(Privileged Gateway Intents)은 켜지 않아도 됩니다.

## 경험치 규칙

| 항목 | 내용 |
|---|---|
| 채팅 | 메시지마다 15~25, 60초에 한 번 |
| 통화 | 1분마다 지급, 헤드셋을 켠 사람이 채널에 2명 이상일 때 |
| 제외 | 봇, 웹후크, 잠수 채널, `/설정 경험치제외`로 지정한 채널과 카테고리와 역할 |
| 레벨 공식 | 레벨 L에서 L+1까지 5L² + 50L + 100 (MEE6와 같음) |
| 포인트 | 레벨 N에 도달하면 N × 레벨당포인트 |

## 명령어

| 명령어 | 설명 |
|---|---|
| `/랭크 [멤버]` | 레벨 카드 이미지 |
| `/순위 [기준]` | 레벨 순위표나 포인트 순위표 |
| `/포인트 [멤버]` | 포인트 확인 |
| `/송금 멤버 금액` | 다른 멤버에게 포인트 보내기 |
| `/설정 보기` | 현재 설정 |
| `/설정 알림` | 레벨업 알림을 보낼 곳과 문구 |
| `/설정 수치` | 경험치 배율, 통화 경험치, 레벨당 포인트, 보상 역할 누적 여부 |
| `/설정 보상역할 레벨 [역할]` | 레벨 보상 역할 지정, 역할을 비워 두면 제거 |
| `/설정 경험치제외 [채널] [역할]` | 경험치 제외 대상 지정, 다시 지정하면 해제 |
| `/관리 경험치`, `/관리 포인트` | 지급, 차감, 설정 |
| `/관리 초기화 [멤버]` | 멤버 한 명이나 서버 전체 초기화 |

`/설정`과 `/관리`는 서버 관리 권한이 있는 사람에게만 보입니다.

## 테스트

```sh
.venv/bin/python test_bot.py
```

## 라이선스

코드는 [MIT License](LICENSE)를 따릅니다.

랭크 카드는 `assets/`의 [Pretendard](https://github.com/orioncactus/pretendard) 글꼴을 씁니다. 글꼴 라이선스는 SIL Open Font License이며 `assets/Pretendard-LICENSE.txt`에 있습니다.
