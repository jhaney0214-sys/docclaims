"""Tests for docclaims.

Most of these stage a regression and require the check to go red, because a
checker that cannot fail is the defect it was written to find, one level up.

The regressions staged here are the real ones this tool exists for:

  * the engine moves and the prose does not          (computed)
  * the prose is edited in one place and not another (contradiction)
  * a number is rounded differently                  (rounding)
  * a new file quotes a claim and nobody pins it     (coverage)
  * a horizon passes with nobody watching            (stale)

`unittest.main()` is at the END of this file, after every class. Running a
file whose guard sits above its classes executes only the classes defined
before it and still prints a green OK — a partial count reading as a complete
one, which is exactly the failure this tool exists to catch.
"""

import datetime
import io
import json
import os
import pathlib
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout

import docclaims as claims


def write(root, relative, text):
    target = pathlib.Path(root) / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    with io.open(str(target), "w", encoding="utf-8") as handle:
        handle.write(text)
    return target


def a_claim(**overrides):
    base = {
        "id": "pc1_share",
        "claim": "First component's share of variance, Index A",
        "value": "12.5%",
        "raw": 0.1249733141,
        "format": "%.1f%%",
        "scale": 100,
        "status": "measured",
        "anchor": "the source Index A, 88 complete rows",
        "checked_on": "2026-09-19",
        "recheck_by": "2027-01-15",
        "appears_in": ["README.md"],
        "near": ["variance on one component"],
    }
    base.update(overrides)
    return base


class TemporaryProject(unittest.TestCase):
    """A throwaway project directory with a ledger and some prose."""

    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="claims-test-"))
        self.addCleanup(shutil.rmtree, str(self.root), True)

    def put_ledger(self, claim_list):
        write(self.root, "claims.json",
              json.dumps(claim_list if isinstance(claim_list, list)
                         else [claim_list], indent=2))

    def fatal_kinds(self, findings):
        return sorted(f.kind for f in findings if f.fatal)


class Loading(TemporaryProject):

    def test_a_missing_ledger_raises_rather_than_returning_nothing(self):
        """"Could not look" and "found nothing" are different answers.

        A ledger file that is absent must not read as a project with no
        claims, because the second is a pass and the first is not.
        """
        with self.assertRaises(claims.LedgerError):
            claims.load(self.root / "claims.json")

    def test_malformed_json_raises_with_the_path_named(self):
        write(self.root, "claims.json", "{not json")
        with self.assertRaises(claims.LedgerError) as caught:
            claims.load(self.root / "claims.json")
        self.assertIn("claims.json", str(caught.exception))

    def test_a_bare_list_is_accepted(self):
        self.put_ledger([a_claim()])
        self.assertEqual(len(claims.load(self.root / "claims.json")), 1)

    def test_an_object_with_a_claims_key_is_accepted(self):
        write(self.root, "claims.json",
              json.dumps({"claims": [a_claim()], "note": "room to grow"}))
        self.assertEqual(len(claims.load(self.root / "claims.json")), 1)

    def test_a_json_scalar_is_refused(self):
        write(self.root, "claims.json", "42")
        with self.assertRaises(claims.LedgerError):
            claims.load(self.root / "claims.json")


class Schema(TemporaryProject):

    def check(self, claim):
        return claims.check_schema([claim])

    def test_a_complete_claim_passes(self):
        self.assertEqual(self.check(a_claim()), [])

    def test_every_required_field_is_required(self):
        """Staged one at a time, so a check that only looks at the first
        missing field cannot pass this."""
        for field in claims.REQUIRED:
            claim = a_claim()
            del claim[field]
            findings = self.check(claim)
            self.assertTrue(
                any(field in f.message for f in findings),
                "dropping %r produced no finding naming it" % field)

    def test_an_unrecognised_status_fails(self):
        findings = self.check(a_claim(status="verified"))
        self.assertIn("schema", self.fatal_kinds(findings))
        self.assertIn("verified", findings[0].message)

    def test_all_four_statuses_are_accepted(self):
        for status in claims.STATUSES:
            self.assertEqual(self.check(a_claim(status=status)), [],
                             "%s was refused" % status)

    def test_a_misspelled_field_fails_rather_than_being_ignored(self):
        """`appears_at` instead of `appears_in` would silently unpin a claim.

        A typo that fails open is worse than no check: the ledger looks like
        it guards a file and guards nothing.
        """
        claim = a_claim()
        claim["appears_at"] = claim.pop("appears_in")
        findings = self.check(claim)
        self.assertIn("schema", self.fatal_kinds(findings))
        self.assertTrue(any("appears_at" in f.message for f in findings))

    def test_a_duplicate_id_fails(self):
        findings = claims.check_schema([a_claim(), a_claim()])
        self.assertTrue(any("duplicate" in f.message for f in findings))

    def test_an_id_with_spaces_or_capitals_fails(self):
        for bad in ("PC1 share", "pc1-share", "Pc1"):
            findings = self.check(a_claim(id=bad))
            self.assertTrue(findings, "%r was accepted as an id" % bad)

    def test_a_date_that_is_not_a_date_fails(self):
        findings = self.check(a_claim(checked_on="September 2026"))
        self.assertTrue(any("ISO date" in f.message for f in findings))

    def test_a_horizon_before_its_own_check_date_fails(self):
        findings = self.check(a_claim(checked_on="2026-09-19",
                                      recheck_by="2026-01-01"))
        self.assertTrue(any("not after" in f.message for f in findings))

    def test_no_horizon_and_no_durable_reason_fails(self):
        claim = a_claim()
        del claim["recheck_by"]
        findings = self.check(claim)
        self.assertIn("schema", self.fatal_kinds(findings))

    def test_durable_excuses_a_missing_horizon(self):
        claim = a_claim()
        del claim["recheck_by"]
        claim["durable"] = "a statute citation; it changes by amendment, not by date"
        self.assertEqual(self.check(claim), [])

    def test_raw_without_format_fails(self):
        claim = a_claim()
        del claim["format"]
        self.assertTrue(any("only mean anything together" in f.message
                            for f in self.check(claim)))

    def test_format_without_raw_fails(self):
        claim = a_claim()
        del claim["raw"]
        self.assertTrue(any("only mean anything together" in f.message
                            for f in self.check(claim)))

    def test_an_allow_list_without_reasons_fails(self):
        findings = self.check(a_claim(allow=["61 regions"]))
        self.assertIn("schema", self.fatal_kinds(findings))
        self.assertTrue(any("nobody can disagree" in f.message
                            for f in findings))

    def test_an_allow_entry_with_an_empty_reason_fails(self):
        findings = self.check(a_claim(allow={"61 regions": "   "}))
        self.assertIn("schema", self.fatal_kinds(findings))

    def test_an_allow_entry_with_a_reason_passes(self):
        self.assertEqual(
            self.check(a_claim(allow={"12.4%": "a different index's share"})),
            [])

    def test_a_window_with_no_near_is_a_note_not_a_failure(self):
        claim = a_claim(window=500)
        del claim["near"]
        findings = self.check(claim)
        self.assertEqual(self.fatal_kinds(findings), [])
        self.assertTrue(findings)


class Evidence(TemporaryProject):
    """A number nothing can recompute, anchored to the run that produced it.

    Some findings come from one-shot analyses over a cache too large to commit,
    and what the repository keeps is the run's transcript. Before this
    existed, such a claim could sit in a ledger with no `raw` and nothing would
    say so — the ledger would be the only record the number was ever produced.
    """

    LINE = "  best units covering 5% of the land hold 20% of localities"

    def traced(self, **over):
        claim = a_claim(id="enrichment", value="3.2x", near=["3.2x"],
                        evidence={"file": "notes/probe.txt",
                                  "line": self.LINE.strip()})
        for key in ("raw", "format", "scale"):
            claim.pop(key, None)
        claim.update(over)
        return claim

    def test_a_claim_with_neither_raw_nor_evidence_fails(self):
        claim = self.traced()
        del claim["evidence"]
        findings = claims.check_schema([claim])
        self.assertIn("schema", self.fatal_kinds(findings))
        self.assertTrue(any("only record" in f.message for f in findings))

    def test_evidence_needs_both_a_file_and_a_line(self):
        for bad in ({"file": "notes/probe.txt"}, {"line": "x"}, "notes/probe.txt"):
            findings = claims.check_schema([self.traced(evidence=bad)])
            self.assertIn("schema", self.fatal_kinds(findings),
                          "%r was accepted as evidence" % (bad,))

    def test_the_line_still_being_there_passes(self):
        write(self.root, "notes/probe.txt", "header\n%s\nfooter\n" % self.LINE)
        self.assertEqual(claims.check_evidence([self.traced()], self.root), [])

    def test_the_line_having_changed_fails(self):
        """The staged regression: a re-run rewrote the transcript."""
        write(self.root, "notes/probe.txt",
              "header\n  best units covering 5% of the land hold 17% of "
              "localities\nfooter\n")
        findings = claims.check_evidence([self.traced()], self.root)
        self.assertEqual(self.fatal_kinds(findings), ["evidence"])
        self.assertIn("read off", findings[0].message)

    def test_the_transcript_being_deleted_fails(self):
        findings = claims.check_evidence([self.traced()], self.root)
        self.assertEqual(self.fatal_kinds(findings), ["evidence"])
        self.assertIn("gone", findings[0].message)

    def test_a_line_wrapped_in_the_transcript_is_still_matched(self):
        write(self.root, "notes/probe.txt",
              "best units covering 5% of the land\nhold 20% of localities\n")
        self.assertEqual(claims.check_evidence([self.traced()], self.root), [])

    def test_a_recomputable_claim_needs_no_evidence(self):
        self.assertEqual(claims.check_schema([a_claim()]), [])
        self.assertEqual(claims.check_evidence([a_claim()], self.root), [])


class Rounding(TemporaryProject):

    def test_the_real_value_renders_the_published_string(self):
        self.assertEqual(claims.check_rounding([a_claim()]), [])

    def test_a_raw_value_that_no_longer_rounds_to_the_published_one_fails(self):
        """The staged regression: the engine moved, the prose did not."""
        findings = claims.check_rounding([a_claim(raw=0.8379571221535493)])
        self.assertEqual(self.fatal_kinds(findings), ["rounding"])
        self.assertIn("83.8%", findings[0].message)

    def test_changing_the_number_of_decimals_fails(self):
        """A formatting change is a change to a published claim."""
        findings = claims.check_rounding([a_claim(format="%.2f%%")])
        self.assertEqual(self.fatal_kinds(findings), ["rounding"])

    def test_a_format_that_cannot_render_the_raw_value_fails(self):
        findings = claims.check_rounding([a_claim(raw="not a number")])
        self.assertEqual(self.fatal_kinds(findings), ["rounding"])

    def test_a_claim_with_no_raw_is_skipped_silently_here(self):
        claim = a_claim()
        del claim["raw"]
        del claim["format"]
        del claim["scale"]
        self.assertEqual(claims.check_rounding([claim]), [])

    def test_the_scale_and_not_the_raw_value_carries_the_units(self):
        """`raw` stays exactly what the engine returns.

        The engine gives a proportion and the README publishes a percentage.
        If the ledger stored 12.497 instead, every project would have to apply
        the scale itself before comparing against its engine — which is the
        code this tool exists to stop each of them writing.
        """
        claim = a_claim()
        self.assertEqual(claim["raw"], 0.1249733141)
        self.assertEqual(claims.rendered_value(claim), "12.5%")

    def test_a_wrong_scale_fails(self):
        findings = claims.check_rounding([a_claim(scale=1)])
        self.assertEqual(self.fatal_kinds(findings), ["rounding"])

    def test_scale_is_not_applied_to_a_non_numeric_value(self):
        claim = a_claim(raw="Producer", format="%s", value="Producer")
        del claim["scale"]
        self.assertEqual(claims.check_rounding([claim]), [])

    def test_scale_without_raw_fails_the_schema(self):
        claim = a_claim()
        del claim["raw"]
        del claim["format"]
        findings = claims.check_schema([claim])
        self.assertTrue(any("no `raw` to convert" in f.message
                            for f in findings))


class Shapes(unittest.TestCase):
    """`shape_of` is what separates "the right number is here" from
    "a wrong number is here too"."""

    def test_a_percentage_matches_other_percentages_of_the_same_precision(self):
        shape = claims.shape_of("12.5%")
        self.assertTrue(shape.search("12.4%"))
        self.assertTrue(shape.search("9.7%"))
        self.assertTrue(shape.search("100.0%"))

    def test_a_percentage_does_not_match_a_different_precision(self):
        shape = claims.shape_of("12.5%")
        self.assertIsNone(shape.fullmatch("12.54%"))

    def test_four_decimals_do_not_match_two(self):
        shape = claims.shape_of("0.4412")
        self.assertTrue(shape.search("0.7731"))
        self.assertIsNone(shape.fullmatch("0.99"))

    def test_literal_text_around_the_number_is_held(self):
        """"88 regions" must not match every two-digit number."""
        shape = claims.shape_of("88 regions")
        self.assertTrue(shape.search("we used 41 regions"))
        self.assertIsNone(shape.search("88 rows"))

    def test_a_shape_does_not_match_the_prefix_of_a_longer_decimal(self):
        """Found by running this against a real repository, not by review.

        `0.4412` has the shape \\d+\\.\\d{4}, which matches the first six
        characters of the full-precision `0.4412337190823511` that sits in a
        test file. Every claim reported its own `raw` value as a contradiction
        of itself until the guards went in.
        """
        shape = claims.shape_of("0.4412")
        self.assertIsNone(shape.search("0.4412337190823511"))
        self.assertIsNone(shape.search("10.4412543"))
        self.assertTrue(shape.search("the value 0.4413, rounded"))

    def test_an_integer_shape_matches_the_whole_number_or_none_of_it(self):
        """A longer count is a real contradiction, not a partial match.

        "1188 regions" must match in full — it is a different region count
        written the same way, which is exactly what this looks for. What must
        not happen is matching "88" inside it and reporting agreement.
        """
        shape = claims.shape_of("88 regions")
        self.assertEqual(shape.search("1188 regions").group(0),
                         "1188 regions")
        self.assertTrue(shape.search("61 regions"))

    def test_a_value_with_no_digits_matches_only_itself(self):
        shape = claims.shape_of("refuses rather than guesses")
        self.assertTrue(shape.search("it refuses rather than guesses here"))
        self.assertIsNone(shape.search("refuses rather than answering"))

    def test_a_dollar_amount_keeps_its_separators(self):
        shape = claims.shape_of("$58,000")
        self.assertTrue(shape.search("$91,000"))
        self.assertIsNone(shape.search("58,000 copies"))


class Windows(unittest.TestCase):

    def test_a_window_spans_both_sides_of_the_phrase(self):
        text = "A" * 100 + "needle" + "B" * 100
        spans = claims.windows(text, ["needle"], 10)
        self.assertEqual(spans, [(90, 116)])

    def test_overlapping_windows_are_merged(self):
        text = "needle" + "x" * 5 + "needle"
        spans = claims.windows(text, ["needle"], 20)
        self.assertEqual(len(spans), 1)

    def test_the_phrase_match_is_case_insensitive(self):
        self.assertTrue(claims.windows("The Needle", ["needle"], 5))

    def test_a_phrase_that_is_absent_produces_no_window(self):
        self.assertEqual(claims.windows("nothing here", ["needle"], 5), [])


class Prose(TemporaryProject):

    GOOD = ("# Project\n\n"
            "On 88 regions in the sample, the project reports 12.5% of variance on "
            "one component against three claimed dimensions.\n")

    def test_a_readme_that_carries_the_claim_passes(self):
        write(self.root, "README.md", self.GOOD)
        self.assertEqual(claims.check_prose([a_claim()], self.root), [])

    def test_a_readme_that_lost_the_claim_fails(self):
        write(self.root, "README.md",
              self.GOOD.replace("12.5% of variance on one component",
                                "a large share of variance"))
        findings = claims.check_prose([a_claim()], self.root)
        self.assertEqual(self.fatal_kinds(findings), ["presence"])

    def test_a_file_that_does_not_exist_fails(self):
        findings = claims.check_prose([a_claim()], self.root)
        self.assertEqual(self.fatal_kinds(findings), ["presence"])
        self.assertEqual(findings[0].path, "README.md")

    def test_a_half_finished_edit_is_caught(self):
        """The regression a bare assertIn cannot see.

        The right number is still present, so "does the README contain 12.5%"
        passes. A second, different number of the same shape now sits beside
        it, which is what editing one sentence and not the next leaves behind.
        """
        write(self.root, "README.md",
              self.GOOD + "\nThat 12.4% of variance on one component is the "
                          "headline.\n")
        findings = claims.check_prose([a_claim()], self.root)
        self.assertEqual(self.fatal_kinds(findings), ["contradiction"])
        self.assertIn("12.4%", findings[0].message)

    def test_a_different_number_outside_the_window_is_not_flagged(self):
        """Scoping is what keeps this from crying wolf.

        16.0% stands for a real, correct, unrelated number in the same README.
        Flagging it would make the check useless, so the window is the whole
        design.
        """
        write(self.root, "README.md",
              self.GOOD + "\n" + "z" * 2000 +
              "\nThe remaining 16.0% decides who sits above whom.\n")
        self.assertEqual(claims.check_prose([a_claim()], self.root), [])

    def test_no_near_phrases_reports_not_checked_rather_than_passing(self):
        claim = a_claim()
        del claim["near"]
        write(self.root, "README.md", self.GOOD)
        findings = claims.check_prose([claim], self.root)
        self.assertEqual(self.fatal_kinds(findings), [])
        self.assertEqual(findings[0].kind, "contradiction")
        self.assertIn("NOT CHECKED", findings[0].message)

    def test_near_phrases_that_are_absent_report_not_checked(self):
        """A `near` phrase deleted from the prose silently disarms the scan.

        Reporting it as a note rather than passing is the difference between
        an instrument that looked and one that could not.
        """
        write(self.root, "README.md",
              "# Project\n\nThe figure is 12.5% and nothing explains it.\n")
        findings = claims.check_prose([a_claim()], self.root)
        self.assertEqual(self.fatal_kinds(findings), [])
        self.assertIn("no window to scan", findings[0].message)

    def test_a_declared_legitimate_neighbour_is_excused(self):
        """Two indices' denominators in one methods note.

        61 is Index B's region count sitting beside Index A's 88. The check was
        right to see it and wrong to call it drift, and the exemption has to
        carry a reason somebody can disagree with rather than being a silent
        widening of the rule.
        """
        write(self.root, "README.md",
              "Index A: 88 regions. Index B: 61 regions after deletion.\n")
        claim = a_claim(
            id="countries", value="88 regions", raw=88,
            format="%d regions", near=["88 regions"],
            allow={"61 regions": "Index B's denominator, a different index"})
        del claim["scale"]
        self.assertEqual(claims.check_prose([claim], self.root), [])

    def test_an_undeclared_neighbour_is_still_caught(self):
        """The exemption must not widen the rule beyond what it names."""
        write(self.root, "README.md",
              "Index A: 88 regions. Index B: 61 regions. Old: 81 regions.\n")
        claim = a_claim(
            id="countries", value="88 regions", raw=88,
            format="%d regions", near=["88 regions"],
            allow={"61 regions": "Index B's denominator, a different index"})
        del claim["scale"]
        findings = claims.check_prose([claim], self.root)
        self.assertEqual(self.fatal_kinds(findings), ["contradiction"])
        self.assertIn("81 regions", findings[0].message)

    def test_an_exemption_that_no_longer_fires_is_reported(self):
        """A stale reason gets copied forward and quietly widens the rule."""
        write(self.root, "README.md", "Index A: 88 regions, and nothing else.\n")
        claim = a_claim(
            id="countries", value="88 regions", raw=88,
            format="%d regions", near=["88 regions"],
            allow={"61 regions": "Index B's denominator, a different index"})
        del claim["scale"]
        findings = claims.check_prose([claim], self.root)
        self.assertEqual(self.fatal_kinds(findings), [])
        self.assertEqual(findings[0].kind, "allow")

    def test_a_claim_with_no_appears_in_is_a_note(self):
        claim = a_claim()
        del claim["appears_in"]
        findings = claims.check_prose([claim], self.root)
        self.assertEqual(self.fatal_kinds(findings), [])
        self.assertEqual(findings[0].kind, "unpublished")

    def test_a_widened_window_reaches_further(self):
        text = (self.GOOD + "\n" + "z" * 400 +
                "\nand 12.4% appears well downstream\n")
        write(self.root, "README.md", text)
        self.assertEqual(claims.check_prose([a_claim()], self.root), [])
        findings = claims.check_prose([a_claim(window=900)], self.root)
        self.assertEqual(self.fatal_kinds(findings), ["contradiction"])

    def test_a_claim_broken_across_a_line_wrap_is_still_found(self):
        """Found against a real README, hard-wrapped at 79 columns.

        "12 places of 90" happens to break after "of", and a literal search
        reported the README as not carrying a number it plainly carries.
        """
        claim = a_claim(id="rank_move", value="12 places of 90", raw=12.0,
                        format="%d places of 90",
                        near=["under reweighting"])
        del claim["scale"]
        write(self.root, "README.md",
              "the median region moves 12 places of\n"
              "90 under reweighting, because one factor sets the order.\n")
        self.assertEqual(claims.check_prose([claim], self.root), [])

    def test_a_contradiction_split_by_a_wrap_is_still_caught(self):
        """The worse direction: a wrap must not be able to HIDE a mismatch."""
        claim = a_claim(id="rank_move", value="12 places of 90", raw=12.0,
                        format="%d places of 90",
                        near=["under reweighting"])
        del claim["scale"]
        write(self.root, "README.md",
              "the median region moves 12 places of 90 under reweighting.\n"
              "Elsewhere we said 44 places\nof 90 under reweighting.\n")
        findings = claims.check_prose([claim], self.root)
        self.assertEqual(self.fatal_kinds(findings), ["contradiction"])
        self.assertIn("44 places of 90", findings[0].message)

    def test_a_finding_carries_the_surrounding_sentence(self):
        """A character offset into normalised text helps nobody find it."""
        write(self.root, "README.md",
              self.GOOD + "\nBut 12.4% of variance on one component is the "
                          "figure we printed.\n")
        findings = claims.check_prose([a_claim()], self.root)
        self.assertIn("figure we printed", findings[0].message)

    def test_html_on_one_long_line_is_still_scanned(self):
        """Why the window is characters and not lines.

        A paragraph of HTML is frequently a single very long line, and the
        headline figure often sits alone in a <b> two lines above the sentence
        that names it. A line-scoped window would see neither.
        """
        write(self.root, "docs/index.html",
              "<p><b>12.5%</b></p>\n<p>" + "x" * 20 +
              " of variance on one component, and 12.4% elsewhere.</p>\n")
        findings = claims.check_prose(
            [a_claim(appears_in=["docs/index.html"])], self.root)
        self.assertEqual(self.fatal_kinds(findings), ["contradiction"])


class AlternativeRenderings(TemporaryProject):
    """One number, written two ways.

    A README says `3.2x` in plain text; a designed findings page says `3.2×`
    with a typographic multiplication sign. Neither is wrong and neither
    is a second claim.
    """

    def lift(self, **over):
        claim = a_claim(id="lift", value="3.2x", also_written=["3.2×"],
                        near=["3.2x", "3.2×"],
                        appears_in=["README.md", "findings.html"])
        for key in ("raw", "format", "scale"):
            claim.pop(key, None)
        claim["evidence"] = {"file": "notes/probe.txt", "line": "lift 3.2"}
        claim.update(over)
        return claim

    def setUp(self):
        TemporaryProject.setUp(self)
        write(self.root, "notes/probe.txt", "lift 3.2\n")

    def test_either_rendering_satisfies_the_claim(self):
        write(self.root, "README.md", "Region A 3.2x, counted by place.\n")
        write(self.root, "findings.html", "<p>region A 3.2×.</p>\n")
        self.assertEqual(claims.check_prose([self.lift()], self.root), [])

    def test_a_file_with_neither_rendering_fails(self):
        write(self.root, "README.md", "Region A 3.2x, counted by place.\n")
        write(self.root, "findings.html", "<p>region A is enriched.</p>\n")
        findings = claims.check_prose([self.lift()], self.root)
        self.assertEqual(self.fatal_kinds(findings), ["presence"])
        self.assertIn("3.2x", findings[0].message)

    def test_a_wrong_number_in_the_alternative_rendering_is_caught(self):
        """The alternative form must be guarded, not merely accepted."""
        write(self.root, "README.md", "Region A 3.2x, counted by place.\n")
        write(self.root, "findings.html",
              "<p>region A 3.2×, or 3.6× by specimen.</p>\n")
        findings = claims.check_prose([self.lift()], self.root)
        self.assertEqual(self.fatal_kinds(findings), ["contradiction"])
        self.assertIn("3.6×", findings[0].message)

    def test_coverage_sees_an_unpinned_alternative_rendering(self):
        write(self.root, "README.md", "Region A 3.2x.\n")
        write(self.root, "findings.html", "<p>3.2×</p>\n")
        write(self.root, "docs/summary.html", "<p>3.2× again</p>\n")
        findings = claims.check_coverage([self.lift()], self.root,
                                         ["**/*.html"])
        self.assertEqual(self.fatal_kinds(findings), ["coverage"])
        self.assertEqual(findings[0].path, "docs/summary.html")

    def test_a_window_that_contains_no_declared_form_is_reported(self):
        """A scan that looked in the wrong place must not read as a pass."""
        write(self.root, "README.md", "Region A 3.2x.\n")
        write(self.root, "findings.html",
              "<p>3.2×</p>\n" + "z" * 900 + "\n<p>3.2X uppercase</p>\n")
        findings = claims.check_prose(
            [self.lift(near=["3.2x"])], self.root)
        notes = [f for f in findings if not f.fatal]
        self.assertTrue(any("somewhere the claim is not" in f.message
                            for f in notes), [f.line() for f in findings])


class Coverage(TemporaryProject):

    def setUp(self):
        TemporaryProject.setUp(self)
        write(self.root, "README.md",
              "12.5% of variance on one component.\n")

    def test_a_pinned_file_is_not_reported(self):
        findings = claims.check_coverage([a_claim()], self.root, ["*.md"])
        self.assertEqual(findings, [])

    def test_an_unpinned_file_that_quotes_the_claim_is_reported(self):
        """The direction that can see an absence.

        A check that starts from what is written down cannot find what was
        never written down: a public page quotes 12.5% twice, and the ledger
        names only README.md.
        """
        write(self.root, "docs/index.html", "<b>12.5%</b>")
        findings = claims.check_coverage([a_claim()], self.root,
                                         ["**/*.html"])
        self.assertEqual(self.fatal_kinds(findings), ["coverage"])
        self.assertEqual(findings[0].path, "docs/index.html")

    def test_a_file_that_does_not_quote_the_claim_is_not_reported(self):
        write(self.root, "docs/index.html", "<b>nothing relevant</b>")
        self.assertEqual(
            claims.check_coverage([a_claim()], self.root, ["**/*.html"]), [])


class Computed(TemporaryProject):
    """The link the project's own code has to close."""

    def test_the_engine_agreeing_produces_nothing(self):
        got = {"pc1_share": 0.1249733141}
        self.assertEqual(claims.check_computed([a_claim()], got), [])

    def test_the_engine_drifting_fails(self):
        """The regression the whole tool exists for."""
        got = {"pc1_share": 0.1249733141 + 1e-6}
        findings = claims.check_computed([a_claim()], got)
        self.assertEqual(self.fatal_kinds(findings), ["computed"])

    def test_drift_under_the_tolerance_passes(self):
        got = {"pc1_share": 0.1249733141 + 1e-15}
        self.assertEqual(claims.check_computed([a_claim()], got), [])

    def test_a_claim_specific_tolerance_is_honoured(self):
        claim = a_claim(tolerance=1e-3)
        got = {"pc1_share": 0.1249733141 + 1e-5}
        self.assertEqual(claims.check_computed([claim], got), [])

    def test_a_raw_claim_nobody_recomputed_is_reported(self):
        """A silent skip here would leave the chain looking green while its
        first link was never tested."""
        findings = claims.check_computed([a_claim()], {})
        self.assertEqual(self.fatal_kinds(findings), [])
        self.assertIn("nothing recomputed it", findings[0].message)

    def test_an_engine_value_with_no_claim_fails(self):
        findings = claims.check_computed([a_claim()], {"unknown_id": 1.0})
        self.assertEqual(self.fatal_kinds(findings), ["computed"])

    def test_a_non_numeric_value_is_compared_exactly(self):
        claim = a_claim(raw="Producer", format="%s", value="Producer")
        self.assertEqual(claims.check_computed([claim], {"pc1_share": "Producer"}), [])
        self.assertTrue(claims.check_computed([claim], {"pc1_share": "Prospect"}))


class Staleness(TemporaryProject):

    def test_a_claim_inside_its_horizon_is_not_stale(self):
        rows = claims.stale([a_claim()], datetime.date(2026, 10, 1))
        self.assertEqual(rows, [])

    def test_a_claim_past_its_horizon_is_stale_with_the_day_count(self):
        rows = claims.stale([a_claim()], datetime.date(2027, 1, 25))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][2], 10)

    def test_the_horizon_day_itself_is_not_yet_stale(self):
        self.assertEqual(claims.stale([a_claim()],
                                      datetime.date(2027, 1, 15)), [])

    def test_a_durable_claim_never_goes_stale(self):
        claim = a_claim(durable="cited to statute")
        del claim["recheck_by"]
        self.assertEqual(claims.stale([claim], datetime.date(2099, 1, 1)), [])


class Rendering(TemporaryProject):

    def test_markdown_carries_the_status_and_the_anchor(self):
        out = claims.render([a_claim()], "md")
        self.assertIn("12.5%", out)
        self.assertIn("measured", out)
        self.assertIn("the source Index A", out)
        self.assertIn("2026-09-19", out)

    def test_html_escapes_rather_than_injecting(self):
        out = claims.render([a_claim(anchor="<script>x</script>")], "html")
        self.assertNotIn("<script>", out)
        self.assertIn("&lt;script&gt;", out)

    def test_a_pipe_in_a_cell_does_not_break_the_markdown_table(self):
        out = claims.render([a_claim(claim="share | of variance")], "md")
        body = [line for line in out.splitlines() if "12.5%" in line][0]
        self.assertIn(r"share \| of variance", body)
        self.assertEqual(body.count("|") - body.count(r"\|"), 6,
                         "the escaped pipe is being counted as a cell edge")

    def test_an_unknown_format_raises(self):
        with self.assertRaises(ValueError):
            claims.render([a_claim()], "rtf")


class TheCommandLine(TemporaryProject):

    def setUp(self):
        TemporaryProject.setUp(self)
        write(self.root, "README.md",
              "12.5% of variance on one component, over 88 regions.\n")

    def run_main(self, argv):
        import contextlib
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = claims.main(argv)
        return code, buffer.getvalue()

    def test_a_clean_project_exits_zero(self):
        self.put_ledger([a_claim()])
        code, out = self.run_main(["verify", str(self.root)])
        self.assertEqual(code, 0, out)
        self.assertIn("0 failures, 0 notes", out)

    def test_the_summary_says_how_the_claims_are_anchored(self):
        """A ledger sliding from recomputable to transcript-only is a real
        weakening, and it would otherwise look identical from here."""
        self.put_ledger([a_claim()])
        _, out = self.run_main(["verify", str(self.root)])
        self.assertIn("1 recomputable, 0 read from source, 0 anchored to a "
                      "transcript", out)

    def test_a_failing_project_exits_one(self):
        self.put_ledger([a_claim(value="84.9%", raw=0.849, format="%.1f%%")])
        code, out = self.run_main(["verify", str(self.root)])
        self.assertEqual(code, 1)
        self.assertIn("FAIL", out)

    def test_a_missing_ledger_exits_one_rather_than_reporting_clean(self):
        code, out = self.run_main(["verify", str(self.root)])
        self.assertEqual(code, 1)
        self.assertIn("no ledger", out)

    def test_without_scan_the_coverage_gap_is_stated(self):
        self.put_ledger([a_claim()])
        code, out = self.run_main(["verify", str(self.root)])
        self.assertIn("NOT CHECKED", out)

    def test_quiet_suppresses_notes_but_not_failures(self):
        claim = a_claim(value="84.9%", raw=0.849, format="%.1f%%")
        del claim["near"]
        self.put_ledger([claim])
        code, out = self.run_main(["verify", str(self.root), "--quiet"])
        self.assertEqual(code, 1)
        self.assertIn("FAIL", out)
        self.assertNotIn("note  contradiction", out)

    def test_json_output_records_every_finding(self):
        self.put_ledger([a_claim(value="84.9%", raw=0.849, format="%.1f%%")])
        report = self.root / "report.json"
        self.run_main(["verify", str(self.root), "--json", str(report)])
        with io.open(str(report), encoding="utf-8") as handle:
            data = json.load(handle)
        self.assertEqual(data["claims"], 1)
        self.assertTrue(data["findings"])

    def test_stale_exits_one_when_something_is_past_its_horizon(self):
        self.put_ledger([a_claim()])
        code, out = self.run_main(
            ["stale", str(self.root), "--asof", "2027-06-01"])
        self.assertEqual(code, 1)
        self.assertIn("pc1_share", out)

    def test_stale_exits_zero_when_nothing_is(self):
        self.put_ledger([a_claim()])
        code, out = self.run_main(
            ["stale", str(self.root), "--asof", "2026-10-01"])
        self.assertEqual(code, 0)

    def test_stale_over_a_missing_ledger_fails_rather_than_reporting_clean(self):
        code, out = self.run_main(
            ["stale", str(self.root), "--asof", "2026-10-01"])
        self.assertEqual(code, 1)
        self.assertIn("no ledger", out)

    def test_render_prints_the_table(self):
        self.put_ledger([a_claim()])
        code, out = self.run_main(["render", str(self.root)])
        self.assertEqual(code, 0)
        self.assertIn("| 12.5% |", out)

    def test_no_subcommand_prints_help_and_exits_two(self):
        code, out = self.run_main([])
        self.assertEqual(code, 2)


def a_count(**overrides):
    base = {
        "id": "checks",
        "claim": "Assertions the suite runs",
        "value": "120 checks",
        "format": "%d checks",
        "derive": {"files": ["tests/AutoTest.gd"],
                   "capture": r"const EXPECTED_CHECKS := (\d+)"},
        "status": "measured",
        "anchor": "EXPECTED_CHECKS, which the suite fails on if it moves",
        "checked_on": "2026-09-25",
        "durable": "read from source on every verify",
        "appears_in": ["CLAUDE.md"],
        "near": ["checks"],
    }
    base.update(overrides)
    return base


PYTHON_TESTS = '''import unittest
FIXTURE = """
class T:
    def test_fake(self): pass
"""
class A(unittest.TestCase):
    def test_one(self): pass
    def helper(self): pass
    async def test_two(self): pass
def test_module_level(): pass
'''


class Derived(TemporaryProject):
    """The number is read out of the project, so the ledger cannot drift from it.

    Each test stages the drift this exists for - the code moves and the ledger
    and prose do not - and requires red.
    """

    def setUp(self):
        TemporaryProject.setUp(self)
        write(self.root, "tests/AutoTest.gd",
              "extends Node\nconst EXPECTED_CHECKS := 120\n")
        write(self.root, "CLAUDE.md", "The suite runs 120 checks.\n")

    def verify(self, claim):
        self.put_ledger([claim])
        return claims.verify(self.root)[1]

    def test_a_source_that_agrees_passes(self):
        self.assertEqual(self.fatal_kinds(self.verify(a_count())), [])

    def test_the_constant_moving_fails_even_though_the_prose_agrees(self):
        # The exact failure: the code moved to 127, the ledger and the prose
        # both still say 120, and every other check is green.
        write(self.root, "tests/AutoTest.gd", "const EXPECTED_CHECKS := 127\n")
        found = [f for f in self.verify(a_count()) if f.fatal]
        self.assertEqual([f.kind for f in found], ["derived"])
        self.assertIn("127 checks", found[0].message)

    def test_a_capture_that_matches_twice_is_ambiguous_and_fails(self):
        write(self.root, "tests/Other.gd", "const EXPECTED_CHECKS := 120\n")
        claim = a_count(derive={"files": ["tests/*.gd"],
                                "capture": r"EXPECTED_CHECKS := (\d+)"})
        self.assertEqual(self.fatal_kinds(self.verify(claim)), ["derived"])

    def test_a_glob_that_matches_nothing_fails_rather_than_reading_zero(self):
        claim = a_count(value="0 checks",
                        derive={"files": ["moved/*.gd"], "count": "check"})
        found = [f for f in self.verify(claim) if f.kind == "derived"]
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].fatal)
        self.assertIn("matches no files", found[0].message)

    def test_count_counts_matches_across_files(self):
        write(self.root, "a.gd", "_check(1)\n_check(2)\n")
        write(self.root, "b.gd", "_check(3)\n")
        write(self.root, "CLAUDE.md", "3 checks.\n")
        claim = a_count(value="3 checks",
                        derive={"files": ["*.gd"], "count": r"^_check\("})
        self.assertEqual(self.fatal_kinds(self.verify(claim)), [])
        write(self.root, "b.gd", "")
        self.assertEqual(self.fatal_kinds(self.verify(claim)), ["derived"])

    def test_python_tests_are_counted_by_parsing_not_by_grep(self):
        # A grep for `def test` finds four here; unittest runs two.
        write(self.root, "tests/test_a.py", PYTHON_TESTS)
        write(self.root, "README.md", "2 tests.\n")
        claim = a_count(value="2 tests", format="%d tests",
                        appears_in=["README.md"], near=["tests"],
                        derive={"files": ["tests/test_*.py"],
                                "tests": "python"})
        self.assertEqual(self.fatal_kinds(self.verify(claim)), [])

    def test_a_test_file_that_does_not_parse_fails(self):
        write(self.root, "tests/test_a.py", "def test_(:\n")
        claim = a_count(derive={"files": ["tests/test_*.py"],
                                "tests": "python"})
        self.assertIn("derived", self.fatal_kinds(self.verify(claim)))

    def test_a_capture_that_is_not_a_number_fails(self):
        write(self.root, "tests/AutoTest.gd", "const EXPECTED_CHECKS := many\n")
        claim = a_count(derive={"files": ["tests/AutoTest.gd"],
                                "capture": r"EXPECTED_CHECKS := (\w+)"})
        found = [f for f in self.verify(claim) if f.kind == "derived"]
        self.assertTrue(found and found[0].fatal, found)
        self.assertIn("not a number", found[0].message)

    def test_a_decimal_capture_is_read_as_a_decimal(self):
        write(self.root, "tests/AutoTest.gd", "const EXPECTED_CHECKS := 2.5\n")
        write(self.root, "CLAUDE.md", "2.5 checks.\n")
        claim = a_count(value="2.5 checks", format="%.1f checks",
                        derive={"files": ["tests/AutoTest.gd"],
                                "capture": r"EXPECTED_CHECKS := ([\d.]+)"})
        self.assertEqual(self.fatal_kinds(self.verify(claim)), [])

    def test_a_spec_with_no_mode_says_it_has_none(self):
        found = [f for f in self.verify(a_count(derive={"files": ["a"]}))
                 if f.kind == "schema"]
        self.assertTrue(any("has none" in f.message for f in found), found)

    def test_a_derived_claim_with_a_raw_copy_is_refused(self):
        claim = a_count(raw=120)
        self.assertIn("schema", self.fatal_kinds(self.verify(claim)))

    def test_a_derived_claim_needs_a_format(self):
        claim = a_count()
        del claim["format"]
        self.assertIn("schema", self.fatal_kinds(self.verify(claim)))

    def test_a_derived_claim_needs_no_raw_or_evidence(self):
        found = self.verify(a_count())
        self.assertFalse(any("neither `raw`" in f.message for f in found))

    def test_the_spec_is_checked(self):
        bad = [{"files": [], "count": "x"},
               {"files": ["a"], "count": "x", "capture": "(x)"},
               {"files": ["a"]},
               {"files": ["a"], "capture": "no group"},
               {"files": ["a"], "count": "("},
               {"files": ["a"], "tests": "gdscript"},
               {"files": ["a"], "count": "x", "fies": 1},
               {"files": [""], "count": "x"},
               "tests/*.py"]
        for spec in bad:
            with self.subTest(spec=spec):
                self.assertIn("schema",
                              self.fatal_kinds(self.verify(a_count(derive=spec))))

    def test_a_sibling_project_is_found_case_insensitively(self):
        sibling = self.root.parent / (self.root.name + "-Sibling")
        self.addCleanup(shutil.rmtree, str(sibling), True)
        write(sibling, "tests/AutoTest.gd", "const EXPECTED_CHECKS := 120\n")
        claim = a_count(derive={"project": (self.root.name + "-sibling").upper(),
                                "files": ["tests/AutoTest.gd"],
                                "capture": r"EXPECTED_CHECKS := (\d+)"})
        self.assertEqual(self.fatal_kinds(self.verify(claim)), [])
        write(sibling, "tests/AutoTest.gd", "const EXPECTED_CHECKS := 1\n")
        self.assertEqual(self.fatal_kinds(self.verify(claim)), ["derived"])

    def test_a_project_nested_inside_the_root_is_found(self):
        write(self.root, "Sibling/tests/AutoTest.gd",
              "const EXPECTED_CHECKS := 120\n")
        claim = a_count(derive={"project": "sibling",
                                "files": ["tests/AutoTest.gd"],
                                "capture": r"EXPECTED_CHECKS := (\d+)"})
        self.assertEqual(self.fatal_kinds(self.verify(claim)), [])

    def test_a_project_not_checked_out_is_not_checked_and_says_so(self):
        claim = a_count(derive={"project": "no-such-project-anywhere",
                                "files": ["x"], "count": "x"})
        found = [f for f in self.verify(claim) if f.kind == "derived"]
        self.assertEqual(len(found), 1)
        self.assertFalse(found[0].fatal)
        self.assertIn("NOT CHECKED", found[0].message)

    def test_the_summary_counts_derived_claims(self):
        self.put_ledger([a_count()])
        out = io.StringIO()
        with redirect_stdout(out):
            claims.main(["verify", str(self.root)])
        self.assertIn("0 recomputable, 1 read from source", out.getvalue())


if __name__ == "__main__":
    unittest.main()
