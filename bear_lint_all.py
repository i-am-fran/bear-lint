#!/usr/bin/env python3
"""
bear_lint_all.py - Markdown lint/fix engine, used by the "Bear Lint (All Notes)" Shortcut.

Same rules and behaviour as bear_lint_single.py: reads one note's Markdown
from stdin, writes the fixed Markdown to stdout, and prints an issue
report to stderr. It's kept as a separate file so each Shortcut has its
own clearly-named script to point at.

The "All Notes" Shortcut calls this once per note, inside a "Repeat with
Each" loop over Bear's Search Notes results, writing each note back with
"Add Text to Note" as it goes. This script itself only ever sees one
note's text at a time, it never touches Bear, the filesystem, or the
network. See README.md for the full Shortcut setup.

USAGE
  cat note.md | python3 bear_lint_all.py > fixed.md
  python3 bear_lint_all.py --selftest   # sanity-check the rules, no input needed

WHAT IT CHECKS / FIXES
  - Bullet markers          -> standardises on "-", flags "*" / "+"
  - Bold/italic markers     -> "**bold**" / "*italic*", flags "__"/"_"
  - Heading hierarchy       -> flags skipped levels, fixes missing blank
                               lines before/after headings
  - Duplicate H1            -> strips a redundant "#" on line 1 (Bear
                               already uses line 1 as the note title),
                               flags any other H1 further down
  - Checklist syntax        -> normalises to "- [ ] " / "- [x] "
  - Trailing whitespace     -> stripped
  - Multiple blank lines    -> collapsed to one
  - Bear tag format         -> flags likely-unclosed multi-word tags and
                               unnecessary "#tag#" wraps on single words
  - [[Wiki links]]          -> flags unmatched or empty double brackets
  - Trailing newline        -> exactly one at the end of the note
  - Horizontal rules        -> normalised to "---"
  - Straight vs smart quotes -> flags a note that mixes both styles
"""

import re
import sys
from dataclasses import dataclass

HEADING_RE = re.compile(r"^(#{1,6})(\s*)(.*)$")
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
HR_RE = re.compile(r"^[ \t]{0,3}([-*_])[ \t]*(?:\1[ \t]*){2,}$")
INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
LIST_ITEM_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<marker>[*+-])"
    r"(?P<gap1>[ \t]*)"
    r"(?:\[(?P<box>[ xX])\](?P<gap2>[ \t]*))?"
    r"(?P<text>.*)$"
)
BOLD_UNDERSCORE_RE = re.compile(r"__(?!\s)([^_\n]+?)(?<!\s)__")
ITALIC_UNDERSCORE_RE = re.compile(r"(?<![\w_])_(?!_)([^_\n]+?)(?<!\s)_(?![\w_])")
CLOSED_TAG_RE = re.compile(r"#([^#\s][^#\n]*?)#")
UNCLOSED_TAG_RE = re.compile(r"#([a-zA-Z][\w/-]*)((?:[ \t]+[a-zA-Z][\w/-]*){1,5})")
SMART_QUOTE_CHARS = "“”‘’"


@dataclass
class LintIssue:
    line: int  # 0 = note-wide issue, not tied to one line
    rule: str
    message: str


def code_block_mask(lines):
    """True for any line that is a fenced-code line or inside a fenced code block."""
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
        return line  # not really a list item (e.g. "-text", or "*word*" at line start)

    if marker != "-":
        issues.append(LintIssue(lineno, "bullet-marker", f'Bullet marker "{marker}" changed to "-"'))

    if box is not None:
        norm_box = "x" if box in ("x", "X") else " "
        new_line = f"{indent}- [{norm_box}] {text}"
        if new_line.rstrip() != line.rstrip():
            issues.append(LintIssue(lineno, "checklist-syntax", 'Normalised checklist syntax to "- [ ] " / "- [x] "'))
        return new_line

    return f"{indent}- {text}"


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


def process_headings(lines, mask):
    """Fix blank-line spacing around headings and flag skipped heading levels.

    Line 1 (the note's title) always counts as the implicit H1, even though
    by this point any literal leading '#' has already been stripped from it.
    """
    issues = []
    if not lines:
        return lines, issues

    out = [lines[0]]
    n = len(lines)
    prev_level = 1

    if n > 1 and lines[1].strip() != "":
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
            if level > prev_level + 1:
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


def check_title_heading(lines, issues):
    """Flag (don't touch) a literal '#' on line 1.

    This used to strip the '#' automatically on the assumption that Bear
    would still show line 1 as a styled title either way. Real-world
    testing showed that's wrong: removing the '#' turns a real H1 into a
    plain paragraph, losing heading semantics. So this is report-only now,
    left for you to decide.
    """
    if not lines:
        return
    m = HEADING_RE.match(lines[0])
    if m and m.group(1):
        issues.append(
            LintIssue(
                1,
                "h1-on-title-line",
                "Line 1 starts with '#'. Bear treats line 1 as the note title regardless, "
                "but removing the '#' would also turn it from a real heading into a plain "
                "paragraph, so this is left for you to decide rather than auto-fixed.",
            )
        )


def check_duplicate_h1(lines, mask, issues):
    for idx, line in enumerate(lines[1:], start=2):
        if idx - 1 < len(mask) and mask[idx - 1]:
            continue
        m = HEADING_RE.match(line)
        if m and len(m.group(1)) == 1 and m.group(3).strip():
            issues.append(
                LintIssue(
                    idx,
                    "duplicate-h1",
                    f'Extra "# {m.group(3).strip()}" heading found further down the note. Bear '
                    "already treats the first line as the title/H1 - consider demoting this to H2.",
                )
            )


def check_tags(lines, mask, issues):
    for idx, raw in enumerate(lines, start=1):
        if idx == 1 or (idx - 1 < len(mask) and mask[idx - 1]):
            continue
        protected, _ = protect_inline_code(raw)
        masked = CLOSED_TAG_RE.sub(lambda m: "#" + "\x02" * (len(m.group(0)) - 2) + "#", protected)

        for m in UNCLOSED_TAG_RE.finditer(masked):
            if masked[m.end() : m.end() + 1] == "#":
                continue
            phrase = (m.group(1) + m.group(2)).strip()
            issues.append(
                LintIssue(
                    idx,
                    "tag-format",
                    f'Possible unclosed multi-word tag "#{phrase}" - Bear needs "#{phrase}#" '
                    "to tag the whole phrase (please verify manually)",
                )
            )

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


def check_quotes(lines, mask, issues):
    straight = 0
    smart = 0
    for idx, line in enumerate(lines, start=1):
        if idx - 1 < len(mask) and mask[idx - 1]:
            continue
        protected, _ = protect_inline_code(line)
        straight += protected.count('"') + protected.count("'")
        smart += sum(protected.count(c) for c in SMART_QUOTE_CHARS)
    if straight and smart:
        issues.append(
            LintIssue(
                0,
                "quote-consistency",
                f"Note mixes straight ({straight}) and curly ({smart}) quotes - pick one style",
            )
        )


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


def ensure_single_trailing_newline(text, issues):
    stripped = text.rstrip("\n")
    if text != stripped + "\n":
        issues.append(LintIssue(0, "trailing-newline", "Normalised to a single trailing newline"))
    return stripped + "\n"


def lint_note(text):
    """Pure function: text in, (fixed_text, issues) out."""
    issues = []
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")

    mask = code_block_mask(lines)
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
        new_line, changed = normalize_emphasis(line)
        if changed:
            issues.append(LintIssue(i + 1, "emphasis-marker", "Converted __/_ emphasis to **/*"))
        lines[i] = new_line

    check_title_heading(lines, issues)

    mask = code_block_mask(lines)
    lines, heading_issues = process_headings(lines, mask)
    issues.extend(heading_issues)

    mask = code_block_mask(lines)
    check_duplicate_h1(lines, mask, issues)
    check_tags(lines, mask, issues)
    check_wiki_links(lines, mask, issues)
    check_quotes(lines, mask, issues)

    lines = collapse_blank_lines(lines, issues)

    text_out = "\n".join(lines)
    text_out = ensure_single_trailing_newline(text_out, issues)

    issues.sort(key=lambda x: (x.line, x.rule))
    return text_out, issues


def print_report(issues):
    if not issues:
        print("No issues found.", file=sys.stderr)
        return
    print(f"{len(issues)} issue(s) fixed:", file=sys.stderr)
    for i in issues:
        where = f"L{i.line}" if i.line else "note"
        print(f"  [{where}] {i.rule}: {i.message}", file=sys.stderr)


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
Tag test: #work and #project management without closing, plus #done#.
***
Horizontal rule above should become ---.
"""


def main():
    if "--selftest" in sys.argv:
        fixed, issues = lint_note(SAMPLE_NOTE)
        print("=== bear_lint_all.py selftest ===", file=sys.stderr)
        print_report(issues)
        print("\n--- fixed text ---", file=sys.stderr)
        sys.stdout.write(fixed)
        return

    original = sys.stdin.read()
    fixed, issues = lint_note(original)
    sys.stdout.write(fixed)
    print_report(issues)


if __name__ == "__main__":
    main()
