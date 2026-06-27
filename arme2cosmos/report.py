"""Read-only coverage report for one or many parsed missions.

Tallies every command/condition by ``kind_key``, joins with :mod:`coverage`, and
renders a human summary plus an optional machine-readable dict. No translation, no
file output -- this is the confidence meter and punch-list that comes *before* any
emit stage.
"""

from __future__ import annotations

from collections import Counter

from .coverage import STATUS_ORDER, UNKNOWN, classify
from .model import Mission


def analyze(mission: Mission) -> dict:
    """Return a structured coverage summary for a single mission."""
    by_kind: Counter[str] = Counter()
    for node in mission.all_nodes():
        by_kind[node.kind_key()] += 1

    status_counts: Counter[str] = Counter()
    kinds: list[dict] = []
    for kind, count in sorted(by_kind.items(), key=lambda kv: (-kv[1], kv[0])):
        cov = classify(kind)
        status_counts[cov.status] += count
        kinds.append(
            {"kind": kind, "count": count, "status": cov.status, "note": cov.note}
        )

    total = sum(by_kind.values())
    return {
        "mission": mission.name,
        "source": mission.source_path,
        "events": len(mission.events),
        "start_commands": len(mission.start),
        "total_nodes": total,
        "distinct_kinds": len(by_kind),
        "status_counts": dict(status_counts),
        "kinds": kinds,
    }


def _bar(status_counts: dict, total: int) -> str:
    if not total:
        return ""
    parts = []
    for st in STATUS_ORDER:
        n = status_counts.get(st, 0)
        if n:
            parts.append(f"{st}={n}")
    return "  ".join(parts)


def render_mission(summary: dict, *, show_kinds: bool = True) -> str:
    lines = []
    lines.append(f"== {summary['mission']} ==")
    lines.append(
        f"   events={summary['events']}  start_cmds={summary['start_commands']}  "
        f"nodes={summary['total_nodes']}  distinct={summary['distinct_kinds']}"
    )
    lines.append(f"   {_bar(summary['status_counts'], summary['total_nodes'])}")
    if show_kinds:
        lines.append(f"   {'COUNT':>5}  {'STATUS':<8}  KIND")
        for k in summary["kinds"]:
            flag = "  <-- unmapped" if k["status"] == UNKNOWN else ""
            lines.append(
                f"   {k['count']:>5}  {k['status']:<8}  {k['kind']}{flag}"
            )
    return "\n".join(lines)


def render_corpus(summaries: list[dict]) -> str:
    """A one-line-per-mission overview plus an aggregate footer."""
    lines = []
    header = f"{'MISSION':<28} {'NODES':>6} {'EVENTS':>6}  COVERAGE"
    lines.append(header)
    lines.append("-" * len(header))
    agg: Counter[str] = Counter()
    agg_total = 0
    unknown_kinds: Counter[str] = Counter()
    for s in summaries:
        lines.append(
            f"{s['mission'][:28]:<28} {s['total_nodes']:>6} {s['events']:>6}  "
            f"{_bar(s['status_counts'], s['total_nodes'])}"
        )
        for st, n in s["status_counts"].items():
            agg[st] += n
        agg_total += s["total_nodes"]
        for k in s["kinds"]:
            if k["status"] == UNKNOWN:
                unknown_kinds[k["kind"]] += k["count"]
    lines.append("-" * len(header))
    lines.append(f"{'TOTAL (' + str(len(summaries)) + ' missions)':<28} {agg_total:>6} "
                 f"{sum(s['events'] for s in summaries):>6}  {_bar(dict(agg), agg_total)}")
    mapped = agg.get("full", 0) + agg.get("partial", 0)
    if agg_total:
        lines.append(
            f"\nMapped (full+partial): {mapped}/{agg_total} "
            f"({100 * mapped / agg_total:.0f}%)  |  manual: {agg.get('manual', 0)}  "
            f"unknown: {agg.get('unknown', 0)}"
        )
    if unknown_kinds:
        lines.append("\nUnmapped kinds across corpus (add to coverage table):")
        for kind, n in unknown_kinds.most_common():
            lines.append(f"   {n:>4}  {kind}")
    return "\n".join(lines)
