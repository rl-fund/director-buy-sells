#!/usr/bin/env python3
"""
Daily US Stock Overnight Trading Summary - Email at 8am AEST.

Fetches previous US trading session data for a watchlist and emails
a summary via Gmail. Designed to be run via cron at 8am Australian time.

Crontab example (8am AEST every weekday):
    0 8 * * 1-5 /usr/bin/python3 /path/to/daily_stock_email.py

Stocks tracked: TDW, GOOGL, TSLA, SATL, AMC
"""

import os
import smtplib
import sys
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WATCHLIST = {
    "TDW": "Tidewater Inc",
    "GOOGL": "Google (Alphabet)",
    "TSLA": "Tesla",
    "SATL": "Satellogic",
    "AMC": "AMC Entertainment",
}

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS")          # your Gmail address
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD") # Gmail App Password
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL", GMAIL_ADDRESS)  # defaults to self


def fetch_stock_data(ticker: str) -> dict | None:
    """Fetch the most recent trading day's data for a US ticker."""
    stock = yf.Ticker(ticker)
    # Grab last 5 days to ensure we get at least 2 trading days
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


def format_number(n: float, decimals: int = 2) -> str:
    return f"{n:,.{decimals}f}"


def format_volume(v: int) -> str:
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


def build_email_body(results: dict) -> tuple[str, str]:
    """Build plain-text and HTML email bodies."""
    now_aest = datetime.utcnow() + timedelta(hours=11)
    subject = f"US Stock Overnight Summary - {now_aest.strftime('%a %d %b %Y')}"

    # --- Plain text ---
    lines = [
        f"US Stock Overnight Summary",
        f"Report generated: {now_aest.strftime('%a %d %b %Y %I:%M %p AEDT')}",
        "=" * 60,
        "",
    ]

    for ticker, name in WATCHLIST.items():
        data = results.get(ticker)
        lines.append(f"{name} ({ticker})")
        if data is None:
            lines.append("  ⚠ No data available")
            lines.append("")
            continue
        sign = "+" if data["change"] >= 0 else ""
        lines.append(f"  Date:       {data['date']}")
        lines.append(f"  Close:      ${format_number(data['close'])}")
        lines.append(f"  Change:     {sign}${format_number(data['change'])} ({sign}{format_number(data['change_pct'])}%)")
        lines.append(f"  Open:       ${format_number(data['open'])}")
        lines.append(f"  High:       ${format_number(data['high'])}")
        lines.append(f"  Low:        ${format_number(data['low'])}")
        lines.append(f"  Volume:     {format_volume(data['volume'])} ({data['volume']:,})")
        lines.append("")

    lines.append("=" * 60)
    plain_body = "\n".join(lines)

    # --- HTML ---
    rows_html = ""
    for ticker, name in WATCHLIST.items():
        data = results.get(ticker)
        if data is None:
            rows_html += f"""
            <tr>
                <td style="padding:8px;border:1px solid #ddd;font-weight:bold;">{name}<br><span style="color:#666;font-size:0.85em;">{ticker}</span></td>
                <td colspan="6" style="padding:8px;border:1px solid #ddd;color:#999;">No data available</td>
            </tr>"""
            continue
        color = "#16a34a" if data["change"] >= 0 else "#dc2626"
        sign = "+" if data["change"] >= 0 else ""
        arr = arrow(data["change"])
        rows_html += f"""
            <tr>
                <td style="padding:8px;border:1px solid #ddd;font-weight:bold;">{name}<br><span style="color:#666;font-size:0.85em;">{ticker}</span></td>
                <td style="padding:8px;border:1px solid #ddd;text-align:right;">${format_number(data['close'])}</td>
                <td style="padding:8px;border:1px solid #ddd;text-align:right;color:{color};font-weight:bold;">
                    {arr} {sign}${format_number(data['change'])}<br>
                    <span style="font-size:0.85em;">({sign}{format_number(data['change_pct'])}%)</span>
                </td>
                <td style="padding:8px;border:1px solid #ddd;text-align:right;">${format_number(data['open'])}</td>
                <td style="padding:8px;border:1px solid #ddd;text-align:right;">${format_number(data['high'])}</td>
                <td style="padding:8px;border:1px solid #ddd;text-align:right;">${format_number(data['low'])}</td>
                <td style="padding:8px;border:1px solid #ddd;text-align:right;">{format_volume(data['volume'])}</td>
            </tr>"""

    html_body = f"""
    <html><body style="font-family:Arial,sans-serif;max-width:800px;margin:auto;">
    <h2 style="color:#1e293b;">US Stock Overnight Summary</h2>
    <p style="color:#64748b;">Report generated: {now_aest.strftime('%a %d %b %Y %I:%M %p AEDT')}</p>
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
    <p style="color:#94a3b8;font-size:12px;margin-top:20px;">Data sourced from Yahoo Finance. Prices in USD.</p>
    </body></html>
    """

    return subject, plain_body, html_body


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


def main():
    print("Fetching US stock data...")
    results = {}
    for ticker in WATCHLIST:
        try:
            results[ticker] = fetch_stock_data(ticker)
            status = "OK" if results[ticker] else "no data"
        except Exception as e:
            results[ticker] = None
            status = f"error: {e}"
        print(f"  {ticker}: {status}")

    subject, plain_body, html_body = build_email_body(results)

    # Print to console as well (useful for debugging / dry runs)
    print("\n" + plain_body)

    send_email(subject, plain_body, html_body)


if __name__ == "__main__":
    main()
