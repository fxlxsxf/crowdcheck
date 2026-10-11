from __future__ import annotations

from rich.console import Console
from rich.table import Table

from ..models import METRIC_LABELS, Report


def render_terminal(report: Report, console: Console | None = None) -> None:
    console = console or Console()
    title = f"CROWD REPORT · ${report.symbol}" if report.symbol else f"CROWD REPORT · {report.mint}"
    console.print(f"\n[bold]{title}[/bold]")
    console.print(f"[dim]{report.mint} · top {report.holders_found} holders · "
                  f"{report.generated_at:%Y-%m-%d %H:%M} UTC[/dim]\n")

    table = Table(show_lines=False, header_style="bold")
    table.add_column("Metric", no_wrap=True)
    table.add_column("Value")
    table.add_column("Coverage", style="dim")
    table.add_column("Weight", justify="right")
    table.add_column("Sub-score", justify="right")
    table.add_column("Points", justify="right")

    for r in report.results:
        c = report.score.contributions[r.name]
        value = r.display if r.visible else f"[yellow]not visible[/yellow] [dim]({r.reason})[/dim]"
        table.add_row(METRIC_LABELS[r.name], value, r.coverage or "", str(c.weight),
                      "-" if c.subscore is None else f"{c.subscore:.2f}",
                      "-" if c.points is None else f"{c.points:.1f}")
    console.print(table)

    s = report.score
    if s.total is None:
        console.print("[yellow]History score: not printed, the sample was too thin "
                      "(three or more metrics not visible).[/yellow]")
    else:
        console.print(f"[bold]History score: {s.total:.0f} / 100[/bold] [dim](points over the visible weight "
                      f"{s.visible_weight}/100; 100 = long durable history, 0 = fresh and short-lived; "
                      "not a safety rating)[/dim]")
    for note in report.notes:
        console.print(f"[dim]note: {note}[/dim]")
    console.print(f"\n[bold]VERDICT:[/bold] {report.verdict}")
    console.print(f"[bold]{report.closing_line}[/bold]\n")
    console.print("[dim]Descriptive report of on-chain history. Not financial advice.[/dim]")
