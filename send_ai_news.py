import os
import smtplib
import feedparser
import anthropic
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone

# ── 설정 ──────────────────────────────────────────────
GMAIL_USER     = os.environ["GMAIL_USER"]
GMAIL_APP_PW   = os.environ["GMAIL_APP_PW"]
TO_EMAIL       = os.environ["TO_EMAIL"]
ANTHROPIC_KEY  = os.environ["ANTHROPIC_API_KEY"]

RSS_FEEDS = [
    ("TechCrunch AI",   "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("VentureBeat AI",  "https://venturebeat.com/category/ai/feed/"),
    ("The Verge AI",    "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
    ("MIT Tech Review", "https://www.technologyreview.com/feed/"),
    ("Wired AI",        "https://www.wired.com/feed/category/artificial-intelligence/latest/rss"),
    ("AI News",         "https://artificialintelligence-news.com/feed/"),
]

KST = timezone(timedelta(hours=9))


# ── 뉴스 수집 ──────────────────────────────────────────
def fetch_news(hours: int = 12) -> list[dict]:
    cutoff   = datetime.now(tz=KST) - timedelta(hours=hours)
    articles = []

    for source_name, url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:
                pub = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    pub = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).astimezone(KST)

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

    return articles[:20]


# ── Claude 요약 (구조화된 JSON 형식 요청) ──────────────
def summarize_with_claude(articles: list[dict]) -> list[dict]:
    if not articles:
        return []

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
각 뉴스를 한국어로 요약해서 아래 JSON 형식으로만 응답하세요. 다른 텍스트는 절대 포함하지 마세요.

{{
  "trend_summary": "오늘의 AI 트렌드 종합 정리 (3문장)",
  "articles": [
    {{
      "number": 1,
      "title": "한국어 제목",
      "source": "출처명",
      "pub": "발행시간",
      "link": "URL",
      "summary": "2~3문장 핵심 요약",
      "category": "카테고리 (모델/서비스/연구/규제/산업 중 하나)"
    }}
  ]
}}

뉴스 목록:
{news_text}
"""

    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )

    import json
    text = response.content[0].text.strip()
    # JSON 블록만 추출
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


# ── 카테고리 색상 ──────────────────────────────────────
CATEGORY_COLORS = {
    "모델":  "#c0392b",
    "서비스": "#2980b9",
    "연구":  "#8e44ad",
    "규제":  "#e67e22",
    "산업":  "#27ae60",
}

def category_color(cat: str) -> str:
    return CATEGORY_COLORS.get(cat, "#b22222")


# ── 타임지 스타일 HTML 빌드 ────────────────────────────
def build_html(data: dict, article_count: int) -> str:
    today    = datetime.now(tz=KST).strftime("%B %d, %Y").upper()
    weekday  = datetime.now(tz=KST).strftime("%A").upper()
    trend    = data.get("trend_summary", "")
    articles = data.get("articles", [])

    # 헤드라인 (첫 번째 기사)
    headline_html = ""
    if articles:
        h = articles[0]
        col = category_color(h.get("category", ""))
        headline_html = f"""
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td style="padding:0 0 8px 0;">
              <span style="background:{col};color:#fff;font-size:10px;font-weight:700;
                           letter-spacing:1.5px;padding:3px 10px;text-transform:uppercase;">
                {h.get('category','NEWS')}
              </span>
            </td>
          </tr>
          <tr>
            <td>
              <a href="{h['link']}" style="text-decoration:none;color:#1a1a1a;">
                <div style="font-family:Georgia,serif;font-size:28px;font-weight:700;
                            line-height:1.25;color:#1a1a1a;margin:0 0 12px 0;">
                  {h['title']}
                </div>
              </a>
            </td>
          </tr>
          <tr>
            <td style="font-size:15px;color:#444;line-height:1.7;
                       font-family:Georgia,serif;padding:0 0 12px 0;">
              {h['summary']}
            </td>
          </tr>
          <tr>
            <td style="font-size:11px;color:#999;font-family:Arial,sans-serif;
                       border-top:1px solid #e0e0e0;padding:10px 0 0 0;">
              {h['source']} &nbsp;·&nbsp; {h['pub']}
            </td>
          </tr>
        </table>
        """

    # 나머지 기사 카드
    cards_html = ""
    for a in articles[1:]:
        col = category_color(a.get("category", ""))
        cards_html += f"""
        <table width="100%" cellpadding="0" cellspacing="0"
               style="border-bottom:1px solid #ececec;margin-bottom:20px;padding-bottom:20px;">
          <tr>
            <td width="4" style="background:{col};border-radius:2px;" valign="top">
              &nbsp;
            </td>
            <td width="16">&nbsp;</td>
            <td>
              <div style="margin-bottom:5px;">
                <span style="background:{col};color:#fff;font-size:9px;font-weight:700;
                             letter-spacing:1px;padding:2px 7px;text-transform:uppercase;
                             border-radius:2px;">
                  {a.get('category','NEWS')}
                </span>
                <span style="color:#999;font-size:11px;margin-left:8px;font-family:Arial,sans-serif;">
                  {a['source']} · {a['pub']}
                </span>
              </div>
              <a href="{a['link']}" style="text-decoration:none;color:#1a1a1a;">
                <div style="font-family:Georgia,serif;font-size:17px;font-weight:700;
                            line-height:1.35;color:#1a1a1a;margin:0 0 7px 0;">
                  {a['title']}
                </div>
              </a>
              <div style="font-size:13px;color:#555;line-height:1.65;
                          font-family:Arial,sans-serif;">
                {a['summary']}
              </div>
            </td>
          </tr>
        </table>
        """

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="margin:0;padding:0;background:#f2f2f0;">

<table width="100%" cellpadding="0" cellspacing="0" style="background:#f2f2f0;">
<tr><td align="center" style="padding:24px 16px;">

  <!-- 전체 컨테이너 -->
  <table width="660" cellpadding="0" cellspacing="0"
         style="max-width:660px;width:100%;background:#fff;
                box-shadow:0 1px 6px rgba(0,0,0,.12);">

    <!-- ① 최상단 날짜 바 -->
    <tr>
      <td style="background:#1a1a1a;padding:8px 32px;">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td style="color:#ccc;font-size:10px;font-family:Arial,sans-serif;
                       letter-spacing:1px;">{weekday}, {today}</td>
            <td align="right" style="color:#ccc;font-size:10px;
                font-family:Arial,sans-serif;letter-spacing:1px;">
              AI NEWS BRIEFING
            </td>
          </tr>
        </table>
      </td>
    </tr>

    <!-- ② 마스트헤드 -->
    <tr>
      <td style="background:#b22222;padding:24px 32px 20px;text-align:center;">
        <div style="font-family:Georgia,serif;font-size:52px;font-weight:700;
                    color:#fff;letter-spacing:-1px;line-height:1;">AI TIMES</div>
        <div style="color:rgba(255,255,255,.75);font-size:11px;font-family:Arial,sans-serif;
                    letter-spacing:2px;margin-top:4px;">
          ARTIFICIAL INTELLIGENCE · DAILY BRIEFING
        </div>
        <div style="border-top:1px solid rgba(255,255,255,.3);margin-top:14px;
                    padding-top:10px;color:rgba(255,255,255,.85);font-size:12px;
                    font-family:Arial,sans-serif;">
          지난 12시간 뉴스 {article_count}건 수집 &nbsp;|&nbsp; 매일 오전 8시 KST 발송
        </div>
      </td>
    </tr>

    <!-- ③ 오늘의 트렌드 요약 -->
    <tr>
      <td style="background:#fdf6e3;border-top:3px solid #b22222;
                 border-bottom:1px solid #e0d8c0;padding:18px 32px;">
        <div style="font-family:Arial,sans-serif;font-size:10px;font-weight:700;
                    letter-spacing:2px;color:#b22222;margin-bottom:8px;">
          TODAY'S TREND
        </div>
        <div style="font-family:Georgia,serif;font-size:14px;color:#333;line-height:1.75;">
          {trend}
        </div>
      </td>
    </tr>

    <!-- ④ 헤드라인 기사 -->
    <tr>
      <td style="padding:28px 32px 0;">
        <div style="font-family:Arial,sans-serif;font-size:10px;font-weight:700;
                    letter-spacing:2px;color:#b22222;border-bottom:2px solid #b22222;
                    padding-bottom:6px;margin-bottom:20px;">
          HEADLINE
        </div>
        {headline_html}
      </td>
    </tr>

    <!-- ⑤ 구분선 -->
    <tr>
      <td style="padding:16px 32px;">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td style="border-top:1px solid #ccc;"></td>
            <td width="12"></td>
            <td style="font-family:Arial,sans-serif;font-size:10px;color:#999;
                       letter-spacing:2px;white-space:nowrap;">MORE STORIES</td>
            <td width="12"></td>
            <td style="border-top:1px solid #ccc;"></td>
          </tr>
        </table>
      </td>
    </tr>

    <!-- ⑥ 나머지 기사 -->
    <tr>
      <td style="padding:0 32px 24px;">
        {cards_html}
      </td>
    </tr>

    <!-- ⑦ 푸터 -->
    <tr>
      <td style="background:#1a1a1a;padding:18px 32px;">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td style="font-family:Georgia,serif;font-size:16px;
                       color:#b22222;font-weight:700;">AI TIMES</td>
            <td align="right" style="font-family:Arial,sans-serif;font-size:10px;
                color:#666;letter-spacing:1px;">
              POWERED BY CLAUDE AI · GITHUB ACTIONS
            </td>
          </tr>
          <tr>
            <td colspan="2" style="padding-top:8px;font-family:Arial,sans-serif;
                font-size:10px;color:#555;">
              © {datetime.now(tz=KST).year} AI Times Daily · 자동 발송 뉴스레터
            </td>
          </tr>
        </table>
      </td>
    </tr>

  </table>
</td></tr>
</table>

</body>
</html>"""
    return html


# ── Gmail 발송 ─────────────────────────────────────────
def send_email(data: dict, article_count: int):
    today   = datetime.now(tz=KST).strftime("%Y년 %m월 %d일")
    subject = f"🗞️ AI Times Daily | {today} 아침 브리핑"

    articles = data.get("articles", [])
    plain    = data.get("trend_summary", "") + "\n\n"
    for a in articles:
        plain += f"[{a.get('category','')}] {a['title']}\n{a['summary']}\n{a['link']}\n\n"

    html = build_html(data, article_count)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_USER
    msg["To"]      = TO_EMAIL
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

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
    data = summarize_with_claude(articles)

    print("📧 Gmail 발송 중...")
    send_email(data, len(articles))
