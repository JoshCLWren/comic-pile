#!/usr/bin/env python3
"""Generate a human-readable GitHub Pages dashboard for the ComicPile factory."""
from __future__ import annotations

import html
import importlib.util
import json
import os
import sys
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO = os.environ.get("GITHUB_REPOSITORY", "JoshCLWren/comic-pile")
REPO_URL = f"https://github.com/{REPO}"
OUTPUT = Path(os.environ.get("FACTORY_DASHBOARD_OUTPUT", "site/index.html"))
SCRIPTS = Path(__file__).resolve().parent
MANIFEST = Path(__file__).resolve().parents[1] / "free-model-factories.tsv"


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def label_names(item: Mapping[str, Any]) -> set[str]:
    names: set[str] = set()
    for label in item.get("labels") or []:
        if isinstance(label, Mapping):
            name = label.get("name")
        else:
            name = label
        if name:
            names.add(str(name))
    return names


def count_with_label(items: Iterable[Mapping[str, Any]], label: str) -> int:
    return sum(label in label_names(item) for item in items)


def github_search_total(completion_controller: Any, query: str) -> int:
    result = completion_controller.gh_json(
        ["api", "-X", "GET", "search/issues", "-f", f"q=repo:{REPO} {query}", "-f", "per_page=1"]
    )
    if not isinstance(result, Mapping):
        return 0
    return int(result.get("total_count") or 0)


def iso_search_time(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) - delta).strftime("%Y-%m-%dT%H:%M:%SZ")


def latest_completion_funnel(completion_controller: Any) -> dict[str, str]:
    marker = "<!-- factory-completion-funnel:v1 -->"
    for comment in reversed(completion_controller.registry_comments()):
        body = str(comment.get("body") or "")
        if marker not in body:
            continue
        values: dict[str, str] = {}
        for line in body.splitlines():
            if ":" not in line or line.startswith("<!--"):
                continue
            key, value = line.split(":", 1)
            values[key.strip().casefold()] = value.strip()
        return values
    return {}


def collect_snapshot() -> dict[str, Any]:
    completion = load_module("factory_completion_controller_dashboard", SCRIPTS / "factory_completion_controller.py")
    full = load_module("factory_full_completion_controller_dashboard", SCRIPTS / "factory_full_completion_controller.py")
    work = completion.load_controller()

    issues = work.list_issues()
    prs = work.list_prs()
    demand, capacity = full.current_demand(completion)

    workers = completion.load_manifest_workers(MANIFEST)
    owned = completion.owned_worker_ids([*issues, *prs])
    slot_health_counts = capacity.get("slot_health_counts") or {}
    candidate_health_counts = capacity.get("candidate_health_counts") or {}

    hour = iso_search_time(timedelta(hours=1))
    day = iso_search_time(timedelta(hours=24))
    opened_hour = github_search_total(completion, f"is:pr created:>={hour}")
    merged_hour = github_search_total(completion, f"is:pr is:merged merged:>={hour}")
    opened_day = github_search_total(completion, f"is:pr created:>={day}")
    merged_day = github_search_total(completion, f"is:pr is:merged merged:>={day}")
    open_prs = github_search_total(completion, "is:pr is:open")
    open_issues = github_search_total(completion, "is:issue is:open")

    funnel = latest_completion_funnel(completion)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "open_prs": open_prs,
        "open_issues": open_issues,
        "completion_demand": demand.completion,
        "production_demand": demand.production,
        "completion_share": demand.completion_share,
        "completion_target": full.completion_worker_target(demand),
        "configured_workers": len(workers),
        "busy_workers": len(set(workers) & owned),
        "idle_workers": demand.idle_workers,
        "executable_slot_capacity": capacity.get("executable_slot_capacity", 0),
        "healthy_slots": slot_health_counts.get("healthy", 0),
        "degraded_slots": slot_health_counts.get("degraded", 0),
        "cooling_slots": slot_health_counts.get("cooling", 0),
        "unavailable_slots": slot_health_counts.get("unavailable", 0),
        "executable_candidate_count": capacity.get("executable_candidate_count", 0),
        "healthy_candidates": candidate_health_counts.get("healthy", 0),
        "degraded_candidates": candidate_health_counts.get("degraded", 0),
        "cooling_candidates": candidate_health_counts.get("cooling", 0),
        "unavailable_candidates": candidate_health_counts.get("unavailable", 0),
        "pipeline": {
            "review": count_with_label(prs, "factory:review"),
            "changes_requested": count_with_label(prs, "factory:changes-requested"),
            "ci": count_with_label(prs, "factory:ci"),
            "ready": count_with_label(prs, "factory:ready"),
            "unowned": count_with_label(prs, "factory:unowned"),
            "conflict": sum(
                bool({"factory:conflict", "factory:conflicted"} & label_names(pr)) for pr in prs
            ),
        },
        "throughput": {
            "opened_hour": opened_hour,
            "merged_hour": merged_hour,
            "net_hour": opened_hour - merged_hour,
            "opened_day": opened_day,
            "merged_day": merged_day,
            "net_day": opened_day - merged_day,
        },
        "funnel": funnel,
    }


def esc(value: object) -> str:
    return html.escape(str(value))


def signed(value: int) -> str:
    return f"{value:+d}"


def render_dashboard(snapshot: Mapping[str, Any]) -> str:
    pipeline = snapshot["pipeline"]
    throughput = snapshot["throughput"]
    funnel = snapshot.get("funnel") or {}
    completion_pct = round(float(snapshot["completion_share"]) * 100)
    production_pct = 100 - completion_pct if snapshot["completion_demand"] or snapshot["production_demand"] else 0

    cards = [
        ("Open PRs", snapshot["open_prs"], f"{REPO_URL}/pulls"),
        ("Open issues", snapshot["open_issues"], f"{REPO_URL}/issues"),
        ("Completion demand", snapshot["completion_demand"], f"{REPO_URL}/pulls?q=is%3Aopen"),
        ("Production demand", snapshot["production_demand"], f"{REPO_URL}/issues?q=is%3Aopen+is%3Aissue"),
    ]
    card_html = "".join(
        f'<a class="metric" href="{esc(url)}"><span>{esc(label)}</span><strong>{esc(value)}</strong></a>'
        for label, value, url in cards
    )

    pipeline_rows = [
        ("Review", "review", "factory%3Areview"),
        ("Changes requested", "changes_requested", "factory%3Achanges-requested"),
        ("CI", "ci", "factory%3Aci"),
        ("Ready", "ready", "factory%3Aready"),
        ("Unowned", "unowned", "factory%3Aunowned"),
        ("Conflict", "conflict", "factory%3Aconflict"),
    ]
    pipeline_html = "".join(
        f'<a class="row" href="{REPO_URL}/pulls?q=is%3Aopen+label%3A{query}"><span>{label}</span><strong>{esc(pipeline[key])}</strong></a>'
        for label, key, query in pipeline_rows
    )

    funnel_text = "Latest allocator telemetry unavailable"
    if funnel:
        target = funnel.get("completion target") or funnel.get("workers selected") or "?"
        selected = funnel.get("workers selected", "?")
        claimed = funnel.get("pr claims succeeded", "?")
        updated = funnel.get("updated", "unknown")
        funnel_text = f"target {target} · selected {selected} · claims {claimed} · {updated}"

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="300">
<title>ComicPile Factory Status</title>
<style>
:root {{ color-scheme: dark; --bg:#0d1117; --panel:#161b22; --line:#30363d; --text:#f0f6fc; --muted:#8b949e; --good:#3fb950; --warn:#d29922; --bad:#f85149; --link:#58a6ff; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text); font:15px/1.45 ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
main {{ max-width:1180px; margin:0 auto; padding:28px 20px 60px; }}
header {{ display:flex; gap:18px; align-items:flex-end; justify-content:space-between; flex-wrap:wrap; margin-bottom:22px; }}
h1 {{ margin:0; font-size:28px; letter-spacing:-.02em; }}
.sub {{ color:var(--muted); font-size:13px; }}
a {{ color:inherit; text-decoration:none; }}
.metrics {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; }}
.metric,.panel {{ background:var(--panel); border:1px solid var(--line); border-radius:10px; }}
.metric {{ padding:16px; min-height:94px; display:flex; flex-direction:column; justify-content:space-between; }}
.metric:hover,.row:hover {{ border-color:var(--link); }}
.metric span {{ color:var(--muted); }} .metric strong {{ font-size:30px; }}
.grid {{ display:grid; grid-template-columns:1.15fr 1fr 1fr; gap:12px; margin-top:12px; }}
.panel {{ padding:16px; }} h2 {{ font-size:15px; margin:0 0 12px; color:var(--muted); font-weight:600; }}
.ratio {{ display:flex; height:18px; border-radius:99px; overflow:hidden; background:#21262d; margin:12px 0 8px; }}
.ratio .completion {{ width:{completion_pct}%; background:var(--link); }} .ratio .production {{ width:{production_pct}%; background:var(--good); }}
.big {{ font-size:28px; font-weight:700; }} .muted {{ color:var(--muted); }}
.row {{ display:flex; justify-content:space-between; padding:9px 0; border-top:1px solid var(--line); }} .row:first-of-type {{ border-top:0; }}
.good {{ color:var(--good); }} .bad {{ color:var(--bad); }} .warn {{ color:var(--warn); }}
footer {{ margin-top:14px; color:var(--muted); font-size:12px; }}
@media (max-width:850px) {{ .metrics {{ grid-template-columns:repeat(2,1fr); }} .grid {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body><main>
<header><div><h1>🏭 ComicPile Factory</h1><div class="sub">One place to see whether the factory is actually moving.</div></div><div class="sub">Generated {esc(snapshot['generated_at'])} · refreshes every 5 min · <a href="{REPO_URL}/actions">Actions ↗</a></div></header>
<section class="metrics">{card_html}</section>
<section class="grid">
<div class="panel"><h2>Live allocation</h2><div><span class="big">{completion_pct}%</span> completion · <span class="big">{production_pct}%</span> production</div><div class="ratio"><div class="completion"></div><div class="production"></div></div><div class="muted">Target completion workers: <strong>{esc(snapshot['completion_target'])}</strong> from {esc(snapshot['idle_workers'])} currently idle.</div><div class="sub" style="margin-top:12px">{esc(funnel_text)}</div></div>
<div class="panel"><h2>Executable capacity now</h2><div class="row"><span>Executable slots</span><strong class="good">{esc(snapshot['executable_slot_capacity'])}</strong></div><div class="row"><span>Executable provider/models</span><strong class="good">{esc(snapshot['executable_candidate_count'])}</strong></div><div class="row"><span>Candidate health</span><strong>{esc(snapshot['healthy_candidates'])} healthy · {esc(snapshot['degraded_candidates'])} degraded</strong></div><div class="row"><span>Candidate exclusions</span><strong>{esc(snapshot['cooling_candidates'])} cooling · {esc(snapshot['unavailable_candidates'])} unavailable</strong></div><div class="sub" style="margin-top:10px">{esc(snapshot['healthy_slots'])} healthy · {esc(snapshot['degraded_slots'])} degraded · {esc(snapshot['cooling_slots'])} cooling · {esc(snapshot['unavailable_slots'])} unavailable slots</div><div class="sub" style="margin-top:6px">{esc(snapshot['busy_workers'])} busy · {esc(snapshot['idle_workers'])} idle executable · {esc(snapshot['configured_workers'])} configured slots</div></div>
<div class="panel"><h2>PR pipeline</h2>{pipeline_html}</div>
<div class="panel"><h2>Throughput · last hour</h2><div class="row"><span>Opened</span><strong>{esc(throughput['opened_hour'])}</strong></div><div class="row"><span>Merged</span><strong>{esc(throughput['merged_hour'])}</strong></div><div class="row"><span>Net PR change</span><strong class="{'good' if throughput['net_hour'] < 0 else 'bad' if throughput['net_hour'] > 0 else ''}">{signed(int(throughput['net_hour']))}</strong></div></div>
<div class="panel"><h2>Throughput · last 24h</h2><div class="row"><span>Opened</span><strong>{esc(throughput['opened_day'])}</strong></div><div class="row"><span>Merged</span><strong>{esc(throughput['merged_day'])}</strong></div><div class="row"><span>Net PR change</span><strong class="{'good' if throughput['net_day'] < 0 else 'bad' if throughput['net_day'] > 0 else ''}">{signed(int(throughput['net_day']))}</strong></div></div>
<div class="panel"><h2>Raw control plane</h2><a class="row" href="{REPO_URL}/issues/1093"><span>Heartbeat + allocator registry</span><strong>#1093 ↗</strong></a><a class="row" href="{REPO_URL}/actions/workflows/factory-completion-drain.yml"><span>Completion drain</span><strong>workflow ↗</strong></a><a class="row" href="{REPO_URL}/actions/workflows/fixed-model-factory-dispatcher.yml"><span>Main dispatcher</span><strong>workflow ↗</strong></a></div>
</section>
<footer>Read-only projection of GitHub factory state. GitHub labels, leases, workflow state, and allocator policy remain authoritative.</footer>
</main></body></html>"""


def main() -> int:
    snapshot = collect_snapshot()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render_dashboard(snapshot), encoding="utf-8")
    print(json.dumps(snapshot, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
