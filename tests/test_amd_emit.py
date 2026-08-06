"""What the AMD emitter writes, at the record level.

`convert_file` covers the end-to-end shape; this covers the one record's rendering
where a detail is easy to lose - the 2.8 provenance, which is invisible in the
converted mission by design and therefore invisible in a whole-file assertion too.
"""
import unittest

from arme2cosmos.amd_emit import Quest


def _quest(title, source_name=None, **kw):
    q = Quest("job_key", title)
    if source_name is not None:
        q.source_name = source_name
    for k, v in kw.items():
        setattr(q, k, v)
    return q


class ProvenanceSynopsisTests(unittest.TestCase):
    """`= 2.8 event: <name>` - where a converted record CAME FROM.

    `_quest_title` rewrites the title for readability, so without this the raw 2.8
    event name is lost and there is no way back to the source mission. A `= `
    synopsis is author-only: it shows in hover and the outline and never reaches a
    player, which is exactly the right place for a machine's note to a human."""

    def test_emitted_when_the_title_was_rewritten(self):
        out = _quest("Ramscoop Begin", "Ramscoop Begin 1").render()
        self.assertIn("= 2.8 event: Ramscoop Begin 1", out)

    def test_sits_above_the_fence_so_the_fence_still_opens(self):
        lines = _quest("Ramscoop Begin", "Ramscoop Begin 1",
                       goal="signal done").render().splitlines()
        self.assertTrue(lines[0].startswith("# ["))
        self.assertTrue(lines[1].startswith("= "))
        self.assertEqual(lines[2], "---")
        self.assertIn("Done when: signal done", lines)

    def test_omitted_when_it_would_only_repeat_the_title(self):
        """Noise is worse than nothing: an unrewritten title says it already."""
        out = _quest("Ramscoop Begin", "Ramscoop Begin").render()
        self.assertNotIn("= 2.8 event", out)

    def test_omitted_when_the_difference_is_only_formatting(self):
        out = _quest("Ramscoop Begin", "  Ramscoop   Begin  ").render()
        self.assertNotIn("= 2.8 event", out)

    def test_is_one_ascii_line(self):
        """Engine text is ASCII-only, and a synopsis is a single line by definition."""
        out = _quest("Clean", "two\nlines and a — dash").render()
        syn = [l for l in out.splitlines() if l.startswith("= ")]
        self.assertEqual(len(syn), 1)
        self.assertTrue(all(ord(c) < 128 for c in syn[0]), syn[0])

    def test_body_prose_is_unaffected(self):
        out = _quest("Ramscoop Begin", "Ramscoop Begin 1",
                     desc="Bring the ramscoop online.").render()
        self.assertTrue(out.rstrip().endswith("Bring the ramscoop online."))


if __name__ == "__main__":
    unittest.main()
