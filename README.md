# bear-lint

A small Markdown linter for [Bear](https://bear.app) notes. It checks and fixes common Markdown inconsistencies — bullet markers, emphasis style, checklist syntax, heading structure, tags, and more — by reading and writing your notes directly via `bearcli`.

## What it checks

| Rule | Behaviour |
|---|---|
| Bullet markers | Standardises on `-`, flags `*` / `+` |
| Bold/italic markers | Standardises on `**bold**` / `*italic*`, flags `__`/`_` |
| Heading hierarchy | Flags skipped levels between real headings, fixes missing blank lines before/after headings |
| Missing H1 | Flags when the title-equivalent line (line 1, or the first line after YAML frontmatter) isn't a literal `# ` H1 heading, left for you to fix by hand |
| Duplicate H1 | Flags an extra `#` heading further down the note (the title-equivalent line — line 1, or the first line after YAML frontmatter — is exempt), left for you to fix by hand since demoting a heading changes real Markdown semantics |
| Checklist syntax | Normalises to `- [ ] ` / `- [x] ` |
| Trailing whitespace | Stripped |
| Multiple blank lines | Collapsed to one |
| Bear tag format | Flags unnecessary `#tag#` wraps on single-word tags |
| `[[Wiki links]]` | Flags unmatched or empty double brackets, and stray triple+ brackets like `[[[typo]]]` |
| Trailing newline | Exactly one at the end of the note |
| Horizontal rules | Normalised to `---`; consecutive rules collapsed into one; a blank line is enforced above and below |
| Curly quotes | Converted to straight quotes (`"`/`'`) |
| YAML frontmatter | Blank lines inside a frontmatter block are removed |
| Blockquote spacing | Adds the missing space after `>`, e.g. `>Text` → `> Text` |
| List spacing | Adds a blank line separating a list from the paragraph before/after it |

## Requirements

- macOS with Bear 2.8 or later installed
- Python 3.8+ (pre-installed on macOS)

## Installation

```bash
git clone https://github.com/<your-username>/bear-lint.git
```

Then make it runnable as `bear-lint` from anywhere. Pick one:

**Alias** (add to `~/.zshrc`):
```bash
alias bear-lint='python3 /path/to/bear-lint/bear_lint.py'
```

**Symlink** (makes it a first-class command on your PATH):
```bash
chmod +x /path/to/bear-lint/bear_lint.py
ln -s /path/to/bear-lint/bear_lint.py /usr/local/bin/bear-lint
```

After either, reload your shell and `bear-lint --help` will work.

## Usage

```bash
bear-lint --help                 # show all commands
bear-lint <note-id>              # lint one note by ID
bear-lint --all                  # lint all notes (prompts for confirmation)
bear-lint -a "#tag"              # -a is a short alias for --all
bear-lint --all "#tag"           # lint notes matching a Bear search query
bear-lint --selftest             # sanity check, no Bear needed
bear-lint <note-id> -o           # lint one note and also save the report as a Bear note
bear-lint --all "#tag" -o        # same, for a batch run
```

Get a note's ID from `bearcli list` or `bearcli search "query"`. Output shows `Title (id): N issue(s) fixed`. Issue reports go to stderr; exit code is 0 on success.

Add `-o` / `--output` to also save the report inside Bear: a new note per run, titled `Bear Lint Report — <timestamp>` and tagged `#bear-lint`, containing the same text as the stderr output. No note is created if there's nothing to report (aborted run, or no notes matched the query).

## Try it without touching your notes

```bash
python3 bear_lint.py --selftest
```

This runs all rules against a bundled sample note and prints the fixed text plus a report so you can see exactly what it does.

## Testing

`test-note.md` in this repo is a single note deliberately built to trigger every rule at once. Import it into Bear (`File → Import → Files/Folders…`, or drag it onto Bear's note list), then run:

```bash
bearcli search "Bear Lint Test Note" --fields id,title
python3 bear_lint.py <note-id>
```

Compare what Bear shows afterwards against the table above.

## A note on safety

**Back up first.** Export your Bear library before running this on your real notes: Bear → File → Export Notes. Bear's built-in [version history](https://bear.app/faq/backup-restore/) (Pro) also lets you roll back individual notes, but a full export gives you a snapshot you can restore from without Bear.

Writes use bearcli's `--no-update-modified` flag, so fixed notes keep their original modification date and don't reorder your note list.

## Limitations

- Heuristic-based, not a full Markdown parser. Handles fenced code blocks, inline code spans, and YAML frontmatter (a `---` on line 1 with a matching closing `---`) as protected regions (aside from stripping blank lines inside frontmatter), but very unusual formatting may confuse a rule or two.
- A few rules are report-only by design (duplicate H1, tag format, wiki-link problems), because auto-fixing them risks changing the note's actual structure or meaning.
- Locked/encrypted Bear notes are skipped automatically.

## Contributing

Issues and pull requests are welcome.

## License

MIT, see [LICENSE](LICENSE).
