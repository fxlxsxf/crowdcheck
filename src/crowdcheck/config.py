"""Every tunable number CROWDCHECK uses lives in this file.

READ THIS FIRST: every threshold, cap and weight below is an arbitrary choice by
the author. None of them is a validated finding, a backtested parameter or an
industry standard. They exist so the output is reproducible and so you can see
exactly which knobs shape it. Change them and the report changes with them.
"""

from __future__ import annotations

from datetime import timedelta

# --- Sample ------------------------------------------------------------------

TOP_N = 100                         # holders analysed by default
HOLDER_SCAN_PAGE_CAP = 10           # pages of 1000 token accounts scanned to rank holders
TRADE_LOOKBACK = timedelta(days=180)  # how far back wallet DEX trades are fetched
WALLET_TRADE_PAGE_CAP = 5           # pages of 100 enhanced transactions per wallet
SIGNATURE_PAGE_CAP = 10             # pages of 1000 signatures when looking for a wallet's first activity
MINT_HISTORY_PAGE_CAP = 20          # pages of 100 swaps when reconstructing a mint's trade history

# Holders whose owner is one of these accounts are pools, vaults or programs,
# not people. Helius additionally drops owners that are not System-program wallets.
EXCLUDED_OWNERS: frozenset[str] = frozenset({
    "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",  # Raydium AMM v4 authority
    "GpMZbSM2GgvTKHJirzeGfMFoaZ8UR2X7F4v8vHTvxFbL",  # Raydium CPMM authority
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",   # Pump.fun program
    "39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg",  # Pump.fun migration account
    "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",   # Orca Whirlpool program
    "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo",   # Meteora DLMM program
})

# --- Metric 1: crowd track record ----------------------------------------------

SURVIVOR_MIN_LIFESPAN = timedelta(days=30)  # last_trade - first_trade must be at least this
SURVIVOR_MAX_STALENESS = timedelta(days=7)  # last_trade must be at most this old
PRIOR_MINT_CAP = 2000                       # total prior mints resolved per run

# --- Metric 2: wallet age ------------------------------------------------------

WALLET_NEW_DAY = timedelta(hours=24)
WALLET_NEW_WEEK = timedelta(days=7)

# --- Metric 3: deployer history ------------------------------------------------

FUNDING_GRAPH_DEPTH = 2           # creator -> funder -> wallets the funder funded
FUNDING_GRAPH_MAX_WALLETS = 50    # hard stop on wallets visited
FUNDER_SCAN_OLDEST_TXS = 5        # oldest transactions inspected to find a wallet's first SOL

# --- Metric 4: overlap ---------------------------------------------------------

OVERLAP_TOP_K = 3
# Held by almost everyone, so sharing them says nothing about a crowd.
OVERLAP_IGNORE_MINTS: frozenset[str] = frozenset({
    "So11111111111111111111111111111111111111112",   # wSOL
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
})

# --- Metrics 5 and 6: positions ------------------------------------------------

POSITION_CLOSED_FRACTION = 0.95   # a position is closed when sells cover this share of buys
FAST_EXIT_SECONDS = 60

# --- Scoring -------------------------------------------------------------------
# The score is a "history score": 100 means the crowd's visible history is long
# and durable, 0 means it is fresh and short-lived. It is NOT a safety rating.
# Each metric maps its raw value to a 0..1 sub-score (see scoring.py, every
# mapping is a straight line between the two anchors below) and is multiplied by
# its weight. Weights sum to 100.

WEIGHTS: dict[str, int] = {
    "track_record": 25,
    "wallet_age": 20,
    "deployer": 15,
    "overlap": 10,
    "hold_time": 15,
    "exit_percentile": 15,
}
MAX_NOT_VISIBLE_FOR_SCORE = 2      # three or more not-visible metrics: no score

SURVIVAL_RATE_FULL = 0.25          # survival rate at or above this scores 1.0
DEPLOYER_OUTCOME_ZERO = -100.0     # median linked-mint outcome (%) that scores 0
DEPLOYER_OUTCOME_FULL = 0.0        # ... and that scores 1
HOLD_TIME_ZERO_SECONDS = 60        # median hold at or below this scores 0 (log scale)
HOLD_TIME_FULL_SECONDS = 7 * 24 * 3600  # median hold at or above this scores 1

# --- Network -------------------------------------------------------------------

HTTP_CONCURRENCY = 8
HTTP_MAX_RETRIES = 5
HTTP_BACKOFF_BASE_SECONDS = 1.0
HTTP_TIMEOUT_SECONDS = 30.0

# --- Cache (seconds a cached answer stays valid) -------------------------------

CACHE_TTL: dict[str, int] = {
    "top_holders": 10 * 60,
    "first_activity": 30 * 24 * 3600,   # a wallet's first activity never changes once found
    "dex_trades": 6 * 3600,
    "holdings": 3600,
    "mint_meta": 3600,
    "mint_creator": 30 * 24 * 3600,
    "first_funder": 30 * 24 * 3600,
    "funded_by": 24 * 3600,
    "created_by": 24 * 3600,
}
