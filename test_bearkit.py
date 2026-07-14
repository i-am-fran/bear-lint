#!/usr/bin/env python3
"""
test_bear_lint.py - Plain assert-based tests for bear_lint.py's lint_note().

No pytest, no external deps - matches bear_lint.py's own dependency-free
philosophy. Run with: python3 test_bear_lint.py
"""

import json
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


def test_extract_wikilink_targets_basic():
    lines = ["# Title", "See [[Note A]] and [[Note B]]."]
    mask = bear_lint.protected_mask(lines)
    targets = bear_lint.extract_wikilink_targets(lines, mask, set())
    assert targets == {"Note A", "Note B"}, targets


def test_extract_wikilink_targets_skips_masked_lines():
    lines = ["# Title", "```", "[[Note In Code]]", "```", "[[Note Outside]]"]
    mask = bear_lint.protected_mask(lines)
    targets = bear_lint.extract_wikilink_targets(lines, mask, set())
    assert targets == {"Note Outside"}, targets


def test_extract_wikilink_targets_ignores_empty_link():
    lines = ["# Title", "See [[ ]] here."]
    mask = bear_lint.protected_mask(lines)
    targets = bear_lint.extract_wikilink_targets(lines, mask, set())
    assert targets == set(), targets


def test_extract_wikilink_targets_resolves_heading_link():
    lines = ["# Title", "See [[Note A/Some Heading]]."]
    mask = bear_lint.protected_mask(lines)
    titles = {"Note A"}
    targets = bear_lint.extract_wikilink_targets(lines, mask, titles)
    assert targets == {"Note A"}, targets


def test_extract_wikilink_targets_resolves_alias_link():
    lines = ["# Title", "See [[Note A|display text]]."]
    mask = bear_lint.protected_mask(lines)
    titles = {"Note A"}
    targets = bear_lint.extract_wikilink_targets(lines, mask, titles)
    assert targets == {"Note A"}, targets


def _titles_by_lower(titles):
    return {t.lower(): t for t in titles}


def test_check_dangling_wikilinks_flags_missing_target():
    lines = ["# Title", "See [[Missing Note]] and [[Existing Note]]."]
    mask = bear_lint.protected_mask(lines)
    titles = {"Existing Note", "Title"}
    found = []
    bear_lint.check_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles), found)
    assert len(found) == 1, found
    assert found[0].target == "Missing Note", found[0].target
    assert not any(t.target == "Existing Note" for t in found), found


def test_check_dangling_wikilinks_skips_masked_lines():
    lines = ["# Title", "```", "[[Missing Note]]", "```"]
    mask = bear_lint.protected_mask(lines)
    titles = {"Title"}
    found = []
    bear_lint.check_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles), found)
    assert found == [], found


def test_check_dangling_wikilinks_ignores_empty_link():
    lines = ["# Title", "See [[ ]] here."]
    mask = bear_lint.protected_mask(lines)
    titles = {"Title"}
    found = []
    bear_lint.check_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles), found)
    assert found == [], found


def test_check_dangling_wikilinks_flags_case_mismatch_as_typo():
    lines = ["# Title", "See [[existing note]] here."]
    mask = bear_lint.protected_mask(lines)
    titles = {"Existing Note", "Title"}
    found = []
    bear_lint.check_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles), found)
    assert len(found) == 1, found
    assert found[0].target == "existing note", found[0].target
    assert found[0].suggestion == "Existing Note", found[0].suggestion


def test_check_dangling_wikilinks_flags_close_typo():
    lines = ["# Title", "See [[Existing Notee]] here."]
    mask = bear_lint.protected_mask(lines)
    titles = {"Existing Note", "Title"}
    found = []
    bear_lint.check_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles), found)
    assert len(found) == 1, found
    assert found[0].suggestion == "Existing Note", found[0].suggestion


def test_check_dangling_wikilinks_no_suggestion_for_unrelated_target():
    lines = ["# Title", "See [[Steve Jobs]] here."]
    mask = bear_lint.protected_mask(lines)
    titles = {"Existing Note", "Title"}
    found = []
    bear_lint.check_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles), found)
    assert len(found) == 1, found
    assert found[0].suggestion is None, found[0].suggestion


def test_wiki_logical_target_strips_marker_when_dangling():
    titles = {"Existing Note"}
    assert bear_lint._wiki_logical_target("Missing Note +", titles) == "Missing Note"


def test_wiki_logical_target_keeps_raw_when_real_title_ends_in_marker():
    titles = {"Target +"}
    assert bear_lint._wiki_logical_target("Target +", titles) == "Target +"


def test_wiki_logical_target_returns_raw_when_no_marker():
    titles = {"Existing Note"}
    assert bear_lint._wiki_logical_target("Missing Note", titles) == "Missing Note"


def test_check_dangling_wikilinks_resolves_already_marked_target():
    lines = ["# Title", "See [[Missing Note +]] here."]
    mask = bear_lint.protected_mask(lines)
    titles = {"Title"}
    found = []
    bear_lint.check_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles), found)
    assert len(found) == 1, found
    assert found[0].target == "Missing Note", found[0].target


def test_check_dangling_wikilinks_unmarks_when_target_now_exists():
    lines = ["# Title", "See [[Missing Note +]] here."]
    mask = bear_lint.protected_mask(lines)
    titles = {"Title", "Missing Note"}
    found = []
    bear_lint.check_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles), found)
    assert found == [], found


def test_wiki_note_title_whole_string_exact_match_wins():
    titles = {"A/B"}
    assert bear_lint._wiki_note_title("A/B", titles) == "A/B"


def test_wiki_note_title_alias_only():
    titles = {"Note"}
    assert bear_lint._wiki_note_title("Note|Alias", titles) == "Note"


def test_wiki_note_title_heading_only():
    titles = {"Note"}
    assert bear_lint._wiki_note_title("Note/Heading", titles) == "Note"


def test_wiki_note_title_heading_and_alias_combined():
    titles = {"Note"}
    assert bear_lint._wiki_note_title("Note/Heading|Alias", titles) == "Note"


def test_wiki_note_title_alias_stripped_intermediate_match_wins():
    # A literal note title containing "/" combined with an alias: the
    # alias-stripped intermediate ("A/B") must match before the heading
    # split ever touches the "/".
    titles = {"A/B"}
    assert bear_lint._wiki_note_title("A/B|Alias", titles) == "A/B"


def test_wiki_note_title_no_match_falls_back_to_heading_stripped():
    titles = {"Existing Note"}
    assert bear_lint._wiki_note_title("Missing Thing/Heading", titles) == "Missing Thing"


def test_check_dangling_wikilinks_heading_link_to_existing_note_not_flagged():
    lines = ["# Title", "See [[Existing Note/Some Heading]] here."]
    mask = bear_lint.protected_mask(lines)
    titles = {"Existing Note", "Title"}
    found = []
    bear_lint.check_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles), found)
    assert found == [], found


def test_check_dangling_wikilinks_alias_link_to_existing_note_not_flagged():
    lines = ["# Title", "See [[Existing Note|display text]] here."]
    mask = bear_lint.protected_mask(lines)
    titles = {"Existing Note", "Title"}
    found = []
    bear_lint.check_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles), found)
    assert found == [], found


def test_check_dangling_wikilinks_combined_heading_alias_to_existing_note_not_flagged():
    lines = ["# Title", "See [[Existing Note/Some Heading|display text]] here."]
    mask = bear_lint.protected_mask(lines)
    titles = {"Existing Note", "Title"}
    found = []
    bear_lint.check_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles), found)
    assert found == [], found


def test_check_dangling_wikilinks_flags_dangling_heading_link_with_full_target():
    lines = ["# Title", "See [[Missing Note/Some Heading]] here."]
    mask = bear_lint.protected_mask(lines)
    titles = {"Title"}
    found = []
    bear_lint.check_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles), found)
    assert len(found) == 1, found
    assert found[0].target == "Missing Note/Some Heading", found[0].target
    assert found[0].suggestion is None, found[0].suggestion


def test_check_dangling_wikilinks_typo_suggestion_preserves_heading_suffix():
    lines = ["# Title", "See [[Existing Notee/Some Heading]] here."]
    mask = bear_lint.protected_mask(lines)
    titles = {"Existing Note", "Title"}
    found = []
    bear_lint.check_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles), found)
    assert len(found) == 1, found
    assert found[0].target == "Existing Notee/Some Heading", found[0].target
    assert found[0].suggestion == "Existing Note/Some Heading", found[0].suggestion


def test_check_dangling_wikilinks_typo_suggestion_preserves_alias_suffix():
    lines = ["# Title", "See [[Existing Notee|display text]] here."]
    mask = bear_lint.protected_mask(lines)
    titles = {"Existing Note", "Title"}
    found = []
    bear_lint.check_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles), found)
    assert len(found) == 1, found
    assert found[0].suggestion == "Existing Note|display text", found[0].suggestion


def test_mark_dangling_wikilinks_appends_marker():
    lines = ["# Title", "See [[Missing Note]] here."]
    mask = bear_lint.protected_mask(lines)
    titles = {"Title"}
    new_lines, marked, unmarked = bear_lint.mark_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles))
    assert new_lines[1] == "See [[Missing Note +]] here.", new_lines
    assert marked == {"Missing Note"}, marked
    assert unmarked == set(), unmarked


def test_mark_dangling_wikilinks_is_idempotent():
    lines = ["# Title", "See [[Missing Note +]] here."]
    mask = bear_lint.protected_mask(lines)
    titles = {"Title"}
    new_lines, marked, unmarked = bear_lint.mark_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles))
    assert new_lines == lines, new_lines
    assert marked == set(), marked
    assert unmarked == set(), unmarked


def test_mark_dangling_wikilinks_unmarks_when_target_now_exists():
    lines = ["# Title", "See [[Missing Note +]] here."]
    mask = bear_lint.protected_mask(lines)
    titles = {"Title", "Missing Note"}
    new_lines, marked, unmarked = bear_lint.mark_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles))
    assert new_lines[1] == "See [[Missing Note]] here.", new_lines
    assert unmarked == {"Missing Note"}, unmarked
    assert marked == set(), marked


def test_mark_dangling_wikilinks_leaves_typo_suggestions_unmarked():
    lines = ["# Title", "See [[existing note]] here."]
    mask = bear_lint.protected_mask(lines)
    titles = {"Title", "Existing Note"}
    new_lines, marked, unmarked = bear_lint.mark_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles))
    assert new_lines == lines, new_lines
    assert marked == set(), marked
    assert unmarked == set(), unmarked


def test_mark_dangling_wikilinks_skips_masked_lines():
    lines = ["# Title", "```", "[[Missing Note]]", "```"]
    mask = bear_lint.protected_mask(lines)
    titles = {"Title"}
    new_lines, marked, unmarked = bear_lint.mark_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles))
    assert new_lines == lines, new_lines
    assert marked == set(), marked
    assert unmarked == set(), unmarked


def test_mark_dangling_wikilinks_ignores_empty_link():
    lines = ["# Title", "See [[ ]] here."]
    mask = bear_lint.protected_mask(lines)
    titles = {"Title"}
    new_lines, marked, unmarked = bear_lint.mark_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles))
    assert new_lines == lines, new_lines
    assert marked == set(), marked


def test_mark_dangling_wikilinks_heading_link_to_existing_note_never_marked():
    lines = ["# Title", "See [[Existing Note/Some Heading]] here."]
    mask = bear_lint.protected_mask(lines)
    titles = {"Title", "Existing Note"}
    new_lines, marked, unmarked = bear_lint.mark_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles))
    assert new_lines == lines, new_lines
    assert marked == set(), marked
    assert unmarked == set(), unmarked


def test_mark_dangling_wikilinks_alias_link_to_existing_note_never_marked():
    lines = ["# Title", "See [[Existing Note|display text]] here."]
    mask = bear_lint.protected_mask(lines)
    titles = {"Title", "Existing Note"}
    new_lines, marked, unmarked = bear_lint.mark_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles))
    assert new_lines == lines, new_lines
    assert marked == set(), marked
    assert unmarked == set(), unmarked


def test_mark_dangling_wikilinks_dangling_heading_link_marks_suffix_at_end():
    lines = ["# Title", "See [[Missing Note/Some Heading]] here."]
    mask = bear_lint.protected_mask(lines)
    titles = {"Title"}
    new_lines, marked, unmarked = bear_lint.mark_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles))
    assert new_lines[1] == "See [[Missing Note/Some Heading +]] here.", new_lines
    assert marked == {"Missing Note/Some Heading"}, marked
    assert unmarked == set(), unmarked


def test_mark_dangling_wikilinks_compound_target_is_idempotent():
    lines = ["# Title", "See [[Missing Note/Some Heading +]] here."]
    mask = bear_lint.protected_mask(lines)
    titles = {"Title"}
    new_lines, marked, unmarked = bear_lint.mark_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles))
    assert new_lines == lines, new_lines
    assert marked == set(), marked
    assert unmarked == set(), unmarked


def test_mark_dangling_wikilinks_compound_target_unmarks_when_note_now_exists():
    lines = ["# Title", "See [[Missing Note/Some Heading +]] here."]
    mask = bear_lint.protected_mask(lines)
    titles = {"Title", "Missing Note"}
    new_lines, marked, unmarked = bear_lint.mark_dangling_wikilinks(lines, mask, titles, _titles_by_lower(titles))
    assert new_lines[1] == "See [[Missing Note/Some Heading]] here.", new_lines
    assert unmarked == {"Missing Note/Some Heading"}, unmarked
    assert marked == set(), marked


def test_render_wiki_body_shows_marker_for_marked_target():
    targets = [bear_lint.WikiTarget("Missing Note", marked=True)]
    body = bear_lint.render_wiki_body(targets)
    assert body == "- [[Missing Note +]]", body


def test_render_wiki_body_unmarked_targets_get_own_line():
    body = bear_lint.render_wiki_body([], unmarked={"Missing Note"})
    assert body == "- [[Missing Note]] — no longer dangling, marker removed", body


def test_render_wiki_body_without_marking_is_unchanged():
    targets = [bear_lint.WikiTarget("Missing Note")]
    body = bear_lint.render_wiki_body(targets)
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


def test_lint_one_by_tag_fetches_and_threads_tags():
    def fake_bearcli(*args, **kwargs):
        if args[0] == "show":
            return json.dumps({"title": "My Note", "tags": ["#work"]})
        if args[0] == "cat":
            return "# My Note\n\nBody.\n"
        raise AssertionError(f"unexpected bearcli call: {args}")

    orig_bearcli = bear_lint.bearcli
    bear_lint.bearcli = fake_bearcli
    try:
        sections = []
        lint_one("some-note-id", sections=sections, by_tag=True)
    finally:
        bear_lint.bearcli = orig_bearcli

    assert len(sections) == 1, sections
    entry = sections[0]
    assert isinstance(entry, bear_lint.ReportEntry), entry
    assert entry.heading == "[[My Note]] (some-note-id)", entry
    assert entry.tags == ["#work"], entry


def test_write_report_note_includes_description():
    captured = {}

    def fake_bearcli(*args, **kwargs):
        captured["args"] = args
        captured["stdin"] = kwargs.get("stdin")
        return ""

    orig_bearcli = bear_lint.bearcli
    bear_lint.bearcli = fake_bearcli
    try:
        bear_lint.write_report_note(
            ["## [[Note]]\n\nBody"], title_prefix="Bear Lint Report", description="Some description."
        )
    finally:
        bear_lint.bearcli = orig_bearcli

    stdin = captured["stdin"]
    assert stdin.startswith("Some description.\n\n"), stdin
    assert "## [[Note]]" in stdin, stdin


def test_render_grouped_sections_groups_by_tag_and_untagged():
    entries = [
        bear_lint.ReportEntry("[[Note A]] (id-a)", "**1 issue(s) fixed**", ["#work"]),
        bear_lint.ReportEntry("[[Note B]] (id-b)", "No issues found.", []),
        bear_lint.ReportEntry("[[Note C]] (id-c)", "No issues found.", ["#home"]),
    ]
    rendered = bear_lint.render_grouped_sections(entries)

    assert rendered.index("## `#home`") < rendered.index("## `#work`") < rendered.index("## Untagged"), rendered
    assert "### [[Note A]] (id-a)\n\n**1 issue(s) fixed**" in rendered, rendered
    assert "### [[Note B]] (id-b)\n\nNo issues found." in rendered, rendered
    assert "### [[Note C]] (id-c)\n\nNo issues found." in rendered, rendered


def test_render_grouped_sections_shields_tag_headings_from_bear():
    entries = [bear_lint.ReportEntry("[[Note A]] (id-a)", "Body", ["#work"])]
    rendered = bear_lint.render_grouped_sections(entries)

    assert "## `#work`" in rendered, rendered
    assert "## #work" not in rendered, rendered


def test_render_grouped_sections_repeats_multi_tag_entries():
    entries = [bear_lint.ReportEntry("[[Note A]] (id-a)", "Body", ["#home", "#work"])]
    rendered = bear_lint.render_grouped_sections(entries)

    assert rendered.count("[[Note A]] (id-a)") == 2, rendered
    assert "## `#home`" in rendered and "## `#work`" in rendered, rendered


def test_render_grouped_sections_passes_raw_strings_through():
    entries = [
        bear_lint.ReportEntry("[[Note A]] (id-a)", "Body", ["#work"]),
        "---\n\n**1 notes checked, 1 fixed.**",
    ]
    rendered = bear_lint.render_grouped_sections(entries)

    assert rendered.endswith("---\n\n**1 notes checked, 1 fixed.**"), rendered


def test_write_report_note_by_tag_groups_sections():
    captured = {}

    def fake_bearcli(*args, **kwargs):
        captured["stdin"] = kwargs.get("stdin")
        return ""

    orig_bearcli = bear_lint.bearcli
    bear_lint.bearcli = fake_bearcli
    try:
        bear_lint.write_report_note(
            [bear_lint.ReportEntry("[[Note]] (id)", "No issues found.", ["#work"])],
            title_prefix="Bear Lint Report",
            description="Some description.",
            by_tag=True,
        )
    finally:
        bear_lint.bearcli = orig_bearcli

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

    orig_bearcli = bear_lint.bearcli
    bear_lint.bearcli = fake_bearcli

    import io
    from contextlib import redirect_stderr

    buf = io.StringIO()
    sections = []
    try:
        with redirect_stderr(buf):
            bear_lint.lint_wiki(sections=sections)
    finally:
        bear_lint.bearcli = orig_bearcli

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

    orig_bearcli = bear_lint.bearcli
    bear_lint.bearcli = fake_bearcli

    import io
    from contextlib import redirect_stderr

    buf = io.StringIO()
    sections = []
    try:
        with redirect_stderr(buf):
            bear_lint.lint_wiki(sections=sections)
    finally:
        bear_lint.bearcli = orig_bearcli

    output = buf.getvalue()
    assert "did you mean [[Existing Note]]?" in output, output

    section = sections[0]
    assert "did you mean [[Existing Note]]?" in section, section
    assert "- [[Some Unrelated Thing]]" in section, section
    assert "[[Some Unrelated Thing]] →" not in section, section


def test_lint_wiki_skips_bear_lint_tagged_notes():
    notes_json = json.dumps([
        {"id": "id-1", "title": "Note One", "tags": []},
        {"id": "id-2", "title": "Bear Wikilinks Report — 2026-01-01 00:00", "tags": ["#bear-lint"]},
    ])

    def fake_bearcli(*args, **kwargs):
        if args[0] == "list":
            return notes_json
        if args[0] == "cat":
            note_id = args[1]
            if note_id == "id-2":
                raise AssertionError("lint_wiki should not fetch the body of a #bear-lint tagged note")
            return "# Note One\n\nSee [[Missing Note]].\n"
        raise AssertionError(f"unexpected bearcli call: {args}")

    orig_bearcli = bear_lint.bearcli
    bear_lint.bearcli = fake_bearcli

    import io
    from contextlib import redirect_stderr

    buf = io.StringIO()
    sections = []
    try:
        with redirect_stderr(buf):
            bear_lint.lint_wiki(sections=sections)
    finally:
        bear_lint.bearcli = orig_bearcli

    output = buf.getvalue()
    assert "Bear Wikilinks Report" not in output, output
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

    orig_bearcli = bear_lint.bearcli
    bear_lint.bearcli = fake_bearcli
    try:
        sections = []
        bear_lint.lint_wiki(sections=sections, by_tag=True)
    finally:
        bear_lint.bearcli = orig_bearcli

    entries = [s for s in sections if isinstance(s, bear_lint.ReportEntry)]
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

    orig_bearcli = bear_lint.bearcli
    bear_lint.bearcli = fake_bearcli
    try:
        sections = []
        bear_lint.lint_wiki(sections=sections, mark=True, yes=True)
    finally:
        bear_lint.bearcli = orig_bearcli

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

    orig_bearcli = bear_lint.bearcli
    bear_lint.bearcli = fake_bearcli

    import io
    from contextlib import redirect_stderr

    buf = io.StringIO()
    sections = []
    try:
        with redirect_stderr(buf):
            bear_lint.lint_wiki(sections=sections, mark=True, yes=True)
    finally:
        bear_lint.bearcli = orig_bearcli

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

    orig_bearcli = bear_lint.bearcli
    bear_lint.bearcli = fake_bearcli

    import io
    from contextlib import redirect_stderr

    buf = io.StringIO()
    try:
        with redirect_stderr(buf):
            bear_lint.lint_wiki(mark=True, dry_run=True)
    finally:
        bear_lint.bearcli = orig_bearcli

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

    orig_bearcli = bear_lint.bearcli
    bear_lint.bearcli = fake_bearcli
    try:
        bear_lint.lint_wiki(mark=True, yes=True)
    finally:
        bear_lint.bearcli = orig_bearcli

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

    orig_bearcli = bear_lint.bearcli
    bear_lint.bearcli = fake_bearcli
    try:
        sections = []
        bear_lint.lint_wiki(sections=sections, mark=True, yes=True)
    finally:
        bear_lint.bearcli = orig_bearcli

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

    orig_bearcli = bear_lint.bearcli
    bear_lint.bearcli = fake_bearcli
    try:
        sections = []
        bear_lint.lint_wiki(sections=sections, mark=True, yes=True)
    finally:
        bear_lint.bearcli = orig_bearcli

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

    orig_bearcli = bear_lint.bearcli
    bear_lint.bearcli = fake_bearcli
    try:
        sections = []
        bear_lint.lint_wiki(sections=sections, mark=True, yes=True)
    finally:
        bear_lint.bearcli = orig_bearcli

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

    orig_bearcli = bear_lint.bearcli
    bear_lint.bearcli = fake_bearcli
    try:
        bear_lint.lint_wiki(sections=[])
    finally:
        bear_lint.bearcli = orig_bearcli


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

    orig_bearcli = bear_lint.bearcli
    bear_lint.bearcli = fake_bearcli

    import io
    from contextlib import redirect_stderr

    buf = io.StringIO()
    sections = []
    try:
        with redirect_stderr(buf):
            bear_lint.lint_orphans(sections=sections)
    finally:
        bear_lint.bearcli = orig_bearcli

    output = buf.getvalue()
    assert "[[Note One]]" in output, output
    assert "[[Note Three]]" in output, output
    assert "[[Note Two]]" not in output, output

    assert len(sections) == 2, sections
    assert sections[0] == "## Orphaned Notes\n\n- [[Note One]]\n- [[Note Three]]", sections[0]


def test_lint_orphans_excludes_bear_lint_tagged_notes():
    notes_json = json.dumps([
        {"id": "id-1", "title": "Note One", "tags": []},
        {"id": "id-2", "title": "Bear Orphans Report — 2026-01-01 00:00", "tags": ["#bear-lint"]},
    ])

    def fake_bearcli(*args, **kwargs):
        if args[0] == "list":
            return notes_json
        if args[0] == "cat":
            note_id = args[1]
            if note_id == "id-2":
                raise AssertionError("lint_orphans should not fetch the body of a #bear-lint tagged note")
            return "# Note One\n\nNo links to anything.\n"
        raise AssertionError(f"unexpected bearcli call: {args}")

    orig_bearcli = bear_lint.bearcli
    bear_lint.bearcli = fake_bearcli

    import io
    from contextlib import redirect_stderr

    buf = io.StringIO()
    sections = []
    try:
        with redirect_stderr(buf):
            bear_lint.lint_orphans(sections=sections)
    finally:
        bear_lint.bearcli = orig_bearcli

    output = buf.getvalue()
    assert "Bear Orphans Report" not in output, output
    assert "[[Note One]]" in output, output
    assert "1 notes checked, 1 orphan(s) found." in output, output


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

    orig_bearcli = bear_lint.bearcli
    bear_lint.bearcli = fake_bearcli
    try:
        sections = []
        bear_lint.lint_orphans(sections=sections, by_tag=True)
    finally:
        bear_lint.bearcli = orig_bearcli

    assert not any(isinstance(s, bear_lint.ReportEntry) for s in sections), sections

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

    orig_bearcli = bear_lint.bearcli
    bear_lint.bearcli = fake_bearcli

    import io
    from contextlib import redirect_stderr

    buf = io.StringIO()
    sections = []
    try:
        with redirect_stderr(buf):
            bear_lint.lint_orphans(sections=sections)
    finally:
        bear_lint.bearcli = orig_bearcli

    output = buf.getvalue()
    assert "[[Note Two]]" not in output, output
    assert "1 orphan(s) found" in output, output


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
    """Run bear_lint.main() with sys.argv patched, capturing stdout/stderr and
    exit behaviour. Returns (exit_code, stdout, stderr). exit_code is None if
    main() returned normally without calling sys.exit()."""
    import io
    from contextlib import redirect_stderr, redirect_stdout

    orig_argv = sys.argv
    sys.argv = ["bear_lint.py", *argv]
    out, err = io.StringIO(), io.StringIO()
    exit_code = None
    try:
        with redirect_stdout(out), redirect_stderr(err):
            try:
                bear_lint.main()
            except SystemExit as e:
                exit_code = e.code
    finally:
        sys.argv = orig_argv
    return exit_code, out.getvalue(), err.getvalue()


def test_cli_unknown_flag_errors_clearly():
    def fake_bearcli(*args, **kwargs):
        raise AssertionError("bearcli should not be called for an unrecognised flag")

    orig_bearcli = bear_lint.bearcli
    bear_lint.bearcli = fake_bearcli
    try:
        exit_code, out, err = _run_main(["--bogus"])
    finally:
        bear_lint.bearcli = orig_bearcli

    assert exit_code not in (None, 0), exit_code
    assert "unrecognised" in err.lower() or "unrecognised" in str(exit_code).lower(), (err, exit_code)


def test_cli_unknown_flag_not_treated_as_note_id():
    calls = []

    def fake_lint_one(note_id, **kwargs):
        calls.append(note_id)

    orig_lint_one = bear_lint.lint_one
    bear_lint.lint_one = fake_lint_one
    try:
        _run_main(["--bogus"])
    finally:
        bear_lint.lint_one = orig_lint_one

    assert calls == [], f"lint_one() should not have been called, but was with {calls}"


def test_cli_all_passes_query_through():
    captured = {}

    def fake_lint_all(query=None, sections=None, dry_run=False, yes=False, by_tag=False):
        captured["query"] = query
        captured["dry_run"] = dry_run
        captured["yes"] = yes

    orig_lint_all = bear_lint.lint_all
    bear_lint.lint_all = fake_lint_all
    try:
        exit_code, out, err = _run_main(["--all", "#work"])
    finally:
        bear_lint.lint_all = orig_lint_all

    assert exit_code in (None, 0), (exit_code, err)
    assert captured.get("query") == "#work", captured


def test_cli_all_output_flag_uses_default_title_and_description():
    captured = {}

    def fake_lint_all(query=None, sections=None, dry_run=False, yes=False, by_tag=False):
        if sections is not None:
            sections.append("dummy section")

    def fake_write_report_note(sections, title_prefix="Bear Lint Report", description=None, by_tag=False):
        captured["title_prefix"] = title_prefix
        captured["description"] = description

    orig_lint_all = bear_lint.lint_all
    orig_write_report_note = bear_lint.write_report_note
    bear_lint.lint_all = fake_lint_all
    bear_lint.write_report_note = fake_write_report_note
    try:
        exit_code, out, err = _run_main(["--all", "-o", "-y"])
    finally:
        bear_lint.lint_all = orig_lint_all
        bear_lint.write_report_note = orig_write_report_note

    assert exit_code in (None, 0), (exit_code, err)
    assert captured.get("title_prefix") == "Bear Lint Report", captured
    assert captured.get("description") == bear_lint.LINT_REPORT_DESCRIPTION, captured


def test_cli_wiki_flag_dispatches():
    calls = []

    def fake_lint_wiki(sections=None, by_tag=False, mark=False, dry_run=False, yes=False):
        calls.append(sections)

    orig_lint_wiki = bear_lint.lint_wiki
    bear_lint.lint_wiki = fake_lint_wiki
    try:
        exit_code, out, err = _run_main(["--wiki"])
    finally:
        bear_lint.lint_wiki = orig_lint_wiki

    assert exit_code in (None, 0), (exit_code, err)
    assert len(calls) == 1, calls


def test_cli_wiki_rejects_note_id():
    def fake_bearcli(*args, **kwargs):
        raise AssertionError("bearcli should not be called when --wiki is combined with a note ID")

    orig_bearcli = bear_lint.bearcli
    bear_lint.bearcli = fake_bearcli
    try:
        exit_code, out, err = _run_main(["--wiki", "some-note-id"])
    finally:
        bear_lint.bearcli = orig_bearcli

    assert exit_code not in (None, 0), exit_code
    assert "--wiki" in str(exit_code), exit_code
    assert "note id" in str(exit_code).lower(), exit_code


def test_cli_wiki_rejects_all():
    exit_code, out, err = _run_main(["--wiki", "--all"])
    assert exit_code not in (None, 0), exit_code
    assert "--all" in str(exit_code), exit_code


def test_cli_wiki_rejects_dry_run():
    exit_code, out, err = _run_main(["--wiki", "-n"])
    assert exit_code not in (None, 0), exit_code
    assert "--dry-run" in str(exit_code), exit_code


def test_cli_wiki_rejects_yes():
    exit_code, out, err = _run_main(["--wiki", "-y"])
    assert exit_code not in (None, 0), exit_code
    assert "--yes" in str(exit_code), exit_code


def test_cli_mark_requires_wiki():
    exit_code, out, err = _run_main(["--mark"])
    assert exit_code not in (None, 0), exit_code
    assert "--mark" in str(exit_code), exit_code
    assert "--wiki" in str(exit_code), exit_code


def test_cli_wiki_mark_allows_dry_run_and_yes():
    captured = {}

    def fake_lint_wiki(sections=None, by_tag=False, mark=False, dry_run=False, yes=False):
        captured["mark"] = mark
        captured["dry_run"] = dry_run
        captured["yes"] = yes

    orig_lint_wiki = bear_lint.lint_wiki
    bear_lint.lint_wiki = fake_lint_wiki
    try:
        exit_code, out, err = _run_main(["--wiki", "--mark", "-n"])
    finally:
        bear_lint.lint_wiki = orig_lint_wiki

    assert exit_code in (None, 0), (exit_code, err)
    assert captured.get("mark") is True, captured
    assert captured.get("dry_run") is True, captured


def test_cli_wiki_mark_dispatches_yes():
    captured = {}

    def fake_lint_wiki(sections=None, by_tag=False, mark=False, dry_run=False, yes=False):
        captured["yes"] = yes

    orig_lint_wiki = bear_lint.lint_wiki
    bear_lint.lint_wiki = fake_lint_wiki
    try:
        exit_code, out, err = _run_main(["--wiki", "--mark", "-y"])
    finally:
        bear_lint.lint_wiki = orig_lint_wiki

    assert exit_code in (None, 0), (exit_code, err)
    assert captured.get("yes") is True, captured


def test_cli_wiki_allows_output_flag():
    captured = {}

    def fake_lint_wiki(sections=None, by_tag=False, mark=False, dry_run=False, yes=False):
        captured["sections"] = sections
        if sections is not None:
            sections.append("dummy section")

    def fake_write_report_note(sections, title_prefix="Bear Lint Report", description=None, by_tag=False):
        captured["written"] = sections
        captured["title_prefix"] = title_prefix
        captured["description"] = description

    orig_lint_wiki = bear_lint.lint_wiki
    orig_write_report_note = bear_lint.write_report_note
    bear_lint.lint_wiki = fake_lint_wiki
    bear_lint.write_report_note = fake_write_report_note
    try:
        exit_code, out, err = _run_main(["--wiki", "-o"])
    finally:
        bear_lint.lint_wiki = orig_lint_wiki
        bear_lint.write_report_note = orig_write_report_note

    assert exit_code in (None, 0), (exit_code, err)
    assert captured.get("sections") is not None, captured
    assert captured.get("written") == ["dummy section"], captured
    assert captured.get("title_prefix") == "Bear Wikilinks Report", captured
    assert captured.get("description") == bear_lint.WIKI_REPORT_DESCRIPTION, captured


def test_cli_orphans_flag_dispatches():
    calls = []

    def fake_lint_orphans(sections=None, by_tag=False):
        calls.append(sections)

    orig_lint_orphans = bear_lint.lint_orphans
    bear_lint.lint_orphans = fake_lint_orphans
    try:
        exit_code, out, err = _run_main(["--orphans"])
    finally:
        bear_lint.lint_orphans = orig_lint_orphans

    assert exit_code in (None, 0), (exit_code, err)
    assert len(calls) == 1, calls


def test_cli_orphans_rejects_note_id():
    def fake_bearcli(*args, **kwargs):
        raise AssertionError("bearcli should not be called when --orphans is combined with a note ID")

    orig_bearcli = bear_lint.bearcli
    bear_lint.bearcli = fake_bearcli
    try:
        exit_code, out, err = _run_main(["--orphans", "some-note-id"])
    finally:
        bear_lint.bearcli = orig_bearcli

    assert exit_code not in (None, 0), exit_code
    assert "--orphans" in str(exit_code), exit_code
    assert "note id" in str(exit_code).lower(), exit_code


def test_cli_orphans_rejects_all():
    exit_code, out, err = _run_main(["--orphans", "--all"])
    assert exit_code not in (None, 0), exit_code
    assert "--all" in str(exit_code), exit_code


def test_cli_orphans_rejects_dry_run():
    exit_code, out, err = _run_main(["--orphans", "-n"])
    assert exit_code not in (None, 0), exit_code
    assert "--dry-run" in str(exit_code), exit_code


def test_cli_orphans_rejects_yes():
    exit_code, out, err = _run_main(["--orphans", "-y"])
    assert exit_code not in (None, 0), exit_code
    assert "--yes" in str(exit_code), exit_code


def test_cli_orphans_rejects_wiki():
    exit_code, out, err = _run_main(["--orphans", "--wiki"])
    assert exit_code not in (None, 0), exit_code
    assert "--wiki" in str(exit_code), exit_code
    assert "--orphans" in str(exit_code), exit_code


def test_cli_orphans_allows_output_flag():
    captured = {}

    def fake_lint_orphans(sections=None, by_tag=False):
        captured["sections"] = sections
        if sections is not None:
            sections.append("dummy section")

    def fake_write_report_note(sections, title_prefix="Bear Lint Report", description=None, by_tag=False):
        captured["written"] = sections
        captured["title_prefix"] = title_prefix
        captured["description"] = description

    orig_lint_orphans = bear_lint.lint_orphans
    orig_write_report_note = bear_lint.write_report_note
    bear_lint.lint_orphans = fake_lint_orphans
    bear_lint.write_report_note = fake_write_report_note
    try:
        exit_code, out, err = _run_main(["--orphans", "-o"])
    finally:
        bear_lint.lint_orphans = orig_lint_orphans
        bear_lint.write_report_note = orig_write_report_note

    assert exit_code in (None, 0), (exit_code, err)
    assert captured.get("sections") is not None, captured
    assert captured.get("written") == ["dummy section"], captured
    assert captured.get("title_prefix") == "Bear Orphans Report", captured
    assert captured.get("description") == bear_lint.ORPHANS_REPORT_DESCRIPTION, captured


def test_cli_by_tag_requires_output():
    def fake_bearcli(*args, **kwargs):
        raise AssertionError("bearcli should not be called when --by-tag is rejected before dispatch")

    orig_bearcli = bear_lint.bearcli
    bear_lint.bearcli = fake_bearcli
    try:
        exit_code, out, err = _run_main(["--all", "-t", "-y"])
    finally:
        bear_lint.bearcli = orig_bearcli

    assert exit_code not in (None, 0), exit_code
    assert "--by-tag" in str(exit_code), exit_code
    assert "--output" in str(exit_code) or "-o" in str(exit_code), exit_code


def test_cli_by_tag_threads_through_to_lint_all_and_write_report_note():
    captured = {}

    def fake_lint_all(query=None, sections=None, dry_run=False, yes=False, by_tag=False):
        captured["lint_all_by_tag"] = by_tag
        if sections is not None:
            sections.append("dummy section")

    def fake_write_report_note(sections, title_prefix="Bear Lint Report", description=None, by_tag=False):
        captured["write_report_note_by_tag"] = by_tag

    orig_lint_all = bear_lint.lint_all
    orig_write_report_note = bear_lint.write_report_note
    bear_lint.lint_all = fake_lint_all
    bear_lint.write_report_note = fake_write_report_note
    try:
        exit_code, out, err = _run_main(["--all", "-o", "-t", "-y"])
    finally:
        bear_lint.lint_all = orig_lint_all
        bear_lint.write_report_note = orig_write_report_note

    assert exit_code in (None, 0), (exit_code, err)
    assert captured.get("lint_all_by_tag") is True, captured
    assert captured.get("write_report_note_by_tag") is True, captured


def test_cli_flag_before_and_after_positional():
    calls = []

    def fake_lint_one(note_id, sections=None, dry_run=False, by_tag=False):
        calls.append((note_id, dry_run))

    orig_lint_one = bear_lint.lint_one
    bear_lint.lint_one = fake_lint_one
    try:
        _run_main(["-n", "some-note-id"])
        _run_main(["some-note-id", "-n"])
    finally:
        bear_lint.lint_one = orig_lint_one

    assert calls == [("some-note-id", True), ("some-note-id", True)], calls


def test_cli_help_prints_exact_help_string():
    exit_code, out, err = _run_main(["--help"])
    assert out == bear_lint.HELP, out
    assert exit_code == 0, exit_code

    exit_code, out, err = _run_main(["-h"])
    assert out == bear_lint.HELP, out
    assert exit_code == 0, exit_code


def test_cli_missing_note_id_or_all():
    exit_code, out, err = _run_main([])
    # No args at all prints HELP to stdout and exits non-zero.
    assert exit_code not in (None, 0), exit_code
    assert out == bear_lint.HELP, out


def test_cli_missing_note_id_or_all_with_only_flags():
    def fake_bearcli(*args, **kwargs):
        raise AssertionError("bearcli should not be called when no note ID or --all is given")

    orig_bearcli = bear_lint.bearcli
    bear_lint.bearcli = fake_bearcli
    try:
        exit_code, out, err = _run_main(["-n"])
    finally:
        bear_lint.bearcli = orig_bearcli

    assert exit_code == "bear_lint: missing note ID or --all", exit_code


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
