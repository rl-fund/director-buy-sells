#!/usr/bin/env python3
"""
Daily Portfolio Stock Summary - Email at 8am AEST.

Fetches previous trading session data for a multi-region watchlist and
emails a summary (with news headlines) via Gmail.

Designed to be run via GitHub Actions at 8am AEST or via cron.

Regions: ASX (Australia), US (NYSE/NASDAQ/ARCA), Europe (LSE/XETRA/WSE),
         Canada (TSX)
"""

import os
import smtplib
import sys
from collections import OrderedDict
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# Stocks grouped by region. Keys are (yfinance ticker, display name).
REGIONS = OrderedDict([
    ("🇦🇺 ASX (Australia)", {
        "360.AX": "Life360",
        "ALQ.AX": "ALS Limited",
        "GDX.AX": "Global X Gold Miners ETF",
        "PNI.AX": "Pinnacle Investment Mgmt",
        "QBTC.AX": "21Shares Bitcoin ETF",
        "WTC.AX": "WiseTech Global",
    }),
    ("🇺🇸 US (NYSE / NASDAQ / ARCA)", {
        "AEXA": "Aexa Aerospace",
        "AMC": "AMC Entertainment",
        "GOOG": "Google (Alphabet)",
        "LPTH": "LightPath Technologies",
        "ODFL": "Old Dominion Freight Line",
        "PFE": "Pfizer",
        "QQQ": "Invesco QQQ (NASDAQ 100)",
        "SATL": "Satellogic",
        "SLV": "iShares Silver Trust",
        "TDW": "Tidewater Inc",
        "TSLA": "Tesla",
        "URA": "Global X Uranium ETF",
        "V": "Visa",
    }),
    ("🇪🇺 Europe", {
        "CDR.WA": "CD Projekt (Warsaw)",
        "RHM.DE": "Rheinmetall (XETRA)",
        "SPX.L": "S&P 500 ETF (LSE)",
    }),
    ("🇨🇦 Canada (TSX)", {
        "MDI.TO": "Major Drilling Group",
    }),
])

# Currency symbols per region
REGION_CURRENCY = {
    "🇦🇺 ASX (Australia)": "A$",
    "🇺🇸 US (NYSE / NASDAQ / ARCA)": "$",
    "🇪🇺 Europe": "",       # mixed currencies, shown per-stock
    "🇨🇦 Canada (TSX)": "C$",
}

# Override currency for specific European tickers
TICKER_CURRENCY = {
    "CDR.WA": "PLN ",
    "RHM.DE": "€",
    "SPX.L": "£",
}

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL", GMAIL_ADDRESS)


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------
def fetch_stock_data(ticker: str) -> dict | None:
    """Fetch the most recent trading day's data for a ticker."""
    stock = yf.Ticker(ticker)
    hist = stock.history(period="5d")
    if hist.empty or len(hist) < 1:
        return None

    latest = hist.iloc[-1]
    prev = hist.iloc[-2] if len(hist) >= 2 else None

    close = latest["Close"]
    open_price = latest["Open"]
    high = latest["High"]
    low = latest["Low"]
    volume = int(latest["Volume"])

    prev_close = prev["Close"] if prev is not None else open_price
    change = close - prev_close
    change_pct = (change / prev_close) * 100 if prev_close else 0

    return {
        "date": str(hist.index[-1].date()),
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "prev_close": prev_close,
        "change": change,
        "change_pct": change_pct,
        "volume": volume,
    }


def fetch_news(ticker: str, max_items: int = 3) -> list[dict]:
    """Fetch recent news headlines for a ticker via yfinance."""
    try:
        stock = yf.Ticker(ticker)
        news = stock.news or []
        results = []
        for item in news[:max_items]:
            title = item.get("title", "")
            link = item.get("link", "")
            publisher = item.get("publisher", "")
            if title:
                results.append({
                    "title": title,
                    "link": link,
                    "publisher": publisher,
                })
        return results
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------
def fmt(n: float, decimals: int = 2) -> str:
    return f"{n:,.{decimals}f}"


def fmt_vol(v: int) -> str:
    if v >= 1_000_000:
        return f"{v / 1_000_000:.2f}M"
    if v >= 1_000:
        return f"{v / 1_000:.1f}K"
    return str(v)


def arrow(change: float) -> str:
    if change > 0:
        return "▲"
    if change < 0:
        return "▼"
    return "▬"


def get_currency(ticker: str, region: str) -> str:
    if ticker in TICKER_CURRENCY:
        return TICKER_CURRENCY[ticker]
    return REGION_CURRENCY.get(region, "$")


# ---------------------------------------------------------------------------
# Email body builders
# ---------------------------------------------------------------------------
def build_email_body(results: dict, news_data: dict) -> tuple[str, str, str]:
    """Build subject, plain-text and HTML email bodies."""
    now_aest = datetime.utcnow() + timedelta(hours=11)
    subject = f"Portfolio Daily Summary - {now_aest.strftime('%a %d %b %Y')}"

    # ---- Plain text ----
    lines = [
        "Portfolio Daily Summary",
        f"Report generated: {now_aest.strftime('%a %d %b %Y %I:%M %p AEDT')}",
        "=" * 65,
        "",
    ]

    for region, stocks in REGIONS.items():
        lines.append(region)
        lines.append("-" * 50)
        for ticker, name in stocks.items():
            cur = get_currency(ticker, region)
            data = results.get(ticker)
            lines.append(f"  {name} ({ticker})")
            if data is None:
                lines.append("    ⚠ No data available")
            else:
                sign = "+" if data["change"] >= 0 else ""
                lines.append(f"    Close: {cur}{fmt(data['close'])}  "
                             f"Change: {sign}{cur}{fmt(data['change'])} "
                             f"({sign}{fmt(data['change_pct'])}%)")
                lines.append(f"    Open: {cur}{fmt(data['open'])}  "
                             f"High: {cur}{fmt(data['high'])}  "
                             f"Low: {cur}{fmt(data['low'])}  "
                             f"Vol: {fmt_vol(data['volume'])}")
            # News
            ticker_news = news_data.get(ticker, [])
            if ticker_news:
                for n in ticker_news:
                    lines.append(f"    📰 {n['title']}")
            lines.append("")
        lines.append("")

    lines.append("=" * 65)
    plain_body = "\n".join(lines)

    # ---- HTML ----
    sections_html = ""
    for region, stocks in REGIONS.items():
        rows_html = ""
        for ticker, name in stocks.items():
            cur = get_currency(ticker, region)
            data = results.get(ticker)

            # News bullets
            ticker_news = news_data.get(ticker, [])
            news_html = ""
            if ticker_news:
                news_items = ""
                for n in ticker_news:
                    title = n["title"]
                    link = n.get("link", "")
                    pub = n.get("publisher", "")
                    if link:
                        news_items += f'<li><a href="{link}" style="color:#2563eb;text-decoration:none;">{title}</a>'
                    else:
                        news_items += f"<li>{title}"
                    if pub:
                        news_items += f' <span style="color:#94a3b8;">— {pub}</span>'
                    news_items += "</li>"
                news_html = f'<ul style="margin:4px 0 0 0;padding-left:18px;font-size:12px;color:#475569;">{news_items}</ul>'

            if data is None:
                rows_html += f"""
                <tr>
                    <td style="padding:8px;border:1px solid #ddd;font-weight:bold;">
                        {name}<br><span style="color:#666;font-size:0.85em;">{ticker}</span>
                        {news_html}
                    </td>
                    <td colspan="6" style="padding:8px;border:1px solid #ddd;color:#999;">No data</td>
                </tr>"""
                continue

            color = "#16a34a" if data["change"] >= 0 else "#dc2626"
            sign = "+" if data["change"] >= 0 else ""
            arr = arrow(data["change"])
            rows_html += f"""
                <tr>
                    <td style="padding:8px;border:1px solid #ddd;font-weight:bold;">
                        {name}<br><span style="color:#666;font-size:0.85em;">{ticker}</span>
                        {news_html}
                    </td>
                    <td style="padding:8px;border:1px solid #ddd;text-align:right;">{cur}{fmt(data['close'])}</td>
                    <td style="padding:8px;border:1px solid #ddd;text-align:right;color:{color};font-weight:bold;">
                        {arr} {sign}{cur}{fmt(data['change'])}<br>
                        <span style="font-size:0.85em;">({sign}{fmt(data['change_pct'])}%)</span>
                    </td>
                    <td style="padding:8px;border:1px solid #ddd;text-align:right;">{cur}{fmt(data['open'])}</td>
                    <td style="padding:8px;border:1px solid #ddd;text-align:right;">{cur}{fmt(data['high'])}</td>
                    <td style="padding:8px;border:1px solid #ddd;text-align:right;">{cur}{fmt(data['low'])}</td>
                    <td style="padding:8px;border:1px solid #ddd;text-align:right;">{fmt_vol(data['volume'])}</td>
                </tr>"""

        sections_html += f"""
        <h3 style="color:#334155;margin:24px 0 8px 0;border-bottom:2px solid #e2e8f0;padding-bottom:4px;">
            {region}
        </h3>
        <table style="border-collapse:collapse;width:100%;font-size:14px;">
            <tr style="background:#f1f5f9;">
                <th style="padding:8px;border:1px solid #ddd;text-align:left;">Stock</th>
                <th style="padding:8px;border:1px solid #ddd;text-align:right;">Close</th>
                <th style="padding:8px;border:1px solid #ddd;text-align:right;">Change</th>
                <th style="padding:8px;border:1px solid #ddd;text-align:right;">Open</th>
                <th style="padding:8px;border:1px solid #ddd;text-align:right;">High</th>
                <th style="padding:8px;border:1px solid #ddd;text-align:right;">Low</th>
                <th style="padding:8px;border:1px solid #ddd;text-align:right;">Volume</th>
            </tr>
            {rows_html}
        </table>
        """

    html_body = f"""
    <html><body style="font-family:Arial,sans-serif;max-width:900px;margin:auto;padding:16px;">
    <h2 style="color:#1e293b;">Portfolio Daily Summary</h2>
    <p style="color:#64748b;">Report generated: {now_aest.strftime('%a %d %b %Y %I:%M %p AEDT')}</p>
    {sections_html}
    <p style="color:#94a3b8;font-size:12px;margin-top:20px;">
        Data sourced from Yahoo Finance. Prices in local currency.
    </p>
    </body></html>
    """

    return subject, plain_body, html_body


# ---------------------------------------------------------------------------
# Email sending
# ---------------------------------------------------------------------------
def send_email(subject: str, plain_body: str, html_body: str):
    """Send the summary email via Gmail SMTP."""
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        print("ERROR: Set GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env file.")
        sys.exit(1)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = RECIPIENT_EMAIL

    msg.attach(MIMEText(plain_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, RECIPIENT_EMAIL, msg.as_string())

    print(f"Email sent to {RECIPIENT_EMAIL}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    all_tickers = []
    for stocks in REGIONS.values():
        all_tickers.extend(stocks.keys())

    print(f"Fetching data for {len(all_tickers)} stocks across {len(REGIONS)} regions...")

    results = {}
    news_data = {}
    for ticker in all_tickers:
        # Price data
        try:
            results[ticker] = fetch_stock_data(ticker)
            status = "OK" if results[ticker] else "no data"
        except Exception as e:
            results[ticker] = None
            status = f"error: {e}"
        print(f"  {ticker}: {status}")

        # News
        news_data[ticker] = fetch_news(ticker)
        news_count = len(news_data[ticker])
        if news_count:
            print(f"    -> {news_count} news item(s)")

    subject, plain_body, html_body = build_email_body(results, news_data)

    print("\n" + plain_body)

    send_email(subject, plain_body, html_body)


if __name__ == "__main__":
    main()
