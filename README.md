# arme2cosmos

A migration **assistant** that helps port legacy **Artemis 2.8** XML missions
(`MISS_*.xml`) to **Artemis Cosmos** MAST. It is a *scaffolder*, not a perfect
compiler: the goal is to get a mission 80–90% of the way to MAST and leave a clear
punch-list for the human to finish.

Stdlib-only (no pip dependencies). Python 3.10+.

> Design and rationale: see `A2X_MIGRATION_PLAN.md` in the `sbs_utils` repo.

## Status

Implemented:
- **`report`** — read-only coverage analysis. Parses a mission (or a whole corpus),
  classifies every command/condition against the 2.8→MAST mapping table, and prints a
  confidence meter + punch-list. Writes nothing.
- **`convert`** — scaffold a Cosmos MAST mission (`story.mast`, `script.py`,
  `story.json`, `description.yaml`, `MIGRATION_NOTES.md`). The create family translates
  to real `a2x_*` calls; everything else is `# TODO`-marked with the original XML
  inline and collected into the notes. Events become a linear chain of `---` labels.

- **`artmap`** — draft the `vesselData.xml` ↔ `shipDataBB.json` hull crosswalk
  (`hullmap.json`) by fuzzy-matching race + classname. Pass it to `convert --hullmap`
  to resolve real ship art instead of placeholders.

## Usage

```sh
# Single mission, full per-kind breakdown
python -m arme2cosmos report path/to/MISS_Foo/MISS_Foo.xml

# A whole corpus (recurses, dedups case-insensitively, skips ~backups)
python -m arme2cosmos report path/to/a28/dat/missions

# Machine-readable
python -m arme2cosmos report <path> --json

# Scaffold a mission (or a whole corpus) into out/
python -m arme2cosmos convert path/to/MISS_Foo --out out/
```

Coverage statuses: `full` (mechanical), `partial` (emits a `# TODO`), `manual`
(needs a human / chosen new path — comms buttons, Game Master, tags), `unknown`
(not in the mapping table yet — should stay at 0).

## Layout

```
arme2cosmos/
├── model.py      # typed mission model (Mission / Event / XmlNode)
├── parser.py     # tolerant ElementTree parser; corpus discovery
├── coverage.py   # the 2.8 XML -> Cosmos MAST mapping/coverage table
├── report.py     # coverage analysis + renderers (mission / corpus)
├── cli.py        # argparse CLI
└── __main__.py
tests/            # stdlib unittest (no pip): python -m unittest discover -s tests
```

## Tests

```sh
python -m unittest discover -s tests
```
