from datetime import datetime, timedelta, timezone

from crowdcheck.models import Holder, MintMeta, Position, Trade

T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def trade(mint, side, seconds, amount, price=None, wallet="W", quote="SOL"):
    return Trade(wallet=wallet, mint=mint, side=side, ts=at(seconds), token_amount=amount, price=price,
                 quote=quote if price is not None else None)


def holders(*wallets):
    return [Holder(wallet=w, amount=1.0) for w in wallets]


def closed_position(seconds, *, mint="M", wallet="W", sell_price=None, quote="SOL"):
    return Position(wallet=wallet, mint=mint, first_buy_ts=T0, last_sell_ts=at(seconds), bought=1, sold=1,
                    avg_sell_price=sell_price, quote=quote, closed=True)


def meta(mint="M", **kw):
    return MintMeta(mint=mint, **kw)
