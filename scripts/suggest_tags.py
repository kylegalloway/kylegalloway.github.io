#!/usr/bin/env python3
"""Lexical tag classifier for blog drafts and posts.

Scores a post's text against the word-frequency profile of every existing
tag (built from posts already carrying that tag). Suggests the best-matching
existing tags, proposes a brand-new top-level tag when nothing fits well,
and separately flags parent tags that have grown large enough to be worth
splitting into a child tag. Writes the chosen tags into the post's front
matter and regenerates _data/tags.yml.

Single-file mode: score and (optionally) retag one draft.
Bulk mode (--all): walk every post in _posts/ (and _drafts/ with
--include-drafts) one at a time, prompting for each — useful after adding a
new child tag in _data/tag_hierarchy.yml, to see which older posts might
deserve it too. Each already-tagged post is scored with its own words
excluded from its current tags' profiles first (leave-one-out), so it isn't
just trivially matching itself.

Usage:
  python3 scripts/suggest_tags.py _drafts/my-post.md
  python3 scripts/suggest_tags.py _drafts/my-post.md --new-tag-threshold 0.08 --split-threshold 5
  python3 scripts/suggest_tags.py --all
  python3 scripts/suggest_tags.py --all --include-drafts --dry-run
"""
import argparse
import math
import re
import sys
from collections import Counter
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
POSTS_DIRS = [REPO_ROOT / "_posts", REPO_ROOT / "_drafts"]
TAG_HIERARCHY_PATH = REPO_ROOT / "_data" / "tag_hierarchy.yml"
TAGS_YML_PATH = REPO_ROOT / "_data" / "tags.yml"

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "then", "else", "of", "to",
    "in", "on", "for", "with", "at", "by", "from", "up", "about", "into",
    "is", "are", "was", "were", "be", "been", "being", "this", "that",
    "these", "those", "it", "its", "as", "so", "than", "too", "very", "can",
    "will", "just", "not", "no", "do", "does", "did", "has", "have", "had",
    "i", "you", "he", "she", "we", "they", "my", "your", "our", "their",
    "what", "which", "who", "when", "where", "why", "how", "all", "some",
    "one", "also", "there", "here", "out", "over", "again", "more", "most",
}

FRONT_MATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
WORD_RE = re.compile(r"[a-z][a-z0-9']+")


def load_post(path: Path):
    text = path.read_text()
    match = FRONT_MATTER_RE.match(text)
    if not match:
        return {}, text
    front_matter = yaml.safe_load(match.group(1)) or {}
    return front_matter, match.group(2)


def tokenize(*texts: str) -> Counter:
    words = []
    for text in texts:
        # Strip the crudest markdown noise before tokenizing.
        stripped = re.sub(r"[`*_#>\[\]()!]", " ", text)
        words.extend(WORD_RE.findall(stripped.lower()))
    return Counter(w for w in words if w not in STOPWORDS and len(w) > 2)


def load_all_posts():
    posts = []
    for directory in POSTS_DIRS:
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.md")):
            front_matter, body = load_post(path)
            posts.append({
                "path": path,
                "tags": front_matter.get("tags", []) or [],
                "words": tokenize(front_matter.get("title", ""), body),
            })
    return posts


def build_tag_profiles(posts, hierarchy):
    """One word-frequency Counter per tag, built only from posts carrying
    that exact tag (a parent's profile excludes posts that only carry a
    child, so it doesn't drift toward one child's vocabulary)."""
    profiles = {}
    counts = Counter()
    for post in posts:
        for tag in post["tags"]:
            profiles.setdefault(tag, Counter()).update(post["words"])
            counts[tag] += 1
    for tag in hierarchy:
        profiles.setdefault(tag, Counter())
        counts.setdefault(tag, 0)
    for children in (info.get("children", []) or [] for info in hierarchy.values()):
        for child in children:
            profiles.setdefault(child, Counter())
            counts.setdefault(child, 0)
    return profiles, counts


def profiles_excluding(profiles, post):
    """Copy of profiles with `post`'s own words subtracted from any tag it
    already carries, so scoring an already-tagged post doesn't just measure
    how well it matches itself."""
    adjusted = {}
    for tag, profile in profiles.items():
        if tag in post["tags"]:
            trimmed = profile.copy()
            for word, count in post["words"].items():
                if word in trimmed:
                    trimmed[word] -= count
                    if trimmed[word] <= 0:
                        del trimmed[word]
            adjusted[tag] = trimmed
        else:
            adjusted[tag] = profile
    return adjusted


def cosine_similarity(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    dot = sum(a[w] * b[w] for w in common)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def child_tags_of(hierarchy):
    children = set()
    for tag, info in hierarchy.items():
        children.update((info or {}).get("children", []) or [])
    return children


def distinctive_words(words: Counter, background: Counter, limit=6):
    scored = []
    for word, count in words.items():
        bg = background.get(word, 0)
        scored.append((count / (1 + bg), word))
    scored.sort(reverse=True)
    return [w for _, w in scored[:limit]]


def print_split_candidates(hierarchy, counts, posts, threshold):
    for tag, total in counts.items():
        combined = total + sum(
            counts.get(c, 0) for c in (hierarchy.get(tag, {}) or {}).get("children", []) or []
        )
        if combined >= threshold and not (hierarchy.get(tag, {}) or {}).get("children"):
            tag_posts = [p for p in posts if tag in p["tags"]]
            merged = Counter()
            for p in tag_posts:
                merged.update(p["words"])
            words = distinctive_words(merged, Counter(), limit=8)
            print(f"Candidate for splitting '{tag}' ({combined} posts) — "
                  f"frequent words: {', '.join(words)}")


def score_post(path, front_matter, words, profiles, hierarchy, children_set, new_tag_threshold):
    """Return (top_level_scores, child_scores, new_tag_candidate)."""
    scored = sorted(
        ((tag, cosine_similarity(words, profile)) for tag, profile in profiles.items()),
        key=lambda t: t[1], reverse=True,
    )
    top_level_scores = [(t, s) for t, s in scored if t not in children_set]
    child_scores = {t: s for t, s in scored if t in children_set}

    print(f"Scoring '{path.name}' against {len(profiles)} known tag(s):\n")
    for tag, score in top_level_scores[:8]:
        marker = " *" if score >= new_tag_threshold else ""
        print(f"  {tag:<20} {score:.3f}{marker}")
        for child in (hierarchy.get(tag, {}) or {}).get("children", []) or []:
            if child in child_scores:
                print(f"    └─ {child:<16} {child_scores[child]:.3f}")

    best_score = top_level_scores[0][1] if top_level_scores else 0.0
    new_tag_candidate = None
    if best_score < new_tag_threshold:
        background = Counter()
        for profile in profiles.values():
            background.update(profile)
        candidate_words = distinctive_words(words, background)
        new_tag_candidate = "-".join(candidate_words[:2]) if candidate_words else None
        if new_tag_candidate:
            print(f"\nNo strong match against existing tags (best={best_score:.3f}).")
            print(f"Candidate new top-level tag: '{new_tag_candidate}' "
                  f"(distinctive words: {', '.join(candidate_words)})")

    return top_level_scores, child_scores, new_tag_candidate


def prompt_and_apply(path, front_matter, body, current_tags, new_tag_candidate, dry_run):
    print()
    prompt = "Enter comma-separated tags to apply"
    if current_tags:
        prompt += f" (blank = keep current: {', '.join(current_tags)})"
    elif new_tag_candidate:
        prompt += f" (candidate new tag: {new_tag_candidate})"

    if dry_run:
        print(f"[dry run] {prompt}: (skipped, not prompting)")
        return None

    chosen_raw = input(f"{prompt}: ").strip()
    chosen = [t.strip() for t in chosen_raw.split(",") if t.strip()]

    if not chosen:
        print("No tags entered, leaving unchanged.")
        return None

    front_matter["tags"] = chosen
    new_text = "---\n" + yaml.safe_dump(front_matter, sort_keys=False).strip() + "\n---\n" + body
    path.write_text(new_text)
    print(f"Wrote tags to {path}: {chosen}")
    return chosen


def update_hierarchy_and_tags_yml(hierarchy, children_set, chosen):
    for tag in chosen:
        if tag not in hierarchy and tag not in children_set:
            hierarchy[tag] = {"children": []}
            print(f"Added new top-level tag to {TAG_HIERARCHY_PATH.name}: {tag}")
    TAG_HIERARCHY_PATH.write_text(yaml.safe_dump(hierarchy, sort_keys=True) or "{}\n")

    posts = load_all_posts()
    final_counts = Counter()
    for post in posts:
        for tag in post["tags"]:
            final_counts[tag] += 1
    TAGS_YML_PATH.write_text(
        yaml.safe_dump(dict(sorted(final_counts.items())), sort_keys=False)
    )
    print(f"Regenerated {TAGS_YML_PATH.name}")


def run_single(args, hierarchy, posts, profiles, counts, children_set):
    if not args.draft.exists():
        sys.exit(f"no such file: {args.draft}")

    front_matter, body = load_post(args.draft)
    words = tokenize(front_matter.get("title", ""), body)

    top_level_scores, child_scores, new_tag_candidate = score_post(
        args.draft, front_matter, words, profiles, hierarchy, children_set, args.new_tag_threshold
    )
    print()
    print_split_candidates(hierarchy, counts, posts, args.split_threshold)

    chosen = prompt_and_apply(
        args.draft, front_matter, body, front_matter.get("tags", []) or [],
        new_tag_candidate, args.dry_run,
    )
    if chosen:
        update_hierarchy_and_tags_yml(hierarchy, children_set, chosen)


def run_bulk(args, hierarchy, posts, profiles, counts, children_set):
    targets = posts if args.include_drafts else [p for p in posts if "_posts" in p["path"].parts]
    if not targets:
        print("No posts to retag.")
        return

    print(f"Retagging {len(targets)} post(s){' (dry run)' if args.dry_run else ''}.\n")
    print_split_candidates(hierarchy, counts, posts, args.split_threshold)
    print()

    for i, post in enumerate(targets, 1):
        print(f"--- [{i}/{len(targets)}] {post['path'].relative_to(REPO_ROOT)} ---")
        front_matter, body = load_post(post["path"])
        adjusted_profiles = profiles_excluding(profiles, post)

        _, _, new_tag_candidate = score_post(
            post["path"], front_matter, post["words"], adjusted_profiles,
            hierarchy, children_set, args.new_tag_threshold,
        )
        chosen = prompt_and_apply(
            post["path"], front_matter, body, post["tags"], new_tag_candidate, args.dry_run,
        )
        if chosen:
            # Reflect the change immediately so later posts in this same run
            # score against the update (e.g. a freshly-added tag).
            post["tags"] = chosen
            profiles = build_tag_profiles(posts, hierarchy)[0]
            update_hierarchy_and_tags_yml(hierarchy, children_set, chosen)
            children_set = child_tags_of(hierarchy)
        print()


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("draft", type=Path, nargs="?",
                         help="a single draft/post to score and retag")
    parser.add_argument("--all", action="store_true",
                         help="retag every post in _posts/, one at a time, instead of a single file")
    parser.add_argument("--include-drafts", action="store_true",
                         help="with --all, also walk _drafts/")
    parser.add_argument("--dry-run", action="store_true",
                         help="print suggestions only, don't prompt or write anything")
    parser.add_argument("--new-tag-threshold", type=float, default=0.08,
                         help="below this best-match cosine similarity, propose a new top-level tag")
    parser.add_argument("--split-threshold", type=int, default=5,
                         help="post count (parent + children) at which a split candidate is flagged")
    args = parser.parse_args()

    if args.all and args.draft:
        sys.exit("pass either a single draft path or --all, not both")
    if not args.all and not args.draft:
        sys.exit("pass a draft path, or --all to retag every post")

    hierarchy = yaml.safe_load(TAG_HIERARCHY_PATH.read_text()) or {}
    posts = load_all_posts()
    profiles, counts = build_tag_profiles(posts, hierarchy)
    children_set = child_tags_of(hierarchy)

    if args.all:
        run_bulk(args, hierarchy, posts, profiles, counts, children_set)
    else:
        run_single(args, hierarchy, posts, profiles, counts, children_set)


if __name__ == "__main__":
    main()
