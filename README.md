# docclaims

**Check the numbers your README states against where they come from.**

"120 tests." "Supports 3 formats." "Retries at most 5 times." Every one was true
the day it was typed. Then the code moved, the test suite stayed green, CI
stayed green, and the README went quietly wrong. Nothing re-runs a number
written in prose.

docclaims does. The numbers stay plain text, with no generator markup around
them. A small ledger, `claims.json`, says what each number is and where it
comes from, and `docclaims verify` fails when the two disagree.

```
$ docclaims verify examples/tiny --scan "*.md"
FAIL  derived        max_retries: the source now says 'at most 7 times'; the ledger publishes 'at most 5 times'
3 claims: 0 recomputable, 3 read from source, 0 anchored to a transcript
1 failures, 0 notes
```

One file, standard library only, Python 3.8 or later, MIT licensed.

## Install

```bash
pip install git+https://github.com/jhaney0214-sys/docclaims
```

Or copy `docclaims.py` into your repository and run it with `python
docclaims.py`. That is a supported way to use it: there is nothing to install
and nothing it depends on.

## A worked example

`examples/tiny/README.md` says:

> It retries a failed request at most 5 times, reads 3 formats, and has 3 tests.

`examples/tiny/claims.json` says where each of those comes from:

```json
{
  "id": "max_retries",
  "claim": "How many times a failed request is retried",
  "value": "at most 5 times",
  "format": "at most %d times",
  "derive": {"files": ["src/limits.py"], "capture": "^MAX_RETRIES = (\\d+)"},
  "status": "measured",
  "anchor": "MAX_RETRIES in src/limits.py",
  "checked_on": "2026-09-25",
  "durable": "read from source on every verify",
  "appears_in": ["README.md"],
  "near": ["retries"]
}
```

Change `MAX_RETRIES` to 7 and `verify` fails, naming the new value. Change
the README to say 6 and it fails there instead. Leave a stale "5" in one
sentence while fixing another, and the contradiction scan catches the one you
missed.

## Starting a ledger: `docclaims suggest`

Writing `claims.json` by hand for an existing README is the slow part, so
`suggest` drafts it:

```
$ cd examples/tiny && docclaims suggest README.md --ledger none.json
source  README.md:5              5 times  <- src/limits.py
draft   README.md:5              3 formats
source  README.md:5              3 tests  <- tests/**/test_*.py
3 drafts, 2 with a source that reproduces the number; every draft fails verify until its todo is deleted
```

It picks out numbers followed by a plural noun ("27 routes"), or with a `%`
or `x`, and skips years, versions, URLs, list numbering, inline code and
anything already pinned in the ledger. In code blocks it reads only comments,
so terminal output doesn't flood it but `# 138 tests` beside a command is
found.

For each candidate it looks for a source. For a test count it tries both
counting styles, and elsewhere it searches the code for a constant
(`MAX_RETRIES = 5`). For a count of 10 or more that no constant holds, it
tries labelled lines of committed transcripts (`.txt`, `.log`, `.out`), such
as `articles read   1270` in a summary a script printed; a label that
appears twice is skipped as ambiguous. **A `derive` is proposed only if it was run and gave back
the same number.** A plausible source that gives a different one is worse than
none.

**Every draft fails `verify` until a person has read it.** Each one carries a
`todo`, which `verify` reports as "still a draft", so drafts can't pass
unreviewed. Deleting a draft that isn't really a claim is part of the review.
`--out` writes the drafts to a new file, and refuses to write over an existing
ledger.

## Where a number can come from

**Read from the source (`derive`).** Most numbers a README states about the
project itself are already written in the code. docclaims reads them:

| `derive` | reads |
| --- | --- |
| `{"files": [...], "capture": "regex"}` | the one group of a regex that matches exactly once across the files. Twice is ambiguous, and it fails rather than picking one |
| `{"files": [...], "count": "regex"}` | how many times a line-anchored regex matches |
| `{"files": [...], "tests": "python"}` | test methods on classes, the way unittest's loader finds them, counted by parsing, so a test file embedded in a string as a fixture is not counted |
| `{"files": [...], "tests": "pytest"}` | what pytest's default collection finds: module-level `test*` functions, `test*` methods on `Test*` classes without an `__init__` (nested ones too), and `unittest.TestCase` methods. `@pytest.mark.parametrize` over a literal list counts once per case, stacked decorators multiply. Parametrizing over a variable fails with the function's name rather than guessing |

A `capture` that isn't a number is kept as text, so a version such as
`"0.1.1"` can be pinned with `"format": "v%s"`.

`format` is `%`-style, or `{}`-style when it contains a brace. The second can
write what the first can't, such as a thousands separator:
`"format": "{:,} respondents"` renders 37583 as "37,583 respondents".

`tests: "pytest"` was checked against `pytest --collect-only` on the
`packaging` project's own suite: every file it could count matched exactly
(293 tests over 6 files), and the 5 that parametrize over variables were
refused. It doesn't see parametrized fixtures or custom collection hooks. A
suite that relies on those should record `pytest --collect-only` output in a
committed file and anchor the claim with `evidence` instead.

A glob that matches no files fails. It never reads as zero, because a test
directory that moved would otherwise report "0 tests" and render cleanly.

**Recomputed by your own code (`raw`).** For a number some computation
produces, such as a benchmark or a share of variance, the ledger holds `raw`,
exactly as the code returns it, and `format` (plus an optional `scale`) turns
it into the published string. A test in your project compares `raw` with what
the code returns today, using `docclaims.check_computed`. docclaims checks
everything to the right of `raw`: that `format % (raw * scale)` still renders
`value`, and that the prose still says it.

**Read off a committed transcript (`evidence`).** Some numbers come from a
one-off run over data too large to commit. The ledger names the file and the
line the number was read from, and `verify` fails if that line is gone. That
proves the number was produced, not that it is right, and the report says so.

A claim with none of the three fails the schema check, because then the ledger
would be the only record that the number ever existed.

## What `verify` checks

| check | fails when |
| --- | --- |
| schema | a field is missing, misspelled, or a date doesn't parse. An unknown field fails, because a typo would otherwise mean the check silently never runs |
| derived | the number read from the source no longer renders as `value` |
| rounding | `format % (raw * scale)` no longer renders `value` |
| evidence | the transcript line a number was read off has gone |
| presence | a file in `appears_in` no longer contains the value |
| contradiction | a *different* number of the same shape sits near the claim, within `window` characters of a `near` phrase. This is what editing one sentence and not the next leaves behind |
| coverage | (with `--scan`) a file quotes the value and isn't in `appears_in`: the copy nobody remembered |

Whitespace is normalised first, so a hard-wrapped README can't fail a check,
or hide a contradiction, just by where a line happens to break.

Anything the checker couldn't actually check is reported as **NOT CHECKED**,
never as a pass: a claim with no `near` phrases, or a sibling repository that
isn't checked out.

## Every field

| field | |
| --- | --- |
| `id` | lowercase, digits, underscores; unique |
| `claim` | what the number is, in words |
| `value` | exactly as the prose writes it |
| `status` | `measured`, `estimated`, `modeled` or `unconfirmed`. Four, fixed, and not extensible, so one repository can't grow three vocabularies for the same idea |
| `anchor` | where a reader goes to disagree |
| `checked_on` | ISO date |
| `recheck_by` | ISO date after which `docclaims stale` reports it. Or `durable`, a reason it has no horizon |
| `appears_in` | files that write the number |
| `near`, `window` | phrases that open the contradiction scan, and how far it looks (default 300 characters) |
| `allow` | numbers the scan should excuse, each mapped to the reason it's legitimate |
| `also_written` | other renderings of the same value, e.g. `3.2x` and `3.2×` |
| `derive`, `raw`, `format`, `scale`, `tolerance`, `evidence` | where it comes from; see above |

Top-level `exempt` maps a path to the reason the coverage scan skips it, for a
changelog full of superseded numbers.

## In CI

As a GitHub Action, one step:

```yaml
- uses: actions/checkout@v4
- uses: jhaney0214-sys/docclaims@v0.4.0
  with:
    path: .                 # where claims.json lives
    scan: "**/*.md docs/*.html"
```

`scan` is a space-separated list of globs for the coverage sweep. Leave it
empty to skip the sweep. This repository's own CI runs the action twice: on
the clean example, where it must pass, and on a copy where one number has
drifted, where it must fail.

Or without the action, in any CI:

```yaml
- run: python docclaims.py verify . --scan "**/*.md" "docs/*.html"
```

Everything except `raw`-against-your-code is text against text, so this runs
on a runner that can't build or import your project at all.

## A badge

Run the check as its own workflow, and its status is a badge that says the
README's numbers were checked on the last push. In
`.github/workflows/docclaims.yml`, the two steps above; in the README:

```markdown
[![numbers checked by docclaims](https://github.com/OWNER/REPO/actions/workflows/docclaims.yml/badge.svg)](https://github.com/jhaney0214-sys/docclaims)
```

[freshcite](https://github.com/jhaney0214-sys/freshcite) does this: every
count its README states is read from a committed scan summary, and the badge
is green only while they agree.

## Before each commit

With [pre-commit](https://pre-commit.com), in `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/jhaney0214-sys/docclaims
    rev: v0.4.0
    hooks:
      - id: docclaims
```

It runs on every commit, not only when `claims.json` changes, because a count
moves when the code it's read from moves, and that's the commit to stop. Pass
`args: [--scan, "*.md"]` to sweep for unpinned copies too.

## Other commands

```bash
docclaims stale . --asof 2027-01-01   # claims past their recheck_by
docclaims render . --format md        # a table of every claim, for a docs page
docclaims verify . --json out.json    # machine-readable findings
```

## How this differs from what already exists

- **[cog](https://github.com/nedbat/cog)** regenerates text in place from
  Python embedded in the file, and its `--check` fails CI when the output is
  stale. If you're happy to put generator markers around every number, it's
  excellent. docclaims is for prose that stays prose, and for the numbers cog
  can't regenerate: ones that come from a transcript, or that appear on a page
  you don't want markup in.
- **[embedmd](https://github.com/campoy/embedmd)** and
  **[snips](https://github.com/cortesi/snips)** keep *code blocks* in sync with
  source files. docclaims is about numbers in sentences.
- **[driftcheck](https://github.com/yunaremaia/driftcheck)** catches *version*
  drift, a README naming a different toolchain version from the one a config
  pins. docclaims doesn't try to.

None of them look for a *second, stale* copy of a number beside the right one,
and that's the failure a partial edit produces.

## What it does not do

It doesn't find your claims for you. Pointed at a README and asked which
figures are claims, a tool produces a flood: years, versions, ports, HTTP
statuses. A checker that cries wolf gets muted, so claims are declared.

It doesn't decide whether a claim is *true*. `status` is your assertion about
how you know the number, and `anchor` is where someone checks. docclaims makes
sure the assertion is stated, dated and consistent everywhere it appears.

## Development

```bash
PYTHONPATH=. python -m unittest discover -s tests   # 167 tests
python docclaims.py verify . --scan "*.md"          # this README against its ledger
```

This README's own test count is pinned in `claims.json`, and CI fails if it
drifts. So is the release the examples above pin, read from `__version__`.
When a new version reaches `main` with CI green, CI tags it; an existing tag
is never moved. Publishing a GitHub release from that tag uploads it to PyPI
(`.github/workflows/release.yml`, through PyPI's trusted publishing, so no
token is stored) and is the same step that lists the action on the
Marketplace.

MIT licence. See `LICENSE`.
