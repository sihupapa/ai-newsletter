import os
import smtplib
import feedparser
import anthropic
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone

# ── 설정 ──────────────────────────────────────────────
GMAIL_USER     = os.environ["GMAIL_USER"]       # 발신 Gmail 주소
GMAIL_APP_PW   = os.environ["GMAIL_APP_PW"]     # Gmail 앱 비밀번호
TO_EMAIL       = os.environ["TO_EMAIL"]         # 수신 Gmail 주소
ANTHROPIC_KEY  = os.environ["ANTHROPIC_API_KEY"]

# AI 뉴스 RSS 피드 목록 (무료, 키 불필요)
RSS_FEEDS = [
    ("TechCrunch AI",     "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("VentureBeat AI",    "https://venturebeat.com/category/ai/feed/"),
    ("The Verge AI",      "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
    ("MIT Tech Review",   "https://www.technologyreview.com/feed/"),
    ("Wired AI",          "https://www.wired.com/feed/category/artificial-intelligence/latest/rss"),
    ("AI News",           "https://artificialintelligence-news.com/feed/"),
]

KST = timezone(timedelta(hours=9))

# ── 뉴스 수집 ──────────────────────────────────────────
def fetch_news(hours: int = 12) -> list[dict]:
    """지난 N시간 이내 AI 뉴스 수집"""
    cutoff = datetime.now(tz=KST) - timedelta(hours=hours)
    articles = []

    for source_name, url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:  # 피드당 최대 10개 확인
                # 발행 시간 파싱
                pub = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    pub = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).astimezone(KST)

                # 시간 필터: 지난 12시간 이내만
                if pub and pub < cutoff:
                    continue

                title   = entry.get("title", "제목 없음").strip()
                link    = entry.get("link", "")
                summary = entry.get("summary", entry.get("description", ""))[:500]

                articles.append({
                    "source":  source_name,
                    "title":   title,
                    "link":    link,
                    "summary": summary,
                    "pub":     pub.strftime("%Y-%m-%d %H:%M KST") if pub else "시간 미상",
                })
        except Exception as e:
            print(f"[WARN] {source_name} 피드 실패: {e}")

    # 최신순 정렬, 최대 20개
    return articles[:20]


# ── Claude 요약 ────────────────────────────────────────
def summarize_with_claude(articles: list[dict]) -> str:
    """Claude API로 뉴스 요약"""
    if not articles:
        return "오늘 수집된 AI 뉴스가 없습니다."

    news_text = ""
    for i, a in enumerate(articles, 1):
        news_text += f"""
[{i}] {a['title']}
출처: {a['source']} | 시간: {a['pub']}
링크: {a['link']}
내용: {a['summary']}
"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    today  = datetime.now(tz=KST).strftime("%Y년 %m월 %d일")

    prompt = f"""
다음은 {today} 아침 기준 지난 12시간 동안의 AI 관련 뉴스입니다.
한국어로 읽기 좋게 요약해 주세요.

형식:
- 각 뉴스는 번호와 함께 **굵은 제목**으로 시작
- 2~3문장으로 핵심만 요약
- 마지막에 🔗 출처와 링크 표시
- 마지막에 오늘의 AI 트렌드를 2~3줄로 종합 정리

뉴스 목록:
{news_text}
"""

    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


# ── Gmail 발송 ─────────────────────────────────────────
def send_email(summary: str, article_count: int):
    today = datetime.now(tz=KST).strftime("%Y년 %m월 %d일")
    subject = f"🤖 AI 뉴스 브리핑 | {today} 아침 8시"

    # HTML 본문 (줄바꿈 → <br> 변환)
    html_summary = summary.replace("\n", "<br>")

    html_body = f"""
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<style>
  body      {{ font-family: 'Apple SD Gothic Neo', sans-serif; background: #f5f5f5; margin: 0; padding: 20px; }}
  .container{{ max-width: 680px; margin: auto; background: #fff; border-radius: 12px;
               box-shadow: 0 2px 12px rgba(0,0,0,.08); overflow: hidden; }}
  .header   {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
               color: #fff; padding: 32px 40px; }}
  .header h1{{ margin: 0; font-size: 22px; }}
  .header p {{ margin: 6px 0 0; opacity: .85; font-size: 14px; }}
  .body     {{ padding: 32px 40px; color: #333; line-height: 1.8; font-size: 15px; }}
  .footer   {{ background: #f0f0f0; text-align: center; padding: 16px;
               font-size: 12px; color: #999; }}
  a         {{ color: #667eea; }}
</style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>🤖 AI 뉴스 브리핑</h1>
      <p>{today} · 지난 12시간 뉴스 {article_count}건 수집</p>
    </div>
    <div class="body">
      {html_summary}
    </div>
    <div class="footer">
      자동 발송 · GitHub Actions + Claude AI · 매일 오전 8시 KST
    </div>
  </div>
</body>
</html>
"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_USER
    msg["To"]      = TO_EMAIL
    msg.attach(MIMEText(summary, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PW)
        server.sendmail(GMAIL_USER, TO_EMAIL, msg.as_string())

    print(f"✅ 이메일 발송 완료 → {TO_EMAIL}")


# ── 메인 ───────────────────────────────────────────────
if __name__ == "__main__":
    print("📡 AI 뉴스 수집 중...")
    articles = fetch_news(hours=12)
    print(f"   {len(articles)}건 수집 완료")

    print("🧠 Claude로 요약 중...")
    summary = summarize_with_claude(articles)

    print("📧 Gmail 발송 중...")
    send_email(summary, len(articles))
