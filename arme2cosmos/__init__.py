"""arme2cosmos -- Artemis 2.8 XML mission -> Artemis Cosmos MAST migration assistant.

Stdlib-only. The tool is a *scaffolder*: it gets a mission 80-90% of the way to MAST
and leaves a clear punch-list (``MIGRATION_NOTES.md``) for the human to finish.

This package currently implements the read-only ``report`` (coverage) stage. Parsing
and the coverage model are deliberately separated from any future emit stage so the
analysis is useful on its own.
"""

__version__ = "0.0.1"
