#!/usr/bin/env python3
"""
bear_lint.py - Markdown lint/fix for Bear notes.

USAGE
  bear_lint.py <note-id> [-o]         # lint one note by ID, optionally save a report note
  bear_lint.py --all|-a [-o]          # lint all notes (prompts for confirmation)
  bear_lint.py --all|-a "#tag" [-o]   # lint notes matching a Bear search query
  bear_lint.py --selftest             # sanity check, no Bear needed
"""

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime

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
    out = []
    for idx, line in enumerate(lines, start=1):
        stripped = line.rstrip(" \t")
        if stripped != line:
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


def check_tags(lines, mask, issues):
    for idx, raw in enumerate(lines, start=1):
        if idx == 1 or (idx - 1 < len(mask) and mask[idx - 1]):
            continue
        protected, _ = protect_inline_code(raw)

        for m in CLOSED_TAG_RE.finditer(protected):
            if " " not in m.group(1) and "\t" not in m.group(1):
                issues.append(
                    LintIssue(idx, "tag-format", f'Tag "#{m.group(1)}#" is a single word; the trailing "#" is unnecessary')
                )


BRACKET_RUN_RE = re.compile(r"\[+|\]+")
CLEAN_WIKI_OPEN_RE = re.compile(r"(?<!\[)\[\[(?!\[)")
CLEAN_WIKI_CLOSE_RE = re.compile(r"(?<!\])\]\](?!\])")
CLEAN_WIKILINK_RE = re.compile(r"(?<!\[)\[\[(?!\[)(.*?)(?<!\])\]\](?!\])")


def check_wiki_links(lines, mask, issues):
    for idx, line in enumerate(lines, start=1):
        if idx - 1 < len(mask) and mask[idx - 1]:
            continue

        for m in BRACKET_RUN_RE.finditer(line):
            run = m.group(0)
            if len(run) >= 3:
                issues.append(
                    LintIssue(idx, "wiki-link", f'{len(run)} "{run[0]}" in a row - likely a typo in a [[wiki link]]')
                )

        opens = len(CLEAN_WIKI_OPEN_RE.findall(line))
        closes = len(CLEAN_WIKI_CLOSE_RE.findall(line))
        if opens != closes:
            issues.append(
                LintIssue(idx, "wiki-link", f"Unmatched [[ ]] on this line - {opens} opening vs {closes} closing")
            )
        else:
            for m in CLEAN_WIKILINK_RE.finditer(line):
                if not m.group(1).strip():
                    issues.append(LintIssue(idx, "wiki-link", "Empty [[ ]] wiki link"))


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
        if not m:
            return False
        return m.group("box") is not None or m.group("gap1") != ""

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


def print_report(issues, fixed=True, capture=None):
    def emit(text):
        print(text, file=sys.stderr)
        if capture is not None:
            capture.append(text)

    if not issues:
        emit("No issues found.")
        return
    label = "issue(s) fixed" if fixed else "issue(s) found (manual attention needed)"
    emit(f"{len(issues)} {label}:")
    for i in issues:
        where = f"L{i.line}" if i.line else "note"
        emit(f"  [{where}] {i.rule}: {i.message}")


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


def bearcli(*args, stdin=None):
    global _bearcli_path
    if _bearcli_path is None:
        found = shutil.which("bearcli")
        if found:
            _bearcli_path = found
        elif os.path.exists(BEARCLI_FALLBACK):
            _bearcli_path = BEARCLI_FALLBACK
        else:
            sys.exit(
                "bear_lint: bearcli not found.\n"
                "Install Bear 2.8 or later: https://bear.app"
            )
    result = subprocess.run(
        [_bearcli_path, *args],
        input=stdin,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise BearcliError(result.stderr.strip())
    return result.stdout


def write_report_note(content):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    title = f"Bear Lint Report — {timestamp}"
    # Fenced so stray "#" in issue messages (e.g. quoted heading markers) aren't
    # parsed as Bear tags, and so headings/emphasis in the transcript stay inert.
    body = f"```\n{content}```"
    try:
        bearcli("create", title, "--tags", "bear-lint", stdin=body)
    except BearcliError as e:
        print(f"bear_lint: could not create report note: {e}", file=sys.stderr)
        return
    print(f"Report note created: {title}", file=sys.stderr)


# --- CLI commands ---


def lint_one(note_id, capture=None):
    def emit(text):
        print(text, file=sys.stderr)
        if capture is not None:
            capture.append(text)

    try:
        title = bearcli("show", note_id, "--fields", "title").strip()
        content = bearcli("cat", note_id)
    except BearcliError as e:
        sys.exit(f"bear_lint: {e}")

    fixed, issues = lint_note(content)
    label = f"{title} ({note_id})"

    if fixed == content:
        if not issues:
            emit(f"{label}: no issues.")
        else:
            emit(f"{label}:")
            print_report(issues, fixed=False, capture=capture)
        return

    try:
        bearcli("overwrite", note_id, "--no-update-modified", stdin=fixed)
    except BearcliError as e:
        sys.exit(f"bear_lint: could not write note: {e}")

    emit(f"{label}:")
    print_report(issues, capture=capture)


def lint_all(query=None, capture=None):
    def emit(text):
        print(text, file=sys.stderr)
        if capture is not None:
            capture.append(text)

    try:
        if query:
            out = bearcli("search", query, "--format", "json", "--fields", "id,title")
        else:
            out = bearcli("list", "--format", "json", "--fields", "id,title")
    except BearcliError as e:
        sys.exit(f"bear_lint: {e}")

    try:
        notes = json.loads(out)
    except json.JSONDecodeError as e:
        sys.exit(f"bear_lint: could not parse bearcli output: {e}\nRaw output: {out[:200]!r}")

    if not notes:
        print("No notes found.", file=sys.stderr)
        return

    if not query:
        answer = input(f"About to lint {len(notes)} notes — continue? [y/N] ")
        if answer.strip().lower() != "y":
            print("Aborted.", file=sys.stderr)
            return

    checked = 0
    fixed_count = 0

    for note in notes:
        note_id = note["id"]
        title = note["title"]
        try:
            content = bearcli("cat", note_id)
        except BearcliError as e:
            emit(f"{title}: skipped ({e})")
            continue

        fixed, issues = lint_note(content)
        checked += 1

        if fixed == content:
            if issues:
                emit(f"\n{title}:")
                print_report(issues, fixed=False, capture=capture)
            continue

        try:
            bearcli("overwrite", note_id, "--no-update-modified", stdin=fixed)
        except BearcliError as e:
            emit(f"{title}: could not write ({e})")
            continue

        emit(f"\n{title}:")
        print_report(issues, capture=capture)
        fixed_count += 1

    emit(f"\n{checked} notes checked, {fixed_count} fixed.")


HELP = """\
bear-lint — Markdown linter and fixer for Bear notes

USAGE
  bear-lint <note-id> [options]        Lint one note by ID.
  bear-lint --all|-a [query] [options] Lint all notes, or only notes matching
                                        a Bear search query. Without a query,
                                        asks for confirmation first.
  bear-lint --selftest                 Run all rules against a built-in
                                        sample note. Doesn't touch Bear.
  bear-lint --help|-h                  Show this message.

OPTIONS
  -o, --output   Also save the report as a new Bear note (tagged #bear-lint,
                 titled "Bear Lint Report — <timestamp>"). Skipped if there's
                 nothing to report (e.g. the run was aborted or nothing
                 matched the query).

EXAMPLES
  bear-lint <note-id>          Lint a single note.
  bear-lint <note-id> -o       ...and save the report as a note.
  bear-lint --all "#work"      Lint every note tagged #work.
  bear-lint -a                 Lint every note (asks to confirm first).
  bear-lint --selftest         Dry-run against the bundled sample note.

GETTING A NOTE ID
  bearcli list --fields id,title
  bearcli search "my note" --fields id,title

OUTPUT
  Progress and issue reports go to stderr; exit code is 0 on success.
    "N issue(s) fixed"                          auto-fixed, note rewritten
    "N issue(s) found (manual attention needed)" flagged only, note left as-is

  See the README for which rules auto-fix vs. report-only.

REQUIRES
  Bear 2.8+
"""


def main():
    args = sys.argv[1:]

    if not args or "--help" in args or "-h" in args:
        print(HELP, end="")
        sys.exit(0 if args else 1)

    if "--selftest" in args:
        fixed, issues = lint_note(SAMPLE_NOTE)
        print("=== bear_lint.py selftest ===", file=sys.stderr)
        print_report(issues)
        print("\n--- fixed text ---", file=sys.stderr)
        sys.stdout.write(fixed)
        return

    output_note = "-o" in args or "--output" in args
    args = [a for a in args if a not in ("-o", "--output")]
    if not args:
        sys.exit("bear_lint: missing note ID or --all")

    capture = [] if output_note else None

    if args[0] in ("--all", "-a"):
        query = args[1] if len(args) > 1 else None
        lint_all(query, capture=capture)
    else:
        lint_one(args[0], capture=capture)

    if output_note:
        if capture:
            write_report_note("\n".join(capture) + "\n")
        else:
            print("bear_lint: nothing to report — no note created.", file=sys.stderr)


if __name__ == "__main__":
    main()
