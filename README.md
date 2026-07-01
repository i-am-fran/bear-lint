# bear-lint

A small Markdown linter for [Bear](https://bear.app) notes. It checks and fixes common Markdown inconsistencies — bullet markers, emphasis style, checklist syntax, heading structure, tags, and more — by reading and writing your notes directly via `bearcli`.

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
bear-lint --all "#tag"           # lint notes matching a Bear search query
bear-lint --selftest             # sanity check, no Bear needed
```

Get a note's ID from `bearcli list` or `bearcli search "query"`. Output shows `Title (id): N issue(s) fixed`. Issue reports go to stderr; exit code is 0 on success.

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

`bear_lint.py` overwrites notes in place. Before running `--all` on your real library, try it on a small tagged subset first, and know that Bear's own [version history](https://bear.app/faq/backup-restore/) (Pro) is your safety net if something looks wrong.

## Limitations

- Heuristic-based, not a full Markdown parser. Handles fenced code blocks and inline code spans, but very unusual formatting may confuse a rule or two — especially the tag-format check, which flags likely issues for you to confirm rather than auto-fixing.
- A few rules are report-only by design (duplicate/title H1s, tag format, wiki-link problems, quote consistency), because auto-fixing them risks changing the note's actual structure or meaning.
- Locked/encrypted Bear notes are skipped automatically.

## Contributing

Issues and pull requests are welcome.

## License

MIT, see [LICENSE](LICENSE).
