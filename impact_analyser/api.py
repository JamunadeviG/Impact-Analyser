import frappe
from pathlib import Path
from impact_analyser.scanner.dead_code_analyzer import DeadCodeAnalyzer
from impact_analyser.scanner.ai_evaluator import AISemanticEvaluator

@frappe.whitelist()
def start_scan(app=None, **kwargs):
    """Desk UI scan: runs AST scan, enriches with AI, and returns results."""
    apps_path = Path(frappe.get_app_path("frappe")).resolve().parents[1]

    frappe.publish_realtime("scan_progress", {"status": "Scanning Controllers", "progress": 35})
    analyzer = DeadCodeAnalyzer(str(apps_path))
    findings = analyzer.get_dead_code() if hasattr(analyzer, "get_dead_code") else analyzer.scan()

    if app and app != "All":
        findings = [f for f in findings if f"/apps/{app}/" in f.get("file", "")]

    frappe.publish_realtime("scan_progress", {"status": "Organizing Findings with AI", "progress": 75})
    evaluator = AISemanticEvaluator()
    report = evaluator.evaluate_findings(findings, project_name=app or "Frappe Bench")

    result_data = {
        "status": "Completed",
        "total_dead_methods": report.get("dead_count", len(findings)),
        "dead_code": report.get("findings", findings),
        "ai_summary": report.get("summary", ""),
        "results": report.get("findings", findings)
    }

    frappe.publish_realtime("scan_completed", result_data)
    return result_data

@frappe.whitelist()
def run_dead_code_analysis(**kwargs):
    return start_scan(**kwargs)
