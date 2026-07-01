# bear-lint

A small Markdown linter for [Bear](https://bear.app) notes, built to run from a macOS Shortcut rather than the terminal. It checks and fixes common Markdown inconsistencies (bullet markers, emphasis style, checklist syntax, heading structure, tags, and more).

The Python side is two small, dependency-free scripts, `bear_lint_single.py` and `bear_lint_all.py`, one per Shortcut, that just transform text: Markdown in, fixed Markdown out. They share the same rules and behaviour; they're kept as separate files purely so each Shortcut has its own clearly-named script to point at. Finding notes and writing the result back is handled entirely by Bear's own native Shortcuts actions, so there's no CLI, no API keys, and nothing else to install.

## What it checks

| Rule | Behaviour |
|---|---|
| Bullet markers | Standardises on `-`, flags `*` / `+` |
| Bold/italic markers | Standardises on `**bold**` / `*italic*`, flags `__`/`_` |
| Heading hierarchy | Flags skipped levels, fixes missing blank lines before/after headings |
| Duplicate H1 | Flags a `#` on line 1 and any other H1 further down, left for you to fix by hand since removing a heading marker changes real Markdown semantics |
| Checklist syntax | Normalises to `- [ ] ` / `- [x] ` |
| Trailing whitespace | Stripped |
| Multiple blank lines | Collapsed to one |
| Bear tag format | Flags likely-unclosed multi-word tags and unnecessary `#tag#` wraps on single-word tags |
| `[[Wiki links]]` | Flags unmatched or empty double brackets, and stray triple+ brackets like `[[[typo]]]` |
| Trailing newline | Exactly one at the end of the note |
| Horizontal rules | Normalised to `---` |
| Straight vs smart quotes | Flags a note that mixes both styles |

## Requirements

- macOS with Bear installed
- Python 3.8+ (preinstalled on macOS)
- The Shortcuts app (preinstalled on macOS)

## Installation

```bash
git clone https://github.com/<your-username>/bear-lint.git
```

Note where you cloned it, you'll need the full path when setting up the Shortcuts below.

## Try it without touching Bear

```bash
python3 bear_lint_single.py --selftest
```

This runs the checks against a bundled sample note and prints the fixed text plus a report, so you can see exactly what it does before wiring it up to anything. `bear_lint_all.py --selftest` does the same thing, they're identical under the hood.

You can also pipe any note text through either one directly:

```bash
cat some-note.md | python3 bear_lint_single.py
```

Fixed Markdown comes out on stdout; the list of issues found goes to stderr, so the two never get mixed together.

## Set up the Shortcuts

This repo includes two ready-made Shortcuts:

- **Bear Lint (One Note).shortcut**: search for and pick a single note, lint it, write it back.
- **Bear Lint (All Notes).shortcut**: same, but loops over every note matched by a search term.

To install one: double-click the `.shortcut` file (or open it via the Shortcuts app) to import it, then open its **Run Shell Script** step and update the path so it points at wherever you cloned this repo, e.g.:

```
/usr/bin/python3 "/path/to/bear-lint/bear_lint_single.py"
```

**One-time setup:** Shortcuts app → menu bar **Shortcuts → Settings → Advanced** → turn on **Allow Running Scripts**. Without this, the Run Shell Script step will refuse to run.

Run "All Notes" on a small tagged subset first before trusting it with your whole library.

**Troubleshooting**

- If the shell script step can't find `python3` or the script file, double-check the absolute path, Shortcuts runs with a minimal environment and won't pick up your shell's PATH.
- If file access fails silently, check **System Settings → Privacy & Security → Full Disk Access** and enable it for Shortcuts.
- Locked/encrypted Bear notes can't be read or written by Shortcuts, they'll be skipped.
- The `h1-on-title-line` flag (a literal `#` on line 1) will likely never fire through the Shortcuts path, since Bear splits a note into Title and Text before the script sees it. It only matters if you're linting exported `.md` files directly.

## A note on safety

Neither script touches Bear on its own, only text handed to it. But the Shortcuts overwrite the note when they write back, and there's no built-in backup step, on purpose, to keep things simple. Before running "All Notes" on your real library for the first time: try it on a couple of test notes first (see [Testing](#testing) below), and know that Bear's own [version history](https://bear.app/faq/backup-restore/) (Pro) is your safety net if something looks wrong afterwards.

## Testing

`test-note.md` in this repo is a single note deliberately built to trigger every rule at once, bullet markers, checklist syntax, heading issues, tags, wiki links, quotes, the works. Import it into Bear (`File → Import → Files/Folders...`, or just drag the file onto Bear's note list) and run either Shortcut against it before trusting either one with your real notes. Compare what you see against the table above.

## Limitations

- Heuristic-based, not a full Markdown parser. It handles fenced code blocks and inline code spans, but very unusual formatting may confuse a rule or two, especially the tag-format check, which flags likely issues for you to confirm rather than auto-fixing them.
- No dry-run/diff step baked in, the Shortcut writes the fixed text straight back. Add a **Show Result** action between the Run Shell Script and Add Text to Note steps if you want to review first.
- A few rules are report-only by design (duplicate/title H1s, tag format, wiki-link problems, quote consistency), because auto-fixing them risks changing the note's actual structure or meaning rather than just its style.

## Contributing

Issues and pull requests are welcome.

## License

MIT, see [LICENSE](LICENSE).
