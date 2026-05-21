# 📈 Trading Morning Brief

매일 아침 8시, 설정한 지지/저항 레벨 기준으로 글로벌 자산 자동 분석 리포트

---

## 🏗 구성

```
TradingView Pine Script 알림
        ↓
GitHub Actions (매일 KST 08:00 자동 실행)
        ↓
Python (yfinance 가격 fetch + Claude API 분석)
        ↓
GitHub Pages 웹 리포트 + Gmail 이메일
```

---

## ⚡ 세팅 방법 (5단계)

### 1. GitHub 레포 생성 & 파일 업로드
```bash
git init
git add .
git commit -m "init"
git remote add origin https://github.com/{YOUR_ID}/trading-morning-brief.git
git push -u origin main
```

### 2. GitHub Secrets 등록
레포 → Settings → Secrets and variables → Actions → New repository secret

| Secret 이름 | 값 |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic Console에서 발급 |
| `GMAIL_USER` | 발신용 Gmail 주소 |
| `GMAIL_APP_PASSWORD` | Gmail → 2단계 인증 → 앱 비밀번호 발급 |

### 3. config.json 수정
`config.json`에서 각 종목의 지지/저항 레벨을 **네가 실제로 그은 선** 기준으로 수정:

```json
{
  "name": "Bitcoin",
  "ticker": "BTC-USD",
  "levels": {
    "support": [90000, 85000],       ← 실제 지지선
    "resistance": [100000, 105000]   ← 실제 저항선
  }
}
```

그리고 이메일 주소 수정:
```json
"settings": {
    "email_to": "your@email.com",       ← 수신 이메일
    "email_from": "your_gmail@gmail.com"  ← 발신 Gmail
}
```

### 4. GitHub Pages 활성화
레포 → Settings → Pages → Source: `gh-pages` 브랜치 선택

### 5. TradingView Pine Script (선택)
1. TradingView → Pine Editor에 `tradingview_alert.pine` 붙여넣기
2. 각 종목별로 레벨값 수정 후 저장
3. 알림(Alert) 설정 → Webhook URL (Pro+ 이상 필요)

---

## 🔧 수동 실행

GitHub Actions → Workflows → Trading Morning Brief → Run workflow 버튼

또는 로컬 실행:
```bash
pip install anthropic yfinance pytz
export ANTHROPIC_API_KEY=sk-ant-...
export GMAIL_USER=your@gmail.com
export GMAIL_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
python analyze.py
```

---

## 📋 config.json 종목 추가 방법

```json
{
  "name": "표시 이름",
  "ticker": "야후파이낸스 티커",
  "type": "crypto | us_stock | korean_stock | futures | commodity | forex",
  "levels": {
    "support": [가격1, 가격2],
    "resistance": [가격1, 가격2]
  },
  "notes": "메모"
}
```

**주요 티커 형식:**
- 한국주식: `005930.KS` (삼성), `000660.KS` (하이닉스)
- 크립토: `BTC-USD`, `ETH-USD`, `SOL-USD`
- 미국주식: `AAPL`, `NVDA`, `TSLA`
- 선물: `NQ=F` (나스닥), `GC=F` (금), `SI=F` (은)
- 외환: `USDKRW=X`

---

## ⚙️ 알림 기준 조정

`config.json`의 `proximity_pct` 값 수정:
- `1.5` = 레벨에서 1.5% 이내이면 알림 (기본값)
- 더 민감하게: `0.5 ~ 1.0`
- 더 넓게: `2.0 ~ 3.0`
