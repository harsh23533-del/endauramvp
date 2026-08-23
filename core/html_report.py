"""
HTML observability report.
Renders the build's report dict into a single static HTML file so
you can open workspace/build-report.html in a browser and see the
whole build at a glance -- instead of scrolling terminal output
(PDF section 34).
"""
import html


def _esc(text) -> str:
    return html.escape(str(text)) if text is not None else ""


def generate_html_report(report: dict) -> str:
    scores = report.get("scores", {})
    security_result = report.get("security_result", {})
    review_result = report.get("review_result", {})
    critic_result = report.get("critic_result", {})
    trace = report.get("traceability", [])
    gate = report.get("release_gate", {})
    metrics = report.get("metrics", {})

    trace_rows = "".join(
        f"<tr><td>{_esc(t['requirement_id'])}</td><td>{_esc(t['description'])}</td>"
        f"<td>{_esc(t['file'])}</td><td>{_esc(t['status'])}</td></tr>"
        for t in trace
    )

    findings_rows = "".join(
        f"<li>{_esc(f['file'])}:{_esc(f['line'])} -- {_esc(f['issue'])}</li>"
        for f in security_result.get("findings", [])
    )

    issues_rows = "".join(
        f"<li>[{_esc(i.get('severity'))}] {_esc(i.get('file'))}: {_esc(i.get('note'))}</li>"
        for i in review_result.get("issues", [])
    )

    breaks_rows = "".join(
        f"<li>{_esc(b.get('file'))}: {_esc(b.get('scenario'))} -&gt; {_esc(b.get('consequence'))}</li>"
        for b in critic_result.get("breaks_found", [])
    )

    gate_class = "ok" if gate.get("status") == "RELEASE_READY" else "blocked"
    gate_reasons = "".join(f"<li>{_esc(r)}</li>" for r in gate.get("reasons", []))

    metrics_rows = "".join(
        f"<tr><td>{_esc(model)}</td><td>{_esc(stats.get('attempts'))}</td>"
        f"<td>{_esc(stats.get('successes'))}</td><td>{_esc(stats.get('failures'))}</td>"
        f"<td>{_esc(stats.get('latency'))}s</td><td>{_esc(stats.get('tokens'))}</td></tr>"
        for model, stats in metrics.get("by_model", {}).items()
    )

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>AURA Build Report</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, sans-serif; max-width: 900px; margin: 40px auto; padding: 0 20px; color: #1a1a1a; }}
  h1 {{ font-size: 1.5rem; }}
  h2 {{ font-size: 1.1rem; margin-top: 2rem; border-bottom: 1px solid #ddd; padding-bottom: 4px; }}
  .score {{ font-size: 2rem; font-weight: bold; }}
  .score-row {{ display: flex; gap: 24px; margin: 12px 0; }}
  .score-item {{ flex: 1; text-align: center; padding: 12px; background: #f5f5f5; border-radius: 8px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 8px; }}
  th, td {{ text-align: left; padding: 6px 10px; border-bottom: 1px solid #eee; font-size: 0.9rem; }}
  .gate {{ padding: 16px; border-radius: 8px; font-weight: bold; }}
  .gate.ok {{ background: #e6f4ea; color: #1e7e34; }}
  .gate.blocked {{ background: #fdecea; color: #c0392b; }}
  ul {{ margin: 4px 0; padding-left: 20px; }}
  li {{ font-size: 0.9rem; margin: 2px 0; }}
</style>
</head>
<body>
  <h1>AURA Build Report</h1>
  <p><strong>Request:</strong> {_esc(report.get('request'))}</p>

  <h2>AURA Score</h2>
  <div class="score-row">
    <div class="score-item"><div class="score">{_esc(scores.get('overall'))}%</div>Overall</div>
    <div class="score-item">{_esc(scores.get('requirements'))}%<br>Requirements</div>
    <div class="score-item">{_esc(scores.get('tests'))}%<br>Tests</div>
    <div class="score-item">{_esc(scores.get('security'))}%<br>Security</div>
    <div class="score-item">{_esc(scores.get('code_quality'))}%<br>Code Quality</div>
  </div>

  <h2>Release Gate</h2>
  <div class="gate {gate_class}">{_esc(gate.get('status'))}</div>
  <ul>{gate_reasons}</ul>

  <h2>LLM Metrics</h2>
  <div class="score-row">
    <div class="score-item">{_esc(metrics.get('invocations', 0))}<br>Invocations</div>
    <div class="score-item">{_esc(metrics.get('retries', 0))}<br>Retries/Fallbacks</div>
    <div class="score-item">{_esc(metrics.get('total_latency', 0))}s<br>Total Latency</div>
    <div class="score-item">{_esc(metrics.get('total_tokens', 0))}<br>Tokens</div>
  </div>
  <table>
    <tr><th>Model</th><th>Attempts</th><th>OK</th><th>Failed</th><th>Latency</th><th>Tokens</th></tr>
    {metrics_rows or "<tr><td colspan='6'>No LLM calls recorded</td></tr>"}
  </table>

  <h2>Requirement Traceability</h2>
  <table>
    <tr><th>ID</th><th>Description</th><th>File</th><th>Status</th></tr>
    {trace_rows}
  </table>

  <h2>Security Findings</h2>
  <ul>{findings_rows or "<li>None</li>"}</ul>

  <h2>Review Issues</h2>
  <ul>{issues_rows or "<li>None</li>"}</ul>

  <h2>Critic Findings</h2>
  <p>Verdict: <strong>{_esc(critic_result.get('verdict'))}</strong></p>
  <ul>{breaks_rows or "<li>None found</li>"}</ul>

</body>
</html>
"""
