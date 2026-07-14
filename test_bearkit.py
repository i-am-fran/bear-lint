#!/usr/bin/env python3
"""
test_bearkit.py - Plain assert-based tests for bearkit.py's lint_note().

No pytest, no external deps - matches bearkit.py's own dependency-free
philosophy. Run with: python3 test_bearkit.py
"""

import json
import subprocess
import sys

import bearkit
from bearkit import SAMPLE_NOTE, BearcliError, lint_note, lint_one

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


def test_extract_wikilink_targets_basic():
    lines = ["# Title", "See [[Note A]] and [[Note B]]."]
    mask = bearkit.protected_mask(lines)
    targets = bearkit.extract_wikilink_targets(lines, mask, set())
    assert targets == {"Note A", "Note B"}, targets


def test_extract_wikilink_targets_skips_masked_lines():
    lines = ["# Title", "```", "[[Note In Code]]", "```", "[[Note Outside]]"]
    mask = bearkit.protected_mask(lines)
    targets = bearkit.extract_wikilink_targets(lines, mask, set())
    assert targets == {"Note Outside"}, targets


def test_extract_wikilink_targets_ignores_empty_link():
    lines = ["# Title", "See [[ ]] here."]
    mask = bearkit.protected_mask(lines)
    targets = bearkit.extract_wikilink_targets(lines, mask, set())
    assert targets == set(), targets


def test_extract_wikilink_targets_resolves_heading_link():
    lines = ["# Title", "See [[Note A/Some Heading]]."]
    mask = bearkit.protected_mask(lines)
    titles = {"Note A"}
    targets = bearkit.extract_wikilink_targets(lines, mask, titles)
    assert targets == {"Note A"}, targets


def test_extract_wikilink_targets_resolves_alias_link():
    lines = ["# Title", "See [[Note A|display text]]."]
    mask = bearkit.protected_mask(lines)
    titles = {"Note A"}
    targets = bearkit.extract_wikilink_targets(lines, mask, titles)
    assert targets == {"Note A"}, targets


def _titles_by_lower(titles):
    return {t.lower(): t for t in titles}


def test_check_dangling_wikilinks_flags_missing_target():
    lines = ["# Title", "See [[Missing Note]] and [[Existing Note]]."]
    mask = bearkit.protected_mask(lines)
    titles = {"Existing Note", "Title"}
    found = []
    bearkit.check_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles), found)
    assert len(found) == 1, found
    assert found[0].target == "Missing Note", found[0].target
    assert not any(t.target == "Existing Note" for t in found), found


def test_check_dangling_wikilinks_skips_masked_lines():
    lines = ["# Title", "```", "[[Missing Note]]", "```"]
    mask = bearkit.protected_mask(lines)
    titles = {"Title"}
    found = []
    bearkit.check_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles), found)
    assert found == [], found


def test_check_dangling_wikilinks_ignores_empty_link():
    lines = ["# Title", "See [[ ]] here."]
    mask = bearkit.protected_mask(lines)
    titles = {"Title"}
    found = []
    bearkit.check_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles), found)
    assert found == [], found


def test_check_dangling_wikilinks_flags_case_mismatch_as_typo():
    lines = ["# Title", "See [[existing note]] here."]
    mask = bearkit.protected_mask(lines)
    titles = {"Existing Note", "Title"}
    found = []
    bearkit.check_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles), found)
    assert len(found) == 1, found
    assert found[0].target == "existing note", found[0].target
    assert found[0].suggestion == "Existing Note", found[0].suggestion


def test_check_dangling_wikilinks_flags_close_typo():
    lines = ["# Title", "See [[Existing Notee]] here."]
    mask = bearkit.protected_mask(lines)
    titles = {"Existing Note", "Title"}
    found = []
    bearkit.check_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles), found)
    assert len(found) == 1, found
    assert found[0].suggestion == "Existing Note", found[0].suggestion


def test_check_dangling_wikilinks_no_suggestion_for_unrelated_target():
    lines = ["# Title", "See [[Steve Jobs]] here."]
    mask = bearkit.protected_mask(lines)
    titles = {"Existing Note", "Title"}
    found = []
    bearkit.check_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles), found)
    assert len(found) == 1, found
    assert found[0].suggestion is None, found[0].suggestion


def test_wiki_logical_target_strips_marker_when_dangling():
    titles = {"Existing Note"}
    assert bearkit._wiki_logical_target("Missing Note +", titles) == "Missing Note"


def test_wiki_logical_target_keeps_raw_when_real_title_ends_in_marker():
    titles = {"Target +"}
    assert bearkit._wiki_logical_target("Target +", titles) == "Target +"


def test_wiki_logical_target_returns_raw_when_no_marker():
    titles = {"Existing Note"}
    assert bearkit._wiki_logical_target("Missing Note", titles) == "Missing Note"


def test_check_dangling_wikilinks_resolves_already_marked_target():
    lines = ["# Title", "See [[Missing Note +]] here."]
    mask = bearkit.protected_mask(lines)
    titles = {"Title"}
    found = []
    bearkit.check_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles), found)
    assert len(found) == 1, found
    assert found[0].target == "Missing Note", found[0].target


def test_check_dangling_wikilinks_unmarks_when_target_now_exists():
    lines = ["# Title", "See [[Missing Note +]] here."]
    mask = bearkit.protected_mask(lines)
    titles = {"Title", "Missing Note"}
    found = []
    bearkit.check_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles), found)
    assert found == [], found


def test_wiki_note_title_whole_string_exact_match_wins():
    titles = {"A/B"}
    assert bearkit._wiki_note_title("A/B", titles) == "A/B"


def test_wiki_note_title_alias_only():
    titles = {"Note"}
    assert bearkit._wiki_note_title("Note|Alias", titles) == "Note"


def test_wiki_note_title_heading_only():
    titles = {"Note"}
    assert bearkit._wiki_note_title("Note/Heading", titles) == "Note"


def test_wiki_note_title_heading_and_alias_combined():
    titles = {"Note"}
    assert bearkit._wiki_note_title("Note/Heading|Alias", titles) == "Note"


def test_wiki_note_title_alias_stripped_intermediate_match_wins():
    # A literal note title containing "/" combined with an alias: the
    # alias-stripped intermediate ("A/B") must match before the heading
    # split ever touches the "/".
    titles = {"A/B"}
    assert bearkit._wiki_note_title("A/B|Alias", titles) == "A/B"


def test_wiki_note_title_no_match_falls_back_to_heading_stripped():
    titles = {"Existing Note"}
    assert bearkit._wiki_note_title("Missing Thing/Heading", titles) == "Missing Thing"


def test_check_dangling_wikilinks_heading_link_to_existing_note_not_flagged():
    lines = ["# Title", "See [[Existing Note/Some Heading]] here."]
    mask = bearkit.protected_mask(lines)
    titles = {"Existing Note", "Title"}
    found = []
    bearkit.check_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles), found)
    assert found == [], found


def test_check_dangling_wikilinks_alias_link_to_existing_note_not_flagged():
    lines = ["# Title", "See [[Existing Note|display text]] here."]
    mask = bearkit.protected_mask(lines)
    titles = {"Existing Note", "Title"}
    found = []
    bearkit.check_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles), found)
    assert found == [], found


def test_check_dangling_wikilinks_combined_heading_alias_to_existing_note_not_flagged():
    lines = ["# Title", "See [[Existing Note/Some Heading|display text]] here."]
    mask = bearkit.protected_mask(lines)
    titles = {"Existing Note", "Title"}
    found = []
    bearkit.check_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles), found)
    assert found == [], found


def test_check_dangling_wikilinks_flags_dangling_heading_link_with_full_target():
    lines = ["# Title", "See [[Missing Note/Some Heading]] here."]
    mask = bearkit.protected_mask(lines)
    titles = {"Title"}
    found = []
    bearkit.check_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles), found)
    assert len(found) == 1, found
    assert found[0].target == "Missing Note/Some Heading", found[0].target
    assert found[0].suggestion is None, found[0].suggestion


def test_check_dangling_wikilinks_typo_suggestion_preserves_heading_suffix():
    lines = ["# Title", "See [[Existing Notee/Some Heading]] here."]
    mask = bearkit.protected_mask(lines)
    titles = {"Existing Note", "Title"}
    found = []
    bearkit.check_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles), found)
    assert len(found) == 1, found
    assert found[0].target == "Existing Notee/Some Heading", found[0].target
    assert found[0].suggestion == "Existing Note/Some Heading", found[0].suggestion


def test_check_dangling_wikilinks_typo_suggestion_preserves_alias_suffix():
    lines = ["# Title", "See [[Existing Notee|display text]] here."]
    mask = bearkit.protected_mask(lines)
    titles = {"Existing Note", "Title"}
    found = []
    bearkit.check_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles), found)
    assert len(found) == 1, found
    assert found[0].suggestion == "Existing Note|display text", found[0].suggestion


def test_mark_dangling_wikilinks_appends_marker():
    lines = ["# Title", "See [[Missing Note]] here."]
    mask = bearkit.protected_mask(lines)
    titles = {"Title"}
    new_lines, marked, unmarked = bearkit.mark_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles))
    assert new_lines[1] == "See [[Missing Note +]] here.", new_lines
    assert marked == {"Missing Note"}, marked
    assert unmarked == set(), unmarked


def test_mark_dangling_wikilinks_is_idempotent():
    lines = ["# Title", "See [[Missing Note +]] here."]
    mask = bearkit.protected_mask(lines)
    titles = {"Title"}
    new_lines, marked, unmarked = bearkit.mark_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles))
    assert new_lines == lines, new_lines
    assert marked == set(), marked
    assert unmarked == set(), unmarked


def test_mark_dangling_wikilinks_unmarks_when_target_now_exists():
    lines = ["# Title", "See [[Missing Note +]] here."]
    mask = bearkit.protected_mask(lines)
    titles = {"Title", "Missing Note"}
    new_lines, marked, unmarked = bearkit.mark_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles))
    assert new_lines[1] == "See [[Missing Note]] here.", new_lines
    assert unmarked == {"Missing Note"}, unmarked
    assert marked == set(), marked


def test_mark_dangling_wikilinks_leaves_typo_suggestions_unmarked():
    lines = ["# Title", "See [[existing note]] here."]
    mask = bearkit.protected_mask(lines)
    titles = {"Title", "Existing Note"}
    new_lines, marked, unmarked = bearkit.mark_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles))
    assert new_lines == lines, new_lines
    assert marked == set(), marked
    assert unmarked == set(), unmarked


def test_mark_dangling_wikilinks_skips_masked_lines():
    lines = ["# Title", "```", "[[Missing Note]]", "```"]
    mask = bearkit.protected_mask(lines)
    titles = {"Title"}
    new_lines, marked, unmarked = bearkit.mark_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles))
    assert new_lines == lines, new_lines
    assert marked == set(), marked
    assert unmarked == set(), unmarked


def test_mark_dangling_wikilinks_ignores_empty_link():
    lines = ["# Title", "See [[ ]] here."]
    mask = bearkit.protected_mask(lines)
    titles = {"Title"}
    new_lines, marked, unmarked = bearkit.mark_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles))
    assert new_lines == lines, new_lines
    assert marked == set(), marked


def test_mark_dangling_wikilinks_heading_link_to_existing_note_never_marked():
    lines = ["# Title", "See [[Existing Note/Some Heading]] here."]
    mask = bearkit.protected_mask(lines)
    titles = {"Title", "Existing Note"}
    new_lines, marked, unmarked = bearkit.mark_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles))
    assert new_lines == lines, new_lines
    assert marked == set(), marked
    assert unmarked == set(), unmarked


def test_mark_dangling_wikilinks_alias_link_to_existing_note_never_marked():
    lines = ["# Title", "See [[Existing Note|display text]] here."]
    mask = bearkit.protected_mask(lines)
    titles = {"Title", "Existing Note"}
    new_lines, marked, unmarked = bearkit.mark_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles))
    assert new_lines == lines, new_lines
    assert marked == set(), marked
    assert unmarked == set(), unmarked


def test_mark_dangling_wikilinks_dangling_heading_link_marks_suffix_at_end():
    lines = ["# Title", "See [[Missing Note/Some Heading]] here."]
    mask = bearkit.protected_mask(lines)
    titles = {"Title"}
    new_lines, marked, unmarked = bearkit.mark_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles))
    assert new_lines[1] == "See [[Missing Note/Some Heading +]] here.", new_lines
    assert marked == {"Missing Note/Some Heading"}, marked
    assert unmarked == set(), unmarked


def test_mark_dangling_wikilinks_compound_target_is_idempotent():
    lines = ["# Title", "See [[Missing Note/Some Heading +]] here."]
    mask = bearkit.protected_mask(lines)
    titles = {"Title"}
    new_lines, marked, unmarked = bearkit.mark_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles))
    assert new_lines == lines, new_lines
    assert marked == set(), marked
    assert unmarked == set(), unmarked


def test_mark_dangling_wikilinks_compound_target_unmarks_when_note_now_exists():
    lines = ["# Title", "See [[Missing Note/Some Heading +]] here."]
    mask = bearkit.protected_mask(lines)
    titles = {"Title", "Missing Note"}
    new_lines, marked, unmarked = bearkit.mark_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles))
    assert new_lines[1] == "See [[Missing Note/Some Heading]] here.", new_lines
    assert unmarked == {"Missing Note/Some Heading"}, unmarked
    assert marked == set(), marked


def test_render_wiki_body_shows_marker_for_marked_target():
    targets = [bearkit.WikiTarget("Missing Note", marked=True)]
    body = bearkit.render_wiki_body(targets)
    assert body == "- [[Missing Note +]]", body


def test_render_wiki_body_unmarked_targets_get_own_line():
    body = bearkit.render_wiki_body([], unmarked={"Missing Note"})
    assert body == "- [[Missing Note]] — no longer dangling, marker removed", body


def test_render_wiki_body_without_marking_is_unchanged():
    targets = [bearkit.WikiTarget("Missing Note")]
    body = bearkit.render_wiki_body(targets)
    assert body == "- [[Missing Note]]", body


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
    orig_path = bearkit._bearcli_path
    subprocess.run = fake_run
    bearkit._bearcli_path = "/usr/bin/true"
    try:
        try:
            bearkit.bearcli("cat", "some-id")
            raised = False
            message = ""
        except BearcliError as e:
            raised = True
            message = str(e)
        assert raised, "bearcli() did not raise BearcliError on subprocess timeout"
        assert "timed out" in message.lower(), message
    finally:
        subprocess.run = orig_run
        bearkit._bearcli_path = orig_path


def test_lint_one_skips_locked_note():
    def fake_bearcli(*args, **kwargs):
        raise BearcliError("note is locked")

    orig_bearcli = bearkit.bearcli
    bearkit.bearcli = fake_bearcli

    import io
    from contextlib import redirect_stderr

    buf = io.StringIO()
    try:
        with redirect_stderr(buf):
            lint_one("some-note-id")
    except SystemExit:
        raise AssertionError("lint_one() should not sys.exit() on a locked/encrypted note")
    finally:
        bearkit.bearcli = orig_bearcli

    output = buf.getvalue()
    assert "skipped" in output.lower(), output
    assert "some-note-id" in output, output


def test_lint_one_by_tag_fetches_and_threads_tags():
    def fake_bearcli(*args, **kwargs):
        if args[0] == "show":
            return json.dumps({"title": "My Note", "tags": ["#work"]})
        if args[0] == "cat":
            return "# My Note\n\nBody.\n"
        raise AssertionError(f"unexpected bearcli call: {args}")

    orig_bearcli = bearkit.bearcli
    bearkit.bearcli = fake_bearcli
    try:
        sections = []
        lint_one("some-note-id", sections=sections, by_tag=True)
    finally:
        bearkit.bearcli = orig_bearcli

    assert len(sections) == 1, sections
    entry = sections[0]
    assert isinstance(entry, bearkit.ReportEntry), entry
    assert entry.heading == "[[My Note]] (some-note-id)", entry
    assert entry.tags == ["#work"], entry


def test_lint_one_lints_a_bearkit_tagged_note_when_id_given_explicitly():
    # -i/--id is an explicit request and must be honored even if the note
    # happens to carry a #bearkit/* tag - self-exclusion only governs
    # automatic scan sources, not direct access by ID.
    def fake_bearcli(*args, **kwargs):
        if args[0] == "show":
            return "My Report"
        if args[0] == "cat":
            return "# My Report\n\n* stray bullet\n"
        if args[0] == "overwrite":
            return ""
        raise AssertionError(f"unexpected bearcli call: {args}")

    orig_bearcli = bearkit.bearcli
    bearkit.bearcli = fake_bearcli
    try:
        sections = []
        lint_one("some-note-id", sections=sections)
    finally:
        bearkit.bearcli = orig_bearcli

    assert len(sections) == 1, sections


def test_lint_all_excludes_bearkit_tagged_notes():
    notes_json = json.dumps([
        {"id": "id-1", "title": "Note One", "tags": []},
        {"id": "id-2", "title": "BearKit Lint Report — 2026-01-01 00:00", "tags": ["#bearkit", "#bearkit/edits"]},
    ])

    def fake_bearcli(*args, **kwargs):
        if args[0] == "list":
            return notes_json
        if args[0] == "cat":
            if args[1] == "id-2":
                raise AssertionError("lint_all should not fetch the body of a #bearkit/edits tagged note")
            return "# Note One\n\n* stray bullet\n"
        if args[0] == "overwrite":
            return ""
        raise AssertionError(f"unexpected bearcli call: {args}")

    orig_bearcli = bearkit.bearcli
    bearkit.bearcli = fake_bearcli
    try:
        bearkit.lint_all(sections=[], yes=True)
    finally:
        bearkit.bearcli = orig_bearcli


def test_lint_all_scoped_by_tag():
    notes_json = json.dumps([
        {"id": "id-1", "title": "Work Note", "tags": ["#work"]},
        {"id": "id-2", "title": "Other Note", "tags": ["#home"]},
    ])

    def fake_bearcli(*args, **kwargs):
        if args[0] == "list":
            return notes_json
        if args[0] == "cat":
            if args[1] == "id-2":
                raise AssertionError("lint_all(tag=...) should not fetch notes outside the tag scope")
            return "# Work Note\n\nAll good.\n"
        raise AssertionError(f"unexpected bearcli call: {args}")

    orig_bearcli = bearkit.bearcli
    bearkit.bearcli = fake_bearcli
    try:
        bearkit.lint_all(tag="work", sections=[], yes=True)
    finally:
        bearkit.bearcli = orig_bearcli


def test_check_wikilinks_scoped_by_tag_still_resolves_targets_vault_wide():
    # A #work note linking to a note outside #work must not be misflagged
    # as dangling just because the target wasn't in the scoped fetch.
    notes_json = json.dumps([
        {"id": "id-1", "title": "Work Note", "tags": ["#work"]},
        {"id": "id-2", "title": "Other Note", "tags": ["#home"]},
    ])
    contents = {"id-1": "# Work Note\n\nSee [[Other Note]].\n"}

    def fake_bearcli(*args, **kwargs):
        if args[0] == "list":
            return notes_json
        if args[0] == "cat":
            if args[1] == "id-2":
                raise AssertionError("check_wikilinks(tag=...) should not fetch notes outside the tag scope")
            return contents[args[1]]
        raise AssertionError(f"unexpected bearcli call: {args}")

    orig_bearcli = bearkit.bearcli
    bearkit.bearcli = fake_bearcli

    import io
    from contextlib import redirect_stderr

    buf = io.StringIO()
    try:
        with redirect_stderr(buf):
            bearkit.check_wikilinks(tag="work")
    finally:
        bearkit.bearcli = orig_bearcli

    assert "0 dangling wikilink(s) found" in buf.getvalue(), buf.getvalue()


def test_write_report_note_includes_description():
    captured = {}

    def fake_bearcli(*args, **kwargs):
        captured["args"] = args
        captured["stdin"] = kwargs.get("stdin")
        return ""

    orig_bearcli = bearkit.bearcli
    bearkit.bearcli = fake_bearcli
    try:
        bearkit.write_report_note(
            ["## [[Note]]\n\nBody"], title_prefix="Bear Lint Report", description="Some description.",
            tag=bearkit.BEARKIT_EDITS_TAG,
        )
    finally:
        bearkit.bearcli = orig_bearcli

    stdin = captured["stdin"]
    assert stdin.startswith("Some description.\n\n"), stdin
    assert "## [[Note]]" in stdin, stdin


def test_render_grouped_sections_groups_by_tag_and_untagged():
    entries = [
        bearkit.ReportEntry("[[Note A]] (id-a)", "**1 issue(s) fixed**", ["#work"]),
        bearkit.ReportEntry("[[Note B]] (id-b)", "No issues found.", []),
        bearkit.ReportEntry("[[Note C]] (id-c)", "No issues found.", ["#home"]),
    ]
    rendered = bearkit.render_grouped_sections(entries)

    assert rendered.index("## `#home`") < rendered.index("## `#work`") < rendered.index("## Untagged"), rendered
    assert "### [[Note A]] (id-a)\n\n**1 issue(s) fixed**" in rendered, rendered
    assert "### [[Note B]] (id-b)\n\nNo issues found." in rendered, rendered
    assert "### [[Note C]] (id-c)\n\nNo issues found." in rendered, rendered


def test_render_grouped_sections_shields_tag_headings_from_bear():
    entries = [bearkit.ReportEntry("[[Note A]] (id-a)", "Body", ["#work"])]
    rendered = bearkit.render_grouped_sections(entries)

    assert "## `#work`" in rendered, rendered
    assert "## #work" not in rendered, rendered


def test_render_grouped_sections_repeats_multi_tag_entries():
    entries = [bearkit.ReportEntry("[[Note A]] (id-a)", "Body", ["#home", "#work"])]
    rendered = bearkit.render_grouped_sections(entries)

    assert rendered.count("[[Note A]] (id-a)") == 2, rendered
    assert "## `#home`" in rendered and "## `#work`" in rendered, rendered


def test_render_grouped_sections_passes_raw_strings_through():
    entries = [
        bearkit.ReportEntry("[[Note A]] (id-a)", "Body", ["#work"]),
        "---\n\n**1 notes checked, 1 fixed.**",
    ]
    rendered = bearkit.render_grouped_sections(entries)

    assert rendered.endswith("---\n\n**1 notes checked, 1 fixed.**"), rendered


def test_write_report_note_by_tag_groups_sections():
    captured = {}

    def fake_bearcli(*args, **kwargs):
        captured["stdin"] = kwargs.get("stdin")
        return ""

    orig_bearcli = bearkit.bearcli
    bearkit.bearcli = fake_bearcli
    try:
        bearkit.write_report_note(
            [bearkit.ReportEntry("[[Note]] (id)", "No issues found.", ["#work"])],
            title_prefix="Bear Lint Report",
            description="Some description.",
            tag=bearkit.BEARKIT_EDITS_TAG,
            group_by_tag=True,
        )
    finally:
        bearkit.bearcli = orig_bearcli

    stdin = captured["stdin"]
    assert "## `#work`" in stdin, stdin
    assert "### [[Note]] (id)" in stdin, stdin


def test_lint_wiki_reports_dangling_links():
    notes_json = json.dumps([
        {"id": "id-1", "title": "Note One"},
        {"id": "id-2", "title": "Note Two"},
    ])
    contents = {
        "id-1": "# Note One\n\nSee [[Note Two]] and [[Missing Note]].\n",
        "id-2": "# Note Two\n\nAll good, links to [[Note One]].\n",
    }

    def fake_bearcli(*args, **kwargs):
        if args[0] == "list":
            return notes_json
        if args[0] == "cat":
            return contents[args[1]]
        raise AssertionError(f"unexpected bearcli call: {args}")

    orig_bearcli = bearkit.bearcli
    bearkit.bearcli = fake_bearcli

    import io
    from contextlib import redirect_stderr

    buf = io.StringIO()
    sections = []
    try:
        with redirect_stderr(buf):
            bearkit.check_wikilinks(sections=sections)
    finally:
        bearkit.bearcli = orig_bearcli

    output = buf.getvalue()
    assert "[[Missing Note]]" in output, output

    # Only the note with an actual dangling link gets a section, plus the
    # trailing summary section - Note Two (no dangling links) is skipped.
    assert len(sections) == 2, sections
    assert sections[0] == "## [[Note One]]\n\n- [[Missing Note]]", sections[0]
    assert "id-1" not in sections[0], sections[0]
    assert not any("Note Two" in s for s in sections[:-1]), sections


def test_lint_wiki_reports_typo_suggestion_separately():
    notes_json = json.dumps([
        {"id": "id-1", "title": "Note One"},
        {"id": "id-2", "title": "Existing Note"},
    ])
    contents = {
        "id-1": "# Note One\n\nSee [[existing note]] and [[Some Unrelated Thing]].\n",
        "id-2": "# Existing Note\n\nNo links.\n",
    }

    def fake_bearcli(*args, **kwargs):
        if args[0] == "list":
            return notes_json
        if args[0] == "cat":
            return contents[args[1]]
        raise AssertionError(f"unexpected bearcli call: {args}")

    orig_bearcli = bearkit.bearcli
    bearkit.bearcli = fake_bearcli

    import io
    from contextlib import redirect_stderr

    buf = io.StringIO()
    sections = []
    try:
        with redirect_stderr(buf):
            bearkit.check_wikilinks(sections=sections)
    finally:
        bearkit.bearcli = orig_bearcli

    output = buf.getvalue()
    assert "did you mean [[Existing Note]]?" in output, output

    section = sections[0]
    assert "did you mean [[Existing Note]]?" in section, section
    assert "- [[Some Unrelated Thing]]" in section, section
    assert "[[Some Unrelated Thing]] →" not in section, section


def test_check_wikilinks_skips_bearkit_tagged_notes():
    notes_json = json.dumps([
        {"id": "id-1", "title": "Note One", "tags": []},
        {"id": "id-2", "title": "BearKit Wikilinks Report — 2026-01-01 00:00", "tags": ["#bearkit", "#bearkit/lists"]},
    ])

    def fake_bearcli(*args, **kwargs):
        if args[0] == "list":
            return notes_json
        if args[0] == "cat":
            note_id = args[1]
            if note_id == "id-2":
                raise AssertionError("check_wikilinks should not fetch the body of a #bearkit/lists tagged note")
            return "# Note One\n\nSee [[Missing Note]].\n"
        raise AssertionError(f"unexpected bearcli call: {args}")

    orig_bearcli = bearkit.bearcli
    bearkit.bearcli = fake_bearcli

    import io
    from contextlib import redirect_stderr

    buf = io.StringIO()
    sections = []
    try:
        with redirect_stderr(buf):
            bearkit.check_wikilinks(sections=sections)
    finally:
        bearkit.bearcli = orig_bearcli

    output = buf.getvalue()
    assert "BearKit Wikilinks Report" not in output, output
    assert "1 notes checked, 1 dangling wikilink(s) found in 1 note(s)." in output, output


def test_lint_wiki_by_tag_builds_report_entries_with_tags():
    notes_json = json.dumps([
        {"id": "id-1", "title": "Note One", "tags": ["#work"]},
    ])

    def fake_bearcli(*args, **kwargs):
        if args[0] == "list":
            return notes_json
        if args[0] == "cat":
            return "# Note One\n\nSee [[Missing Note]].\n"
        raise AssertionError(f"unexpected bearcli call: {args}")

    orig_bearcli = bearkit.bearcli
    bearkit.bearcli = fake_bearcli
    try:
        sections = []
        bearkit.check_wikilinks(sections=sections, by_tag=True)
    finally:
        bearkit.bearcli = orig_bearcli

    entries = [s for s in sections if isinstance(s, bearkit.ReportEntry)]
    assert len(entries) == 1, sections
    assert entries[0].heading == "[[Note One]]", entries[0]
    assert entries[0].tags == ["#work"], entries[0]
    assert "Missing Note" in entries[0].body, entries[0]


def test_lint_wiki_mark_rewrites_dangling_link():
    notes_json = json.dumps([
        {"id": "id-1", "title": "Note One", "tags": []},
    ])
    contents = {"id-1": "# Note One\n\nSee [[Missing Note]].\n"}
    written = {}

    def fake_bearcli(*args, **kwargs):
        if args[0] == "list":
            return notes_json
        if args[0] == "cat":
            return contents[args[1]]
        if args[0] == "overwrite":
            written[args[1]] = kwargs.get("stdin")
            return ""
        raise AssertionError(f"unexpected bearcli call: {args}")

    orig_bearcli = bearkit.bearcli
    bearkit.bearcli = fake_bearcli
    try:
        sections = []
        bearkit.check_wikilinks(sections=sections, mark=True, yes=True)
    finally:
        bearkit.bearcli = orig_bearcli

    assert written["id-1"] == "# Note One\n\nSee [[Missing Note +]].\n", written
    assert any("Missing Note +" in s for s in sections), sections


def test_lint_wiki_mark_skips_reporting_when_write_fails():
    notes_json = json.dumps([
        {"id": "id-1", "title": "Note One", "tags": []},
    ])
    contents = {"id-1": "# Note One\n\nSee [[Missing Note]].\n"}

    def fake_bearcli(*args, **kwargs):
        if args[0] == "list":
            return notes_json
        if args[0] == "cat":
            return contents[args[1]]
        if args[0] == "overwrite":
            raise BearcliError("boom")
        raise AssertionError(f"unexpected bearcli call: {args}")

    orig_bearcli = bearkit.bearcli
    bearkit.bearcli = fake_bearcli

    import io
    from contextlib import redirect_stderr

    buf = io.StringIO()
    sections = []
    try:
        with redirect_stderr(buf):
            bearkit.check_wikilinks(sections=sections, mark=True, yes=True)
    finally:
        bearkit.bearcli = orig_bearcli

    output = buf.getvalue()
    assert "could not write" in output, output
    assert not any("Missing Note +" in s for s in sections), sections


def test_lint_wiki_mark_dry_run_does_not_write():
    notes_json = json.dumps([
        {"id": "id-1", "title": "Note One", "tags": []},
    ])
    contents = {"id-1": "# Note One\n\nSee [[Missing Note]].\n"}

    def fake_bearcli(*args, **kwargs):
        if args[0] == "list":
            return notes_json
        if args[0] == "cat":
            return contents[args[1]]
        if args[0] == "overwrite":
            raise AssertionError("dry-run should not write")
        raise AssertionError(f"unexpected bearcli call: {args}")

    orig_bearcli = bearkit.bearcli
    bearkit.bearcli = fake_bearcli

    import io
    from contextlib import redirect_stderr

    buf = io.StringIO()
    try:
        with redirect_stderr(buf):
            bearkit.check_wikilinks(mark=True, dry_run=True)
    finally:
        bearkit.bearcli = orig_bearcli

    assert "Missing Note +" in buf.getvalue(), buf.getvalue()


def test_lint_wiki_mark_leaves_typo_suggestions_unmarked():
    notes_json = json.dumps([
        {"id": "id-1", "title": "Note One", "tags": []},
        {"id": "id-2", "title": "Existing Note", "tags": []},
    ])
    contents = {
        "id-1": "# Note One\n\nSee [[existing note]].\n",
        "id-2": "# Existing Note\n\nNo links.\n",
    }
    written = {}

    def fake_bearcli(*args, **kwargs):
        if args[0] == "list":
            return notes_json
        if args[0] == "cat":
            return contents[args[1]]
        if args[0] == "overwrite":
            written[args[1]] = kwargs.get("stdin")
            return ""
        raise AssertionError(f"unexpected bearcli call: {args}")

    orig_bearcli = bearkit.bearcli
    bearkit.bearcli = fake_bearcli
    try:
        bearkit.check_wikilinks(mark=True, yes=True)
    finally:
        bearkit.bearcli = orig_bearcli

    assert "id-1" not in written, written


def test_lint_wiki_mark_writes_back_unmark_only_changes():
    notes_json = json.dumps([
        {"id": "id-1", "title": "Note One", "tags": []},
        {"id": "id-2", "title": "Missing Note", "tags": []},
    ])
    contents = {
        "id-1": "# Note One\n\nSee [[Missing Note +]].\n",
        "id-2": "# Missing Note\n\nNo links.\n",
    }
    written = {}

    def fake_bearcli(*args, **kwargs):
        if args[0] == "list":
            return notes_json
        if args[0] == "cat":
            return contents[args[1]]
        if args[0] == "overwrite":
            written[args[1]] = kwargs.get("stdin")
            return ""
        raise AssertionError(f"unexpected bearcli call: {args}")

    orig_bearcli = bearkit.bearcli
    bearkit.bearcli = fake_bearcli
    try:
        sections = []
        bearkit.check_wikilinks(sections=sections, mark=True, yes=True)
    finally:
        bearkit.bearcli = orig_bearcli

    assert written["id-1"] == "# Note One\n\nSee [[Missing Note]].\n", written
    assert any("marker removed" in s for s in sections), sections


def test_lint_wiki_mark_handles_marked_and_unmarked_in_same_note():
    notes_json = json.dumps([
        {"id": "id-1", "title": "Note One", "tags": []},
        {"id": "id-2", "title": "Now Exists", "tags": []},
    ])
    contents = {
        "id-1": (
            "# Note One\n\n"
            "See [[Still Missing]] and [[Now Exists +]].\n"
        ),
        "id-2": "# Now Exists\n\nNo links.\n",
    }
    written = {}

    def fake_bearcli(*args, **kwargs):
        if args[0] == "list":
            return notes_json
        if args[0] == "cat":
            return contents[args[1]]
        if args[0] == "overwrite":
            written[args[1]] = kwargs.get("stdin")
            return ""
        raise AssertionError(f"unexpected bearcli call: {args}")

    orig_bearcli = bearkit.bearcli
    bearkit.bearcli = fake_bearcli
    try:
        sections = []
        bearkit.check_wikilinks(sections=sections, mark=True, yes=True)
    finally:
        bearkit.bearcli = orig_bearcli

    assert written["id-1"] == (
        "# Note One\n\nSee [[Still Missing +]] and [[Now Exists]].\n"
    ), written
    assert "[[Now Exists +]]" not in written["id-1"], written

    assert any("Still Missing +" in s for s in sections), sections
    assert any("marker removed" in s for s in sections), sections


def test_lint_wiki_mark_does_not_corrupt_valid_heading_link():
    # Regression test for the reported bug: a valid Bear heading-link like
    # [[Bear/Things I don't love]] must never be rewritten by --mark.
    notes_json = json.dumps([
        {"id": "id-1", "title": "Note One", "tags": []},
        {"id": "id-2", "title": "Bear", "tags": []},
    ])
    contents = {
        "id-1": "# Note One\n\nSee [[Bear/Things I don't love]].\n",
        "id-2": "# Bear\n\n## Things I don't love\n\nSome text.\n",
    }
    written = {}

    def fake_bearcli(*args, **kwargs):
        if args[0] == "list":
            return notes_json
        if args[0] == "cat":
            return contents[args[1]]
        if args[0] == "overwrite":
            written[args[1]] = kwargs.get("stdin")
            return ""
        raise AssertionError(f"unexpected bearcli call: {args}")

    orig_bearcli = bearkit.bearcli
    bearkit.bearcli = fake_bearcli
    try:
        sections = []
        bearkit.check_wikilinks(sections=sections, mark=True, yes=True)
    finally:
        bearkit.bearcli = orig_bearcli

    assert "id-1" not in written, written
    assert not any("Things I don't love +" in s for s in sections), sections


def test_lint_wiki_without_mark_never_writes():
    notes_json = json.dumps([{"id": "id-1", "title": "Note One", "tags": []}])
    contents = {"id-1": "# Note One\n\nSee [[Missing Note]].\n"}

    def fake_bearcli(*args, **kwargs):
        if args[0] == "list":
            return notes_json
        if args[0] == "cat":
            return contents[args[1]]
        if args[0] == "overwrite":
            raise AssertionError("plain --wiki should never write")
        raise AssertionError(f"unexpected bearcli call: {args}")

    orig_bearcli = bearkit.bearcli
    bearkit.bearcli = fake_bearcli
    try:
        bearkit.check_wikilinks(sections=[])
    finally:
        bearkit.bearcli = orig_bearcli


def test_lint_orphans_flags_notes_with_no_incoming_links():
    notes_json = json.dumps([
        {"id": "id-1", "title": "Note One"},
        {"id": "id-2", "title": "Note Two"},
        {"id": "id-3", "title": "Note Three"},
    ])
    contents = {
        "id-1": "# Note One\n\nSee [[Note Two]].\n",
        "id-2": "# Note Two\n\nNothing links here but Note One does.\n",
        "id-3": "# Note Three\n\nNobody links to this one.\n",
    }

    def fake_bearcli(*args, **kwargs):
        if args[0] == "list":
            return notes_json
        if args[0] == "cat":
            return contents[args[1]]
        raise AssertionError(f"unexpected bearcli call: {args}")

    orig_bearcli = bearkit.bearcli
    bearkit.bearcli = fake_bearcli

    import io
    from contextlib import redirect_stderr

    buf = io.StringIO()
    sections = []
    try:
        with redirect_stderr(buf):
            bearkit.find_orphans(sections=sections)
    finally:
        bearkit.bearcli = orig_bearcli

    output = buf.getvalue()
    assert "[[Note One]]" in output, output
    assert "[[Note Three]]" in output, output
    assert "[[Note Two]]" not in output, output

    assert len(sections) == 2, sections
    assert sections[0] == "## Orphaned Notes\n\n- [[Note One]]\n- [[Note Three]]", sections[0]


def test_find_orphans_excludes_bearkit_tagged_notes():
    notes_json = json.dumps([
        {"id": "id-1", "title": "Note One", "tags": []},
        {"id": "id-2", "title": "BearKit Orphans Report — 2026-01-01 00:00", "tags": ["#bearkit", "#bearkit/lists"]},
    ])

    def fake_bearcli(*args, **kwargs):
        if args[0] == "list":
            return notes_json
        if args[0] == "cat":
            note_id = args[1]
            if note_id == "id-2":
                raise AssertionError("find_orphans should not fetch the body of a #bearkit/lists tagged note")
            return "# Note One\n\nNo links to anything.\n"
        raise AssertionError(f"unexpected bearcli call: {args}")

    orig_bearcli = bearkit.bearcli
    bearkit.bearcli = fake_bearcli

    import io
    from contextlib import redirect_stderr

    buf = io.StringIO()
    sections = []
    try:
        with redirect_stderr(buf):
            bearkit.find_orphans(sections=sections)
    finally:
        bearkit.bearcli = orig_bearcli

    output = buf.getvalue()
    assert "BearKit Orphans Report" not in output, output
    assert "[[Note One]]" in output, output
    assert "1 notes checked, 1 orphan(s) found." in output, output


def test_find_orphans_scoped_by_tag_still_sees_links_from_outside_scope():
    # A #work note that's only linked to from a note outside #work must
    # still count as linked, not a false-positive orphan - the incoming
    # link scan always covers the whole vault, even when -t narrows which
    # titles are reportable.
    notes_json = json.dumps([
        {"id": "id-1", "title": "Outside Note", "tags": []},
        {"id": "id-2", "title": "Work Note", "tags": ["#work"]},
    ])
    contents = {
        "id-1": "# Outside Note\n\nSee [[Work Note]].\n",
        "id-2": "# Work Note\n\nNo links.\n",
    }

    def fake_bearcli(*args, **kwargs):
        if args[0] == "list":
            return notes_json
        if args[0] == "cat":
            return contents[args[1]]
        raise AssertionError(f"unexpected bearcli call: {args}")

    orig_bearcli = bearkit.bearcli
    bearkit.bearcli = fake_bearcli

    import io
    from contextlib import redirect_stderr

    buf = io.StringIO()
    sections = []
    try:
        with redirect_stderr(buf):
            bearkit.find_orphans(sections=sections, tag="work")
    finally:
        bearkit.bearcli = orig_bearcli

    output = buf.getvalue()
    assert "0 orphaned note(s)" in output, output


def test_lint_orphans_by_tag_groups_titles_as_flat_lists():
    # Orphan bodies are all the same boilerplate ("nothing links here"), so
    # grouped mode renders titles as a plain per-tag bullet list rather than
    # repeating a heading + boilerplate body for every note.
    notes_json = json.dumps([
        {"id": "id-1", "title": "Note One", "tags": ["#home", "#work"]},
        {"id": "id-2", "title": "Note Two", "tags": []},
    ])
    contents = {
        "id-1": "# Note One\n\nNo links.\n",
        "id-2": "# Note Two\n\nNo links.\n",
    }

    def fake_bearcli(*args, **kwargs):
        if args[0] == "list":
            return notes_json
        if args[0] == "cat":
            return contents[args[1]]
        raise AssertionError(f"unexpected bearcli call: {args}")

    orig_bearcli = bearkit.bearcli
    bearkit.bearcli = fake_bearcli
    try:
        sections = []
        bearkit.find_orphans(sections=sections, by_tag=True)
    finally:
        bearkit.bearcli = orig_bearcli

    assert not any(isinstance(s, bearkit.ReportEntry) for s in sections), sections

    home_section = next(s for s in sections if s.startswith("## `#home`"))
    work_section = next(s for s in sections if s.startswith("## `#work`"))
    untagged_section = next(s for s in sections if s.startswith("## Untagged"))

    assert home_section == "## `#home`\n\n- [[Note One]]", home_section
    assert work_section == "## `#work`\n\n- [[Note One]]", work_section
    assert untagged_section == "## Untagged\n\n- [[Note Two]]", untagged_section
    assert "### " not in "\n".join(sections), sections
    assert "## #home" not in "\n".join(sections), sections
    assert "## #work" not in "\n".join(sections), sections


def test_lint_orphans_heading_only_link_counts_as_incoming_link():
    notes_json = json.dumps([
        {"id": "id-1", "title": "Note One"},
        {"id": "id-2", "title": "Note Two"},
    ])
    contents = {
        "id-1": "# Note One\n\nSee [[Note Two/Some Heading]].\n",
        "id-2": "# Note Two\n\nNo outgoing links.\n",
    }

    def fake_bearcli(*args, **kwargs):
        if args[0] == "list":
            return notes_json
        if args[0] == "cat":
            return contents[args[1]]
        raise AssertionError(f"unexpected bearcli call: {args}")

    orig_bearcli = bearkit.bearcli
    bearkit.bearcli = fake_bearcli

    import io
    from contextlib import redirect_stderr

    buf = io.StringIO()
    sections = []
    try:
        with redirect_stderr(buf):
            bearkit.find_orphans(sections=sections)
    finally:
        bearkit.bearcli = orig_bearcli

    output = buf.getvalue()
    assert "[[Note Two]]" not in output, output
    assert "1 orphan(s) found" in output, output


def test_find_duplicates_groups_by_title():
    notes_json = json.dumps([
        {"id": "id-1", "title": "Same Title", "tags": ["#work"]},
        {"id": "id-2", "title": "Same Title", "tags": ["#home"]},
        {"id": "id-3", "title": "Unique Title", "tags": []},
    ])

    def fake_bearcli(*args, **kwargs):
        if args[0] == "list":
            return notes_json
        raise AssertionError(f"unexpected bearcli call: {args}")

    orig_bearcli = bearkit.bearcli
    bearkit.bearcli = fake_bearcli

    import io
    from contextlib import redirect_stderr

    buf = io.StringIO()
    sections = []
    try:
        with redirect_stderr(buf):
            bearkit.find_duplicates(sections=sections)
    finally:
        bearkit.bearcli = orig_bearcli

    output = buf.getvalue()
    assert '"Same Title" — 2 notes: id-1, id-2' in output, output
    assert "Unique Title" not in output, output
    assert "1 duplicate title(s) found" in output, output

    assert len(sections) == 2, sections
    assert sections[0].startswith("## Same Title (2 notes)"), sections[0]
    assert "bear://x-callback-url/open-note?id=id-1" in sections[0], sections[0]
    assert "bear://x-callback-url/open-note?id=id-2" in sections[0], sections[0]
    # Tags are backtick-shielded so Bear doesn't parse them as real tags and
    # silently apply them to the report note itself.
    assert "`#work`" in sections[0] and "`#home`" in sections[0], sections[0]
    assert "— #work" not in sections[0] and "— #home" not in sections[0], sections[0]


def test_find_duplicates_scoped_by_tag():
    notes_json = json.dumps([
        {"id": "id-1", "title": "Same Title", "tags": ["#work"]},
        {"id": "id-2", "title": "Same Title", "tags": ["#home"]},
    ])

    def fake_bearcli(*args, **kwargs):
        if args[0] == "list":
            return notes_json
        raise AssertionError(f"unexpected bearcli call: {args}")

    orig_bearcli = bearkit.bearcli
    bearkit.bearcli = fake_bearcli

    import io
    from contextlib import redirect_stderr

    buf = io.StringIO()
    sections = []
    try:
        with redirect_stderr(buf):
            bearkit.find_duplicates(sections=sections, tag="work")
    finally:
        bearkit.bearcli = orig_bearcli

    output = buf.getvalue()
    assert "0 duplicate title(s) found among 1 note(s) checked" in output, output


def test_find_duplicates_excludes_bearkit_tagged_notes():
    notes_json = json.dumps([
        {"id": "id-1", "title": "Note One", "tags": []},
        {"id": "id-2", "title": "BearKit Duplicates Report — 2026-01-01 00:00", "tags": ["#bearkit", "#bearkit/lists"]},
        {"id": "id-3", "title": "BearKit Duplicates Report — 2026-01-02 00:00", "tags": ["#bearkit", "#bearkit/lists"]},
    ])

    def fake_bearcli(*args, **kwargs):
        if args[0] == "list":
            return notes_json
        raise AssertionError(f"unexpected bearcli call: {args}")

    orig_bearcli = bearkit.bearcli
    bearkit.bearcli = fake_bearcli
    try:
        sections = []
        bearkit.find_duplicates(sections=sections)
    finally:
        bearkit.bearcli = orig_bearcli

    assert sections == ["---\n\n**1 notes checked, 0 duplicate title(s) found.**"], sections


def test_open_random_opens_chosen_notes():
    notes_json = json.dumps([
        {"id": "id-1", "title": "Note One", "tags": []},
        {"id": "id-2", "title": "Note Two", "tags": []},
    ])
    opened = []

    def fake_bearcli(*args, **kwargs):
        if args[0] == "list":
            return notes_json
        if args[0] == "app" and args[1] == "open":
            opened.append(args[2])
            return ""
        raise AssertionError(f"unexpected bearcli call: {args}")

    def fake_sample(population, k):
        return list(population)[:k]

    orig_bearcli = bearkit.bearcli
    orig_sample = bearkit.random.sample
    bearkit.bearcli = fake_bearcli
    bearkit.random.sample = fake_sample
    try:
        bearkit.open_random(count=1)
    finally:
        bearkit.bearcli = orig_bearcli
        bearkit.random.sample = orig_sample

    assert opened == ["id-1"], opened


def test_open_random_clamps_count_to_available_notes():
    notes_json = json.dumps([{"id": "id-1", "title": "Only Note", "tags": []}])
    opened = []

    def fake_bearcli(*args, **kwargs):
        if args[0] == "list":
            return notes_json
        if args[0] == "app" and args[1] == "open":
            opened.append(args[2])
            return ""
        raise AssertionError(f"unexpected bearcli call: {args}")

    orig_bearcli = bearkit.bearcli
    bearkit.bearcli = fake_bearcli
    try:
        bearkit.open_random(count=9)
    finally:
        bearkit.bearcli = orig_bearcli

    assert opened == ["id-1"], opened


def test_open_random_scoped_by_tag():
    notes_json = json.dumps([
        {"id": "id-1", "title": "Work Note", "tags": ["#work"]},
        {"id": "id-2", "title": "Home Note", "tags": ["#home"]},
    ])
    opened = []

    def fake_bearcli(*args, **kwargs):
        if args[0] == "list":
            return notes_json
        if args[0] == "app" and args[1] == "open":
            opened.append(args[2])
            return ""
        raise AssertionError(f"unexpected bearcli call: {args}")

    orig_bearcli = bearkit.bearcli
    bearkit.bearcli = fake_bearcli
    try:
        bearkit.open_random(count=1, tag="work")
    finally:
        bearkit.bearcli = orig_bearcli

    assert opened == ["id-1"], opened


def test_open_random_excludes_bearkit_tagged_notes():
    notes_json = json.dumps([
        {"id": "id-1", "title": "BearKit Lists Report", "tags": ["#bearkit", "#bearkit/lists"]},
    ])

    def fake_bearcli(*args, **kwargs):
        if args[0] == "list":
            return notes_json
        if args[0] == "app" and args[1] == "open":
            raise AssertionError("open_random should never open a #bearkit/* tagged note")
        raise AssertionError(f"unexpected bearcli call: {args}")

    orig_bearcli = bearkit.bearcli
    bearkit.bearcli = fake_bearcli

    import io
    from contextlib import redirect_stderr

    buf = io.StringIO()
    try:
        with redirect_stderr(buf):
            bearkit.open_random(count=1)
    finally:
        bearkit.bearcli = orig_bearcli

    assert "No notes found" in buf.getvalue(), buf.getvalue()


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


# --- CLI / argument parsing tests ---


def _run_main(argv):
    """Run bearkit.main() with sys.argv patched, capturing stdout/stderr and
    exit behaviour. Returns (exit_code, stdout, stderr). exit_code is None if
    main() returned normally without calling sys.exit()."""
    import io
    from contextlib import redirect_stderr, redirect_stdout

    orig_argv = sys.argv
    sys.argv = ["bearkit.py", *argv]
    out, err = io.StringIO(), io.StringIO()
    exit_code = None
    try:
        with redirect_stdout(out), redirect_stderr(err):
            try:
                bearkit.main()
            except SystemExit as e:
                exit_code = e.code
    finally:
        sys.argv = orig_argv
    return exit_code, out.getvalue(), err.getvalue()


def test_cli_unknown_command_errors_clearly():
    def fake_bearcli(*args, **kwargs):
        raise AssertionError("bearcli should not be called for an unrecognised subcommand")

    orig_bearcli = bearkit.bearcli
    bearkit.bearcli = fake_bearcli
    try:
        exit_code, out, err = _run_main(["bogus"])
    finally:
        bearkit.bearcli = orig_bearcli

    assert exit_code not in (None, 0), exit_code
    assert "invalid choice" in err.lower(), err


def test_cli_missing_subcommand_prints_help():
    exit_code, out, err = _run_main([])
    assert exit_code not in (None, 0), exit_code
    assert out == bearkit.HELP, out


def test_cli_help_prints_exact_help_string():
    exit_code, out, err = _run_main(["--help"])
    assert out == bearkit.HELP, out
    assert exit_code == 0, exit_code

    exit_code, out, err = _run_main(["-h"])
    assert out == bearkit.HELP, out
    assert exit_code == 0, exit_code


def test_cli_version_prints_version():
    exit_code, out, err = _run_main(["--version"])
    assert out == f"bearkit {bearkit.__version__}\n", out
    assert exit_code in (None, 0), exit_code


def _no_sections_dispatch(*args, **kwargs):
    pass


def _patched(name, fn):
    """Context-manager-free monkeypatch helper: returns (orig, restore_fn)."""
    orig = getattr(bearkit, name)
    setattr(bearkit, name, fn)
    return orig


def test_cli_orphans_dispatches_with_tag_and_group_by_tag():
    captured = {}

    def fake_find_orphans(sections=None, by_tag=False, tag=None):
        captured["sections"] = sections
        captured["by_tag"] = by_tag
        captured["tag"] = tag

    orig = _patched("find_orphans", fake_find_orphans)
    try:
        exit_code, out, err = _run_main(["orphans", "-t", "work", "--group-by-tag"])
    finally:
        bearkit.find_orphans = orig

    assert exit_code in (None, 0), (exit_code, err)
    assert captured.get("sections") == [], captured
    assert captured.get("by_tag") is True, captured
    assert captured.get("tag") == "work", captured


def test_cli_duplicates_dispatches_with_tag():
    captured = {}

    def fake_find_duplicates(sections=None, tag=None):
        captured["sections"] = sections
        captured["tag"] = tag

    orig = _patched("find_duplicates", fake_find_duplicates)
    try:
        exit_code, out, err = _run_main(["duplicates", "-t", "work"])
    finally:
        bearkit.find_duplicates = orig

    assert exit_code in (None, 0), (exit_code, err)
    assert captured.get("tag") == "work", captured


def test_cli_wikilinks_dispatches():
    calls = []

    def fake_check_wikilinks(**kwargs):
        calls.append(kwargs)

    orig = _patched("check_wikilinks", fake_check_wikilinks)
    try:
        exit_code, out, err = _run_main(["wikilinks"])
    finally:
        bearkit.check_wikilinks = orig

    assert exit_code in (None, 0), (exit_code, err)
    assert len(calls) == 1, calls
    assert calls[0]["mark"] is False, calls


def test_cli_wikilinks_dry_run_without_mark_rejected():
    exit_code, out, err = _run_main(["wikilinks", "-n"])
    assert exit_code not in (None, 0), exit_code
    assert "--mark" in str(exit_code), exit_code


def test_cli_wikilinks_yes_without_mark_rejected():
    exit_code, out, err = _run_main(["wikilinks", "-y"])
    assert exit_code not in (None, 0), exit_code
    assert "--mark" in str(exit_code), exit_code


def test_cli_wikilinks_mark_allows_dry_run_and_yes():
    captured = {}

    def fake_check_wikilinks(sections=None, by_tag=False, mark=False, dry_run=False, yes=False, tag=None):
        captured["mark"] = mark
        captured["dry_run"] = dry_run

    orig = _patched("check_wikilinks", fake_check_wikilinks)
    try:
        exit_code, out, err = _run_main(["wikilinks", "--mark", "-n"])
    finally:
        bearkit.check_wikilinks = orig

    assert exit_code in (None, 0), (exit_code, err)
    assert captured.get("mark") is True, captured
    assert captured.get("dry_run") is True, captured


def test_cli_lint_mutually_exclusive_id_and_tag():
    exit_code, out, err = _run_main(["lint", "-i", "some-id", "-t", "work"])
    assert exit_code not in (None, 0), exit_code


def test_cli_lint_dashes_i_dispatches_to_lint_one_without_confirmation():
    calls = []

    def fake_lint_one(note_id, sections=None, dry_run=False, by_tag=False):
        calls.append((note_id, dry_run))

    orig = _patched("lint_one", fake_lint_one)
    try:
        exit_code, out, err = _run_main(["lint", "-i", "some-note-id", "-n"])
    finally:
        bearkit.lint_one = orig

    assert exit_code in (None, 0), (exit_code, err)
    assert calls == [("some-note-id", True)], calls


def test_cli_lint_bare_dispatches_to_lint_all():
    captured = {}

    def fake_lint_all(tag=None, sections=None, dry_run=False, yes=False, by_tag=False):
        captured["tag"] = tag
        captured["yes"] = yes

    orig = _patched("lint_all", fake_lint_all)
    try:
        exit_code, out, err = _run_main(["lint", "-t", "work", "-y"])
    finally:
        bearkit.lint_all = orig

    assert exit_code in (None, 0), (exit_code, err)
    assert captured.get("tag") == "work", captured
    assert captured.get("yes") is True, captured


def test_cli_random_dispatches_with_count_and_tag():
    captured = {}

    def fake_open_random(count=1, tag=None):
        captured["count"] = count
        captured["tag"] = tag

    orig = _patched("open_random", fake_open_random)
    try:
        exit_code, out, err = _run_main(["random", "4", "-t", "evergreen"])
    finally:
        bearkit.open_random = orig

    assert exit_code in (None, 0), (exit_code, err)
    assert captured.get("count") == 4, captured
    assert captured.get("tag") == "evergreen", captured


def test_cli_random_default_count_is_one():
    captured = {}

    def fake_open_random(count=1, tag=None):
        captured["count"] = count

    orig = _patched("open_random", fake_open_random)
    try:
        exit_code, out, err = _run_main(["random"])
    finally:
        bearkit.open_random = orig

    assert exit_code in (None, 0), (exit_code, err)
    assert captured.get("count") == 1, captured


def test_cli_random_rejects_out_of_range_count():
    exit_code, out, err = _run_main(["random", "10"])
    assert exit_code not in (None, 0), exit_code

    exit_code, out, err = _run_main(["random", "0"])
    assert exit_code not in (None, 0), exit_code


def test_cli_random_never_creates_summary_note():
    def fake_open_random(count=1, tag=None):
        pass

    def fake_write_report_note(*args, **kwargs):
        raise AssertionError("random should never create a summary note")

    orig_open_random = _patched("open_random", fake_open_random)
    orig_write = _patched("write_report_note", fake_write_report_note)
    try:
        exit_code, out, err = _run_main(["random"])
    finally:
        bearkit.open_random = orig_open_random
        bearkit.write_report_note = orig_write

    assert exit_code in (None, 0), (exit_code, err)


def test_cli_list_action_creates_lists_tagged_note():
    captured = {}

    def fake_find_orphans(sections=None, by_tag=False, tag=None):
        sections.append("dummy section")

    def fake_write_report_note(sections, title_prefix, description, tag, group_by_tag=False):
        captured["tag"] = tag
        captured["title_prefix"] = title_prefix
        captured["description"] = description

    orig_find = _patched("find_orphans", fake_find_orphans)
    orig_write = _patched("write_report_note", fake_write_report_note)
    try:
        exit_code, out, err = _run_main(["orphans"])
    finally:
        bearkit.find_orphans = orig_find
        bearkit.write_report_note = orig_write

    assert exit_code in (None, 0), (exit_code, err)
    assert captured.get("tag") == bearkit.BEARKIT_LISTS_TAG, captured
    assert captured.get("title_prefix") == "BearKit Orphans Report", captured
    assert captured.get("description") == bearkit.ORPHANS_REPORT_DESCRIPTION, captured


def test_cli_edit_action_creates_edits_tagged_note():
    captured = {}

    def fake_lint_all(tag=None, sections=None, dry_run=False, yes=False, by_tag=False):
        sections.append("dummy section")

    def fake_write_report_note(sections, title_prefix, description, tag, group_by_tag=False):
        captured["tag"] = tag

    orig_lint = _patched("lint_all", fake_lint_all)
    orig_write = _patched("write_report_note", fake_write_report_note)
    try:
        exit_code, out, err = _run_main(["lint", "-y"])
    finally:
        bearkit.lint_all = orig_lint
        bearkit.write_report_note = orig_write

    assert exit_code in (None, 0), (exit_code, err)
    assert captured.get("tag") == bearkit.BEARKIT_EDITS_TAG, captured


def test_cli_edit_action_dry_run_skips_summary_note():
    def fake_lint_all(tag=None, sections=None, dry_run=False, yes=False, by_tag=False):
        sections.append("dummy section")

    def fake_write_report_note(*args, **kwargs):
        raise AssertionError("dry-run edit actions must not create a summary note")

    orig_lint = _patched("lint_all", fake_lint_all)
    orig_write = _patched("write_report_note", fake_write_report_note)
    try:
        exit_code, out, err = _run_main(["lint", "-n"])
    finally:
        bearkit.lint_all = orig_lint
        bearkit.write_report_note = orig_write

    assert exit_code in (None, 0), (exit_code, err)


def test_cli_edit_action_aborted_confirmation_skips_summary_note():
    # lint_all() itself never populates sections when the confirmation
    # prompt is declined - main() should fall through to "nothing to
    # report" rather than creating an empty/stale summary note.
    def fake_write_report_note(*args, **kwargs):
        raise AssertionError("an aborted run must not create a summary note")

    def fake_input(prompt):
        return "n"

    notes_json = json.dumps([{"id": "id-1", "title": "Note One", "tags": []}])

    def fake_bearcli(*args, **kwargs):
        if args[0] == "list":
            return notes_json
        raise AssertionError(f"unexpected bearcli call: {args}")

    orig_write = _patched("write_report_note", fake_write_report_note)
    orig_bearcli = _patched("bearcli", fake_bearcli)
    import builtins
    orig_input = builtins.input
    builtins.input = fake_input
    try:
        exit_code, out, err = _run_main(["lint"])
    finally:
        bearkit.write_report_note = orig_write
        bearkit.bearcli = orig_bearcli
        builtins.input = orig_input

    assert exit_code in (None, 0), (exit_code, err)
    assert "nothing to report" in err, err


def test_cli_no_findings_prints_nothing_to_report():
    def fake_find_orphans(sections=None, by_tag=False, tag=None):
        pass  # no orphans found, sections stays empty

    def fake_write_report_note(*args, **kwargs):
        raise AssertionError("should not create a note when there's nothing to report")

    orig_find = _patched("find_orphans", fake_find_orphans)
    orig_write = _patched("write_report_note", fake_write_report_note)
    try:
        exit_code, out, err = _run_main(["orphans"])
    finally:
        bearkit.find_orphans = orig_find
        bearkit.write_report_note = orig_write

    assert exit_code in (None, 0), (exit_code, err)
    assert "nothing to report" in err, err


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
