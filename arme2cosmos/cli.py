"""Command-line interface for arme2cosmos.

Currently exposes ``report`` (read-only coverage). ``convert`` and ``artmap`` are
declared as stubs so the surface is visible but clearly not yet implemented.
"""

from __future__ import annotations

import argparse
import os
import json
import sys

from . import __version__
from .convert import convert_file
from .parser import find_mission_files, parse_file
from .report import analyze, render_corpus, render_mission


def _cmd_report(args: argparse.Namespace) -> int:
    files = find_mission_files(args.path)
    if not files:
        print(f"No mission .xml files found under: {args.path}", file=sys.stderr)
        return 2

    summaries = []
    for f in files:
        try:
            mission = parse_file(f)
        except Exception as exc:  # noqa: BLE001 - report and continue across corpus
            print(f"!! failed to parse {f}: {exc}", file=sys.stderr)
            continue
        summaries.append(analyze(mission))

    if args.json:
        json.dump(summaries, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if len(summaries) == 1:
        print(render_mission(summaries[0], show_kinds=not args.summary))
    else:
        print(render_corpus(summaries))
        if args.detail:
            for s in summaries:
                print()
                print(render_mission(s, show_kinds=True))
    return 0


def _cmd_convert(args: argparse.Namespace) -> int:
    files = find_mission_files(args.path)
    if not files:
        print(f"No mission .xml files found under: {args.path}", file=sys.stderr)
        return 2
    hullmap = None
    if args.hullmap:
        with open(args.hullmap, encoding="utf-8") as hf:
            hullmap = json.load(hf)
    for f in files:
        try:
            out = convert_file(f, args.out, args.lib_version, hullmap, args.event_model)
        except Exception as exc:  # noqa: BLE001
            print(f"!! failed to convert {f}: {exc}", file=sys.stderr)
            continue
        print(f"scaffolded {os.path.basename(f)} -> {out}")
    return 0


def _cmd_artmap(args: argparse.Namespace) -> int:
    from .artmap import generate
    try:
        hullmap, stats = generate(args.vesseldata, args.shipdata)
    except FileNotFoundError as exc:
        print(f"!! {exc}", file=sys.stderr)
        return 2
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(hullmap, f, indent=2)
    print(f"hullmap -> {args.out}")
    print(f"  vessels={stats['vessels']} hulls={stats['hulls']} "
          f"matched={stats['matched']} unmatched={stats['unmatched']}")
    return 0


def _cmd_stub(args: argparse.Namespace) -> int:
    print(f"'{args._name}' is not implemented yet (planned). See A2X_MIGRATION_PLAN.md.",
          file=sys.stderr)
    return 3


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="arme2cosmos",
        description="Artemis 2.8 XML mission -> Cosmos MAST migration assistant.",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    rep = sub.add_parser("report", help="read-only coverage analysis (no files written)")
    rep.add_argument("path", help="a mission .xml, a MISS_ folder, or a parent dir")
    rep.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    rep.add_argument("--summary", action="store_true",
                     help="single mission: omit the per-kind breakdown")
    rep.add_argument("--detail", action="store_true",
                     help="corpus: also print each mission's per-kind breakdown")
    rep.set_defaults(func=_cmd_report)

    conv = sub.add_parser("convert", help="scaffold a Cosmos MAST mission from 2.8 XML")
    conv.add_argument("path", help="a mission .xml, a MISS_ folder, or a parent dir")
    conv.add_argument("--out", default="out", help="output root directory (default: out/)")
    conv.add_argument("--lib-version", default="v1.4.0_dev",
                      help="sbslib/mastlib version tag for story.json (default: v1.4.0_dev)")
    conv.add_argument("--hullmap", default=None,
                      help="hullmap.json (from `artmap`) to resolve real ship art")
    conv.add_argument("--event-model", choices=["hybrid", "linear", "a28_compatible"],
                      default="hybrid",
                      help="hybrid (default): flag-chained scenes stay linear, "
                           "independent events run as concurrent tasks/routes; "
                           "linear: one sequential scene chain; "
                           "a28_compatible: every event becomes its own polling task "
                           "(2.8 flat-event model -- the worst-case faithful fallback)")
    conv.set_defaults(func=_cmd_convert)

    art = sub.add_parser("artmap", help="draft the vesselData<->shipDataBB hull crosswalk")
    art.add_argument("--vesseldata", required=True,
                     help="path to the Artemis 2.8 vesselData.xml")
    art.add_argument("--shipdata", required=True,
                     help="path to the Cosmos shipDataBB.json")
    art.add_argument("--out", default="hullmap.json", help="output hullmap path")
    art.set_defaults(func=_cmd_artmap)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
