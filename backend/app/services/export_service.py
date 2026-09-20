"""Benchmark exports: JSON, CSV, Markdown and a standalone HTML report."""

from __future__ import annotations

import csv
import html
import io
import json
import re
from datetime import UTC, datetime
from typing import Any

from app.core.pricing import pricing_metadata
from app.models.benchmark import Benchmark, BenchmarkRun, ResultStatus
from app.services.engine import attach_cost_per_1k

SUPPORTED_FORMATS = ("json", "csv", "markdown", "html")

MEDIA_TYPES = {
    "json": "application/json",
    "csv": "text/csv",
    "markdown": "text/markdown",
    "html": "text/html",
}

EXTENSIONS = {"json": "json", "csv": "csv", "markdown": "md", "html": "html"}

_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")

#: Leading characters that make a spreadsheet treat a cell as a formula rather
#: than text. Prompts, variant names and model responses all reach CSV cells, so
#: any of them could otherwise smuggle in a live formula (``=cmd|'/c calc'!A1``)
#: that executes when the export is opened in Excel.
_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value: Any) -> Any:
    """Neutralise spreadsheet formula injection in a CSV cell.

    Only strings are touched: numbers are written by ``csv`` from real numeric
    types, so a negative cost never picks up the escape. Prefixing with an
    apostrophe is the standard mitigation — Excel and LibreOffice strip it and
    render the original text.
    """
    if isinstance(value, str) and value.startswith(_CSV_FORMULA_PREFIXES):
        return "'" + value
    return value


def _md_cell(value: Any) -> str:
    """Render a value safe to drop into a Markdown table cell.

    A newline would end the row and an unescaped pipe would invent a column, so
    a variant name like ``a|b`` silently corrupts the whole table.
    """
    text = str(value).replace("\\", "\\\\").replace("|", "\\|")
    return " ".join(text.split())


def _md_line(value: Any) -> str:
    """Collapse a value to a single line for use in a Markdown heading."""
    return " ".join(str(value).split())


def safe_filename(name: str, benchmark_id: int, fmt: str) -> str:
    """Build a download filename that cannot escape a directory or inject headers."""
    stem = _UNSAFE_FILENAME.sub("-", name.strip()).strip("-.")[:60] or "benchmark"
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"promptbench-{benchmark_id}-{stem}-{stamp}.{EXTENSIONS[fmt]}"


def _cost_display(value: float | None) -> str:
    return "Pricing unavailable" if value is None else f"${value:.6f}"


def _rows(benchmark: Benchmark, run: BenchmarkRun) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in run.results:
        prompt = benchmark.prompt
        for variant in benchmark.variants:
            if variant.id == result.variant_id:
                prompt = variant.prompt
                break
        evaluation = result.evaluation
        rows.append(
            {
                "benchmark_id": benchmark.id,
                "benchmark_name": benchmark.name,
                "run_id": run.id,
                "result_id": result.id,
                "variant": result.variant_name,
                "prompt": prompt,
                "system_prompt": benchmark.system_prompt or "",
                "provider": result.provider,
                "model": result.model,
                "status": result.status,
                "response": result.response or "",
                "error_code": result.error_code or "",
                "error_message": result.error_message or "",
                "latency_ms": result.latency_ms,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "total_tokens": result.total_tokens,
                "tokens_per_second": result.tokens_per_second,
                "token_source": result.token_source or "",
                "estimated_cost_usd": result.estimated_cost,
                "cost_per_1k_tokens_usd": attach_cost_per_1k(result),
                "finish_reason": result.finish_reason or "",
                "temperature": (result.request_params or {}).get("temperature"),
                "max_tokens": (result.request_params or {}).get("max_tokens"),
                "relevance": evaluation.relevance if evaluation else None,
                "correctness": evaluation.correctness if evaluation else None,
                "conciseness": evaluation.conciseness if evaluation else None,
                "clarity": evaluation.clarity if evaluation else None,
                "overall": evaluation.overall if evaluation else None,
                "evaluation_mode": evaluation.mode if evaluation else "",
                "evaluator_model": (evaluation.evaluator_model or "") if evaluation else "",
                "evaluation_reasoning": (evaluation.reasoning or "") if evaluation else "",
                "timestamp": result.created_at.isoformat(),
            }
        )
    return rows


def export_json(benchmark: Benchmark, run: BenchmarkRun) -> str:
    payload = {
        "exported_at": datetime.now(UTC).isoformat(),
        "generator": "PromptBench",
        "pricing": pricing_metadata(),
        "benchmark": {
            "id": benchmark.id,
            "name": benchmark.name,
            "description": benchmark.description,
            "prompt": benchmark.prompt,
            "system_prompt": benchmark.system_prompt,
            "temperature": benchmark.temperature,
            "max_tokens": benchmark.max_tokens,
            "top_p": benchmark.top_p,
            "evaluation_mode": benchmark.evaluation_mode,
            "tags": list(benchmark.tags or []),
            "created_at": benchmark.created_at.isoformat(),
            "variants": [
                {"id": v.id, "name": v.name, "prompt": v.prompt} for v in benchmark.variants
            ],
        },
        "run": {
            "id": run.id,
            "status": run.status,
            "started_at": run.started_at.isoformat(),
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "duration_ms": run.duration_ms,
            "params": run.params_snapshot,
        },
        "results": _rows(benchmark, run),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def export_csv(benchmark: Benchmark, run: BenchmarkRun) -> str:
    rows = _rows(benchmark, run)
    if not rows:
        return "no results\n"
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows({key: _csv_safe(value) for key, value in row.items()} for row in rows)
    return buffer.getvalue()


def export_markdown(benchmark: Benchmark, run: BenchmarkRun) -> str:
    rows = _rows(benchmark, run)
    pricing = pricing_metadata()
    lines: list[str] = [
        f"# {benchmark.name}",
        "",
        f"*PromptBench export — run #{run.id} — {run.started_at.isoformat()}*",
        "",
    ]
    if benchmark.description:
        lines += [benchmark.description, ""]

    lines += [
        "## Configuration",
        "",
        f"- **Temperature:** {benchmark.temperature}",
        f"- **Max tokens:** {benchmark.max_tokens}",
        f"- **Evaluation:** {benchmark.evaluation_mode}",
        f"- **Status:** {run.status}",
        "",
        "## Prompt",
        "",
        "```text",
        benchmark.prompt,
        "```",
        "",
    ]
    if benchmark.system_prompt:
        lines += ["### System prompt", "", "```text", benchmark.system_prompt, "```", ""]

    lines += [
        "## Summary",
        "",
        "| Variant | Provider | Model | Status | Latency | Tokens | Tok/s | Est. cost | Quality |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        latency = f"{row['latency_ms']} ms" if row["latency_ms"] is not None else "—"
        tokens = row["total_tokens"] if row["total_tokens"] is not None else "—"
        tps = f"{row['tokens_per_second']:.1f}" if row["tokens_per_second"] else "—"
        quality = f"{row['overall']:.1f}" if row["overall"] is not None else "—"
        lines.append(
            f"| {_md_cell(row['variant'])} | {_md_cell(row['provider'])} "
            f"| {_md_cell(row['model'])} | {_md_cell(row['status'])} | "
            f"{latency} | {tokens} | {tps} | {_cost_display(row['estimated_cost_usd'])} | {quality} |"
        )

    lines += ["", f"> Costs are ESTIMATED from a price table dated {pricing['as_of']}.", ""]
    lines += ["## Responses", ""]

    for row in rows:
        lines += [
            f"### {_md_line(row['provider'])} / {_md_line(row['model'])}"
            f" — {_md_line(row['variant'])}",
            "",
        ]
        if row["status"] != ResultStatus.SUCCESS:
            lines += [f"**Failed ({row['error_code']}):** {row['error_message']}", ""]
            continue
        lines += [row["response"], ""]
        if row["overall"] is not None:
            lines += [
                "**Evaluation** — "
                f"relevance {row['relevance']}, correctness {row['correctness']}, "
                f"conciseness {row['conciseness']}, clarity {row['clarity']}, "
                f"overall {row['overall']} ({row['evaluation_mode']})",
                "",
            ]
            if row["evaluation_reasoning"]:
                lines += [f"> {row['evaluation_reasoning']}", ""]
    return "\n".join(lines)


def _html_summary_row(row: dict[str, Any]) -> str:
    esc = html.escape
    ok = row["status"] == ResultStatus.SUCCESS
    latency = "—" if row["latency_ms"] is None else f"{row['latency_ms']} ms"
    tokens = "—" if row["total_tokens"] is None else str(row["total_tokens"])
    tps = f"{row['tokens_per_second']:.1f}" if row["tokens_per_second"] else "—"
    quality = "—" if row["overall"] is None else f"{row['overall']:.1f}"
    return (
        "<tr>"
        f"<td>{esc(str(row['variant']))}</td>"
        f"<td>{esc(row['provider'])}</td>"
        f"<td class='mono'>{esc(row['model'])}</td>"
        f"<td><span class='badge {'ok' if ok else 'bad'}'>{esc(row['status'])}</span></td>"
        f"<td class='num'>{latency}</td>"
        f"<td class='num'>{tokens}</td>"
        f"<td class='num'>{tps}</td>"
        f"<td class='num'>{esc(_cost_display(row['estimated_cost_usd']))}</td>"
        f"<td class='num'>{quality}</td>"
        "</tr>"
    )


def export_html(benchmark: Benchmark, run: BenchmarkRun) -> str:
    """Self-contained dark-themed HTML report (no external assets)."""
    rows = _rows(benchmark, run)
    pricing = pricing_metadata()
    esc = html.escape

    summary_rows = "".join(_html_summary_row(row) for row in rows)

    response_blocks = []
    for r in rows:
        if r["status"] == ResultStatus.SUCCESS:
            body = f"<pre class='response'>{esc(r['response'])}</pre>"
            if r["overall"] is not None:
                body += (
                    "<p class='eval'>relevance "
                    f"{r['relevance']} · correctness {r['correctness']} · conciseness "
                    f"{r['conciseness']} · clarity {r['clarity']} · <strong>overall "
                    f"{r['overall']}</strong> <span class='muted'>({esc(r['evaluation_mode'])})</span></p>"
                )
                if r["evaluation_reasoning"]:
                    body += f"<blockquote>{esc(r['evaluation_reasoning'])}</blockquote>"
        else:
            body = (
                f"<p class='error'><strong>{esc(r['error_code'])}</strong> — "
                f"{esc(r['error_message'])}</p>"
            )
        response_blocks.append(
            f"<section><h3>{esc(r['provider'])} / <span class='mono'>{esc(r['model'])}</span>"
            f" <span class='muted'>— {esc(str(r['variant']))}</span></h3>{body}</section>"
        )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(benchmark.name)} — PromptBench report</title>
<style>
:root {{ color-scheme: dark; --bg:#0a0a0b; --panel:#131316; --line:#26262b; --fg:#e7e7ea; --muted:#8b8b95; --accent:#5b9dff; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; padding:32px 24px; background:var(--bg); color:var(--fg);
  font:14px/1.6 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; }}
main {{ max-width:1100px; margin:0 auto; }}
h1 {{ font-size:22px; margin:0 0 4px; }} h2 {{ font-size:16px; margin:32px 0 12px; }}
h3 {{ font-size:14px; margin:0 0 8px; }}
.muted {{ color:var(--muted); }} .mono {{ font-family:ui-monospace,"SFMono-Regular",Menlo,monospace; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th,td {{ padding:8px 10px; border-bottom:1px solid var(--line); text-align:left; }}
th {{ color:var(--muted); font-weight:500; text-transform:uppercase; font-size:11px; letter-spacing:.04em; }}
td.num {{ text-align:right; font-family:ui-monospace,Menlo,monospace; }}
.badge {{ padding:2px 7px; border-radius:4px; font-size:11px; }}
.badge.ok {{ background:#132a1c; color:#61d095; }} .badge.bad {{ background:#2c1618; color:#f1808a; }}
section {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; margin-bottom:12px; }}
pre {{ white-space:pre-wrap; word-wrap:break-word; margin:0; font-family:ui-monospace,Menlo,monospace; font-size:13px; }}
pre.prompt {{ background:#0e0e11; border:1px solid var(--line); border-radius:6px; padding:12px; }}
.eval {{ color:var(--muted); font-size:12px; margin:12px 0 0; }}
blockquote {{ margin:8px 0 0; padding-left:12px; border-left:2px solid var(--line); color:var(--muted); font-size:12px; }}
.error {{ color:#f1808a; }}
footer {{ margin-top:32px; color:var(--muted); font-size:12px; border-top:1px solid var(--line); padding-top:12px; }}
</style></head><body><main>
<h1>{esc(benchmark.name)}</h1>
<p class="muted">PromptBench report · run #{run.id} · {esc(run.started_at.isoformat())} · status {esc(run.status)}</p>
{f"<p>{esc(benchmark.description)}</p>" if benchmark.description else ""}
<h2>Prompt</h2><pre class="prompt">{esc(benchmark.prompt)}</pre>
{f'<h2>System prompt</h2><pre class="prompt">{esc(benchmark.system_prompt)}</pre>' if benchmark.system_prompt else ""}
<h2>Summary</h2>
<table><thead><tr><th>Variant</th><th>Provider</th><th>Model</th><th>Status</th>
<th style="text-align:right">Latency</th><th style="text-align:right">Tokens</th>
<th style="text-align:right">Tok/s</th><th style="text-align:right">Est. cost</th>
<th style="text-align:right">Quality</th></tr></thead><tbody>{summary_rows}</tbody></table>
<h2>Responses</h2>
{"".join(response_blocks)}
<footer>Costs are ESTIMATED from an operator-maintained price table dated {esc(pricing["as_of"])};
they are not provider billing data. Temperature {benchmark.temperature}, max tokens {benchmark.max_tokens}.</footer>
</main></body></html>"""


def render_export(benchmark: Benchmark, run: BenchmarkRun, fmt: str) -> tuple[str, str, str]:
    """Return ``(content, media_type, filename)`` for ``fmt``."""
    normalised = fmt.strip().lower()
    if normalised in ("md", "markdown"):
        normalised = "markdown"
    if normalised not in SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported export format '{fmt}'. Use: {', '.join(SUPPORTED_FORMATS)}.")

    renderers = {
        "json": export_json,
        "csv": export_csv,
        "markdown": export_markdown,
        "html": export_html,
    }
    content = renderers[normalised](benchmark, run)
    return content, MEDIA_TYPES[normalised], safe_filename(benchmark.name, benchmark.id, normalised)
