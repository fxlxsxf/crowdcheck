"""Generate the synthetic demo fixture in examples/demo/.

Everything here is invented, seeded data for showing the tool without an API key.
It is not a real token and not real wallets. Run:

    python examples/make_demo.py
    crowdcheck DemoMint1111111111111111111111111111111111 --provider mock \
        --fixtures examples/demo --as-of 2026-10-01T00:00:00Z
"""

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

random.seed(7)
OUT = Path(__file__).parent / "demo"
NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)
TARGET = "DemoMint1111111111111111111111111111111111"
iso = lambda d: d.isoformat().replace("+00:00", "Z")  # noqa: E731

prior = [f"Prior{i:04d}" for i in range(420)]
survivors = set(random.sample(prior, 3))
wallets = [f"DemoWallet{i:03d}" for i in range(100)]

mints = {TARGET: {"symbol": "DEMO", "creator": "DemoCreator",
                  "first_trade_ts": iso(NOW - timedelta(hours=20)), "last_trade_ts": iso(NOW - timedelta(minutes=3))}}
for m in prior:
    start = NOW - timedelta(days=random.uniform(10, 170))
    life = timedelta(days=random.uniform(45, 120)) if m in survivors else timedelta(hours=random.uniform(0.2, 72))
    last = NOW - timedelta(days=random.uniform(0, 3)) if m in survivors else min(start + life, NOW - timedelta(days=8))
    first_price = random.uniform(0.00001, 0.0001)
    high = first_price * random.uniform(3, 40)
    mints[m] = {"symbol": m[-4:], "first_trade_ts": iso(start if m not in survivors else last - life),
                "last_trade_ts": iso(last), "first_price": first_price,
                "last_price": first_price * random.uniform(0.005, 0.05) if m not in survivors else high * 0.6,
                "price_low": first_price * 0.5, "price_high": high, "quote": "SOL"}

wallet_data = {}
for i, w in enumerate(wallets):
    age = (timedelta(hours=random.uniform(1, 23)) if i < 61 else
           timedelta(days=random.uniform(1.5, 6)) if i < 75 else timedelta(days=random.uniform(30, 600)))
    trades = []
    for m in random.sample(prior, random.randint(4, 14)):
        meta = mints[m]
        t0 = datetime.fromisoformat(meta["first_trade_ts"].replace("Z", "+00:00")) + timedelta(minutes=random.uniform(0, 30))
        hold = random.lognormvariate(4.5, 1.0)  # seconds, median ~90
        amt = random.uniform(1e5, 1e7)
        lo, hi = meta["price_low"], meta["price_high"]
        buy_p = meta["first_price"] * random.uniform(1.0, 1.5)
        sell_p = lo + (hi - lo) * min(1.0, random.betavariate(5, 1.3))
        trades.append({"mint": m, "side": "buy", "ts": iso(t0), "token_amount": amt, "price": buy_p, "quote": "SOL"})
        trades.append({"mint": m, "side": "sell", "ts": iso(t0 + timedelta(seconds=hold)), "token_amount": amt,
                       "price": sell_p, "quote": "SOL"})
    holdings = [{"mint": TARGET, "amount": 1}]
    if i % 100 < 47:
        holdings += [{"mint": "ShadowA", "amount": 1}, {"mint": "ShadowB", "amount": 1}, {"mint": "ShadowC", "amount": 1}]
    holdings += [{"mint": random.choice(prior), "amount": 1}]
    wallet_data[w] = {"first_activity": iso(NOW - age), "trades": trades, "holdings": holdings}

siblings = [f"DemoSibling{i}" for i in range(6)]
linked = [f"Linked{i:02d}" for i in range(31)]
for j, m in enumerate(linked):
    start = NOW - timedelta(days=random.uniform(20, 300))
    days = 64 if j == 0 else random.uniform(0.1, 6)
    fp = random.uniform(0.00001, 0.0001)
    mints[m] = {"first_trade_ts": iso(start), "last_trade_ts": iso(start + timedelta(days=days)),
                "first_price": fp, "last_price": fp * random.uniform(0.005, 0.06), "quote": "SOL"}
created = {"DemoCreator": [TARGET] + linked[:5]}
for k, s in enumerate(siblings):
    created[s] = linked[5 + k * 5: 10 + k * 5] + (linked[30:] if k == 5 else [])

OUT.mkdir(exist_ok=True)
amounts = sorted((random.uniform(1e6, 5e7) for _ in wallets), reverse=True)
(OUT / "holders.json").write_text(json.dumps({TARGET: [{"wallet": w, "amount": a} for w, a in zip(wallets, amounts)]}))
(OUT / "wallets.json").write_text(json.dumps(wallet_data))
(OUT / "mints.json").write_text(json.dumps(mints))
(OUT / "funding.json").write_text(json.dumps({
    "first_funder": {"DemoCreator": "DemoFunder"},
    "funded_by": {"DemoFunder": ["DemoCreator", *siblings]},
    "created_by": created,
}))
print(f"wrote {OUT}")
