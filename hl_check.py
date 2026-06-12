#!/usr/bin/env python3
# Runs ONCE: checks the wallet, texts Telegram on new opens/closes, saves state.
import os
import json
import urllib.request
from pathlib import Path

WALLET = os.environ.get("HL_WALLET", "").lower()
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "1253059682")
ALERT_ON_CLOSE = os.environ.get("ALERT_ON_CLOSE", "true").lower() == "true"

STATE_FILE = Path("hl_state.json")
HL_INFO_URL = "https://api.hyperliquid.xyz/info"


def post_json(url, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def fmt_price(x):
    if x == 0:
        return "0"
    return f"${x:,.2f}" if x >= 1 else f"${x:.6g}"


def short(a):
    return a[:6] + "…" + a[-4:]


def fetch_positions(wallet):
    data = post_json(HL_INFO_URL, {"type": "clearinghouseState", "user": wallet})
    out = {}
    for ap in data.get("assetPositions", []):
        p = ap.get("position", {})
        szi = float(p.get("szi") or 0)
        if szi == 0:
            continue
        lev = p.get("leverage", {}) or {}
        out[p["coin"]] = {
            "side": "LONG" if szi > 0 else "SHORT",
            "entry": float(p.get("entryPx") or 0),
            "lev": f"{lev.get('value', '?')}x {lev.get('type', '')}".strip(),
            "value": float(p.get("positionValue") or 0),
        }
    return out


def send(text):
    if not BOT_TOKEN:
        print("No bot token set.")
        return
    try:
        post_json(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                  {"chat_id": CHAT_ID, "text": text})
        print("Sent:", text.splitlines()[0])
    except Exception as e:
        print("Telegram error:", e)


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return None


def main():
    if not WALLET:
        raise SystemExit("HL_WALLET not set.")
    curr = fetch_positions(WALLET)
    curr_sides = {c: v["side"] for c, v in curr.items()}
    prev = load_state()

    if prev is None:
        STATE_FILE.write_text(json.dumps(curr_sides))
        send(f"✅ Alert bot is live and watching {short(WALLET)} "
             f"({len(curr)} open position(s)). I'll message you on new opens and closes.")
        print("Baseline saved.")
        return

    for coin, pos in curr.items():
        old = prev.get(coin)
        if old is None or old != pos["side"]:
            send(f"🔔 New position\n{short(WALLET)}\n{coin} {pos['side']}\n"
                 f"Entry {fmt_price(pos['entry'])}\nLeverage {pos['lev']}\n"
                 f"Size ~${pos['value']:,.0f}")

    if ALERT_ON_CLOSE:
        for coin in prev:
            if coin not in curr:
                send(f"✅ Closed {coin} position ({short(WALLET)})")

    STATE_FILE.write_text(json.dumps(curr_sides))
    print("Done. Open now:", list(curr_sides))


if __name__ == "__main__":
    main()
