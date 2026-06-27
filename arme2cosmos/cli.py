"""Command-line interface for arme2cosmos.

Currently exposes ``report`` (read-only coverage). ``convert`` and ``artmap`` are
declared as stubs so the surface is visible but clearly not yet implemented.
"""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
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

    for name, help_text in (("convert", "scaffold a Cosmos MAST mission (planned)"),
                            ("artmap", "draft the vesselData<->shipDataBB crosswalk (planned)")):
        s = sub.add_parser(name, help=help_text)
        s.add_argument("path", nargs="?", default=".")
        s.set_defaults(func=_cmd_stub, _name=name)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
