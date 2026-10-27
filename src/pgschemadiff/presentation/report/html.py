"""Render self-contained, offline HTML reports."""

from __future__ import annotations

from datetime import UTC
from html import escape
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pgschemadiff.presentation.report.model import ReportModel, ReportUnit


def _escape(value: object) -> str:
    return escape(str(value), quote=True)


def _badge(level: str) -> str:
    return f'<span class="badge risk-{_escape(level)}">{_escape(level)}</span>'


def _risk_totals(model: ReportModel) -> str:
    items = "".join(
        f"<li>{_badge(level.value)} <span>{_escape(count)}</span></li>"
        for level, count in model.risk_totals
    )
    return f'<ul class="risk-totals">{items}</ul>'


def _rows(model: ReportModel) -> str:
    bundle_report = model.bundle_id is not None
    extra_headers = (
        '<th scope="col">Reversible</th><th scope="col">Reason</th>' if bundle_report else ""
    )
    rows: list[str] = []
    for row in model.rows:
        cells = (
            f"<td>{_escape(row.delta_id)}</td>"
            f"<td>{_badge(row.level.value)}</td>"
            f"<td>{_escape(row.kind)}</td>"
            f"<td>{_escape(row.target)}</td>"
            f"<td>{_escape(row.reason)}</td>"
        )
        if bundle_report:
            reversible = "yes" if row.reversible else "no"
            cells += (
                f"<td>{_escape(reversible)}</td><td>{_escape(row.reversibility_reason or '')}</td>"
            )
        rows.append(f"<tr>{cells}</tr>")
    headers = (
        '<th scope="col">ID</th><th scope="col">Level</th>'
        '<th scope="col">Kind</th><th scope="col">Target</th>'
        f'<th scope="col">Reason</th>{extra_headers}'
    )
    return (
        '<div class="table-scroll"><table><thead><tr>'
        f"{headers}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def _unit_row(unit: ReportUnit) -> str:
    transaction = "transactional" if unit.transactional else "non-transactional"
    delta_ids = ", ".join(unit.delta_ids)
    return (
        f"<tr><td>{_escape(unit.index + 1)}</td><td>{_escape(transaction)}</td>"
        f"<td>{_badge(unit.max_risk.value)}</td><td>{_escape(delta_ids)}</td>"
        f"<td>{_escape(f'{unit.start_line}-{unit.end_line}')}</td></tr>"
    )


def _statement_lines(unit: ReportUnit) -> str:
    lines: list[tuple[int, str]] = []
    for start_line, end_line, sql in unit.statements:
        lines.extend((start_line + offset, line) for offset, line in enumerate(sql.splitlines()))
        lines.append((end_line + 1, ";"))
    return "".join(
        '<span class="sql-line">'
        f'<span class="line-number">{_escape(number)}</span> {_escape(line)}</span>\n'
        for number, line in lines
    )


def _unit_section(unit: ReportUnit) -> str:
    return (
        f'<section class="unit-sql"><h3>Unit {_escape(unit.index + 1)} SQL</h3>'
        f"<pre><code>{_statement_lines(unit)}</code></pre></section>"
    )


def _header(model: ReportModel) -> str:
    generated_at = model.generated_at.astimezone(UTC).isoformat()
    common = (
        "<header><h1>pgschemadiff report</h1>"
        f"<p>Version {_escape(model.tool_version)} · Generated {_escape(generated_at)}</p>"
    )
    if model.bundle_id is not None:
        metadata = (
            "<dl>"
            f"<dt>Bundle ID</dt><dd>{_escape(model.bundle_id)}</dd>"
            f"<dt>Slug</dt><dd>{_escape(model.bundle_slug or '')}</dd>"
            f"<dt>Created</dt><dd>{_escape(model.bundle_created_at or '')}</dd>"
            f"<dt>Delta count</dt><dd>{_escape(model.delta_count or 0)}</dd>"
            "<dt>Overall max risk</dt><dd>"
            f"{_badge(model.overall_max_risk.value if model.overall_max_risk else 'none')}</dd>"
            f"<dt>up.sql SHA-256</dt><dd><code>{_escape(model.up_sql_sha256 or '')}</code></dd>"
            "</dl>"
        )
    else:
        metadata = (
            '<p class="databases">'
            f"<span>Current</span> {_escape(model.source_name or '')}"
            f"<span>Desired</span> {_escape(model.target_name or '')}</p>"
        )
    return f"{common}{metadata}</header>"


def _bundle_units(model: ReportModel) -> str:
    if model.bundle_id is None:
        return ""
    rows = "".join(_unit_row(unit) for unit in model.units)
    sections = "".join(_unit_section(unit) for unit in model.units)
    return (
        "<section><h2>Execution units</h2>"
        '<div class="table-scroll"><table><thead><tr>'
        '<th scope="col">Unit</th><th scope="col">Execution</th>'
        '<th scope="col">Max risk</th><th scope="col">Delta IDs</th>'
        '<th scope="col">up.sql lines</th></tr></thead>'
        f"<tbody>{rows}</tbody></table></div>{sections}</section>"
    )


def render_report(model: ReportModel) -> str:
    """Return a deterministic, self-contained HTML rendering of ``model``."""
    changes = _rows(model) if model.rows else '<p class="empty">No schema changes.</p>'
    footer = (
        "<footer><p>Risk levels are static classifications, not runtime estimates.</p>"
        if model.bundle_id is None
        else "<footer><p>Risk levels are static classifications, not runtime estimates. "
        "<code>down.sql</code> is notes only; no automatic rollback.</p>"
    )
    style = """
    :root{
      color-scheme:light dark;--bg:#f5f7fa;--panel:#fff;--ink:#17202a;
      --muted:#56616f;--line:#d8dee7;--accent:#244d70
    }
    @media(prefers-color-scheme:dark){:root{
      --bg:#111820;--panel:#1a2530;--ink:#e8edf2;--muted:#a9b4c0;
      --line:#34414e;--accent:#9fc7e8
    }}
    *{box-sizing:border-box}
    body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 system-ui,sans-serif}
    main{max-width:1100px;margin:0 auto;padding:clamp(1rem,4vw,3rem)}
    header,section{margin-bottom:2rem}
    h1{font-size:clamp(2rem,5vw,3.5rem);line-height:1.05;margin:.2rem 0}
    h2{font-size:1.35rem;margin-bottom:.8rem}
    header p,.muted{color:var(--muted)}
    .databases span{display:inline-block;margin-left:1.2rem;color:var(--muted)}
    .databases span{font-size:.8rem;text-transform:uppercase;letter-spacing:.08em}
    dl{display:grid;grid-template-columns:max-content 1fr;gap:.35rem 1rem}
    dt{color:var(--muted)}dd{margin:0;overflow-wrap:anywhere}
    .risk-totals{display:flex;flex-wrap:wrap;gap:.6rem;list-style:none;padding:0}
    .risk-totals li{display:flex;gap:.45rem;align-items:center;background:var(--panel)}
    .risk-totals li{border:1px solid var(--line);border-radius:.5rem;padding:.4rem .65rem}
    .badge{display:inline-block;border-radius:999px;padding:.08rem .5rem;font-size:.82rem}
    .badge{font-weight:700;text-transform:capitalize;background:#e1e8ef;color:#17202a}
    .risk-warning{background:#fff0bd;color:#4b3800}
    .risk-dangerous{background:#f5d7b5;color:#542700}
    .risk-destructive,.risk-blocked{background:#f2c9ce;color:#5b1019}
    .risk-none{background:#e1e8ef;color:#17202a}
    table{border-collapse:collapse;width:100%;background:var(--panel)}
    th,td{text-align:left;vertical-align:top;padding:.65rem .75rem}
    th,td{border-bottom:1px solid var(--line)}
    th{color:var(--muted);font-size:.82rem;text-transform:uppercase;letter-spacing:.04em}
    .table-scroll{overflow-x:auto}
    .empty{border-left:3px solid var(--accent);padding:.6rem 1rem;background:var(--panel)}
    pre{overflow:auto;background:var(--panel);border:1px solid var(--line)}
    pre{border-radius:.5rem;padding:1rem;line-height:1.45}
    .line-number{display:inline-block;min-width:3ch;margin-right:1rem;color:var(--muted)}
    .line-number{text-align:right}.sql-line{display:inline-block;min-width:100%}
    footer{border-top:1px solid var(--line);padding-top:.8rem;color:var(--muted)}
    footer{font-size:.9rem}
    @media print{
      body{background:#fff;color:#111;font-size:10pt}main{max-width:none;padding:0}
      header,section,pre,table{break-inside:avoid}
      .badge{border:1px solid #777;background:#fff!important;color:#111!important}
    }
    """
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" '
        "content=\"default-src 'none'; style-src 'unsafe-inline'\">"
        "<title>pgschemadiff report</title><style>"
        f"{style}</style></head><body><main>{_header(model)}"
        f"<section><h2>Risk totals</h2>{_risk_totals(model)}</section>"
        f"<section><h2>Changes</h2>{changes}</section>"
        f"{_bundle_units(model)}{footer}</main></body></html>\n"
    )
