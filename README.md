# BearKit

[Project site](https://i-am-fran.github.io/bearkit/)

A companion tool for [Bear](https://bear.app) notes. It checks and fixes common Markdown inconsistencies, finds orphaned/duplicate/dangling-linked notes, and can open random notes for review — all by reading and writing your notes directly via `bearcli`.

Actions split into three categories:

- **Lists** (`orphans`, `duplicates`, `wikilinks`) never change your notes, and automatically save their report as a new Bear note tagged `#bearkit/lists`.
- **Edits** (`lint`, `wikilinks --mark`) change your notes, and automatically save a summary as a new Bear note tagged `#bearkit/edits` — unless run with `--dry-run`, since nothing was actually changed. They ask for confirmation first unless `-y`/`--yes` is given.
- **Open** (`random`) opens notes in the Bear app and never creates a summary note.

Every action excludes bearkit's own `#bearkit/lists` and `#bearkit/edits` report notes from its scans, so past reports never show up as orphans, duplicates, or lint/wikilink findings.

## What `lint` checks

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

`wikilinks` and `orphans` and `duplicates` are separate, vault-wide commands (see Usage below): `wikilinks` reports `[[wikilinks]]` pointing to notes that don't exist (optionally marking them in place with `--mark`), `orphans` reports notes that no other note links to, and `duplicates` reports notes that share the same title. None of these are per-note `lint` rules, since all three need every note's title and links compared against the whole vault, not just the one note being linted.

## Requirements

- macOS with Bear 2.8 or later installed
- Python 3.8+ (pre-installed on macOS)

## Installation

```bash
git clone https://github.com/i-am-fran/bearkit.git
```

Then make it runnable as `bearkit` from anywhere. Pick one:

**Alias** (add to `~/.zshrc`):
```bash
alias bearkit='python3 /path/to/bearkit/bearkit.py'
```

**Symlink** (makes it a first-class command on your PATH):
```bash
chmod +x /path/to/bearkit/bearkit.py
ln -s /path/to/bearkit/bearkit.py /usr/local/bin/bearkit
```

After either, reload your shell and `bearkit --help` will work.

## Usage

```bash
bearkit --help                       # show all commands
bearkit --version                    # print the installed version
bearkit orphans                      # list notes with no incoming [[wikilinks]]
bearkit orphans -t work              # ...scoped to notes tagged #work
bearkit duplicates                   # list notes that share the same title
bearkit wikilinks                    # list [[wikilinks]] with no matching note
bearkit wikilinks --mark             # ...and mark dangling wikilinks in place (" +")
bearkit wikilinks --mark -y          # ...same, but skip the confirmation prompt
bearkit wikilinks --mark -n          # preview which notes would be marked, without writing
bearkit lint                         # lint every note (asks for confirmation)
bearkit lint -t work                 # ...only notes tagged #work
bearkit lint -t work -y              # ...same, but skip the confirmation prompt
bearkit lint -n                      # preview every note's changes without writing (no prompt)
bearkit lint -i <note-id>            # lint a single note by ID (no confirmation)
bearkit lint -i <note-id> -n         # ...preview the diff without writing it
bearkit random                       # open one random note in Bear
bearkit random 4 -t evergreen        # open 4 random notes tagged #evergreen
bearkit --selftest                   # sanity check against a built-in sample note
```

Get a note's ID from `bearcli list` or `bearcli search "query"`. Output shows `Title (id): N issue(s) fixed`. Issue reports go to stderr; exit code is 0 on success.

Add `-t <tagName>` to scope any command to notes carrying that Bear tag — nested tags match too, so `-t people` also matches a note only tagged `#people/authors`.

Add `--group-by-tag` (on `orphans`, `wikilinks`, `lint`) to reorganize the summary note by Bear tag instead of a flat list: each tag gets an H2 heading, each note under it gets an H3. A note with multiple tags appears once under each of its tags; untagged notes are grouped under an "Untagged" H2. `orphans` reports have no per-note body worth heading, so grouped orphan output is a plain `- [[wikilink]]` bullet list under each tag's H2 instead of one H3 per note.

Add `-n` / `--dry-run` (on `lint`, `wikilinks --mark`) to preview what would change — a unified diff per note — without calling back to Bear at all, and without creating a summary note (nothing was actually changed). Since nothing destructive happens, `--dry-run` also skips the confirmation prompt.

Add `-y` / `--yes` (on `lint`, `wikilinks --mark`) to skip the confirmation prompt, e.g. from cron or launchd.

Add `--mark` (with `wikilinks`) to go a step further: instead of only reporting a dangling target, it rewrites the wikilink in the note itself, appending a trailing marker — `[[Wikilink]]` becomes `[[Wikilink +]]` — so it stands out right inside Bear's own UI. Only targets with no typo suggestion are marked (a likely typo is left for the "did you mean" report to guide a manual fix instead). A heading or alias link that resolves to a real note is never marked; a genuinely dangling one keeps its `/Heading` and/or `|Alias` text intact, with the `" +"` marker appended at the very end. Marking is idempotent and self-healing: re-running never doubles the marker, and once the target note actually gets created, its `" +"` is automatically stripped back off on the next run.

## Actions in depth

### `wikilinks`

Scans every note for `[[wikilinks]]` (reusing the same well-formed-link detection as `lint`'s per-note check), fetches every note's title via `bearcli list`, and flags any wikilink whose target doesn't match an existing note title. Bear's native `[[Note/Heading]]` (heading link) and `[[Note|Alias]]` (alias link, display text only — these may combine as `[[Note/Heading|Alias]]`) syntax is recognized: the note-title portion is resolved from the compound target before being checked against real titles, so a valid heading or alias link is never misflagged as dangling. A dangling target is further checked against every real note title for a likely typo — an exact case-insensitive match, or a close match via `difflib.get_close_matches` — and if one is found, it renders as `- [[target]] → possible typo, did you mean [[Real Title]]?` instead of a plain bullet. `-t` scopes which notes are scanned as *sources*, but target resolution always considers the whole vault, since a scoped note can still legitimately link to something outside its tag.

### `orphans`

The mirror-image vault-wide check: notes that nothing else links to. It scans every note for `[[wikilinks]]` (recognizing Bear's `Note/Heading` and `Note|Alias` compound syntax) and builds a vault-wide set of every title that's been linked to at least once; any note whose title never shows up in that set is flagged as an orphan. `-t` only narrows which titles are *reportable* — the incoming-link scan always covers the whole vault, since a note outside the tag scope can still legitimately link to one inside it.

### `duplicates`

Finds notes that share the same title. Since a `[[Title]]` wikilink can't disambiguate between duplicates, each note in the report renders as a clickable `bear://` link with its tags as a disambiguating suffix, instead of a wikilink.

### `random`

Opens one or more random notes directly in the Bear app via `bearcli open` (1–9 notes, default 1). If `count` exceeds the number of matching notes, it opens all of them rather than erroring.

## Try it without touching your notes

```bash
python3 bearkit.py --selftest
```

This runs all lint rules against a bundled sample note and prints the fixed text plus a report so you can see exactly what it does.

## Testing

`test_bearkit.py` is a plain assert-based test suite (no pytest) covering each rule and command in isolation, plus an idempotency check for `lint_note()` — running it twice on the same input must produce identical output the second time, which catches autofixes that re-trigger each other. Run it with:

```bash
python3 test_bearkit.py
```

`test-note.md` in this repo is a single note deliberately built to trigger every `lint` rule at once. Import it into Bear (`File → Import → Files/Folders…`, or drag it onto Bear's note list), then run:

```bash
bearcli search "Bear Lint Test Note" --fields id,title
python3 bearkit.py lint -i <note-id>
```

Compare what Bear shows afterwards against the table above. (The stub-notes check isn't exercised by this fixture — a note with enough content to trigger every other rule can't also be an empty stub — so test it separately with a note that has only an H1 title and nothing else.)

## A note on safety

**Back up first.** Export your Bear library before running this on your real notes: Bear → File → Export Notes. Bear's built-in [version history](https://bear.app/faq/backup-restore/) (Pro) also lets you roll back individual notes, but a full export gives you a snapshot you can restore from without Bear.

Writes use bearcli's `--no-update-modified` flag, so fixed notes keep their original modification date and don't reorder your note list.

## Limitations

- Heuristic-based, not a full Markdown parser. Handles fenced code blocks, inline code spans, and YAML frontmatter (a `---` on line 1 with a matching closing `---`) as protected regions (aside from stripping blank lines inside frontmatter), but very unusual formatting may confuse a rule or two.
- A few `lint` rules are report-only by design (missing/duplicate H1, heading-level skips, stub notes, tag format, wiki-link problems), because auto-fixing them risks changing the note's actual structure or meaning.
- Locked/encrypted Bear notes are skipped automatically.
- `random count` silently clamps to the number of available notes rather than erroring if you ask for more than exist in scope.

## Upgrading from bear-lint

Old `#bear-lint`-tagged report notes from bear-lint v1 aren't recognized by bearkit's `#bearkit/*` self-exclusion, so they won't automatically stay out of scans. Search `#bear-lint` in Bear and delete them manually once you've confirmed you no longer need them.

## Changelog

See the [Releases page](https://github.com/i-am-fran/bearkit/releases) for what changed between versions.

## Issues

Found a bug or have a feature request? [Open a GitHub issue](https://github.com/i-am-fran/bearkit/issues) — pull requests aren't accepted, but issue reports are very welcome.

## License

MIT, see [LICENSE](LICENSE).

---

[Check out more of my projects 🚀](https://iamfran.com/tags/projects/)
