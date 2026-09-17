import os
import json
import urllib.request
from pathlib import Path
from typing import Dict, Any, List, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except ImportError:
    env_file = Path(__file__).resolve().parents[2] / ".env"
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

try:
    import frappe
    HAS_FRAPPE = True
except ImportError:
    HAS_FRAPPE = False


class AISemanticEvaluator:
    """Evaluates candidate dead code and formats an executive report."""

    def __init__(self, api_key: Optional[str] = None):
        key = api_key or os.environ.get("GROQ_API_KEY") or os.environ.get("GEMINI_API_KEY") or ""
        if not key and HAS_FRAPPE:
            key = frappe.conf.get("groq_api_key") or frappe.conf.get("gemini_api_key") or ""
        self.api_key = key.strip() if key else ""

    def evaluate_findings(self, candidates: List[Dict[str, Any]], project_name: str = "Frappe Bench") -> Dict[str, Any]:
        if not candidates:
            return {
                "dead_count": 0,
                "findings": [],
                "summary": f"### 🤖 AI Code Report for `{project_name}`\n\n✅ **Zero Dead Code!** All scanned controllers and methods are active."
            }

        if not self.api_key:
            return {
                "dead_count": len(candidates),
                "findings": candidates,
                "summary": f"Found {len(candidates)} candidate dead method(s). Add GROQ_API_KEY to .env for AI insights."
            }

        prompt = f"""
You are a senior Frappe Framework auditor.
Evaluate these unreferenced controller methods detected by our AST scanner in '{project_name}':
{json.dumps(candidates, indent=2)}

Format response as JSON:
{{
  "verified_dead_code": [
     {{
       "class": "ClassName",
       "method": "method_name",
       "file": "file_path",
       "line": 1,
       "reason": "Why this method is dead/safe to remove"
     }}
  ],
  "summary": "Short executive summary"
}}
"""
        try:
            req = urllib.request.Request(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "ImpactAnalyser/1.0"
                },
                data=json.dumps({
                    "model": "llama-3.3-70b-versatile",
                    "messages": [
                        {"role": "system", "content": "You are a Frappe code auditor. Output valid JSON only."},
                        {"role": "user", "content": prompt}
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.2
                }).encode("utf-8")
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                content = json.loads(data["choices"][0]["message"]["content"])
                return {
                    "dead_count": len(content.get("verified_dead_code", candidates)),
                    "findings": content.get("verified_dead_code", candidates),
                    "summary": content.get("summary", "")
                }
        except Exception:
            return {
                "dead_count": len(candidates),
                "findings": candidates,
                "summary": f"Identified {len(candidates)} unused controller method(s)."
            }
