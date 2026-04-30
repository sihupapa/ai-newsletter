# 🤖 AI 뉴스 브리핑 자동 발송

매일 아침 8시(KST), 지난 12시간의 AI 뉴스를 Claude가 요약해서 Gmail로 발송합니다.

## 📁 파일 구조

```
.
├── .github/
│   └── workflows/
│       └── ai_news.yml       # GitHub Actions 스케줄러
├── send_ai_news.py            # 메인 스크립트
├── requirements.txt           # Python 패키지
└── README.md
```

## 🚀 설정 방법

### 1단계 — Gmail 앱 비밀번호 발급

1. Google 계정 → **보안** → **2단계 인증** 활성화
2. 보안 → **앱 비밀번호** 검색
3. 앱: `메일`, 기기: `Windows 컴퓨터` 선택 → **생성**
4. 16자리 비밀번호 복사해두기 (예: `abcd efgh ijkl mnop`)

### 2단계 — GitHub 저장소 만들기

1. GitHub → **New repository** → 이름: `ai-news-briefing`
2. **Private** 선택 (API 키 보호)
3. 이 폴더의 파일들을 전부 업로드

### 3단계 — GitHub Secrets 등록

저장소 → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

| Secret 이름 | 값 예시 | 설명 |
|---|---|---|
| `GMAIL_USER` | `yourname@gmail.com` | 발신 Gmail |
| `GMAIL_APP_PW` | `abcdefghijklmnop` | 앱 비밀번호 (공백 제거) |
| `TO_EMAIL` | `yourname@gmail.com` | 수신 Gmail (같아도 됨) |
| `ANTHROPIC_API_KEY` | `sk-ant-...` | Anthropic API 키 |

### 4단계 — 테스트 실행

1. 저장소 → **Actions** 탭
2. `AI 뉴스 브리핑 매일 아침 8시` 워크플로우 클릭
3. **Run workflow** 버튼 → 수동 실행
4. 초록색 체크 확인 → Gmail 수신 확인

## ⏰ 스케줄

- 매일 **오전 8시 KST** 자동 실행
- GitHub Actions cron: `0 23 * * *` (UTC 기준)

## 📰 뉴스 출처

| 출처 | 링크 |
|------|------|
| TechCrunch AI | techcrunch.com |
| VentureBeat AI | venturebeat.com |
| The Verge AI | theverge.com |
| MIT Tech Review | technologyreview.com |
| Wired AI | wired.com |
| AI News | artificialintelligence-news.com |

## 💰 비용

| 항목 | 비용 |
|------|------|
| GitHub Actions | 무료 (월 2,000분) |
| RSS 뉴스 수집 | 무료 |
| Claude API | 약 $0.01~0.03 / 1회 |
| Gmail 발송 | 무료 |
