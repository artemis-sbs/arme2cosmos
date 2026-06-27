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
    for f in files:
        try:
            out = convert_file(f, args.out)
        except Exception as exc:  # noqa: BLE001
            print(f"!! failed to convert {f}: {exc}", file=sys.stderr)
            continue
        print(f"scaffolded {os.path.basename(f)} -> {out}")
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
    conv.set_defaults(func=_cmd_convert)

    art = sub.add_parser("artmap", help="draft the vesselData<->shipDataBB crosswalk (planned)")
    art.add_argument("path", nargs="?", default=".")
    art.set_defaults(func=_cmd_stub, _name="artmap")

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
