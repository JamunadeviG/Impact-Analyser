# Impact Analyzer

An intelligent, native Frappe app that acts as your codebase safety net. It answers the question: *"If I change this field or function, what breaks, and how badly?"*

Powered by a hybrid engine of static analysis (AST parsing, AST-based DB scanning) and AI context reasoning via Anthropic Claude.

## Features

- **3 Scan Paths:** AI Interpretation (plain-English prompts), Direct Target (DocType/fields), or Full Scan.
- **File System Pass:** Deep-scans 9 file types including `.py` (AST & Raw SQL), `.js`, `.json`, `hooks.py`, Jinja/HTML templates, and Reports.
- **Database Pass:** Scans 7 DB Customization DocTypes including Server/Client Scripts, Workflows, Custom Fields, Property Setters, and Notifications.
- **AI Validation & Formatting:** Eliminates false positives by verifying DB/File existence, ranks impact severity (High/Medium/Low), and writes a professional executive summary.
- **Glassmorphic UI:** A beautiful, native Frappe Desk Page with realtime progress tracking.

## Installation

```bash
bench get-app https://github.com/your-org/impact_analyser
bench --site my-site install-app impact_analyser
```

## Configuration

Impact Analyzer uses Claude by Anthropic.
1. Go to **Impact Analyzer Settings** in the Awesome Bar.
2. Enter your **Claude API Key** (or set `ANTHROPIC_API_KEY` in your bench environment).
3. Select your AI models (e.g. `claude-3-5-sonnet-20241022`).
4. (Optional) Check **Enable Mock Fallback** to test the UI without making real API calls.

## Usage

1. Open the **App Switcher** and click **Impact Analyzer**.
2. **Path 1 (AI Interpretation)**: Type a prompt like: *"I want to rename customer_name to full_name in Sales Invoice. What breaks?"*
3. **Path 2 (Direct Target)**: Select an App and DocType (e.g., *Sales Invoice*), enter comma-separated field/function names.
4. Click **Analyze Impact**.
5. Watch the realtime stepper progress through 4 stages: Interpreting → Scanning → Drafting → Formatting.
6. Review the generated Impact Report and apply the suggested actions before making your change!

## Technical Stack & Architecture

- **Backend:** Frappe Python (App: `impact_analyser`)
- **Frontend:** Frappe Desk Page (`page/impact_analyzer`) + Vanilla JS / CSS.
- **Database Tracking:** `Impact Analysis Run`, `Impact Analysis Change` (Child Table), `Impact Analyzer Log`.
- **Background Jobs:** Utilizes `frappe.enqueue` and `frappe.publish_realtime`.

## License
MIT
