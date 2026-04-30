import io
import os
import smtplib
import feedparser
import requests
from google import genai
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone
from PIL import Image, ImageDraw, ImageFont

# ── 설정 ──────────────────────────────────────────────
GMAIL_USER      = os.environ["GMAIL_USER"]
GMAIL_APP_PW    = os.environ["GMAIL_APP_PW"]
TO_EMAIL        = os.environ["TO_EMAIL"]
GEMINI_KEY      = os.environ["GEMINI_API_KEY"]
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_CHANNEL   = os.environ["SLACK_CHANNEL"]

RSS_FEEDS = [
    # 주요 AI 언론 (빅이슈 파악용)
    ("TechCrunch AI",   "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("VentureBeat AI",  "https://venturebeat.com/category/ai/feed/"),
    ("The Verge AI",    "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
    ("MIT Tech Review", "https://www.technologyreview.com/feed/"),
    ("Wired AI",        "https://www.wired.com/feed/category/artificial-intelligence/latest/rss"),
    ("AI News",         "https://artificialintelligence-news.com/feed/"),
    ("Ars Technica AI", "https://feeds.arstechnica.com/arstechnica/index"),
    # AI 기업 공식 블로그 (신규기능 파악용)
    ("Google AI Blog",  "https://blog.google/technology/ai/rss/"),
    ("DeepMind",        "https://deepmind.google/discover/blog/rss.xml"),
    ("Hugging Face",    "https://huggingface.co/blog/feed.xml"),
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

    return articles[:30]


# ── Gemini 요약 (구조화된 JSON 형식 요청) ──────────────
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

    client = genai.Client(api_key=GEMINI_KEY)
    today = datetime.now(tz=KST).strftime("%Y년 %m월 %d일")

    prompt = f"""
다음은 {today} 아침 기준 지난 12시간 동안의 AI 관련 뉴스입니다.
한국어로 요약하되 아래 JSON 형식으로만 응답하세요. 다른 텍스트는 절대 포함하지 마세요.

{{
  "trend_summary": "오늘의 AI 트렌드 종합 정리 (3문장)",
  "big_issues": [
    {{
      "rank": 1,
      "title": "한국어 제목",
      "source": "출처명",
      "pub": "발행시간",
      "link": "URL",
      "summary": "2~3문장 핵심 요약 (왜 많은 언론이 주목하는지 포함)"
    }}
  ],
  "new_features": [
    {{
      "company": "회사명 (예: OpenAI, Google, Anthropic, Meta 등)",
      "title": "한국어 제목",
      "source": "출처명",
      "pub": "발행시간",
      "link": "URL",
      "summary": "2~3문장 신규기능 핵심 요약"
    }}
  ]
}}

규칙:
- big_issues: 여러 언론에서 동시에 다루는 AI 빅이슈 상위 10개 선정
- new_features: Claude Code, OpenAI, Google Gemini, Meta AI 등 주요 AI 서비스/툴의 신규 기능 발표 기사 최대 10개 선정 (없으면 빈 배열)

뉴스 목록:
{news_text}
"""

    import json, time
    models = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash-lite"]
    response = None
    for model in models:
        for attempt in range(2):
            try:
                response = client.models.generate_content(model=model, contents=prompt)
                print(f"✅ 모델 사용: {model}")
                break
            except Exception as e:
                print(f"[WARN] {model} 시도 {attempt+1}/2 실패: {e}")
                time.sleep(10)
        if response:
            break
    if not response:
        raise RuntimeError("모든 Gemini 모델 호출 실패")
    text = response.text.strip()
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
    today       = datetime.now(tz=KST).strftime("%B %d, %Y").upper()
    weekday     = datetime.now(tz=KST).strftime("%A").upper()
    trend       = data.get("trend_summary", "")
    big_issues  = data.get("big_issues", [])
    new_features= data.get("new_features", [])

    # ── 빅이슈 TOP 3 헤드라인 (1위) + 카드 (2·3위)
    big_headline_html = ""
    if big_issues:
        h = big_issues[0]
        big_headline_html = f"""
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td style="padding:0 0 8px 0;">
              <span style="background:#b22222;color:#fff;font-size:11px;font-weight:700;
                           letter-spacing:1.5px;padding:4px 12px;">🔥 TOP 1</span>
            </td>
          </tr>
          <tr>
            <td>
              <a href="{h['link']}" style="text-decoration:none;color:#1a1a1a;">
                <div style="font-family:Georgia,serif;font-size:26px;font-weight:700;
                            line-height:1.25;color:#1a1a1a;margin:0 0 12px 0;">
                  {h['title']}
                </div>
              </a>
            </td>
          </tr>
          <tr>
            <td style="font-size:14px;color:#444;line-height:1.75;
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
        </table>"""

    big_cards_html = ""
    for a in big_issues[1:]:
        rank = a.get("rank", "")
        big_cards_html += f"""
        <table width="100%" cellpadding="0" cellspacing="0"
               style="border-bottom:1px solid #ececec;margin-bottom:20px;padding-bottom:20px;">
          <tr>
            <td width="4" style="background:#b22222;border-radius:2px;" valign="top">&nbsp;</td>
            <td width="16">&nbsp;</td>
            <td>
              <div style="margin-bottom:5px;">
                <span style="background:#b22222;color:#fff;font-size:9px;font-weight:700;
                             letter-spacing:1px;padding:2px 8px;border-radius:2px;">
                  🔥 TOP {rank}
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
              <div style="font-size:13px;color:#555;line-height:1.65;font-family:Arial,sans-serif;">
                {a['summary']}
              </div>
            </td>
          </tr>
        </table>"""

    # ── 신규기능 카드
    feature_cards_html = ""
    for a in new_features:
        company = a.get("company", "AI")
        feature_cards_html += f"""
        <table width="100%" cellpadding="0" cellspacing="0"
               style="border-bottom:1px solid #ececec;margin-bottom:20px;padding-bottom:20px;">
          <tr>
            <td width="4" style="background:#2980b9;border-radius:2px;" valign="top">&nbsp;</td>
            <td width="16">&nbsp;</td>
            <td>
              <div style="margin-bottom:5px;">
                <span style="background:#2980b9;color:#fff;font-size:9px;font-weight:700;
                             letter-spacing:1px;padding:2px 8px;border-radius:2px;">
                  🚀 {company}
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
              <div style="font-size:13px;color:#555;line-height:1.65;font-family:Arial,sans-serif;">
                {a['summary']}
              </div>
            </td>
          </tr>
        </table>"""

    features_section = ""
    if feature_cards_html:
        features_section = f"""
    <!-- 구분선: 신규기능 -->
    <tr>
      <td style="padding:8px 32px 0;">
        <div style="font-family:Arial,sans-serif;font-size:10px;font-weight:700;
                    letter-spacing:2px;color:#2980b9;border-bottom:2px solid #2980b9;
                    padding-bottom:6px;margin-bottom:20px;">
          🚀 최신 AI 신규기능
        </div>
      </td>
    </tr>
    <tr>
      <td style="padding:0 32px 24px;">
        {feature_cards_html}
      </td>
    </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="margin:0;padding:0;background:#f2f2f0;">

<table width="100%" cellpadding="0" cellspacing="0" style="background:#f2f2f0;">
<tr><td align="center" style="padding:24px 16px;">

  <table width="660" cellpadding="0" cellspacing="0"
         style="max-width:660px;width:100%;background:#fff;
                box-shadow:0 1px 6px rgba(0,0,0,.12);">

    <!-- ① 날짜 바 -->
    <tr>
      <td style="background:#1a1a1a;padding:8px 32px;">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td style="color:#ccc;font-size:10px;font-family:Arial,sans-serif;
                       letter-spacing:1px;">{weekday}, {today}</td>
            <td align="right" style="color:#ccc;font-size:10px;
                font-family:Arial,sans-serif;letter-spacing:1px;">AI NEWS BRIEFING</td>
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

    <!-- ③ 트렌드 요약 -->
    <tr>
      <td style="background:#fdf6e3;border-top:3px solid #b22222;
                 border-bottom:1px solid #e0d8c0;padding:18px 32px;">
        <div style="font-family:Arial,sans-serif;font-size:10px;font-weight:700;
                    letter-spacing:2px;color:#b22222;margin-bottom:8px;">TODAY'S TREND</div>
        <div style="font-family:Georgia,serif;font-size:14px;color:#333;line-height:1.75;">
          {trend}
        </div>
      </td>
    </tr>

    <!-- ④ 빅이슈 TOP 3 -->
    <tr>
      <td style="padding:28px 32px 0;">
        <div style="font-family:Arial,sans-serif;font-size:10px;font-weight:700;
                    letter-spacing:2px;color:#b22222;border-bottom:2px solid #b22222;
                    padding-bottom:6px;margin-bottom:20px;">
          🔥 AI 빅이슈 TOP 10
        </div>
        {big_headline_html}
      </td>
    </tr>
    <tr>
      <td style="padding:16px 32px 0;">
        {big_cards_html}
      </td>
    </tr>

    {features_section}

    <!-- ⑦ 푸터 -->
    <tr>
      <td style="background:#1a1a1a;padding:18px 32px;">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td style="font-family:Georgia,serif;font-size:16px;
                       color:#b22222;font-weight:700;">AI TIMES</td>
            <td align="right" style="font-family:Arial,sans-serif;font-size:10px;
                color:#666;letter-spacing:1px;">
              POWERED BY Daeho AI · feat.Claude
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


# ── Slack 이미지 생성 ──────────────────────────────────
def create_news_image(data: dict, article_count: int) -> bytes:
    today      = datetime.now(tz=KST).strftime("%Y년 %m월 %d일")
    big_issues = data.get("big_issues", [])
    trend      = data.get("trend_summary", "")

    items = [{"title": a.get("title",""), "source": a.get("source",""),
              "link": a.get("link",""),   "summary": a.get("summary","")}
             for a in big_issues]

    W       = 900
    HEADER  = 100
    ITEM_H  = 100
    TREND_H = 120
    FOOTER  = 50
    H = HEADER + ITEM_H * max(len(items), 1) + TREND_H + FOOTER + 20

    img  = Image.new("RGB", (W, H), "#0f0f1a")
    draw = ImageDraw.Draw(img)

    def font(size, bold=False):
        candidates = (
            ["/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
             "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
            if bold else
            ["/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
             "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
        )
        for p in candidates:
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
        return ImageFont.load_default()

    f_tiny = font(12); f_sm = font(14); f_md = font(15)
    f_lg   = font(18, bold=True); f_xl = font(26, bold=True)

    for y in range(HEADER):
        r = int(178 + (120-178)*y/HEADER)
        g = int(34  + (20 -34 )*y/HEADER)
        b = int(34  + (20 -34 )*y/HEADER)
        draw.line([(0,y),(W,y)], fill=(r,g,b))

    draw.text((28, 16), "AI TIMES  |  빅이슈 TOP 10", font=f_xl, fill="#ffffff")
    draw.text((30, 60), f"{today}  |  지난 12시간 {article_count}건 수집", font=f_sm, fill="#ffcccc")

    accents = ["#e74c3c","#e67e22","#f1c40f","#2ecc71","#3498db",
               "#9b59b6","#1abc9c","#e91e63","#ff5722","#607d8b"]

    for i, item in enumerate(items):
        y0  = HEADER + 10 + i * ITEM_H
        acc = accents[i % len(accents)]
        ar, ag, ab = int(acc[1:3],16), int(acc[3:5],16), int(acc[5:7],16)

        draw.rounded_rectangle([(16,y0),(W-16,y0+ITEM_H-8)], radius=8, fill="#1a1a2e")
        draw.rounded_rectangle([(16,y0),(22,  y0+ITEM_H-8)], radius=4, fill=(ar,ag,ab))

        draw.ellipse([(30,y0+10),(50,y0+30)], fill=(ar,ag,ab))
        draw.text((35,y0+12), str(i+1), font=f_sm, fill="#ffffff")

        title = (item.get("title","") + " " * 40)[:42]
        draw.text((60,y0+10), title, font=f_lg, fill="#e8e8ff")

        src_txt = f"  {item.get('source','')}  |  {item.get('link','')[:45]}..."
        draw.text((60,y0+36), src_txt, font=f_tiny, fill="#7777aa")

        s = item.get("summary","")
        draw.text((60,y0+56), s[:85], font=f_md, fill="#ccccee")
        if len(s) > 85:
            draw.text((60,y0+76), s[85:160], font=f_md, fill="#ccccee")

    ty = HEADER + 10 + len(items) * ITEM_H + 8
    draw.rounded_rectangle([(16,ty),(W-16,ty+TREND_H-8)], radius=8, fill="#1e1e3f")
    draw.text((30,ty+12), "  TODAY'S AI TREND", font=f_lg, fill="#f0c040")
    t = trend
    draw.text((30,ty+42), t[:90],  font=f_md, fill="#ddddff")
    if len(t) > 90:
        draw.text((30,ty+64), t[90:175], font=f_md, fill="#ddddff")

    fy = ty + TREND_H + 4
    draw.text((30,fy+14), "Powered by Daeho AI · feat.Claude  |  Every day 08:00 KST",
              font=f_tiny, fill="#444466")

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ── Slack 이미지 발송 ──────────────────────────────────
def send_slack_image(image_bytes: bytes, article_count: int):
    today   = datetime.now(tz=KST).strftime("%Y년 %m월 %d일")
    headers = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}"}

    r1 = requests.post(
        "https://slack.com/api/files.getUploadURLExternal",
        headers=headers,
        data={
            "filename": f"ai_news_{datetime.now(tz=KST).strftime('%Y%m%d')}.png",
            "length":   len(image_bytes),
        },
    )
    d1 = r1.json()
    if not d1.get("ok"):
        raise RuntimeError(f"Slack getUploadURL 실패: {d1.get('error')}")

    requests.post(d1["upload_url"], data=image_bytes,
                  headers={"Content-Type": "image/png"}).raise_for_status()

    r3 = requests.post(
        "https://slack.com/api/files.completeUploadExternal",
        headers=headers,
        json={
            "files":           [{"id": d1["file_id"],
                                 "title": f"AI 뉴스 브리핑 | {today}"}],
            "channel_id":      SLACK_CHANNEL,
            "initial_comment": f"*AI Times Daily | {today}*\n지난 12시간 AI 뉴스 {article_count}건 요약 🔥",
        },
    )
    d3 = r3.json()
    if not d3.get("ok"):
        raise RuntimeError(f"Slack completeUpload 실패: {d3.get('error')}")

    print(f"✅ Slack 이미지 발송 완료 → {SLACK_CHANNEL}")


# ── Gmail 발송 ─────────────────────────────────────────
def send_email(data: dict, article_count: int):
    today   = datetime.now(tz=KST).strftime("%Y년 %m월 %d일")
    subject = f"🗞️ AI Times Daily | {today} 아침 브리핑"

    plain = data.get("trend_summary", "") + "\n\n"
    plain += "=== 🔥 AI 빅이슈 TOP 3 ===\n\n"
    for a in data.get("big_issues", []):
        plain += f"TOP {a.get('rank','')} {a['title']}\n{a['summary']}\n{a['link']}\n\n"
    plain += "=== 🚀 최신 AI 신규기능 ===\n\n"
    for a in data.get("new_features", []):
        plain += f"[{a.get('company','')}] {a['title']}\n{a['summary']}\n{a['link']}\n\n"

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

    print("🖼️ Slack 이미지 생성 중...")
    image_bytes = create_news_image(data, len(articles))

    print("💬 Slack 발송 중...")
    send_slack_image(image_bytes, len(articles))

    print("📧 Gmail 발송 중...")
    send_email(data, len(articles))
