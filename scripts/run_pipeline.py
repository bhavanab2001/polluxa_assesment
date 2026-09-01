"""
CLI entry point for the Polluxa Analytics Pipeline.

Usage:
    python scripts/run_pipeline.py seed         # Generate sample data
    python scripts/run_pipeline.py run          # Full pipeline execution
    python scripts/run_pipeline.py risk         # Run risk model only
    python scripts/run_pipeline.py dq           # Run DQ checks only
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is in sys.path so 'src' can be imported from anywhere
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="polluxa",
    help="Polluxa LinkedIn Agent Analytics Pipeline",
    add_completion=False,
)
console = Console(force_terminal=True, legacy_windows=False)


@app.command()
def run(
    mode: str = typer.Option("full", help="Pipeline mode: full, extract, transform, load"),
) -> None:
    """Run the full ETL pipeline."""
    from src.logging_config import setup_logging

    setup_logging()

    console.print("\n[bold blue]🚀 Polluxa Analytics Pipeline[/bold blue]\n")

    from src.pipeline.orchestrator import PipelineOrchestrator

    orchestrator = PipelineOrchestrator()
    result = orchestrator.run()

    # Display results
    table = Table(title="Pipeline Run Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Run ID", result["run_id"])
    table.add_row("Status", f"[{'green' if result['status'] == 'SUCCESS' else 'yellow'}]{result['status']}[/]")
    table.add_row("Rows Extracted", str(result["rows_extracted"]))
    table.add_row("Rows Loaded", str(result["rows_loaded"]))
    table.add_row("Rows Failed", str(result["rows_failed"]))
    table.add_row("DLQ Count", str(result.get("dlq_count", 0)))
    table.add_row("DQ Score", f"{result.get('dq_score', 'N/A')}")
    table.add_row("Duration", f"{result['duration_seconds']:.2f}s")

    console.print(table)


@app.command()
def risk() -> None:
    """Run the risk model on all agents."""
    from src.logging_config import setup_logging

    setup_logging()

    console.print("\n[bold blue]🔍 Running Risk Model[/bold blue]\n")

    from src.analytics.risk_model import RiskModel
    from src.models import get_session

    session = get_session()
    model = RiskModel(session=session)
    profiles = model.score_all_agents()

    # Display results
    table = Table(title="Agent Risk Profiles")
    table.add_column("Agent ID", style="cyan")
    table.add_column("Name")
    table.add_column("Tier")
    table.add_column("Risk Score", justify="right")
    table.add_column("Risk Level")
    table.add_column("Rec. Invites", justify="right")
    table.add_column("Rec. Messages", justify="right")

    for p in profiles:
        level_color = {"Green": "green", "Amber": "yellow", "Red": "red"}.get(p.risk_level, "white")
        table.add_row(
            p.agent_id,
            p.display_name or "-",
            p.tier_name or "-",
            f"{p.risk_score:.1f}",
            f"[{level_color}]{p.risk_level}[/]",
            str(p.recommended_daily_invites or "-"),
            str(p.recommended_daily_messages or "-"),
        )

    console.print(table)

    for p in profiles:
        if p.risk_level in ("Amber", "Red"):
            console.print(f"\n[yellow]⚠ {p.agent_id}:[/] {p.justification}")


@app.command()
def dq() -> None:
    """Run data quality checks only."""
    from src.logging_config import setup_logging

    setup_logging()

    console.print("\n[bold blue]✅ Running Data Quality Checks[/bold blue]\n")

    from src.models import get_session
    from src.quality.scoring import DQScorer

    session = get_session()
    scorer = DQScorer(session=session, run_id="manual_dq_check")
    score = scorer.run_all_checks()

    threshold = 85.0
    status = "[green]PASSED[/]" if score >= threshold else "[red]FAILED[/]"
    console.print(f"\nComposite DQ Score: [bold]{score:.1f}%[/bold] — {status}")


@app.command()
def seed() -> None:
    """Generate realistic sample data for development/testing."""
    from src.logging_config import setup_logging

    setup_logging()

    console.print("\n[bold blue]🌱 Generating Sample Data[/bold blue]\n")

    from scripts.seed_data import generate_sample_data

    generate_sample_data()

    console.print("[green]✓ Sample data generated successfully![/green]")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="API Host bind address"),
    port: int = typer.Option(8000, help="API Port"),
    reload: bool = typer.Option(False, help="Enable auto-reload"),
) -> None:
    """Start the Real-Time Webhook & Streaming Ingestion API server."""
    import uvicorn

    from src.logging_config import setup_logging

    setup_logging()

    console.print(f"\n[bold green]⚡ Starting Polluxa Real-Time Webhook Server on http://{host}:{port}[/bold green]")
    console.print(f"[cyan]📖 Interactive Swagger API Docs: http://{host}:{port}/docs[/cyan]\n")

    uvicorn.run("src.api.main:app", host=host, port=port, reload=reload)


@app.command(name="import-linkedin")
def import_linkedin(
    connections_file: str = typer.Option(None, "--connections", "-c", help="Path to LinkedIn Connections.csv"),
    invitations_file: str = typer.Option(None, "--invitations", "-i", help="Path to LinkedIn Invitations.csv"),
    agent_name: str = typer.Option("My Real LinkedIn Account", help="Display name for this agent"),
) -> None:
    """Import official personal LinkedIn data export files into PostgreSQL."""
    from src.logging_config import setup_logging
    from src.pipeline.linkedin_importer import LinkedInArchiveImporter

    setup_logging()

    console.print("\n[bold blue]📥 Importing Personal LinkedIn Data Archive[/bold blue]\n")

    importer = LinkedInArchiveImporter(agent_display_name=agent_name)

    if connections_file:
        res = importer.import_connections(connections_file)
        console.print(
            f"[green]✓ Connections imported:[/] {res['leads_added']} leads added, {res['events_added']} events added."
        )

    if invitations_file:
        res = importer.import_invitations(invitations_file)
        console.print(f"[green]✓ Invitations imported:[/] {res['invites_added']} outreach events added.")

    if not connections_file and not invitations_file:
        console.print("[yellow]Please provide either --connections <path> or --invitations <path>.[/yellow]")


@app.command()
def demo() -> None:
    """Run the Part 8 live demonstration proving pipeline resilience and fault tolerance."""
    from scripts.demo_resilience import run_live_demo

    run_live_demo()


if __name__ == "__main__":
    app()
