#!/usr/bin/env python3
# Runs ONCE: checks the wallets below across ALL perp venues,
# texts Telegram on new opens/closes, saves state.
import os
import json
import urllib.request
from pathlib import Path

# ============================================================
#   WALLETS TO WATCH — add or remove addresses here.
# ============================================================
WALLETS = [
    "0x0c349d9b92fbd172bbb5a17a9db0a673a6a10ad3",
    "0x1aa780bb10425b86bcf05ecbb7953f9a93729ed9",
]
WALLETS = [w.strip().lower() for w in WALLETS if w.strip()]
# ============================================================

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")   # stays in the GitHub secret
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


def list_dexes():
    names = [""]
    try:
        for d in post_json(HL_INFO_URL, {"type": "perpDexs"}):
            if d and d.get("name"):
                names.append(d["name"])
    except Exception as e:
        print("perpDexs error, using main venue only:", e)
    return names


def fetch_positions(wallet, dexes):
    out = {}
    for dex in dexes:
        payload = {"type": "clearinghouseState", "user": wallet}
        if dex:
            payload["dex"] = dex
        try:
            data = post_json(HL_INFO_URL, payload)
        except Exception as e:
            print(f"venue '{dex or 'main'}' error for {short(wallet)}:", e)
            continue
        for ap in data.get("assetPositions", []):
            p = ap.get("position", {})
            szi = float(p.get("szi") or 0)
            if szi == 0:
                continue
            raw = p["coin"]
            bare = raw.split(":", 1)[1] if ":" in raw else raw
            poskey = f"{dex}:{bare}" if dex else bare
            lev = p.get("leverage", {}) or {}
            out[poskey] = {
                "coin": bare,
                "kind": "🪙 Crypto" if not dex else "📈 Stock",
                "side": "LONG" if szi > 0 else "SHORT",
                "entry": float(p.get("entryPx") or 0),
                "liq": float(p.get("liquidationPx") or 0),
                "lev": f"{lev.get('value', '?')}x",
                "mode": (lev.get("type", "") or "").capitalize(),
                "margin": float(p.get("marginUsed") or 0),
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


def open_message(wallet, pos):
    liq = fmt_price(pos["liq"]) if pos["liq"] else "—"
    return (
        f"🔔 New position\n"
        f"👤 {short(wallet)}\n"
        f"{pos['kind']}\n"
        f"{pos['coin']} {pos['side']}\n"
        f"Entry {fmt_price(pos['entry'])}\n"
        f"Liq {liq}\n"
        f"Leverage {pos['lev']}\n"
        f"Size ~${pos['value']:,.0f}\n"
        f"Margin ${pos['margin']:,.0f} {pos['mode']}"
    )


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return None


def main():
    if not WALLETS:
        raise SystemExit("No wallets configured.")

    dexes = list_dexes()

    curr_full = {}   # "wallet|positionkey" -> (wallet, position)
    curr_sides = {}  # "wallet|positionkey" -> side
    for wallet in WALLETS:
        for poskey, pos in fetch_positions(wallet, dexes).items():
            ckey = f"{wallet}|{poskey}"
            curr_full[ckey] = (wallet, pos)
            curr_sides[ckey] = pos["side"]

    prev = load_state()
    # Migrate old single-wallet state (keys without "|") -> re-baseline cleanly.
    if prev and not all("|" in k for k in prev):
        print("Old state format detected; re-baselining without alerts.")
        prev = None

    if prev is None:
        STATE_FILE.write_text(json.dumps(curr_sides))
        send(f"✅ Alert bot is live — watching {len(WALLETS)} wallet(s), "
             f"{len(curr_sides)} open position(s). I'll message you on new opens and closes.")
        print("Baseline saved.")
        return

    for ckey, (wallet, pos) in curr_full.items():
        old = prev.get(ckey)
        if old is None or old != pos["side"]:
            send(open_message(wallet, pos))

    if ALERT_ON_CLOSE:
        for ckey in prev:
            if ckey not in curr_sides:
                wallet, poskey = ckey.split("|", 1)
                coin = poskey.split(":", 1)[1] if ":" in poskey else poskey
                send(f"✅ Closed {coin} position\n👤 {short(wallet)}")

    STATE_FILE.write_text(json.dumps(curr_sides))
    print("Done. Open now:", list(curr_sides))


if __name__ == "__main__":
    main()
