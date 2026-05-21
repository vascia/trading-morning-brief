"""
Trading Morning Brief - Daily Analysis Script
GitHub Actions 또는 로컬에서 실행
"""

import json
import os
import smtplib
import sys
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
import anthropic
import yfinance as yf
import pytz

# ── 설정 로드 ─────────────────────────────────────────────
CONFIG_PATH = Path(__file__).parent / "config.json"
with open(CONFIG_PATH) as f:
    CONFIG = json.load(f)

ASSETS = CONFIG["assets"]
SETTINGS = CONFIG["settings"]
PROXIMITY_PCT = SETTINGS["proximity_pct"]  # 레벨 근접 판단 기준 (%)
KST = pytz.timezone(SETTINGS["timezone"])


# ── 가격 데이터 fetch ──────────────────────────────────────
def fetch_price(ticker: str, asset_type: str) -> dict | None:
    """yfinance로 현재가 + 최근 데이터 fetch"""
    try:
        period = "5d" if asset_type == "korean_stock" else "5d"
        interval = "1d"
        t = yf.Ticker(ticker)
        hist = t.history(period=period, interval=interval)

        if hist.empty:
            return None

        latest = hist.iloc[-1]
        prev = hist.iloc[-2] if len(hist) >= 2 else latest

        close = float(latest["Close"])
        prev_close = float(prev["Close"])
        change_pct = (close - prev_close) / prev_close * 100
        high = float(latest["High"])
        low = float(latest["Low"])
        volume = float(latest["Volume"])

        return {
            "price": close,
            "change_pct": change_pct,
            "high": high,
            "low": low,
            "volume": volume,
            "prev_close": prev_close,
        }
    except Exception as e:
        print(f"  [WARN] {ticker} fetch 실패: {e}")
        return None


# ── 레벨 근접 분석 ─────────────────────────────────────────
def check_level_proximity(price: float, levels: dict) -> list[dict]:
    """현재가가 지지/저항선에 얼마나 가까운지 분석"""
    alerts = []
    threshold = price * (PROXIMITY_PCT / 100)

    for level_type, prices in levels.items():
        for level_price in prices:
            dist = abs(price - level_price)
            dist_pct = dist / level_price * 100
            if dist <= threshold:
                direction = "위" if price > level_price else "아래"
                alerts.append({
                    "type": level_type,
                    "level": level_price,
                    "distance_pct": dist_pct,
                    "direction": direction,
                    "status": "⚡ 레벨 터치 중" if dist_pct < 0.3 else f"🔶 근접 ({dist_pct:.2f}% {direction})"
                })

    alerts.sort(key=lambda x: x["distance_pct"])
    return alerts


# ── Claude API 분석 ────────────────────────────────────────
def analyze_with_claude(assets_data: list[dict]) -> str:
    """Claude API로 전체 시황 분석"""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # 분석용 데이터 요약
    summary_lines = []
    for a in assets_data:
        if not a.get("price_data"):
            continue
        pd = a["price_data"]
        alerts = a.get("level_alerts", [])
        alert_str = ""
        if alerts:
            alert_str = f" | ⚠️ 레벨 근접: {', '.join([f'{x[\"type\"]} {x[\"level\"]}({x[\"distance_pct\"]:.1f}% {x[\"direction\"]})' for x in alerts[:2]])}"

        summary_lines.append(
            f"- {a['name']} ({a['ticker']}): ${pd['price']:,.4g} "
            f"({pd['change_pct']:+.2f}%) "
            f"[고:{pd['high']:,.4g} 저:{pd['low']:,.4g}]"
            f"{alert_str}"
        )

    data_str = "\n".join(summary_lines)
    today_str = datetime.now(KST).strftime("%Y년 %m월 %d일")

    prompt = f"""오늘은 {today_str}입니다. 아래는 오늘 아침 글로벌 자산 현황입니다.

{data_str}

당신은 전문 트레이더 겸 시황 분석가입니다. 위 데이터를 바탕으로 **한국어**로 다음을 작성해주세요:

1. **📊 오늘의 전체 시황 요약** (3~4문장, 핵심만)
2. **⚡ 레벨 근접 종목 경보** (지지/저항선에 가까운 종목 우선순위 정리)
3. **🌏 섹터별 흐름** (크립토 / 미국주식 / 한국주식 / 원자재·외환 각각 1~2문장)
4. **🎯 오늘 주목할 포인트** (트레이딩 관점 핵심 2~3개)
5. **⚠️ 리스크 요인** (현재 시장에서 주의할 것)

간결하고 실용적으로, 전문용어는 써도 되지만 핵심을 빠르게 파악할 수 있게 작성해주세요.
"""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text


# ── HTML 리포트 생성 ───────────────────────────────────────
def generate_html_report(assets_data: list[dict], ai_analysis: str) -> str:
    now_kst = datetime.now(KST)
    date_str = now_kst.strftime("%Y년 %m월 %d일 %H:%M KST")

    # 자산 카드 HTML 생성
    def format_price(p, ticker):
        if p is None:
            return "N/A"
        # 소수점 자릿수 동적 처리
        if p < 0.001:
            return f"{p:.8f}"
        elif p < 1:
            return f"{p:.5f}"
        elif p < 100:
            return f"{p:.3f}"
        else:
            return f"{p:,.2f}"

    asset_cards = ""
    type_order = ["crypto", "us_stock", "korean_stock", "futures", "commodity", "forex"]
    type_labels = {
        "crypto": "🪙 크립토",
        "us_stock": "🇺🇸 미국주식",
        "korean_stock": "🇰🇷 한국주식",
        "futures": "📈 선물",
        "commodity": "🏅 원자재",
        "forex": "💱 외환",
    }

    grouped = {t: [] for t in type_order}
    for a in assets_data:
        grouped.get(a["type"], grouped["crypto"]).append(a)

    for asset_type in type_order:
        group = grouped[asset_type]
        if not group:
            continue

        asset_cards += f'<div class="sector-label">{type_labels[asset_type]}</div>\n<div class="cards-row">\n'

        for a in group:
            pd = a.get("price_data")
            alerts = a.get("level_alerts", [])

            if pd is None:
                asset_cards += f'''
<div class="card card-error">
  <div class="card-name">{a["name"]}</div>
  <div class="card-ticker">{a["ticker"]}</div>
  <div class="card-price-unavailable">데이터 없음</div>
</div>
'''
                continue

            change = pd["change_pct"]
            change_class = "positive" if change >= 0 else "negative"
            change_sign = "+" if change >= 0 else ""
            price_str = format_price(pd["price"], a["ticker"])

            alert_html = ""
            if alerts:
                alert_items = "".join([
                    f'<span class="alert-badge alert-{al["type"]}">{al["status"]} {al["type"]} {format_price(al["level"], "")}</span>'
                    for al in alerts[:3]
                ])
                alert_html = f'<div class="alert-row">{alert_items}</div>'

            card_class = "card card-alert" if alerts else "card"
            asset_cards += f'''
<div class="{card_class}">
  <div class="card-header">
    <span class="card-name">{a["name"]}</span>
    <span class="card-change {change_class}">{change_sign}{change:.2f}%</span>
  </div>
  <div class="card-price">{price_str}</div>
  <div class="card-hl">H: {format_price(pd["high"], "")} &nbsp; L: {format_price(pd["low"], "")}</div>
  {alert_html}
</div>
'''
        asset_cards += '</div>\n'

    # AI 분석 마크다운 → HTML (간단 변환)
    ai_html = ai_analysis.replace("\n", "<br>")
    # 볼드
    import re
    ai_html = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', ai_html)
    # 헤딩 스타일
    ai_html = re.sub(r'#{1,3} (.*?)<br>', r'<h3>\1</h3>', ai_html)

    html = f'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Morning Brief — {now_kst.strftime("%m/%d")}</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Noto+Sans+KR:wght@300;400;700&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #0a0a0f;
    --surface: #12121a;
    --surface2: #1a1a26;
    --border: #2a2a3d;
    --accent: #00ff88;
    --accent2: #7c3aed;
    --text: #e8e8f0;
    --text2: #8888aa;
    --positive: #00ff88;
    --negative: #ff4466;
    --warn: #ffaa00;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: 'Noto Sans KR', sans-serif;
    min-height: 100vh;
    padding: 0;
  }}
  .header {{
    background: linear-gradient(135deg, #0a0a0f 0%, #12121a 50%, #1a1226 100%);
    border-bottom: 1px solid var(--border);
    padding: 32px 40px 24px;
    position: relative;
    overflow: hidden;
  }}
  .header::before {{
    content: '';
    position: absolute;
    top: -50%;
    right: -10%;
    width: 400px;
    height: 400px;
    background: radial-gradient(circle, rgba(0,255,136,0.05) 0%, transparent 70%);
    pointer-events: none;
  }}
  .header-top {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
  }}
  .title {{
    font-family: 'Space Mono', monospace;
    font-size: 11px;
    letter-spacing: 4px;
    color: var(--accent);
    text-transform: uppercase;
    margin-bottom: 8px;
  }}
  .date-big {{
    font-size: 28px;
    font-weight: 700;
    color: var(--text);
    letter-spacing: -0.5px;
  }}
  .date-sub {{
    font-size: 13px;
    color: var(--text2);
    margin-top: 4px;
    font-family: 'Space Mono', monospace;
  }}
  .pulse-dot {{
    width: 8px; height: 8px;
    background: var(--accent);
    border-radius: 50%;
    display: inline-block;
    margin-right: 8px;
    animation: pulse 2s infinite;
  }}
  @keyframes pulse {{
    0%, 100% {{ opacity: 1; transform: scale(1); }}
    50% {{ opacity: 0.4; transform: scale(0.8); }}
  }}
  .main {{
    max-width: 1400px;
    margin: 0 auto;
    padding: 32px 40px;
  }}
  .section-title {{
    font-family: 'Space Mono', monospace;
    font-size: 10px;
    letter-spacing: 3px;
    color: var(--text2);
    text-transform: uppercase;
    margin-bottom: 20px;
    margin-top: 40px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border);
  }}
  .sector-label {{
    font-size: 12px;
    font-weight: 700;
    color: var(--text2);
    letter-spacing: 1px;
    margin-bottom: 10px;
    margin-top: 24px;
  }}
  .cards-row {{
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    margin-bottom: 8px;
  }}
  .card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px 18px;
    min-width: 180px;
    flex: 1 1 180px;
    max-width: 240px;
    transition: border-color 0.2s, transform 0.15s;
    cursor: default;
  }}
  .card:hover {{
    border-color: var(--accent2);
    transform: translateY(-2px);
  }}
  .card-alert {{
    border-color: var(--warn) !important;
    background: #1a1500;
  }}
  .card-error {{
    opacity: 0.4;
  }}
  .card-header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
  }}
  .card-name {{
    font-size: 13px;
    font-weight: 700;
    color: var(--text);
  }}
  .card-change {{
    font-family: 'Space Mono', monospace;
    font-size: 12px;
    font-weight: 700;
  }}
  .positive {{ color: var(--positive); }}
  .negative {{ color: var(--negative); }}
  .card-price {{
    font-family: 'Space Mono', monospace;
    font-size: 20px;
    font-weight: 700;
    color: var(--text);
    margin-bottom: 4px;
  }}
  .card-hl {{
    font-family: 'Space Mono', monospace;
    font-size: 10px;
    color: var(--text2);
    margin-bottom: 8px;
  }}
  .card-ticker {{
    font-size: 11px;
    color: var(--text2);
  }}
  .card-price-unavailable {{
    font-size: 13px;
    color: var(--text2);
    margin-top: 8px;
  }}
  .alert-row {{
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin-top: 8px;
  }}
  .alert-badge {{
    font-size: 10px;
    padding: 3px 7px;
    border-radius: 4px;
    font-family: 'Space Mono', monospace;
  }}
  .alert-support {{
    background: rgba(0,255,136,0.1);
    color: var(--positive);
    border: 1px solid rgba(0,255,136,0.2);
  }}
  .alert-resistance {{
    background: rgba(255,68,102,0.1);
    color: var(--negative);
    border: 1px solid rgba(255,68,102,0.2);
  }}
  .ai-box {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-left: 3px solid var(--accent);
    border-radius: 10px;
    padding: 28px 32px;
    line-height: 1.9;
    font-size: 14px;
    color: var(--text);
  }}
  .ai-box strong {{
    color: var(--accent);
  }}
  .ai-box h3 {{
    font-size: 15px;
    font-weight: 700;
    color: var(--text);
    margin: 16px 0 8px;
  }}
  .footer {{
    text-align: center;
    padding: 32px;
    color: var(--text2);
    font-size: 11px;
    font-family: 'Space Mono', monospace;
    border-top: 1px solid var(--border);
    margin-top: 60px;
  }}
  @media (max-width: 600px) {{
    .main {{ padding: 20px 16px; }}
    .header {{ padding: 24px 20px; }}
    .card {{ max-width: 100%; }}
  }}
</style>
</head>
<body>

<div class="header">
  <div class="header-top">
    <div>
      <div class="title"><span class="pulse-dot"></span>Morning Brief</div>
      <div class="date-big">{now_kst.strftime("%B %d, %Y")}</div>
      <div class="date-sub">{date_str}</div>
    </div>
  </div>
</div>

<div class="main">
  <div class="section-title">AI 시황 분석</div>
  <div class="ai-box">{ai_html}</div>

  <div class="section-title">자산 현황</div>
  {asset_cards}
</div>

<div class="footer">
  Generated by Trading Morning Brief &nbsp;·&nbsp; Powered by Claude API &nbsp;·&nbsp; Data: Yahoo Finance
</div>

</body>
</html>'''
    return html


# ── 이메일 발송 ────────────────────────────────────────────
def send_email(html_content: str, subject: str):
    """Gmail SMTP으로 이메일 발송"""
    gmail_user = os.environ.get("GMAIL_USER")
    gmail_pass = os.environ.get("GMAIL_APP_PASSWORD")
    email_to = SETTINGS["email_to"]

    if not gmail_user or not gmail_pass:
        print("[SKIP] Gmail 환경변수 없음 - 이메일 발송 건너뜀")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = email_to
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(gmail_user, gmail_pass)
            smtp.sendmail(gmail_user, email_to, msg.as_string())
        print(f"[OK] 이메일 발송 완료 → {email_to}")
    except Exception as e:
        print(f"[ERROR] 이메일 발송 실패: {e}")


# ── 메인 ──────────────────────────────────────────────────
def main():
    print(f"\n{'='*50}")
    print(f"  Trading Morning Brief — {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    print(f"{'='*50}\n")

    assets_data = []

    print("[1/3] 가격 데이터 수집 중...")
    for asset in ASSETS:
        ticker = asset["ticker"]
        print(f"  Fetching {asset['name']} ({ticker})...", end=" ")
        price_data = fetch_price(ticker, asset["type"])

        if price_data:
            level_alerts = check_level_proximity(price_data["price"], asset["levels"])
            print(f"${price_data['price']:,.4g} ({price_data['change_pct']:+.2f}%)" +
                  (f" ⚠️ {len(level_alerts)}개 레벨 근접" if level_alerts else ""))
        else:
            level_alerts = []
            print("FAILED")

        assets_data.append({
            **asset,
            "price_data": price_data,
            "level_alerts": level_alerts
        })

    print("\n[2/3] Claude API 분석 중...")
    try:
        ai_analysis = analyze_with_claude(assets_data)
        print("  분석 완료")
    except Exception as e:
        print(f"  [ERROR] Claude API 실패: {e}")
        ai_analysis = f"⚠️ AI 분석을 불러오지 못했습니다: {e}"

    print("\n[3/3] 리포트 생성 중...")
    html_report = generate_html_report(assets_data, ai_analysis)

    # GitHub Pages용 파일 저장
    output_dir = Path(__file__).parent / "docs"
    output_dir.mkdir(exist_ok=True)
    report_path = output_dir / "index.html"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html_report)
    print(f"  HTML 저장: {report_path}")

    # 이메일 발송
    now = datetime.now(KST)
    subject = f"📈 Morning Brief {now.strftime('%m/%d')} — 레벨 근접 {sum(1 for a in assets_data if a['level_alerts'])}개"
    send_email(html_report, subject)

    print(f"\n✅ 완료!\n")


if __name__ == "__main__":
    main()
