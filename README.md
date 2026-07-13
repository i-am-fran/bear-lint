# bear-lint

[Project site](https://i-am-fran.github.io/bear-lint/)

A small Markdown linter for [Bear](https://bear.app) notes. It checks and fixes common Markdown inconsistencies — bullet markers, emphasis style, checklist syntax, heading structure, tags, and more — by reading and writing your notes directly via `bearcli`.

## What it checks

| Rule | Behaviour |
|---|---|
| Bullet markers | Standardises on `-`, flags `*` / `+` |
| Bold/italic markers | Standardises on `**bold**` / `*italic*`, flags `__`/`_` |
| Heading hierarchy | Flags skipped levels between real headings, fixes missing blank lines before/after headings |
| Missing H1 | Flags when the title-equivalent line (line 1, or the first line after YAML frontmatter) isn't a literal `# ` H1 heading, left for you to fix by hand |
| Duplicate H1 | Flags an extra `#` heading further down the note (the title-equivalent line — line 1, or the first line after YAML frontmatter — is exempt), left for you to fix by hand since demoting a heading changes real Markdown semantics |
| Stub notes | Flags a note that has only its title-equivalent H1 and no content underneath, left for you to fill in or delete |
| Checklist syntax | Normalises to `- [ ] ` / `- [x] ` |
| Trailing whitespace | Stripped, except exactly two trailing spaces mid-note (a CommonMark hard break `<br>`), which are preserved when followed by another non-blank line |
| Multiple blank lines | Collapsed to one |
| Bear tag format | Flags unnecessary `#tag#` wraps on single-word tags |
| `[[Wiki links]]` | Flags unmatched or empty double brackets, and stray triple+ brackets like `[[[typo]]]` |
| Trailing newline | Exactly one at the end of the note |
| Horizontal rules | Normalised to `---`; consecutive rules collapsed into one; a blank line is enforced above and below |
| Curly quotes | Converted to straight quotes (`"`/`'`) |
| YAML frontmatter | Blank lines inside a frontmatter block are removed |
| Blockquote spacing | Adds the missing space after `>`, e.g. `>Text` → `> Text` |
| List spacing | Adds a blank line separating a list from the paragraph before/after it; covers both bullet/checklist lists and ordered (`1.` / `1)`) lists |

`--wiki`/`-w` and `--orphans` are separate, vault-wide commands (see Usage below): `--wiki` reports `[[wikilinks]]` pointing to notes that don't exist, `--orphans` reports notes that no other note links to. Neither is one of the per-note rules above since both need every note's title and links compared against the whole vault, not just the one note being linted.

## Requirements

- macOS with Bear 2.8 or later installed
- Python 3.8+ (pre-installed on macOS)

## Installation

```bash
git clone https://github.com/i-am-fran/bear-lint.git
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
bear-lint --version              # print the installed version
bear-lint <note-id>              # lint one note by ID
bear-lint --all                  # lint all notes (always asks for confirmation first)
bear-lint -a "#tag"              # -a is a short alias for --all
bear-lint --all "#tag"           # lint notes matching a Bear search query (also confirms first)
bear-lint --all "#tag" -y        # skip the confirmation prompt (cron/launchd-friendly)
bear-lint --selftest             # sanity check, no Bear needed
bear-lint <note-id> -o           # lint one note and also save the report as a Bear note
bear-lint --all "#tag" -o        # same, for a batch run
bear-lint <note-id> -n           # preview the diff without writing anything back
bear-lint --all -n               # preview every note's changes without writing (no prompt)
bear-lint --wiki                 # vault-wide: report [[wikilinks]] with no matching note
bear-lint --wiki -o              # ...and save the report as a Bear note
bear-lint --orphans              # vault-wide: report notes with no incoming [[wikilinks]]
bear-lint --orphans -o           # ...and save the report as a Bear note
bear-lint --all -o -t            # save the report grouped by tag (H2 tag, H3 note title)
```

Get a note's ID from `bearcli list` or `bearcli search "query"`. Output shows `Title (id): N issue(s) fixed`. Issue reports go to stderr; exit code is 0 on success. An unrecognised flag (e.g. a typo like `--al`) is rejected with a clear error instead of silently being treated as a note ID or search query.

Add `-o` / `--output` to also save the report inside Bear: a new note per run, titled `Bear Lint Report — <timestamp>` and tagged `#bear-lint`, with a one-line description below the title explaining what the note contains. The body is Markdown, not a plain-text mirror of stderr: each linted note gets a `[[wikilink]]` heading back to it, issues needing manual attention render as `> [!WARNING]` callouts, stub notes as `> [!TIP]`, and auto-fixed issues as a plain bullet list. No note is created if there's nothing to report (aborted run, or no notes matched the query).

Add `-t` / `--by-tag` to reorganize that same `-o` report by Bear tag instead of the default flat list: each tag gets its own H2 heading, and every note under it renders one level deeper, as an H3. A note with more than one tag is repeated under each of its tags; notes with no tags at all are grouped under a catch-all `## Untagged` heading. Tag headings are rendered as `` `#tag` `` (backtick-wrapped) rather than bare `#tag` text, so Bear doesn't parse the heading itself as a real tag and silently apply it to the report note. `-t` only changes the `-o` note's structure, so it requires `-o`/`--output` and works with every report mode (`lint_one`, `--all`, `--wiki`, `--orphans`). `--orphans` is the one exception to the H2/H3 shape: since every orphaned note's body is the same boilerplate ("nothing links here"), an H3 per note would just repeat that line over and over, so grouped orphan reports render each tag's orphans as a plain `- [[wikilink]]` bullet list under its H2 instead.

Add `-n` / `--dry-run` to preview what would change — a unified diff per note — without calling back to Bear at all. Since nothing destructive happens, `--dry-run` also skips the `--all` confirmation prompt. Add `-y` / `--yes` to skip that same prompt for a real (writing) run, e.g. from cron or launchd.

Add `-w` / `--wiki` for a vault-wide check: it scans every note for `[[wikilinks]]` (reusing the same well-formed-link detection as the per-note wiki-link check), fetches every note's title via `bearcli list`, and flags any wikilink whose target doesn't match an existing note title. A dangling target is further checked against every real note title for a likely typo — an exact case-insensitive match, or a close match via `difflib.get_close_matches` — and if one is found, it renders as `- [[target]] → possible typo, did you mean [[Real Title]]?` instead of a plain bullet, so likely mistakes stand out from intentional links to things that were never meant to be notes (people, apps, concepts). Notes tagged `#bear-lint` (i.e. bear-lint's own report notes) are skipped as scan sources — their bullet lists are real `[[wikilinks]]` to nonexistent notes by design, so scanning them would recursively flag every past report. This is a standalone command mode, not a per-note rule — it can't be combined with a note ID, `--all`, `--dry-run`, `--yes`, or `--orphans`, but can be combined with `-o`. With `-o`, the report note is titled `Bear Wikilinks Report — <timestamp>` (distinct from the regular `Bear Lint Report`) and each section is just a plain, clickable list of the dangling `[[wikilinks]]` found under that note's heading (possible typos listed first) — no callouts, note IDs, or line numbers, and only notes with an actual dangling link get a section.

Add `--orphans` for the mirror-image vault-wide check: notes that nothing else links to. It fetches every note's title and content the same way `--wiki` does, scans each note for `[[wikilinks]]`, and builds a vault-wide set of every title that's been linked to at least once; any note whose title never shows up in that set is flagged as an orphan. Notes tagged `#bear-lint` are excluded entirely — both as scan sources and as orphan candidates — since nothing ever links back to a timestamped report note, and flagging every past report as an orphan on every run would be pure noise. Like `--wiki`, this is a standalone command mode — it can't be combined with a note ID, `--all`, `--dry-run`, `--yes`, or `--wiki`, but can be combined with `-o`. With `-o`, the report note is titled `Bear Orphans Report — <timestamp>`, with a single `## Orphaned Notes` section listing every orphaned note as a plain, clickable `[[wikilink]]` bullet.

## Try it without touching your notes

```bash
python3 bear_lint.py --selftest
```

This runs all rules against a bundled sample note and prints the fixed text plus a report so you can see exactly what it does.

## Testing

`test_bear_lint.py` is a plain assert-based test suite (no pytest) covering each rule in isolation plus an idempotency check — running `lint_note()` twice on the same input must produce identical output the second time, which catches autofixes that re-trigger each other. Run it with:

```bash
python3 test_bear_lint.py
```

`test-note.md` in this repo is a single note deliberately built to trigger every rule at once. Import it into Bear (`File → Import → Files/Folders…`, or drag it onto Bear's note list), then run:

```bash
bearcli search "Bear Lint Test Note" --fields id,title
python3 bear_lint.py <note-id>
```

Compare what Bear shows afterwards against the table above. (The stub-notes check isn't exercised by this fixture — a note with enough content to trigger every other rule can't also be an empty stub — so test it separately with a note that has only an H1 title and nothing else.)

## A note on safety

**Back up first.** Export your Bear library before running this on your real notes: Bear → File → Export Notes. Bear's built-in [version history](https://bear.app/faq/backup-restore/) (Pro) also lets you roll back individual notes, but a full export gives you a snapshot you can restore from without Bear.

Writes use bearcli's `--no-update-modified` flag, so fixed notes keep their original modification date and don't reorder your note list.

## Limitations

- Heuristic-based, not a full Markdown parser. Handles fenced code blocks, inline code spans, and YAML frontmatter (a `---` on line 1 with a matching closing `---`) as protected regions (aside from stripping blank lines inside frontmatter), but very unusual formatting may confuse a rule or two.
- A few rules are report-only by design (missing/duplicate H1, heading-level skips, stub notes, tag format, wiki-link problems), because auto-fixing them risks changing the note's actual structure or meaning.
- Locked/encrypted Bear notes are skipped automatically.

## Changelog

See the [Releases page](https://github.com/i-am-fran/bear-lint/releases) for what changed between versions.

## Issues

Found a bug or have a feature request? [Open a GitHub issue](https://github.com/i-am-fran/bear-lint/issues) — pull requests aren't accepted, but issue reports are very welcome.

## License

MIT, see [LICENSE](LICENSE).

---

[Check out more of my projects 🚀](https://iamfran.com/tags/projects/)
