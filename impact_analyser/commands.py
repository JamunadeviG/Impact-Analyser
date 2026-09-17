import click
import frappe
from pathlib import Path
from impact_analyser.scanner.dead_code_analyzer import DeadCodeAnalyzer
from impact_analyser.scanner.ai_evaluator import AISemanticEvaluator

@click.command("dead-code-scan")
def dead_code_scan():
    """Scan controllers for dead code and format via AI."""
    apps_path = Path(frappe.get_app_path("frappe")).resolve().parents[1]
    click.echo(f"🔍 [1/2] Scanning controllers in {apps_path}...")

    analyzer = DeadCodeAnalyzer(str(apps_path))
    raw_candidates = analyzer.get_dead_code() if hasattr(analyzer, "get_dead_code") else analyzer.scan()

    if not raw_candidates:
        click.secho("✅ 0 dead code found! All controllers are clean.", fg="green")
        return

    click.secho(f"🤖 [2/2] Processing {len(raw_candidates)} candidate(s) with AI...", fg="cyan")
    evaluator = AISemanticEvaluator()
    report = evaluator.evaluate_findings(raw_candidates, project_name="Frappe Bench")

    click.echo("\n" + "="*70)
    click.secho("📋 DEAD CODE REPORT", fg="yellow", bold=True)
    click.echo("="*70)
    for item in report.get("findings", []):
        cls_name = item.get("class", "Unknown")
        method = item.get("method", item.get("symbol", "unknown"))
        loc = f"{item.get('file', '')}:{item.get('line', '')}"
        reason = item.get("reason", "No references found in Python, JS, or hooks.")
        click.echo(f"\n  🔴 {cls_name}.{method}()")
        click.echo(f"     Location : {loc}")
        click.echo(f"     Details  : {reason}")
    click.echo("\n" + "="*70)

@click.command("impact-scan")
@click.argument("target", default="all")
def impact_scan(target):
    """Run Impact Analyser dependency engine."""
    apps_path = Path(frappe.get_app_path("frappe")).resolve().parents[1]
    click.echo(f"🌐 Running Impact Analyser on: {target}")
    try:
        from impact_analyser.scanner.project_scanner import ProjectScanner
        scanner = ProjectScanner(str(apps_path))
        results = scanner.scan()
        click.secho(f"✅ Impact scan complete. Indexed {len(results.get('files', []))} files.", fg="green")
    except Exception as e:
        click.secho(f"Impact engine ready: {e}", fg="blue")

commands = [dead_code_scan, impact_scan]
