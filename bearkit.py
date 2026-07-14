#!/usr/bin/env python3
"""
bearkit.py - Markdown linter and Bear-notes companion tool.

USAGE
  bearkit orphans [-t tag]                   list notes with no incoming [[wikilinks]]
  bearkit duplicates [-t tag]                list notes that share the same title
  bearkit wikilinks [-t tag]                 list dangling [[wikilinks]]
  bearkit wikilinks --mark [-t tag] [-n|-y]  ...and mark them in the note itself (" +")
  bearkit lint [-t tag] [-n] [-y]            lint all/tagged notes (asks for confirmation)
  bearkit lint -i <note-id> [-n]             lint a single note (no confirmation)
  bearkit random [count] [-t tag]            open one or more random notes in Bear
  bearkit --selftest                         sanity check, no Bear needed
  bearkit --version|-v                       print version
"""

import argparse
import difflib
import json
import os
import random
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime

__version__ = "2.0.0"

BEARCLI_FALLBACK = "/Applications/Bear.app/Contents/MacOS/bearcli"

# --- lint engine (unchanged) ---

HEADING_RE = re.compile(r"^(#{1,6})(?=\s|$)(\s*)(.*)$")
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
HR_RE = re.compile(r"^[ \t]{0,3}([-*_])[ \t]*(?:\1[ \t]*){2,}$")
INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
LIST_ITEM_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<marker>[*+-])"
    r"(?P<gap1>[ \t]*)"
    r"(?:\[(?P<box>[ xX])\](?P<gap2>[ \t]*))?"
    r"(?P<text>.*)$"
)
# CommonMark ordered list marker: one or more digits followed by "." or ")".
# Used only by ensure_list_spacing() to recognise numbered lists for blank-line
# spacing purposes - process_list_checklist() intentionally ignores this, so
# ordered markers/numbering are never rewritten to "-".
ORDERED_LIST_ITEM_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<marker>\d+[.)])"
    r"(?P<gap1>[ \t]*)"
    r"(?P<text>.*)$"
)
QUOTE_MARKER_RE = re.compile(r"^([ \t]{0,3}(?:>[ \t]*)*>)([^ \t\n].*)$")
BOLD_UNDERSCORE_RE = re.compile(r"__(?!\s)([^_\n]+?)(?<!\s)__")
ITALIC_UNDERSCORE_RE = re.compile(r"(?<![\w_])_(?!_)([^_\n]+?)(?<!\s)_(?![\w_])")
CLOSED_TAG_RE = re.compile(r"#([^#\s][^#\n]*?)#")
SMART_QUOTE_CHARS = "“”‘’"
SMART_QUOTE_MAP = {"“": '"', "”": '"', "‘": "'", "’": "'"}
SMART_QUOTE_RE = re.compile("[" + SMART_QUOTE_CHARS + "]")


@dataclass
class LintIssue:
    line: int
    rule: str
    message: str


@dataclass
class WikiTarget:
    """A dangling [[wikilink]] target, with an optional suggested note title
    when it looks like a typo/case-mismatch of a real note rather than a
    link to something that was never meant to be a note."""
    target: str
    suggestion: str = None
    marked: bool = False


@dataclass
class ReportEntry:
    """A single note's contribution to a -o/--output report, kept unrendered
    (heading separate from body) so -t/--by-tag can regroup entries by tag
    before deciding what heading level to render them at."""
    heading: str
    body: str
    tags: list = field(default_factory=list)


_RULE_ACRONYMS = {"h1": "H1", "hr": "HR", "hrs": "HRs"}


def humanize_rule(slug):
    return " ".join(_RULE_ACRONYMS.get(w, w.capitalize()) for w in slug.split("-"))


CALLOUT_TYPES = {
    "missing-h1": "WARNING",
    "duplicate-h1": "WARNING",
    "heading-skip": "WARNING",
    "tag-format": "WARNING",
    "wiki-link": "WARNING",
    "stub-note": "TIP",
}


def callout_for(rule):
    """Callout type for report-only rules, or None for auto-fixed rules
    (which render as a plain list instead of a callout)."""
    return CALLOUT_TYPES.get(rule)


def code_block_mask(lines):
    mask = [False] * len(lines)
    in_block = False
    fence_char = None
    for i, line in enumerate(lines):
        m = FENCE_RE.match(line)
        if m:
            token = m.group(1)
            if not in_block:
                in_block = True
                fence_char = token[0]
            elif token[0] == fence_char:
                in_block = False
                fence_char = None
            mask[i] = True
            continue
        mask[i] = in_block
    return mask


def frontmatter_mask(lines):
    # YAML frontmatter: a "---" on line 1 and a matching closing "---" later.
    # Everything in between (both delimiters included) is treated like a
    # fenced code block - no rule should reformat its content, aside from
    # remove_frontmatter_blank_lines() which runs before any mask is built.
    mask = [False] * len(lines)
    if not lines or lines[0].strip() != "---":
        return mask
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            for j in range(i + 1):
                mask[j] = True
            return mask
    return mask


def remove_frontmatter_blank_lines(lines, issues):
    fm_mask = frontmatter_mask(lines)
    if not any(fm_mask):
        return lines
    out = []
    for idx, line in enumerate(lines):
        if fm_mask[idx] and line.strip() == "":
            issues.append(LintIssue(idx + 1, "frontmatter-blank-line", "Removed blank line inside YAML frontmatter"))
            continue
        out.append(line)
    return out


def protected_mask(lines):
    code_mask = code_block_mask(lines)
    fm_mask = frontmatter_mask(lines)
    return [c or f for c, f in zip(code_mask, fm_mask)]


def protect_inline_code(line):
    spans = []

    def repl(m):
        spans.append(m.group(0))
        return f"\x00{len(spans) - 1}\x00"

    return INLINE_CODE_RE.sub(repl, line), spans


def restore_inline_code(line, spans):
    return re.sub(r"\x00(\d+)\x00", lambda m: spans[int(m.group(1))], line)


def is_hr(line):
    return bool(HR_RE.match(line.rstrip()))


def strip_trailing_ws(lines, issues):
    # CommonMark hard break: a line ending in exactly two spaces (no tabs)
    # forces a <br> within a paragraph, but only when there's a following
    # non-blank line for it to break before - a hard break at end-of-note or
    # right before a blank line has nothing to act on, so it's still noise
    # and gets stripped like any other trailing whitespace. Anything other
    # than exactly two trailing spaces (0/1/3+, or trailing tabs) is never
    # meaningful hard-break syntax, so it's always stripped regardless of
    # what follows - this deliberately does not extend the CommonMark-legal
    # "2 or more spaces" hard break to 3+, to keep the exception as narrow
    # and unambiguous as possible.
    out = []
    n = len(lines)
    for idx, line in enumerate(lines, start=1):
        stripped = line.rstrip(" \t")
        if stripped != line:
            has_hard_break = line[len(stripped):] == "  " and stripped != ""
            next_line = lines[idx] if idx < n else None
            keeps_break = has_hard_break and next_line is not None and next_line.strip() != ""
            if keeps_break:
                out.append(stripped + "  ")
                continue
            issues.append(LintIssue(idx, "trailing-whitespace", "Removed trailing whitespace"))
        out.append(stripped)
    return out


def process_list_checklist(line, lineno, issues):
    if is_hr(line):
        return line
    m = LIST_ITEM_RE.match(line)
    if not m:
        return line
    indent = m.group("indent")
    marker = m.group("marker")
    gap1 = m.group("gap1")
    box = m.group("box")
    text = m.group("text")

    if box is None and gap1 == "":
        return line

    if marker != "-":
        issues.append(LintIssue(lineno, "bullet-marker", f'Bullet marker "{marker}" changed to "-"'))

    if box is not None:
        norm_box = "x" if box in ("x", "X") else " "
        new_line = f"{indent}- [{norm_box}] {text}"
        if new_line.rstrip() != line.rstrip():
            issues.append(LintIssue(lineno, "checklist-syntax", 'Normalised checklist syntax to "- [ ] " / "- [x] "'))
        return new_line

    return f"{indent}- {text}"


def process_blockquote_spacing(line, lineno, issues):
    protected, spans = protect_inline_code(line)
    m = QUOTE_MARKER_RE.match(protected)
    if not m:
        return line
    marker, rest = m.group(1), m.group(2)
    issues.append(LintIssue(lineno, "blockquote-spacing", 'Inserted missing space after ">"'))
    return restore_inline_code(f"{marker} {rest}", spans)


def normalize_emphasis(line):
    protected, spans = protect_inline_code(line)
    changed = False

    def bold_repl(m):
        nonlocal changed
        changed = True
        return f"**{m.group(1)}**"

    new = BOLD_UNDERSCORE_RE.sub(bold_repl, protected)

    def italic_repl(m):
        nonlocal changed
        changed = True
        return f"*{m.group(1)}*"

    new = ITALIC_UNDERSCORE_RE.sub(italic_repl, new)
    return restore_inline_code(new, spans), changed


def normalize_quotes(line):
    protected, spans = protect_inline_code(line)
    changed = False

    def repl(m):
        nonlocal changed
        changed = True
        return SMART_QUOTE_MAP[m.group(0)]

    new = SMART_QUOTE_RE.sub(repl, protected)
    return restore_inline_code(new, spans), changed


def _title_line_index(lines, mask):
    if mask and mask[0]:
        # Frontmatter present: Bear's line-1 "title" is the frontmatter
        # delimiter itself, so the structural title is really the first
        # non-blank line after the frontmatter closes - skip blank lines
        # too, not just masked ones.
        idx = 0
        while idx < len(mask) and (mask[idx] or lines[idx].strip() == ""):
            idx += 1
        return idx
    return 0


def process_headings(lines, mask):
    issues = []
    if not lines:
        return lines, issues

    out = [lines[0]]
    n = len(lines)

    title_idx = _title_line_index(lines, mask)
    title_match = None
    if title_idx < n and not (title_idx < len(mask) and mask[title_idx]):
        title_match = HEADING_RE.match(lines[title_idx])
    prev_level = len(title_match.group(1)) if title_match and title_match.group(3).strip() else None

    if n > 1 and not mask[1] and lines[1].strip() != "":
        out.append("")
        issues.append(LintIssue(2, "heading-spacing", "Inserted blank line after the title"))

    i = 1
    while i < n:
        line = lines[i]
        m = HEADING_RE.match(line) if not mask[i] else None
        if m and m.group(1) and m.group(3).strip() != "":
            level = len(m.group(1))
            if out and out[-1].strip() != "":
                out.append("")
                issues.append(LintIssue(i + 1, "heading-spacing", "Inserted blank line before heading"))
            if prev_level is not None and level > prev_level + 1:
                issues.append(
                    LintIssue(i + 1, "heading-skip", f"Heading level jumps from H{prev_level} to H{level} (skipped level)")
                )
            out.append(line)
            nxt = lines[i + 1] if i + 1 < n else None
            if nxt is not None and nxt.strip() != "":
                out.append("")
                issues.append(LintIssue(i + 1, "heading-spacing", "Inserted blank line after heading"))
            prev_level = level
        else:
            out.append(line)
        i += 1

    return out, issues


def check_duplicate_h1(lines, mask, issues):
    title_idx = _title_line_index(lines, mask)
    for idx, line in enumerate(lines, start=1):
        if idx - 1 == title_idx:
            continue
        if idx - 1 < len(mask) and mask[idx - 1]:
            continue
        m = HEADING_RE.match(line)
        if m and len(m.group(1)) == 1 and m.group(3).strip():
            issues.append(
                LintIssue(
                    idx,
                    "duplicate-h1",
                    f'Extra "# {m.group(3).strip()}" heading found further down the note. '
                    "The note already has a title line at the top - consider demoting this to H2.",
                )
            )


def check_missing_h1(lines, mask, issues):
    title_idx = _title_line_index(lines, mask)
    if title_idx >= len(lines):
        return
    if title_idx < len(mask) and mask[title_idx]:
        return
    m = HEADING_RE.match(lines[title_idx])
    if m and len(m.group(1)) == 1 and m.group(3).strip():
        return
    issues.append(
        LintIssue(
            title_idx + 1,
            "missing-h1",
            'Note doesn\'t start with an H1 heading - add "# <title>" as the first line so heading hierarchy starts correctly.',
        )
    )


def check_stub_note(lines, mask, issues):
    title_idx = _title_line_index(lines, mask)
    if title_idx >= len(lines):
        return
    if title_idx < len(mask) and mask[title_idx]:
        return
    m = HEADING_RE.match(lines[title_idx])
    if not (m and len(m.group(1)) == 1 and m.group(3).strip()):
        return  # not a real H1 - that's missing-h1's concern

    for idx in range(title_idx + 1, len(lines)):
        if idx < len(mask) and mask[idx]:
            return  # fenced code after the title counts as content
        if lines[idx].strip() != "":
            return  # any non-blank line counts as content

    issues.append(
        LintIssue(
            title_idx + 1,
            "stub-note",
            "Note has only its title with nothing underneath - looks like a stub; "
            "add some body content or delete the note.",
        )
    )


def check_tags(lines, mask, issues):
    for idx, raw in enumerate(lines, start=1):
        if idx == 1 or (idx - 1 < len(mask) and mask[idx - 1]):
            continue
        protected, _ = protect_inline_code(raw)

        for m in CLOSED_TAG_RE.finditer(protected):
            if " " not in m.group(1) and "\t" not in m.group(1):
                issues.append(
                    LintIssue(idx, "tag-format", f'Tag "`#{m.group(1)}#`" is a single word; the trailing "#" is unnecessary')
                )


BRACKET_RUN_RE = re.compile(r"\[+|\]+")
CLEAN_WIKI_OPEN_RE = re.compile(r"(?<!\[)\[\[(?!\[)")
CLEAN_WIKI_CLOSE_RE = re.compile(r"(?<!\])\]\](?!\])")
CLEAN_WIKILINK_RE = re.compile(r"(?<!\[)\[\[(?!\[)(.*?)(?<!\])\]\](?!\])")
MARK_SUFFIX = " +"


def check_wiki_links(lines, mask, issues):
    for idx, line in enumerate(lines, start=1):
        if idx - 1 < len(mask) and mask[idx - 1]:
            continue

        for m in BRACKET_RUN_RE.finditer(line):
            run = m.group(0)
            if len(run) >= 3:
                issues.append(
                    LintIssue(idx, "wiki-link", f'{len(run)} "{run[0]}" in a row - likely a typo in a `[[wiki link]]`')
                )

        opens = len(CLEAN_WIKI_OPEN_RE.findall(line))
        closes = len(CLEAN_WIKI_CLOSE_RE.findall(line))
        if opens != closes:
            issues.append(
                LintIssue(idx, "wiki-link", f"Unmatched `[[ ]]` on this line - {opens} opening vs {closes} closing")
            )
        else:
            for m in CLEAN_WIKILINK_RE.finditer(line):
                if not m.group(1).strip():
                    issues.append(LintIssue(idx, "wiki-link", "Empty `[[ ]]` wiki link"))


def collapse_blank_lines(lines, issues):
    out = []
    run = 0
    changed = False
    for line in lines:
        if line.strip() == "":
            run += 1
            if run <= 1:
                out.append("")
            else:
                changed = True
        else:
            run = 0
            out.append(line)
    if changed:
        issues.append(LintIssue(0, "blank-lines", "Collapsed multiple consecutive blank lines into one"))
    return out


def collapse_consecutive_hrs(lines, mask, issues):
    out = []
    i = 0
    changed = False
    while i < len(lines):
        if not mask[i] and lines[i].strip() == "---":
            j = i + 1
            found_another = False
            while j < len(lines):
                if lines[j].strip() == "" or mask[j]:
                    j += 1
                elif not mask[j] and lines[j].strip() == "---":
                    found_another = True
                    j += 1
                else:
                    break
            if found_another:
                changed = True
                out.append("---")
                i = j
            else:
                out.append(lines[i])
                i += 1
        else:
            out.append(lines[i])
            i += 1
    if changed:
        issues.append(LintIssue(0, "consecutive-hrs", "Collapsed multiple consecutive horizontal rules into one"))
    return out


def ensure_hr_spacing(lines, mask, issues):
    out = []
    n = len(lines)
    for i, line in enumerate(lines):
        if mask[i] or line.strip() != "---":
            out.append(line)
            continue
        if out and out[-1].strip() != "":
            out.append("")
            issues.append(LintIssue(i + 1, "hr-spacing", "Inserted blank line before horizontal rule"))
        out.append(line)
        nxt = lines[i + 1] if i + 1 < n else None
        if nxt is not None and nxt.strip() != "":
            out.append("")
            issues.append(LintIssue(i + 1, "hr-spacing", "Inserted blank line after horizontal rule"))
    return out


def ensure_list_spacing(lines, mask, issues):
    n = len(lines)

    def is_list_line(idx):
        if idx < 0 or idx >= n or mask[idx]:
            return False
        line = lines[idx]
        if is_hr(line):
            return False
        m = LIST_ITEM_RE.match(line)
        if m:
            return m.group("box") is not None or m.group("gap1") != ""
        om = ORDERED_LIST_ITEM_RE.match(line)
        if om:
            return om.group("gap1") != ""
        return False

    def is_continuation(idx):
        # Indented, non-list text right after a list item is treated as that
        # item's wrapped content, not a new paragraph - so it doesn't end the list.
        if idx < 0 or idx >= n or mask[idx] or is_list_line(idx):
            return False
        line = lines[idx]
        return line.strip() != "" and line != line.lstrip()

    out = []
    in_list = False
    last_list_lineno = None
    for i, line in enumerate(lines):
        if mask[i]:
            if in_list and out and out[-1].strip() != "":
                out.append("")
                issues.append(LintIssue(last_list_lineno, "list-spacing", "Inserted blank line after list"))
            out.append(line)
            in_list = False
            continue

        if line.strip() == "":
            out.append(line)
            in_list = False
            continue

        if is_list_line(i):
            if not in_list and out and out[-1].strip() != "":
                out.append("")
                issues.append(LintIssue(i + 1, "list-spacing", "Inserted blank line before list"))
            out.append(line)
            in_list = True
            last_list_lineno = i + 1
            continue

        if in_list and is_continuation(i):
            out.append(line)
            continue

        if in_list and out and out[-1].strip() != "":
            out.append("")
            issues.append(LintIssue(last_list_lineno, "list-spacing", "Inserted blank line after list"))
        out.append(line)
        in_list = False

    return out


def ensure_single_trailing_newline(text, issues):
    stripped = text.rstrip("\n")
    if text != stripped + "\n":
        issues.append(LintIssue(0, "trailing-newline", "Normalised to a single trailing newline"))
    return stripped + "\n"


def lint_note(text):
    issues = []
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")

    lines = remove_frontmatter_blank_lines(lines, issues)

    mask = protected_mask(lines)
    lines = strip_trailing_ws(lines, issues)

    for i, line in enumerate(lines):
        if mask[i]:
            continue
        if is_hr(line) and line.strip() != "---":
            issues.append(LintIssue(i + 1, "hr-style", 'Normalised horizontal rule to "---"'))
            lines[i] = "---"

    for i, line in enumerate(lines):
        if mask[i]:
            continue
        lines[i] = process_list_checklist(line, i + 1, issues)

    for i, line in enumerate(lines):
        if mask[i]:
            continue
        lines[i] = process_blockquote_spacing(line, i + 1, issues)

    for i, line in enumerate(lines):
        if mask[i]:
            continue
        new_line, changed = normalize_emphasis(line)
        if changed:
            issues.append(LintIssue(i + 1, "emphasis-marker", "Converted __/_ emphasis to **/*"))
        lines[i] = new_line

    for i, line in enumerate(lines):
        if mask[i]:
            continue
        new_line, changed = normalize_quotes(line)
        if changed:
            issues.append(LintIssue(i + 1, "quote-style", "Converted curly quotes to straight quotes"))
        lines[i] = new_line

    mask = protected_mask(lines)
    lines, heading_issues = process_headings(lines, mask)
    issues.extend(heading_issues)

    mask = protected_mask(lines)
    check_duplicate_h1(lines, mask, issues)
    check_missing_h1(lines, mask, issues)
    check_stub_note(lines, mask, issues)
    check_tags(lines, mask, issues)
    check_wiki_links(lines, mask, issues)

    lines = collapse_blank_lines(lines, issues)

    mask = protected_mask(lines)
    lines = collapse_consecutive_hrs(lines, mask, issues)

    mask = protected_mask(lines)
    lines = ensure_hr_spacing(lines, mask, issues)

    mask = protected_mask(lines)
    lines = ensure_list_spacing(lines, mask, issues)

    text_out = "\n".join(lines)
    text_out = ensure_single_trailing_newline(text_out, issues)

    issues.sort(key=lambda x: (x.line, x.rule))
    return text_out, issues


def print_report(issues, fixed=True):
    if not issues:
        print("No issues found.", file=sys.stderr)
        return
    label = "issue(s) fixed" if fixed else "issue(s) found (manual attention needed)"
    print(f"{len(issues)} {label}:", file=sys.stderr)
    for i in issues:
        where = f"L{i.line}" if i.line else "note"
        print(f"  [{where}] {i.rule}: {i.message}", file=sys.stderr)


def render_issue_callout(issue):
    where = f"L{issue.line}" if issue.line else "note"
    return f"> [!{callout_for(issue.rule)}] {humanize_rule(issue.rule)}\n> `[{where}]` {issue.message}"


def render_issue_list_item(issue):
    where = f"L{issue.line}" if issue.line else "note"
    return f"- `[{where}]` {issue.message}"


def render_note_body(issues, fixed=None, skipped_reason=None, dry_run=False):
    if skipped_reason:
        return f"Skipped ({skipped_reason})."
    if not issues:
        return "No issues found."

    if dry_run:
        label = "issue(s) would be fixed (dry run)"
    else:
        label = "issue(s) fixed" if fixed else "issue(s) found (manual attention needed)"
    callouts = [i for i in issues if callout_for(i.rule)]
    plain = [i for i in issues if not callout_for(i.rule)]

    parts = [f"**{len(issues)} {label}**"]
    if callouts:
        parts.append("\n\n".join(render_issue_callout(i) for i in callouts))
    if plain:
        parts.append("\n".join(render_issue_list_item(i) for i in plain))
    return "\n\n".join(parts)


def render_note_section(title, note_id, issues, fixed=None, skipped_reason=None, dry_run=False):
    heading = f"## [[{title}]] ({note_id})"
    body = render_note_body(issues, fixed=fixed, skipped_reason=skipped_reason, dry_run=dry_run)
    return f"{heading}\n\n{body}"


def render_wiki_body(targets, unmarked=None):
    typos = [t for t in targets if t.suggestion]
    plain = [t for t in targets if not t.suggestion]
    parts = []
    if typos:
        parts.append(
            "\n".join(f"- [[{t.target}]] → possible typo, did you mean [[{t.suggestion}]]?" for t in typos)
        )
    if plain:
        parts.append("\n".join(f"- [[{t.target} +]]" if t.marked else f"- [[{t.target}]]" for t in plain))
    if unmarked:
        parts.append("\n".join(f"- [[{t}]] — no longer dangling, marker removed" for t in sorted(unmarked)))
    return "\n\n".join(parts)


def render_wiki_section(title, targets, unmarked=None):
    heading = f"## [[{title}]]"
    return f"{heading}\n\n{render_wiki_body(targets, unmarked)}"


def render_orphans_section(titles):
    heading = "## Orphaned Notes"
    body = "\n".join(f"- [[{t}]]" for t in titles)
    return f"{heading}\n\n{body}"


def render_duplicates_section(title, notes):
    # [[Title]] wikilinks can't disambiguate between duplicates, so each
    # note renders as a clickable bear:// link instead, with its tags as a
    # disambiguating suffix.
    heading = f"## {title} ({len(notes)} notes)"
    lines = []
    for n in notes:
        tag_suffix = f" — {', '.join(n.get('tags', []))}" if n.get("tags") else ""
        lines.append(f"- [Open `{n['id']}`](bear://x-callback-url/open-note?id={n['id']}){tag_suffix}")
    return f"{heading}\n\n" + "\n".join(lines)


def _note_report_item(title, note_id, issues, tags, by_tag, fixed=None, skipped_reason=None, dry_run=False):
    if by_tag:
        body = render_note_body(issues, fixed=fixed, skipped_reason=skipped_reason, dry_run=dry_run)
        return ReportEntry(f"[[{title}]] ({note_id})", body, tags)
    return render_note_section(title, note_id, issues, fixed=fixed, skipped_reason=skipped_reason, dry_run=dry_run)


def _wiki_report_item(title, targets, tags, by_tag, unmarked=None):
    if by_tag:
        return ReportEntry(f"[[{title}]]", render_wiki_body(targets, unmarked), tags)
    return render_wiki_section(title, targets, unmarked)


def shield_heading_tag(tag):
    """Backtick-wrap a Bear tag so it renders as literal text in a heading
    instead of being re-parsed by Bear as a real tag on the report note."""
    return f"`{tag}`"


def group_by_tag(items, tags_fn):
    """Group items by tag, bucketing untagged items under a None key. Returns
    an ordered list of (tag_or_None, [items]) tuples, tags sorted
    alphabetically with the untagged bucket last. An item with multiple tags
    appears once per tag it has."""
    groups = {}
    order = []
    for item in items:
        for key in (tags_fn(item) or [None]):
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(item)
    return [(key, groups[key]) for key in sorted(order, key=lambda k: (k is None, (k or "").lower()))]


def render_grouped_sections(sections):
    entries = [s for s in sections if isinstance(s, ReportEntry)]
    raw = [s for s in sections if not isinstance(s, ReportEntry)]

    parts = []
    for key, group_entries in group_by_tag(entries, lambda e: e.tags):
        heading = "Untagged" if key is None else shield_heading_tag(key)
        body = "\n\n".join(f"### {e.heading}\n\n{e.body}" for e in group_entries)
        parts.append(f"## {heading}\n\n{body}")
    parts.extend(raw)
    return "\n\n".join(parts)


SAMPLE_NOTE = """# My Project Notes
## Overview
This note has  trailing spaces, mixed markers, and other issues.
* First bullet
+ Second bullet
- Third bullet


Too many blank lines above.
* [x] Done task
-[ ] Todo without a space
This uses __bold__ and _italic_ the wrong way.
#### Jumped heading level
# Duplicate H1 here
Some "straight quotes" and some “curly quotes” in the same note.
Check out [[Some Note]] and this broken [[link.
>Quote missing a space after the marker.
Tag test: #work and #project management without closing, plus #done#.
***
---
Horizontal rules above should become a single ---.
"""

# --- bearcli helper ---

_bearcli_path = None


class BearcliError(Exception):
    pass


def bearcli(*args, stdin=None, timeout=30):
    global _bearcli_path
    if _bearcli_path is None:
        found = shutil.which("bearcli")
        if found:
            _bearcli_path = found
        elif os.path.exists(BEARCLI_FALLBACK):
            _bearcli_path = BEARCLI_FALLBACK
        else:
            sys.exit(
                "bearkit: bearcli not found.\n"
                "Install Bear 2.8 or later: https://bear.app"
            )
    try:
        result = subprocess.run(
            [_bearcli_path, *args],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise BearcliError(f"bearcli {' '.join(args)!r} timed out after {timeout}s")
    if result.returncode != 0:
        raise BearcliError(result.stderr.strip())
    return result.stdout


def list_notes():
    """Fetch every note's id/title/tags via bearcli. Exits the process on
    any bearcli or JSON error, matching every call site's prior ad hoc
    handling."""
    try:
        out = bearcli("list", "--format", "json", "--fields", "id,title,tags")
    except BearcliError as e:
        sys.exit(f"bearkit: {e}")
    try:
        return json.loads(out)
    except json.JSONDecodeError as e:
        sys.exit(f"bearkit: could not parse bearcli output: {e}\nRaw output: {out[:200]!r}")


def tag_matches(tags, tag):
    """True if a note's tags include <tag>, recognizing that bearcli's
    `list` output already expands nested tags into separate entries (a note
    tagged only #people/authors also carries a plain #people entry), so a
    scope of -t people also matches notes only tagged with a child tag."""
    normalized = tag[1:] if tag.startswith("#") else tag
    return f"#{normalized}" in tags


BEARKIT_LISTS_TAG = "bearkit/lists"
BEARKIT_EDITS_TAG = "bearkit/edits"
BEARKIT_TAG_PREFIX = "#bearkit/"


def has_bearkit_report_tag(tags):
    """True if any of a note's tags falls under the #bearkit/* namespace
    (#bearkit/lists or #bearkit/edits) - bearkit's own summary notes, which
    must never be scanned as sources or flagged as findings, or the tool
    would start reporting on its own output."""
    return any(t.startswith(BEARKIT_TAG_PREFIX) for t in tags)


def confirm(prompt):
    answer = input(f"{prompt} [y/N] ")
    return answer.strip().lower() == "y"


LINT_REPORT_DESCRIPTION = "Per-note lint results — auto-fixed issues and issues left for manual review."
WIKI_REPORT_DESCRIPTION = "Notes containing `[[wikilinks]]` that don't match any existing note title."
ORPHANS_REPORT_DESCRIPTION = "Notes that no other note links to via [[wikilinks]]."
DUPLICATES_REPORT_DESCRIPTION = "Notes that share the same title with at least one other note."


def write_report_note(sections, title_prefix, description, tag, group_by_tag=False):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    title = f"{title_prefix} — {timestamp}"
    body_content = render_grouped_sections(sections) if group_by_tag else "\n\n".join(sections)
    body = f"{description}\n\n{body_content}\n"
    try:
        bearcli("create", title, "--tags", tag, stdin=body)
    except BearcliError as e:
        print(f"bearkit: could not create report note: {e}", file=sys.stderr)
        return
    print(f"Report note created: {title}", file=sys.stderr)


# --- CLI commands ---


def print_dry_run_diff(content, fixed, label):
    diff = difflib.unified_diff(
        content.splitlines(keepends=True),
        fixed.splitlines(keepends=True),
        fromfile=f"{label} (before)",
        tofile=f"{label} (after)",
    )
    diff_text = "".join(diff)
    if diff_text:
        print(diff_text, file=sys.stderr, end="")


def lint_one(note_id, sections=None, dry_run=False, by_tag=False):
    title = note_id
    tags = []
    try:
        if by_tag:
            info = json.loads(bearcli("show", note_id, "--format", "json", "--fields", "title,tags"))
            title = info.get("title", note_id)
            tags = info.get("tags", [])
        else:
            title = bearcli("show", note_id, "--fields", "title").strip()
        content = bearcli("cat", note_id)
    except (BearcliError, json.JSONDecodeError) as e:
        print(f"{note_id}: skipped ({e})", file=sys.stderr)
        if sections is not None:
            sections.append(_note_report_item(title, note_id, [], tags, by_tag, skipped_reason=str(e)))
        return

    fixed, issues = lint_note(content)
    label = f"{title} ({note_id})"

    if fixed == content:
        if not issues:
            print(f"{label}: no issues.", file=sys.stderr)
            if sections is not None:
                sections.append(_note_report_item(title, note_id, [], tags, by_tag))
        else:
            print(f"{label}:", file=sys.stderr)
            print_report(issues, fixed=False)
            if sections is not None:
                sections.append(_note_report_item(title, note_id, issues, tags, by_tag, fixed=False))
        return

    if dry_run:
        print(f"{label}: {len(issues)} issue(s) would be fixed (dry run)", file=sys.stderr)
        print_dry_run_diff(content, fixed, label)
        if sections is not None:
            sections.append(_note_report_item(title, note_id, issues, tags, by_tag, dry_run=True))
        return

    try:
        bearcli("overwrite", note_id, "--no-update-modified", stdin=fixed)
    except BearcliError as e:
        sys.exit(f"bearkit: could not write note: {e}")

    print(f"{label}:", file=sys.stderr)
    print_report(issues)
    if sections is not None:
        sections.append(_note_report_item(title, note_id, issues, tags, by_tag, fixed=True))


def lint_all(tag=None, sections=None, dry_run=False, yes=False, by_tag=False):
    notes = list_notes()
    notes = [n for n in notes if not has_bearkit_report_tag(n.get("tags", []))]
    if tag:
        notes = [n for n in notes if tag_matches(n.get("tags", []), tag)]

    if not notes:
        print("No notes found.", file=sys.stderr)
        return

    if not yes and not dry_run:
        if not confirm(f"About to lint {len(notes)} notes — continue?"):
            print("Aborted.", file=sys.stderr)
            return

    checked = 0
    fixed_count = 0

    for note in notes:
        note_id = note["id"]
        title = note["title"]
        tags = note.get("tags", [])
        try:
            content = bearcli("cat", note_id)
        except BearcliError as e:
            print(f"{title}: skipped ({e})", file=sys.stderr)
            if sections is not None:
                sections.append(_note_report_item(title, note_id, [], tags, by_tag, skipped_reason=str(e)))
            continue

        fixed, issues = lint_note(content)
        checked += 1

        if fixed == content:
            if issues:
                print(f"\n{title}:", file=sys.stderr)
                print_report(issues, fixed=False)
                if sections is not None:
                    sections.append(_note_report_item(title, note_id, issues, tags, by_tag, fixed=False))
            continue

        label = f"{title} ({note_id})"

        if dry_run:
            print(f"\n{title}: {len(issues)} issue(s) would be fixed (dry run)", file=sys.stderr)
            print_dry_run_diff(content, fixed, label)
            if sections is not None:
                sections.append(_note_report_item(title, note_id, issues, tags, by_tag, dry_run=True))
            fixed_count += 1
            continue

        try:
            bearcli("overwrite", note_id, "--no-update-modified", stdin=fixed)
        except BearcliError as e:
            print(f"{title}: could not write ({e})", file=sys.stderr)
            continue

        print(f"\n{title}:", file=sys.stderr)
        print_report(issues)
        if sections is not None:
            sections.append(_note_report_item(title, note_id, issues, tags, by_tag, fixed=True))
        fixed_count += 1

    verb = "would be fixed" if dry_run else "fixed"
    print(f"\n{checked} notes checked, {fixed_count} {verb}.", file=sys.stderr)
    if sections is not None:
        sections.append(f"---\n\n**{checked} notes checked, {fixed_count} {verb}.**")


def extract_wikilink_targets(lines, mask, titles):
    targets = set()
    for idx, line in enumerate(lines):
        if idx < len(mask) and mask[idx]:
            continue
        for m in CLEAN_WIKILINK_RE.finditer(line):
            raw = m.group(1).strip()
            if not raw:
                continue
            target = _wiki_logical_target(raw, titles)
            targets.add(_wiki_note_title(target, titles))
    return targets


def find_typo_suggestion(target, titles, titles_by_lower):
    """Best-guess real note title for a dangling wikilink target, or None if
    it looks like an intentional link to something that was never a note."""
    exact_case_insensitive = titles_by_lower.get(target.lower())
    if exact_case_insensitive and exact_case_insensitive != target:
        return exact_case_insensitive
    close = difflib.get_close_matches(target, titles, n=1, cutoff=0.85)
    return close[0] if close else None


def _wiki_logical_target(raw_target, titles):
    """Resolve a raw [[wikilink]] target to the note title it logically
    refers to, stripping a trailing mark_dangling_wikilinks() marker first -
    unless the raw text is itself a real title (checked first, so a title
    that genuinely ends in " +" is never misread as marked)."""
    if raw_target in titles:
        return raw_target
    if raw_target.endswith(MARK_SUFFIX):
        stripped = raw_target[: -len(MARK_SUFFIX)]
        if stripped:
            return stripped
    return raw_target


def _wiki_note_title(target, titles):
    """Resolve a [[wikilink]] target to the note-title portion, recognizing
    Bear's native compound syntax: `Note/Heading` (heading link) and
    `Note|Alias` (alias link, display text only) - which may combine as
    `Note/Heading|Alias`. Precedence, to disambiguate from a literal note
    title that happens to contain "/" or "|": the whole string is checked
    against real titles first (exact match wins outright); only if that
    fails is the alias suffix (from the first "|") stripped and re-checked;
    only if that still doesn't match is the heading suffix (from the first
    "/" in what's left) also stripped. The result is returned whether or
    not it matches - the caller decides "valid compound link" vs. "still
    dangling" by checking `in titles`. Always returns a prefix of `target`,
    so `target[len(result):]` recovers whatever heading/alias text was
    stripped, for reconstructing display strings."""
    if target in titles:
        return target
    without_alias = target.split("|", 1)[0]
    if without_alias != target and without_alias in titles:
        return without_alias
    return without_alias.split("/", 1)[0]


def check_dangling_wikilinks(lines, mask, titles, titles_by_lower, found):
    for idx, line in enumerate(lines, start=1):
        if idx - 1 < len(mask) and mask[idx - 1]:
            continue
        for m in CLEAN_WIKILINK_RE.finditer(line):
            raw = m.group(1).strip()
            if not raw:
                continue
            target = _wiki_logical_target(raw, titles)
            note_title = _wiki_note_title(target, titles)
            if note_title in titles:
                continue
            suggestion = find_typo_suggestion(note_title, titles, titles_by_lower)
            if suggestion:
                suggestion = f"{suggestion}{target[len(note_title):]}"
            found.append(WikiTarget(target, suggestion))


def mark_dangling_wikilinks(lines, mask, titles, titles_by_lower):
    """Rewrite dangling [[wikilinks]] with no typo suggestion to append
    MARK_SUFFIX, and strip that suffix back off once the target note exists
    or a typo suggestion appears - so re-running is idempotent and
    self-healing in both directions. Returns (new_lines, marked, unmarked),
    where marked/unmarked are sets of logical target names changed this
    call."""
    new_lines = list(lines)
    marked = set()
    unmarked = set()

    for idx, line in enumerate(lines):
        if idx < len(mask) and mask[idx]:
            continue

        def repl(m):
            raw = m.group(1).strip()
            if not raw:
                return m.group(0)
            target = _wiki_logical_target(raw, titles)
            note_title = _wiki_note_title(target, titles)
            if note_title in titles or find_typo_suggestion(note_title, titles, titles_by_lower):
                desired = target
            else:
                desired = f"{target}{MARK_SUFFIX}"
            if raw == desired:
                return m.group(0)
            if desired.endswith(MARK_SUFFIX):
                marked.add(target)
            else:
                unmarked.add(target)
            return f"[[{desired}]]"

        new_line = CLEAN_WIKILINK_RE.sub(repl, line)
        if new_line != line:
            new_lines[idx] = new_line

    return new_lines, marked, unmarked


def check_wikilinks(sections=None, by_tag=False, mark=False, dry_run=False, yes=False, tag=None):
    all_notes = list_notes()
    # Target-title resolution always considers the whole vault, even when
    # -t/tag scopes which notes are scanned as sources - a scoped note can
    # still legitimately link to something outside its tag.
    titles = {note["title"] for note in all_notes}
    titles_by_lower = {t.lower(): t for t in titles}

    notes = [n for n in all_notes if not has_bearkit_report_tag(n.get("tags", []))]
    if tag:
        notes = [n for n in notes if tag_matches(n.get("tags", []), tag)]

    if not notes:
        print("No notes found.", file=sys.stderr)
        return

    if mark and not yes and not dry_run:
        if not confirm(f"About to mark dangling wikilinks in {len(notes)} notes — continue?"):
            print("Aborted.", file=sys.stderr)
            return

    checked = 0
    flagged_notes = 0
    total_targets = 0
    total_marked = 0
    total_unmarked = 0

    for note in notes:
        note_id = note["id"]
        title = note["title"]
        tags = note.get("tags", [])
        try:
            content = bearcli("cat", note_id)
        except BearcliError as e:
            print(f"{title}: skipped ({e})", file=sys.stderr)
            continue

        checked += 1
        content = content.replace("\r\n", "\n").replace("\r", "\n")
        lines = content.split("\n")
        mask = protected_mask(lines)
        found = []
        check_dangling_wikilinks(lines, mask, titles, titles_by_lower, found)

        content_changed = False
        marked_now = set()
        unmarked_now = set()
        if mark:
            new_lines, marked_now, unmarked_now = mark_dangling_wikilinks(lines, mask, titles, titles_by_lower)
            new_content = "\n".join(new_lines)
            content_changed = new_content != content
            if content_changed:
                label = f"{title} ({note_id})"
                if dry_run:
                    print_dry_run_diff(content, new_content, label)
                else:
                    try:
                        bearcli("overwrite", note_id, "--no-update-modified", stdin=new_content)
                    except BearcliError as e:
                        print(f"{title}: could not write ({e})", file=sys.stderr)
                        continue

        if not found and not content_changed:
            continue

        by_target = {}
        for wt in found:
            by_target.setdefault(wt.target, wt.suggestion)
        targets = [WikiTarget(t, s, marked=(mark and s is None)) for t, s in sorted(by_target.items())]
        flagged_notes += 1
        total_targets += len(targets)
        total_marked += len(marked_now)
        total_unmarked += len(unmarked_now)

        print(f"\n{title}:", file=sys.stderr)
        for wt in targets:
            if wt.suggestion:
                print(f"  [[{wt.target}]] -> possible typo, did you mean [[{wt.suggestion}]]?", file=sys.stderr)
            elif wt.marked:
                print(f"  [[{wt.target} +]]", file=sys.stderr)
            else:
                print(f"  [[{wt.target}]]", file=sys.stderr)
        for t in sorted(unmarked_now):
            print(f"  [[{t}]] -> no longer dangling, marker removed", file=sys.stderr)
        if sections is not None:
            sections.append(_wiki_report_item(title, targets, tags, by_tag, unmarked=unmarked_now))

    if mark:
        verb = "would be marked" if dry_run else "marked"
        summary = (
            f"{checked} notes checked, {total_targets} dangling wikilink(s) found in {flagged_notes} note(s), "
            f"{total_marked} {verb}, {total_unmarked} unmarked."
        )
    else:
        summary = f"{checked} notes checked, {total_targets} dangling wikilink(s) found in {flagged_notes} note(s)."
    print(f"\n{summary}", file=sys.stderr)
    if sections is not None:
        sections.append(f"---\n\n**{summary}**")


def find_orphans(sections=None, by_tag=False, tag=None):
    all_notes = list_notes()
    if not all_notes:
        print("No notes found.", file=sys.stderr)
        return

    # bearkit's own report notes (#bearkit/*) are excluded from orphan
    # candidates too - nothing ever links back to a timestamped report, so
    # they'd be flagged as an orphan on every single run.
    scannable = [note for note in all_notes if not has_bearkit_report_tag(note.get("tags", []))]
    all_titles = {n["title"] for n in scannable}

    # -t/tag only narrows which titles are reportable as orphans - the
    # incoming-link scan always covers the whole (non-report) vault, since a
    # note outside the tag scope can still legitimately link to one inside it.
    candidates = [n for n in scannable if tag_matches(n.get("tags", []), tag)] if tag else scannable
    candidate_titles = {n["title"] for n in candidates}

    linked_titles = set()
    checked = 0

    for note in scannable:
        note_id = note["id"]
        title = note["title"]
        try:
            content = bearcli("cat", note_id)
        except BearcliError as e:
            print(f"{title}: skipped ({e})", file=sys.stderr)
            continue

        checked += 1
        content = content.replace("\r\n", "\n").replace("\r", "\n")
        lines = content.split("\n")
        mask = protected_mask(lines)
        linked_titles.update(extract_wikilink_targets(lines, mask, all_titles))

    orphans = sorted(candidate_titles - linked_titles)

    print(f"\n{len(orphans)} orphaned note(s) with no incoming wikilinks:", file=sys.stderr)
    for title in orphans:
        print(f"  [[{title}]]", file=sys.stderr)
    print(f"\n{checked} notes checked, {len(orphans)} orphan(s) found.", file=sys.stderr)

    if sections is not None:
        if by_tag and orphans:
            title_to_tags = {n["title"]: n.get("tags", []) for n in candidates}
            for key, titles_in_group in group_by_tag(orphans, lambda t: title_to_tags.get(t, [])):
                heading = "Untagged" if key is None else shield_heading_tag(key)
                body = "\n".join(f"- [[{t}]]" for t in titles_in_group)
                sections.append(f"## {heading}\n\n{body}")
        elif orphans:
            sections.append(render_orphans_section(orphans))
        sections.append(f"---\n\n**{checked} notes checked, {len(orphans)} orphan(s) found.**")


def find_duplicates(sections=None, tag=None):
    notes = list_notes()
    notes = [n for n in notes if not has_bearkit_report_tag(n.get("tags", []))]
    if tag:
        notes = [n for n in notes if tag_matches(n.get("tags", []), tag)]

    if not notes:
        print("No notes found.", file=sys.stderr)
        return

    by_title = {}
    for n in notes:
        by_title.setdefault(n["title"], []).append(n)
    duplicate_groups = {t: ns for t, ns in by_title.items() if len(ns) > 1}

    checked = len(notes)
    print(f"\n{len(duplicate_groups)} duplicate title(s) found among {checked} note(s) checked:", file=sys.stderr)
    for title, ns in sorted(duplicate_groups.items()):
        print(f"  \"{title}\" — {len(ns)} notes: {', '.join(n['id'] for n in ns)}", file=sys.stderr)

    if sections is not None:
        for title, ns in sorted(duplicate_groups.items()):
            sections.append(render_duplicates_section(title, ns))
        sections.append(f"---\n\n**{checked} notes checked, {len(duplicate_groups)} duplicate title(s) found.**")


def open_random(count=1, tag=None):
    notes = list_notes()
    notes = [n for n in notes if not has_bearkit_report_tag(n.get("tags", []))]
    if tag:
        notes = [n for n in notes if tag_matches(n.get("tags", []), tag)]

    if not notes:
        print("No notes found.", file=sys.stderr)
        return

    for note in random.sample(notes, min(count, len(notes))):
        try:
            bearcli("app", "open", note["id"])
        except BearcliError as e:
            print(f"{note['title']}: could not open ({e})", file=sys.stderr)
            continue
        print(f"Opened: {note['title']} ({note['id']})", file=sys.stderr)


HELP = """\
bearkit — a companion tool for Bear notes

USAGE
  bearkit orphans [options]            List notes with no incoming
                                        [[wikilinks]].
  bearkit duplicates [options]         List notes that share the same title.
  bearkit wikilinks [options]          List [[wikilinks]] whose target note
                                        doesn't exist.
  bearkit wikilinks --mark [options]   ...and mark each one in the note
                                        itself by appending " +", e.g.
                                        [[Wikilink]] -> [[Wikilink +]]. Marks
                                        are self-healing: once a target note
                                        exists, the " +" is stripped back off
                                        on the next run. Asks for
                                        confirmation unless -y; -n previews
                                        the diff without writing.
  bearkit lint [options]               Lint all notes, or notes matching -t.
                                        Asks for confirmation unless -y or -n.
  bearkit lint -i <note-id> [options]  Lint a single note by ID. Never asks
                                        for confirmation.
  bearkit random [count] [options]     Open one or more random notes in Bear
                                        (1-9, default 1).
  bearkit --selftest                   Run all lint rules against a
                                        built-in sample note. Doesn't touch
                                        Bear.
  bearkit --version|-v                 Print the installed version.
  bearkit --help|-h                    Show this message.

ACTIONS
  Lists (orphans, duplicates, wikilinks) never change your notes, and
  automatically save their report as a new Bear note tagged #bearkit/lists.

  Edits (lint, wikilinks --mark) change your notes, and automatically save a
  summary as a new Bear note tagged #bearkit/edits - unless run with
  --dry-run, since nothing was actually changed. They ask for confirmation
  first unless -y/--yes is given.

  Open (random) opens notes in the Bear app and never creates a summary note.

  Every action excludes bearkit's own #bearkit/lists and #bearkit/edits
  report notes from its scans, so past reports never show up as orphans,
  duplicates, or lint/wikilink findings.

OPTIONS
  -t, --tag <tagName>  Scope to notes tagged <tagName> (and its nested
                       tags, e.g. -t people also matches #people/authors).
                       Available on every action.
  -i, --id <noteID>    Lint a single note by ID instead of a tag/vault-wide
                       scan. Only on lint; mutually exclusive with -t.
                       Skips the confirmation prompt.
  --mark               With wikilinks, mark each dangling wikilink in the
                       note itself instead of only reporting it. Targets
                       with a likely typo suggestion are left unmarked.
  --group-by-tag       Reorganize the summary note by Bear tag instead of a
                       flat list: each tag gets an H2 heading, each note
                       under it an H3. A note with multiple tags appears
                       once per tag; untagged notes group under
                       "Untagged". Available on orphans, wikilinks, lint.
  -n, --dry-run        Preview an edit action as a unified diff per note,
                       without writing anything back to Bear or creating a
                       summary note. Available on lint, wikilinks --mark.
  -y, --yes            Skip the confirmation prompt for an edit action
                       (cron/launchd-friendly). Available on lint,
                       wikilinks --mark.

EXAMPLES
  bearkit orphans
  bearkit orphans -t work
  bearkit duplicates
  bearkit wikilinks
  bearkit wikilinks --mark
  bearkit wikilinks --mark -t evergreen -y
  bearkit lint
  bearkit lint -t work -n
  bearkit lint -i 6F98051A-0000-1111-2222-9444C3615B10
  bearkit random
  bearkit random 4 -t evergreen
  bearkit --selftest

GETTING A NOTE ID
  bearcli list --fields id,title
  bearcli search "my note" --fields id,title

OUTPUT
  Progress and issue reports go to stderr; exit code is 0 on success.
    "N issue(s) fixed"                          auto-fixed, note rewritten
    "N issue(s) found (manual attention needed)" flagged only, note left as-is
    "N issue(s) would be fixed (dry run)"        auto-fixable, but -n/--dry-run given

  See the README for which lint rules auto-fix vs. report-only.

REQUIRES
  Bear 2.8+
"""

REPORT_META = {
    "orphans": ("BearKit Orphans Report", ORPHANS_REPORT_DESCRIPTION),
    "duplicates": ("BearKit Duplicates Report", DUPLICATES_REPORT_DESCRIPTION),
    "wikilinks": ("BearKit Wikilinks Report", WIKI_REPORT_DESCRIPTION),
    "lint": ("BearKit Lint Report", LINT_REPORT_DESCRIPTION),
}


def build_arg_parser():
    parser = argparse.ArgumentParser(prog="bearkit", add_help=False)
    sub = parser.add_subparsers(dest="command", required=True)

    p_orphans = sub.add_parser("orphans", add_help=False)
    p_orphans.add_argument("-t", "--tag", default=None)
    p_orphans.add_argument("--group-by-tag", action="store_true")

    p_duplicates = sub.add_parser("duplicates", add_help=False)
    p_duplicates.add_argument("-t", "--tag", default=None)

    p_wikilinks = sub.add_parser("wikilinks", add_help=False)
    p_wikilinks.add_argument("-t", "--tag", default=None)
    p_wikilinks.add_argument("--mark", action="store_true")
    p_wikilinks.add_argument("-n", "--dry-run", action="store_true")
    p_wikilinks.add_argument("-y", "--yes", action="store_true")
    p_wikilinks.add_argument("--group-by-tag", action="store_true")

    p_lint = sub.add_parser("lint", add_help=False)
    scope = p_lint.add_mutually_exclusive_group()
    scope.add_argument("-t", "--tag", default=None)
    scope.add_argument("-i", "--id", dest="note_id", default=None)
    p_lint.add_argument("-n", "--dry-run", action="store_true")
    p_lint.add_argument("-y", "--yes", action="store_true")
    p_lint.add_argument("--group-by-tag", action="store_true")

    p_random = sub.add_parser("random", add_help=False)
    p_random.add_argument("count", nargs="?", type=int, default=1, choices=range(1, 10))
    p_random.add_argument("-t", "--tag", default=None)

    return parser


def main():
    args = sys.argv[1:]

    # These short-circuit before any subcommand parsing applies.
    if not args or "--help" in args or "-h" in args:
        print(HELP, end="")
        sys.exit(0 if args else 1)

    if "--version" in args or "-v" in args:
        print(f"bearkit {__version__}")
        return

    if "--selftest" in args:
        fixed, issues = lint_note(SAMPLE_NOTE)
        print("=== bearkit selftest ===", file=sys.stderr)
        print_report(issues)
        print("\n--- fixed text ---", file=sys.stderr)
        sys.stdout.write(fixed)
        return

    parser = build_arg_parser()
    parsed = parser.parse_args(args)

    if parsed.command == "wikilinks" and (parsed.dry_run or parsed.yes) and not parsed.mark:
        sys.exit("bearkit: --dry-run/-n and --yes/-y require --mark")

    is_edit = parsed.command == "lint" or (parsed.command == "wikilinks" and parsed.mark)
    is_open = parsed.command == "random"
    dry_run = getattr(parsed, "dry_run", False)
    by_tag = getattr(parsed, "group_by_tag", False)

    sections = None if is_open else []

    if parsed.command == "orphans":
        find_orphans(sections=sections, by_tag=by_tag, tag=parsed.tag)
    elif parsed.command == "duplicates":
        find_duplicates(sections=sections, tag=parsed.tag)
    elif parsed.command == "wikilinks":
        check_wikilinks(
            sections=sections, by_tag=by_tag, mark=parsed.mark, dry_run=parsed.dry_run, yes=parsed.yes, tag=parsed.tag
        )
    elif parsed.command == "lint":
        if parsed.note_id:
            lint_one(parsed.note_id, sections=sections, dry_run=parsed.dry_run, by_tag=by_tag)
        else:
            lint_all(parsed.tag, sections=sections, dry_run=parsed.dry_run, yes=parsed.yes, by_tag=by_tag)
    elif parsed.command == "random":
        open_random(count=parsed.count, tag=parsed.tag)

    if is_open:
        return

    if is_edit and dry_run:
        return

    if sections:
        report_tag = BEARKIT_EDITS_TAG if is_edit else BEARKIT_LISTS_TAG
        title_prefix, description = REPORT_META[parsed.command]
        write_report_note(sections, title_prefix=title_prefix, description=description, tag=report_tag, group_by_tag=by_tag)
    else:
        print("bearkit: nothing to report — no note created.", file=sys.stderr)


if __name__ == "__main__":
    main()
