"""crowdcheck MINT  ->  terminal table + PNG card."""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import timedelta
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from . import config
from .cache import Cache
from .errors import CrowdcheckError, MissingApiKey
from .models import parse_ts
from .pipeline import RunOptions, run
from .providers import build_provider
from .providers.cached import CachedProvider
from .render.card import render_card
from .render.terminal import render_terminal

app = typer.Typer(add_completion=False, help="Audit the crowd holding a Solana token, not the contract.")
err = Console(stderr=True)

MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
DEFAULT_CACHE = Path(os.environ.get("CROWDCHECK_CACHE", Path.home() / ".cache" / "crowdcheck" / "cache.sqlite"))

KEY_HELP = {
    "HELIUS_API_KEY": "get a free key at https://dashboard.helius.dev and run: export HELIUS_API_KEY=your_key",
    "BIRDEYE_API_KEY": "get a key at https://bds.birdeye.so and run: export BIRDEYE_API_KEY=your_key",
}


@app.command()
def main(
    mint: str = typer.Argument(..., help="Token mint address."),
    top: int = typer.Option(config.TOP_N, "--top", min=1, max=1000, help="Number of top holders to analyse."),
    provider: str = typer.Option("helius", "--provider", help="helius, birdeye or mock."),
    fixtures: Optional[Path] = typer.Option(None, "--fixtures", help="Fixture directory for --provider mock."),
    funding_graph: bool = typer.Option(True, "--funding-graph/--no-funding-graph",
                                       help="Walk the deployer's funding graph (metric 3)."),
    png: Optional[Path] = typer.Option(None, "--png", help="Where to write the card. Default: crowdcheck-<ticker>.png"),
    no_png: bool = typer.Option(False, "--no-png", help="Skip the PNG card."),
    json_out: Optional[Path] = typer.Option(None, "--json", help="Also write the full report as JSON."),
    cache_path: Path = typer.Option(DEFAULT_CACHE, "--cache", help="SQLite cache file."),
    no_cache: bool = typer.Option(False, "--no-cache", help="Do not read or write the disk cache."),
    max_prior_mints: int = typer.Option(config.PRIOR_MINT_CAP, "--max-prior-mints", min=1),
    lookback_days: int = typer.Option(config.TRADE_LOOKBACK.days, "--lookback-days", min=1),
    as_of: Optional[str] = typer.Option(None, "--as-of", help="Evaluate as of this UTC time (ISO 8601). "
                                        "Useful with fixtures; defaults to now."),
) -> None:
    """Paste a mint. Get one card describing what its holders have done before."""
    if not MINT_RE.match(mint):
        err.print(f"[red]error:[/red] {mint!r} does not look like a Solana mint address")
        raise typer.Exit(2)

    try:
        backend = build_provider(provider, fixtures=fixtures)
    except MissingApiKey as exc:
        err.print(f"[red]error:[/red] {exc.variable} is not set.")
        err.print(KEY_HELP.get(exc.variable, ""))
        raise typer.Exit(2) from None
    except CrowdcheckError as exc:
        err.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(2) from None

    now = parse_ts(as_of) if as_of else None
    if as_of and now is None:
        err.print(f"[red]error:[/red] --as-of {as_of!r} is not an ISO 8601 time")
        raise typer.Exit(2)

    cache = None if no_cache else Cache(cache_path)
    cached = CachedProvider(backend, cache)
    opts = RunOptions(top_n=top, funding_graph=funding_graph, prior_mint_cap=max_prior_mints,
                      lookback=timedelta(days=lookback_days), now=now)

    async def go():
        try:
            return await run(cached, mint, opts)
        finally:
            await cached.aclose()

    try:
        with err.status("reading the room…"):
            report = asyncio.run(go())
    except CrowdcheckError as exc:
        err.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(1) from None
    finally:
        if cache:
            cache.close()

    render_terminal(report)
    if json_out:
        json_out.write_text(json.dumps(report.to_dict(), indent=2))
    if not no_png:
        out = png or Path(f"crowdcheck-{report.symbol or mint[:8]}.png")
        render_card(report, out)
        Console().print(f"card written to {out}")


if __name__ == "__main__":
    app()
