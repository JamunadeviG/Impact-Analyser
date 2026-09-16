/* =====================================================================
   Impact Analyzer — Desk Page JS
   ===================================================================== */
frappe.pages["impact-analyzer"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Impact Analyzer",
		single_column: true,
	});

	const ia = new ImpactAnalyzerPage(page, wrapper);
	frappe.pages["impact-analyzer"]._ia = ia;
};

frappe.pages["impact-analyzer"].on_page_show = function (wrapper) {
	if (frappe.pages["impact-analyzer"]._ia) {
		frappe.pages["impact-analyzer"]._ia.on_show();
	}
};

// ─────────────────────────────────────────────────────────────────────────────
class ImpactAnalyzerPage {
	constructor(page, wrapper) {
		this.page = page;
		this.wrapper = wrapper;
		this.$main = $(wrapper).find(".page-content");
		this.current_run_id = null;
		this.all_changes = [];
		this.active_filter = "all";

		this._inject_google_font();
		this._render();
		this._bind_events();
		this._subscribe_realtime();
	}

	_inject_google_font() {
		if (!document.getElementById("ia-inter-font")) {
			const link = document.createElement("link");
			link.id = "ia-inter-font";
			link.rel = "stylesheet";
			link.href = "https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap";
			document.head.appendChild(link);
		}
	}

	// ── Render shell ──────────────────────────────────────────────────────────
	_render() {
		this.$main.addClass("ia-page").css({ maxWidth: "900px", margin: "0 auto", padding: "24px 16px" });

		this.$main.html(`
			<!-- HERO -->
			<div class="ia-hero">
				<div class="ia-hero-content">
					<div class="ia-hero-icon">🔍</div>
					<h1>Impact Analyzer</h1>
					<p>Discover what breaks before you make the change. Powered by AI + static analysis.</p>
				</div>
			</div>

			<!-- INPUT CARD -->
			<div class="ia-card" id="ia-input-card">
				<div class="ia-card-title"><span class="ia-dot"></span>Analysis Target</div>
				<div class="ia-form-grid">
					<div class="ia-field">
						<label>App</label>
						<select id="ia-app-select">
							<option value="">— select app —</option>
						</select>
					</div>
					<div class="ia-field">
						<label>DocType Target</label>
						<input id="ia-doctype-input" type="text" placeholder="e.g. Sales Invoice" autocomplete="off" />
						<div id="ia-doctype-suggestions" style="position:relative;"></div>
					</div>
					<div class="ia-field">
						<label>Target Files <span style="opacity:.5;font-weight:400;">(comma-separated, optional)</span></label>
						<input id="ia-files-input" type="text" placeholder="e.g. api.py, hooks.py" />
					</div>
					<div class="ia-field">
						<label>Target Functions / Symbols <span style="opacity:.5;font-weight:400;">(optional)</span></label>
						<input id="ia-functions-input" type="text" placeholder="e.g. get_sales_data, validate" />
					</div>
				</div>

				<div class="ia-or">or describe your change in plain English</div>

				<div class="ia-field ia-field-full">
					<label>Prompt <span style="opacity:.5;font-weight:400;">(AI Interpretation path)</span></label>
					<textarea id="ia-prompt-input" placeholder='e.g. "I want to rename the field customer_name to full_name in Sales Invoice. What will break?"'></textarea>
				</div>

				<hr class="ia-divider" />

				<div class="ia-submit-wrap">
					<span id="ia-path-hint" style="font-size:12px;color:rgba(255,255,255,0.35);"></span>
					<button class="ia-btn ia-btn-primary" id="ia-analyze-btn">
						<span>⚡</span> Analyze Impact
					</button>
				</div>
			</div>

			<!-- PROGRESS CARD (hidden until run starts) -->
			<div class="ia-card" id="ia-progress-card" style="display:none;">
				<div class="ia-card-title"><span class="ia-dot"></span>Analysis Progress</div>
				<div class="ia-stepper" id="ia-stepper">
					<div class="ia-step" data-stage="Interpreting">
						<div class="ia-step-circle">1</div>
						<div class="ia-step-label">Interpreting</div>
					</div>
					<div class="ia-step" data-stage="Scanning">
						<div class="ia-step-circle">2</div>
						<div class="ia-step-label">Scanning</div>
					</div>
					<div class="ia-step" data-stage="Drafting">
						<div class="ia-step-circle">3</div>
						<div class="ia-step-label">Drafting</div>
					</div>
					<div class="ia-step" data-stage="Formatting">
						<div class="ia-step-circle">4</div>
						<div class="ia-step-label">Formatting</div>
					</div>
					<div class="ia-step" data-stage="Complete">
						<div class="ia-step-circle">✓</div>
						<div class="ia-step-label">Complete</div>
					</div>
				</div>
				<div class="ia-progress-wrap">
					<div class="ia-progress-bar" id="ia-progress-bar"></div>
				</div>
				<div class="ia-status-msg" id="ia-status-msg">Queued — starting analysis…</div>
				<div style="text-align:center;margin-top:12px;">
					<a id="ia-run-link" href="#" style="font-size:12px;color:rgba(255,255,255,0.35);text-decoration:none;">
						View Run Document →
					</a>
				</div>
			</div>

			<!-- RESULTS CARD (hidden until complete) -->
			<div class="ia-card" id="ia-results-card" style="display:none;">
				<div class="ia-card-title"><span class="ia-dot"></span>Impact Report</div>

				<div class="ia-summary-header" id="ia-summary-box">
					<h3 id="ia-result-title">Analysis Complete</h3>
					<p id="ia-result-summary"></p>
					<div class="ia-stat-row" id="ia-stat-row"></div>
				</div>

				<div class="ia-filter-bar" id="ia-filter-bar">
					<button class="ia-filter-btn active" data-filter="all">All Changes</button>
					<button class="ia-filter-btn" data-filter="high">🔴 High</button>
					<button class="ia-filter-btn" data-filter="medium">🟠 Medium</button>
					<button class="ia-filter-btn" data-filter="low">🔵 Low</button>
					<button class="ia-filter-btn" data-filter="file">📄 File</button>
					<button class="ia-filter-btn" data-filter="database">🗄 Database</button>
				</div>

				<div class="ia-change-list" id="ia-change-list">
					<div class="ia-empty">
						<div class="ia-empty-icon">📋</div>
						<h4>No changes found</h4>
						<p>No impacted files or database records were detected.</p>
					</div>
				</div>

				<div style="margin-top:20px;text-align:right;">
					<button class="ia-btn ia-btn-ghost" id="ia-new-analysis-btn">
						+ New Analysis
					</button>
				</div>
			</div>
		`);
	}

	// ── Bind events ───────────────────────────────────────────────────────────
	_bind_events() {
		// Load app list
		this._load_apps();

		// Path hint on input
		const update_hint = () => {
			const prompt = $("#ia-prompt-input").val().trim();
			const doctype = $("#ia-doctype-input").val().trim();
			const files = $("#ia-files-input").val().trim();
			const fns = $("#ia-functions-input").val().trim();
			let hint = "";
			if (prompt) hint = "🤖 Path: AI Interpretation";
			else if (doctype || files || fns) hint = "🎯 Path: Direct Target";
			else hint = "🔭 Path: Full Scan";
			$("#ia-path-hint").text(hint);
		};
		this.$main.on("input", "input, textarea, select", update_hint);
		update_hint();

		// DocType autocomplete
		let dt_timeout;
		$("#ia-doctype-input").on("input", function () {
			clearTimeout(dt_timeout);
			const q = $(this).val().trim();
			if (q.length < 2) { $("#ia-doctype-suggestions").html(""); return; }
			dt_timeout = setTimeout(() => {
				frappe.call({
					method: "frappe.client.get_list",
					args: { doctype: "DocType", filters: [["name", "like", `%${q}%`]], fields: ["name"], limit: 8 },
					callback(r) {
						if (!r.message) return;
						const items = r.message.map(d =>
							`<div class="ia-dt-opt" style="padding:8px 14px;cursor:pointer;font-size:13px;
							color:#94a3b8;background:rgba(15,23,42,0.95);border-bottom:1px solid rgba(255,255,255,0.06);"
							data-val="${d.name}">${d.name}</div>`
						).join("");
						$("#ia-doctype-suggestions").html(
							`<div style="position:absolute;top:2px;left:0;right:0;z-index:100;
							border:1px solid rgba(255,255,255,0.12);border-radius:8px;overflow:hidden;">${items}</div>`
						);
					},
				});
			}, 250);
		});
		$(document).on("click", ".ia-dt-opt", function () {
			$("#ia-doctype-input").val($(this).data("val"));
			$("#ia-doctype-suggestions").html("");
		});
		$(document).on("click", function (e) {
			if (!$(e.target).closest("#ia-doctype-input, #ia-doctype-suggestions").length) {
				$("#ia-doctype-suggestions").html("");
			}
		});

		// Analyze button
		$("#ia-analyze-btn").on("click", () => this._submit());

		// Filter buttons
		$(document).on("click", ".ia-filter-btn", (e) => {
			$(".ia-filter-btn").removeClass("active");
			$(e.currentTarget).addClass("active");
			this.active_filter = $(e.currentTarget).data("filter");
			this._render_changes();
		});

		// Expand/collapse change rows
		$(document).on("click", ".ia-change-header", function () {
			$(this).closest(".ia-change-item").toggleClass("open");
		});

		// New analysis
		$(document).on("click", "#ia-new-analysis-btn", () => this._reset());
	}

	// ── Load app list ─────────────────────────────────────────────────────────
	_load_apps() {
		frappe.call({
			method: "frappe.client.get_list",
			args: { doctype: "Module Def", fields: ["app_name"], limit: 50 },
			callback: (r) => {
				if (!r.message) return;
				const apps = [...new Set(r.message.map(m => m.app_name))].sort();
				const $sel = $("#ia-app-select");
				apps.forEach(a => $sel.append(`<option value="${a}">${a}</option>`));
			},
		});
	}

	// ── Submit analysis ───────────────────────────────────────────────────────
	_submit() {
		const app = $("#ia-app-select").val();
		const doctype = $("#ia-doctype-input").val().trim();
		const filenames = $("#ia-files-input").val().trim();
		const functions = $("#ia-functions-input").val().trim();
		const prompt = $("#ia-prompt-input").val().trim();

		if (!app && !doctype && !filenames && !functions && !prompt) {
			frappe.msgprint({
				title: "Missing Input",
				message: "Please select an app, specify a target, or enter a prompt.",
				indicator: "orange",
			});
			return;
		}

		// Show progress card, hide input and results
		$("#ia-input-card").hide();
		$("#ia-results-card").hide();
		$("#ia-progress-card").show();
		this._set_progress(0, "Queued", "Queued — sending to background worker…");
		$("#ia-analyze-btn").prop("disabled", true);

		frappe.call({
			method: "impact_analyser.api.analyze",
			args: { app, doctype, filenames, functions, prompt },
			callback: (r) => {
				if (r.exc || !r.message) {
					this._set_failed("Failed to queue analysis. Check console for details.");
					return;
				}
				const { run_id } = r.message;
				this.current_run_id = run_id;
				$("#ia-run-link")
					.attr("href", `/app/impact-analysis-run/${run_id}`)
					.text(`View Run ${run_id} →`);
				this._set_progress(5, "Queued", `Run ${run_id} queued — waiting for worker…`);
			},
			error: (r) => {
				this._set_failed("Server error — check error log.");
			},
		});
	}

	// ── Realtime subscription ─────────────────────────────────────────────────
	_subscribe_realtime() {
		frappe.realtime.on("impact_analyzer_progress", (data) => {
			if (data.run_id !== this.current_run_id) return;

			const stage_progress = {
				Queued: 5,
				Interpreting: 20,
				Scanning: 45,
				Drafting: 70,
				Formatting: 90,
				Complete: 100,
				Failed: 100,
			};

			const pct = stage_progress[data.status] || 0;
			const msg = data.message || `Status: ${data.status}`;

			if (data.status === "Failed") {
				this._set_failed(msg);
			} else if (data.status === "Complete") {
				this._set_progress(100, "Complete", "✓ Analysis complete — loading report…");
				setTimeout(() => this._load_report(data.run_id), 800);
			} else {
				this._set_progress(pct, data.status, msg);
			}
		});
	}

	// ── Progress helpers ──────────────────────────────────────────────────────
	_set_progress(pct, active_stage, msg) {
		$("#ia-progress-bar").css("width", `${pct}%`);
		$("#ia-status-msg").text(msg);

		const stages = ["Interpreting", "Scanning", "Drafting", "Formatting", "Complete"];
		const active_idx = stages.indexOf(active_stage);

		$(".ia-step").each(function (i) {
			const $s = $(this);
			$s.removeClass("active done failed");
			if (active_stage === "Failed") {
				if (i < active_idx) $s.addClass("done");
				else if (i === active_idx) $s.addClass("failed");
			} else {
				if (i < active_idx) $s.addClass("done");
				else if (i === active_idx) $s.addClass("active");
			}
		});
	}

	_set_failed(msg) {
		this._set_progress(100, "Formatting", msg);
		$(".ia-step").last().prev().addClass("failed").removeClass("active done");
		$("#ia-status-msg").css("color", "#f87171").text("❌ " + msg);
		$("#ia-analyze-btn").prop("disabled", false);
		// Show input card again after 2s
		setTimeout(() => {
			$("#ia-progress-card").hide();
			$("#ia-input-card").show();
		}, 3000);
	}

	// ── Load and render report ────────────────────────────────────────────────
	_load_report(run_id) {
		frappe.call({
			method: "frappe.client.get",
			args: { doctype: "Impact Analysis Run", name: run_id },
			callback: (r) => {
				if (!r.message) return;
				const run = r.message;
				this.all_changes = run.changes || [];
				this._render_report(run);
				$("#ia-progress-card").hide();
				$("#ia-results-card").show();
			},
		});
	}

	_render_report(run) {
		// Summary
		const summary_text = run.summary
			? run.summary.replace(/<[^>]+>/g, "")  // strip html tags
			: "Analysis complete. Review the changes below.";
		$("#ia-result-title").text(`Impact Report — ${run.name}`);
		$("#ia-result-summary").text(summary_text.slice(0, 280) + (summary_text.length > 280 ? "…" : ""));

		// Stats
		const changes = run.changes || [];
		const high = changes.filter(c => c.impact === "High").length;
		const med  = changes.filter(c => c.impact === "Medium").length;
		const low  = changes.filter(c => c.impact === "Low").length;
		$("#ia-stat-row").html(`
			<div class="ia-stat"><div class="ia-stat-num" style="color:#f87171;">${high}</div><div class="ia-stat-lbl">High Impact</div></div>
			<div class="ia-stat"><div class="ia-stat-num" style="color:#fb923c;">${med}</div><div class="ia-stat-lbl">Medium Impact</div></div>
			<div class="ia-stat"><div class="ia-stat-num" style="color:#60a5fa;">${low}</div><div class="ia-stat-lbl">Low Impact</div></div>
			<div class="ia-stat"><div class="ia-stat-num">${changes.length}</div><div class="ia-stat-lbl">Total Changes</div></div>
		`);

		this._render_changes();
	}

	_render_changes() {
		const filter = this.active_filter;
		let changes = this.all_changes;
		if (filter === "high")     changes = changes.filter(c => c.impact === "High");
		else if (filter === "medium")   changes = changes.filter(c => c.impact === "Medium");
		else if (filter === "low")      changes = changes.filter(c => c.impact === "Low");
		else if (filter === "file")     changes = changes.filter(c => c.source === "File");
		else if (filter === "database") changes = changes.filter(c => c.source === "Database");

		const $list = $("#ia-change-list").empty();

		if (!changes.length) {
			$list.html(`<div class="ia-empty">
				<div class="ia-empty-icon">✅</div>
				<h4>No changes match this filter</h4>
				<p>Try a different filter or check all changes.</p>
			</div>`);
			return;
		}

		// Sort: High → Medium → Low
		const order = { High: 0, Medium: 1, Low: 2 };
		changes = [...changes].sort((a, b) => (order[a.impact] || 0) - (order[b.impact] || 0));

		changes.forEach((c, idx) => {
			const impact_cls = (c.impact || "Low").toLowerCase();
			const source_cls = (c.source || "File").toLowerCase();
			const impact_lbl = c.impact || "Low";
			const source_lbl = c.source || "File";
			const file_parts = (c.file || "unknown").split("/");
			const file_short = file_parts.slice(-2).join("/");
			const file_dir = file_parts.slice(0, -2).join("/");
			const line_txt = c.line ? `:${c.line}` : "";

			$list.append(`
				<div class="ia-change-item" data-idx="${idx}">
					<div class="ia-change-header">
						<span class="ia-badge ia-badge-${impact_cls}">${impact_lbl}</span>
						<span class="ia-badge ia-badge-${source_cls}">${source_lbl}</span>
						<span class="ia-change-file">
							<span style="opacity:.4;">${file_dir ? file_dir + "/" : ""}</span><span>${file_short}${line_txt}</span>
						</span>
						${c.usage_type ? `<span class="ia-change-type">${c.usage_type}</span>` : ""}
						<span class="ia-change-expand">›</span>
					</div>
					<div class="ia-change-body">
						${c.reason ? `<div class="ia-change-reason">📌 ${c.reason}</div>` : ""}
						${c.suggested_action ? `<div class="ia-change-action">💡 <strong>Suggested:</strong> ${c.suggested_action}</div>` : ""}
						${c.snippet ? `<div class="ia-snippet">${frappe.utils.escape_html(c.snippet)}</div>` : ""}
					</div>
				</div>
			`);
		});
	}

	// ── Reset form ────────────────────────────────────────────────────────────
	_reset() {
		this.current_run_id = null;
		this.all_changes = [];
		this.active_filter = "all";
		$(".ia-filter-btn").removeClass("active").first().addClass("active");
		$("#ia-app-select").val("");
		$("#ia-doctype-input, #ia-files-input, #ia-functions-input, #ia-prompt-input").val("");
		$("#ia-path-hint").text("");
		$("#ia-results-card, #ia-progress-card").hide();
		$("#ia-input-card").show();
		$("#ia-analyze-btn").prop("disabled", false);
		$("#ia-progress-bar").css("width", "0%");
		$("#ia-status-msg").text("").css("color", "");
		$(".ia-step").removeClass("active done failed");
		$("#ia-run-link").attr("href", "#").text("");
	}

	on_show() {
		// nothing extra needed on page re-show
	}
}
