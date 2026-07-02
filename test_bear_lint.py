#!/usr/bin/env python3
"""
test_bear_lint.py - Plain assert-based tests for bear_lint.py's lint_note().

No pytest, no external deps - matches bear_lint.py's own dependency-free
philosophy. Run with: python3 test_bear_lint.py
"""

import subprocess
import sys

import bear_lint
from bear_lint import SAMPLE_NOTE, BearcliError, lint_note, lint_one

FAILURES = []


def rules(issues):
    return {i.rule for i in issues}


def test_bullet_marker():
    fixed, issues = lint_note("# Title\n\n* item one\n")
    assert "- item one" in fixed, fixed
    assert "bullet-marker" in rules(issues)


def test_checklist_syntax():
    fixed, issues = lint_note("# Title\n\n-[ ] Todo without a space\n")
    assert "- [ ] Todo without a space" in fixed, fixed
    assert "checklist-syntax" in rules(issues)
    assert "bullet-marker" not in rules(issues)


def test_blockquote_spacing():
    fixed, issues = lint_note("# Title\n\n>Quote without a space\n")
    assert "> Quote without a space" in fixed, fixed
    assert "blockquote-spacing" in rules(issues)


def test_emphasis_marker():
    fixed, issues = lint_note("# Title\n\nThis is __bold__ and _italic_ text.\n")
    assert "**bold**" in fixed, fixed
    assert "*italic*" in fixed, fixed
    assert "emphasis-marker" in rules(issues)


def test_quote_style():
    fixed, issues = lint_note("# Title\n\nSome “curly quotes” here.\n")
    assert '"curly quotes"' in fixed, fixed
    assert "quote-style" in rules(issues)


def test_hr_style():
    fixed, issues = lint_note("# Title\n\nBody\n\n***\n\nMore\n")
    assert "---" in fixed, fixed
    assert "***" not in fixed, fixed
    assert "hr-style" in rules(issues)


def test_heading_skip():
    fixed, issues = lint_note("# Title\n\n### Sub\n\nBody\n")
    assert "heading-skip" in rules(issues)
    matches = [i for i in issues if i.rule == "heading-skip"]
    assert "H1" in matches[0].message and "H3" in matches[0].message, matches[0].message


def test_duplicate_h1():
    fixed, issues = lint_note("# Title\n\nBody\n\n# Another\n")
    assert "duplicate-h1" in rules(issues)


def test_missing_h1():
    fixed, issues = lint_note("Not a heading\n\nBody\n")
    assert "missing-h1" in rules(issues)


def test_stub_note():
    fixed, issues = lint_note("# Title\n")
    assert "stub-note" in rules(issues)


def test_stub_note_and_missing_h1_are_exclusive():
    _, stub_issues = lint_note("# Title\n")
    assert "missing-h1" not in rules(stub_issues)

    _, missing_issues = lint_note("Not a heading\n")
    assert "stub-note" not in rules(missing_issues)


def test_tag_format():
    fixed, issues = lint_note("# Title\n\nSome #tag# here.\n")
    assert "tag-format" in rules(issues)


def test_wiki_link():
    fixed, issues = lint_note("# Title\n\nBroken [[link here.\n")
    assert "wiki-link" in rules(issues)


def test_blank_lines():
    fixed, issues = lint_note("# Title\n\nBody1\n\n\n\nBody2\n")
    assert "\n\n\n" not in fixed, fixed
    assert "blank-lines" in rules(issues)


def test_consecutive_hrs():
    fixed, issues = lint_note("# Title\n\nBody\n\n---\n---\n\nMore\n")
    assert fixed.count("---\n") == 1, fixed
    assert "consecutive-hrs" in rules(issues)


def test_hr_spacing():
    fixed, issues = lint_note("# Title\n\nBody\n---\nMore\n")
    assert "Body\n\n---\n\nMore" in fixed, fixed
    assert "hr-spacing" in rules(issues)


def test_list_spacing():
    fixed, issues = lint_note("# Title\n\nBody\n- item\nMore\n")
    assert "Body\n\n- item\n\nMore" in fixed, fixed
    assert "list-spacing" in rules(issues)


def test_list_spacing_ordered():
    fixed, issues = lint_note("# Title\n\nBody\n1. item\nMore\n")
    assert "Body\n\n1. item\n\nMore" in fixed, fixed
    assert "list-spacing" in rules(issues)


def test_trailing_whitespace():
    fixed, issues = lint_note("# Title\n\nBody   \n")
    assert "Body   " not in fixed, fixed
    assert "trailing-whitespace" in rules(issues)


def test_trailing_whitespace_hard_break_preserved():
    fixed, issues = lint_note("# Title\n\nLine one  \nLine two\n")
    assert "Line one  \nLine two" in fixed, fixed
    assert "trailing-whitespace" not in rules(issues)


def test_trailing_whitespace_hard_break_at_end_of_note_stripped():
    fixed, issues = lint_note("# Title\n\nLast line  \n")
    assert "Last line  " not in fixed, fixed
    assert "Last line\n" in fixed, fixed
    assert "trailing-whitespace" in rules(issues)


def test_trailing_whitespace_three_spaces_still_stripped():
    fixed, issues = lint_note("# Title\n\nLine one   \nLine two\n")
    assert "Line one   " not in fixed, fixed
    assert "Line one\nLine two" in fixed, fixed
    assert "trailing-whitespace" in rules(issues)


def test_trailing_newline():
    fixed, issues = lint_note("# Title\n\nBody")
    assert fixed.endswith("Body\n"), repr(fixed)
    assert not fixed.endswith("\n\n"), repr(fixed)
    assert "trailing-newline" in rules(issues)


def test_frontmatter_blank_line():
    text = "---\ntitle: Test\n\ntags: x\n---\n# Title\n\nBody\n"
    fixed, issues = lint_note(text)
    assert "frontmatter-blank-line" in rules(issues)
    frontmatter = fixed.split("---")[1]
    assert "\n\n" not in frontmatter, repr(frontmatter)


def test_bearcli_timeout():
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout"))

    orig_run = subprocess.run
    orig_path = bear_lint._bearcli_path
    subprocess.run = fake_run
    bear_lint._bearcli_path = "/usr/bin/true"
    try:
        try:
            bear_lint.bearcli("cat", "some-id")
            raised = False
            message = ""
        except BearcliError as e:
            raised = True
            message = str(e)
        assert raised, "bearcli() did not raise BearcliError on subprocess timeout"
        assert "timed out" in message.lower(), message
    finally:
        subprocess.run = orig_run
        bear_lint._bearcli_path = orig_path


def test_lint_one_skips_locked_note():
    def fake_bearcli(*args, **kwargs):
        raise BearcliError("note is locked")

    orig_bearcli = bear_lint.bearcli
    bear_lint.bearcli = fake_bearcli

    import io
    from contextlib import redirect_stderr

    buf = io.StringIO()
    try:
        with redirect_stderr(buf):
            lint_one("some-note-id")
    except SystemExit:
        raise AssertionError("lint_one() should not sys.exit() on a locked/encrypted note")
    finally:
        bear_lint.bearcli = orig_bearcli

    output = buf.getvalue()
    assert "skipped" in output.lower(), output
    assert "some-note-id" in output, output


IDEMPOTENCY_FIXTURES = [
    SAMPLE_NOTE,
    "# Title\n\n* item one\n\n### Sub\n\n>Quote\n",
    "Not a heading\n\nBody\n",
    "# Title\n",
    "---\ntitle: Test\n\n---\n# Title\n\nBody\n---\nMore\n",
    "# Title\n\nBody\n1. item\nMore\n",
    "# Title\n\nLine one  \nLine two\n",
]


def test_idempotency():
    for text in IDEMPOTENCY_FIXTURES:
        once, _ = lint_note(text)
        twice, _ = lint_note(once)
        assert once == twice, f"lint_note is not idempotent for input:\n{text!r}\n\nfirst pass:\n{once!r}\n\nsecond pass:\n{twice!r}"


def main():
    tests = [(name, fn) for name, fn in sorted(globals().items()) if name.startswith("test_") and callable(fn)]
    passed = 0
    for name, fn in tests:
        try:
            fn()
        except AssertionError as e:
            FAILURES.append((name, e))
            print(f"FAIL {name}: {e}", file=sys.stderr)
        else:
            passed += 1
            print(f"PASS {name}", file=sys.stderr)

    print(f"\n{passed}/{len(tests)} passed.", file=sys.stderr)
    if FAILURES:
        sys.exit(1)


if __name__ == "__main__":
    main()
