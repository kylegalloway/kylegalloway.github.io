# kylegalloway.github.io

Two things live in this repo:

- **`index.html`** at the root — a static landing page. Not part of Jekyll's
  templating (no front matter), so Jekyll copies it through untouched.
- **`/blog/`** — a small Jekyll blog: drafts, tags, pagination, RSS. Served at
  `https://kylegalloway.github.io/blog/`, linked from the landing page.

GitHub Pages builds the site natively (Jekyll) on push to `main` — no GitHub
Actions involved.

## Requirements

- Ruby **3.0+** (not the macOS system Ruby, which is 2.6.x and too old for
  current Jekyll/Liquid). Install a modern one via Homebrew:
  ```
  brew install ruby
  ```
  Then either add it to your `PATH` for this shell session:
  ```
  export PATH="/opt/homebrew/opt/ruby/bin:/opt/homebrew/lib/ruby/gems/4.0.0/bin:$PATH"
  ```
  or add that line to your `~/.zshrc` so it's always available. (Adjust the
  gem path segment, e.g. `4.0.0`, to whatever `ruby -v` reports after
  installing.)
- Bundler (`gem install bundler` if it's not already present).
- [`go-task`](https://taskfile.dev) (`brew install go-task`) — optional but
  the commands below assume it; run `task --list` to see everything it
  wraps. Not required if you'd rather run the underlying `bundle`/`python3`
  commands directly.

**Why this repo doesn't use the `github-pages` gem:** that meta-gem pins an
old Jekyll/Liquid that calls `String#tainted?`, which was removed in Ruby
3.2+ — it simply cannot run on any current Ruby. GitHub Pages' live build
uses its own pinned toolchain server-side regardless of what's in this
repo's `Gemfile`, so local dev instead depends directly on `jekyll` plus the
specific plugins (`jekyll-paginate`, `jekyll-seo-tag`, `jekyll-sitemap`,
`jekyll-feed`) — all on GitHub Pages' supported-plugins list, so the live
build stays compatible even though local dev runs a newer Jekyll.

## Local preview

```
task install
task serve
```
(equivalent to `bundle install` and `bundle exec jekyll serve --drafts`, if
you'd rather skip `go-task`)

Then open `http://localhost:4000/` (landing page) and
`http://localhost:4000/blog/` (blog). `--drafts` makes posts in `_drafts/`
visible locally; they're never included in the live build regardless.

To just build without serving (e.g. to inspect `_site/` output directly):
```
task build
```

## Task commands

`task --list` prints all of these with descriptions. All are one-liners
around the underlying `bundle`/`python3` commands, kept in `Taskfile.yml`
just so they don't need to be remembered/retyped.

| Command | Does |
|---|---|
| `task install` | `bundle install` |
| `task serve` | `bundle exec jekyll serve --drafts` |
| `task build` | `bundle exec jekyll build --drafts` |
| `task tag -- _drafts/my-post.md` | runs the tag classifier on a draft (see [Tagging](#tagging)) |
| `task retag -- [--include-drafts] [--dry-run]` | walks every post, re-suggesting tags one at a time (see [Retagging the whole blog](#retagging-the-whole-blog)) |
| `task clean` | removes `_site/`, `.jekyll-cache/`, `.jekyll-metadata` |

Things worth checking after any layout/config change, before pushing:
- `/` still serves the landing page untouched, with a working link to `/blog/`
- `/blog/` lists posts with excerpt, tags, and a "Read more" link
- `/blog/tags/` renders and its anchors work
- `view-source` on both `/` and `/blog/` — no `<script>` tags, CSS stays inlined
- `_site/feed.xml` and `_site/sitemap.xml` exist

## Writing and publishing a post

1. Create a draft:
   ```
   _drafts/my-new-post.md
   ```
   ```markdown
   ---
   title: "My New Post"
   ---

   Opening paragraph, shown as the excerpt on the blog index.

   <!--more-->

   Everything after this line only shows on the full post page.
   ```
   The `<!--more-->` line needs a **blank line before it** — kramdown only
   treats it as an invisible marker when it's its own paragraph; without the
   blank line it renders as literal visible text.

2. Get tag suggestions (see [Tagging](#tagging) below):
   ```
   task tag -- _drafts/my-new-post.md
   ```
   This writes a `tags:` list into the draft's front matter for you.

3. Preview it locally with `task serve` and check `/blog/`.

4. Publish by moving the file into `_posts/` with a date-prefixed filename:
   ```
   mv _drafts/my-new-post.md "_posts/$(date +%F)-my-new-post.md"
   ```
   The filename's leading `YYYY-MM-DD` is what Jekyll uses as the post date
   (feeding the `/blog/:year/:month/:day/:title/` permalink) — the
   front matter doesn't need an explicit `date:` unless you want to
   backdate/override it.

5. Commit and push to `main`. GitHub Pages rebuilds automatically.

### Writing from a phone

No mobile git workflow here by design — draft in the GitHub mobile app's
built-in file editor, or just jot it in Google Keep if it's easier away
from a keyboard. Either way, nothing gets committed from the phone. Once
back at the computer, pull the text in (paste it into a new file under
`_drafts/`, or `git pull` if it was already saved as a commit through the
GitHub app) and pick up the workflow above from tagging onward.

## Tagging

Tags are meant to start **generic** (`programming`, `kubernetes`,
`around-the-house`) and only gain more **specific child tags**
(`golang`, `python`) once a broad tag has enough posts under it to be
worth splitting — without ever having to word posts precisely, and
without breaking old links when a split happens later.

How it works:
- Tags are plain strings in a post's front matter `tags:` list. A post can
  carry both a broad and a specific tag at once, e.g.
  `tags: [programming, golang]` — the specific tag is additive, never a
  replacement, so the broad tag's listing never loses posts.
- `_data/tag_hierarchy.yml` is the one place the parent/child taxonomy is
  actually declared:
  ```yaml
  programming:
    children: [golang, python]
  kubernetes:
    children: []
  ```
  A tag not listed here is just a standalone top-level tag — the normal
  state early on, before anything's been split.
- `/blog/tags/` reads this file: each parent's section lists posts tagged
  with the parent **or any of its children**, with children noted
  underneath.

### Running the tag classifier

```
task tag -- _drafts/my-post.md
```
It's a small lexical classifier — no external services, nothing leaves your
machine. For every existing tag it builds a word-frequency profile from the
posts that already carry it, scores the draft against each profile by
cosine similarity, and:
- prints the best-matching existing tags (children nested under their parent)
- if nothing matches well, proposes a **new top-level tag** from the
  draft's most distinctive words — accept it, edit it, or ignore it
- separately flags any parent tag that's grown past a size threshold
  (default 5 posts) as a **candidate for splitting**, printing the words
  most distinctive to a sub-cluster of its posts as a hint for a child tag
  name

Then it prompts for the comma-separated tags to actually apply, writes them
into the draft's front matter, and regenerates `_data/tags.yml` (a flat
`tag: count` summary, useful for a quick glance at what exists).

Useful flags:
```
task tag -- _drafts/my-post.md --new-tag-threshold 0.08 --split-threshold 5
```
- `--new-tag-threshold` — lower it to make the classifier more willing to
  reuse an existing tag instead of proposing a new one; raise it to make
  new-tag proposals more frequent.
- `--split-threshold` — post count (parent + children combined) at which a
  parent gets flagged as a split candidate.

**Splitting a tag into a child, by hand:** when the script flags a
candidate, or whenever you decide one yourself, edit
`_data/tag_hierarchy.yml` directly:
```yaml
programming:
  children: [golang]
```
Nothing else needs to change — old posts keep working under `programming`
alone; only new (or manually revisited) posts need to start adding
`golang` too. The classifier picks up the new hierarchy automatically on
its next run, since it re-reads the file each time.

### Retagging the whole blog

`task tag` only ever looks at one file. To sweep every post — most useful
right after adding a new child tag, to find older posts under the parent
that should probably pick it up too — use:

```
task retag -- [--include-drafts] [--dry-run]
```

This walks `_posts/` (add `--include-drafts` to also cover `_drafts/`) one
post at a time, printing the same scoring output as the single-file mode
and prompting for each: press enter to leave a post's tags as they are, or
type a new comma-separated list to replace them. `--dry-run` prints every
post's suggestions without prompting or writing anything — good for a
quick read-only pass before committing to changes post by post.

Two things behave differently from single-file mode, both intentional:
- Each already-tagged post is scored with **its own words excluded** from
  the profiles of tags it already carries (leave-one-out) — otherwise
  every post would just trivially match itself at a near-perfect score.
- A brand-new child tag with **zero** posts under it yet has no vocabulary
  to score against, so it'll show up at `0.000` for everyone until you
  manually apply it to at least one clearly-on-topic post — after that,
  its profile exists and later posts in the same (or a future) `retag`
  run can start matching against it for real.

## Directory structure

```
index.html              landing page (root, untouched by Jekyll templating)
Taskfile.yml             `task` command shortcuts (install/serve/build/tag/clean)
_config.yml              Jekyll config — note paginate_path/permalink are
                          namespaced under /blog/ so they don't collide
                          with the root landing page
_layouts/                default.html (base) and post.html
blog/index.html          paginated blog home, served at /blog/
blog/tags/index.html     tag index, served at /blog/tags/
_posts/                  published posts (date-prefixed filenames)
_drafts/                 unpublished drafts — invisible on the live site
_data/tag_hierarchy.yml  hand-curated tag parent/child taxonomy
_data/tags.yml           generated summary (tag: count) — safe to regenerate
scripts/suggest_tags.py  local tag classifier CLI, never runs on the live site
```

## Rollback

The `archive/legacy-html` branch holds the repo's state from before the
blog was added, in case anything needs to be recovered.

## A note on AI-assistant files

`CLAUDE.md`, `AGENTS.md`, `MIGRATION_PLAN.md`, and `.claude/` are
gitignored — they're local planning/instruction files for AI coding
assistants and aren't meant to be pushed to this repo.
