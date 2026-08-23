#!/usr/bin/env python3
"""Lexical tag classifier for blog drafts.

Scores a draft's text against the word-frequency profile of every existing
tag (built from posts already carrying that tag). Suggests the best-matching
existing tags, proposes a brand-new top-level tag when nothing fits well,
and separately flags parent tags that have grown large enough to be worth
splitting into a child tag. Writes the chosen tags into the draft's front
matter and regenerates _data/tags.yml.

Usage: python3 scripts/suggest_tags.py _drafts/my-post.md
       python3 scripts/suggest_tags.py _drafts/my-post.md --new-tag-threshold 0.08 --split-threshold 5
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
    return profiles, counts


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


def parent_of(hierarchy, tag):
    for parent, info in hierarchy.items():
        if tag in ((info or {}).get("children", []) or []):
            return parent
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("draft", type=Path)
    parser.add_argument("--new-tag-threshold", type=float, default=0.08,
                         help="below this best-match cosine similarity, propose a new top-level tag")
    parser.add_argument("--split-threshold", type=int, default=5,
                         help="post count (parent + children) at which a split candidate is flagged")
    args = parser.parse_args()

    if not args.draft.exists():
        sys.exit(f"no such file: {args.draft}")

    hierarchy = yaml.safe_load(TAG_HIERARCHY_PATH.read_text()) or {}
    posts = load_all_posts()
    profiles, counts = build_tag_profiles(posts, hierarchy)
    children_set = child_tags_of(hierarchy)

    draft_front_matter, draft_body = load_post(args.draft)
    draft_words = tokenize(draft_front_matter.get("title", ""), draft_body)

    scored = sorted(
        ((tag, cosine_similarity(draft_words, profile)) for tag, profile in profiles.items()),
        key=lambda t: t[1], reverse=True,
    )

    print(f"Scoring '{args.draft.name}' against {len(profiles)} known tag(s):\n")

    top_level_scores = [(t, s) for t, s in scored if t not in children_set]
    child_scores = {t: s for t, s in scored if t in children_set}

    for tag, score in top_level_scores[:8]:
        marker = " *" if score >= args.new_tag_threshold else ""
        print(f"  {tag:<20} {score:.3f}{marker}")
        for child in (hierarchy.get(tag, {}) or {}).get("children", []) or []:
            if child in child_scores:
                print(f"    └─ {child:<16} {child_scores[child]:.3f}")

    best_score = top_level_scores[0][1] if top_level_scores else 0.0
    new_tag_candidate = None
    if best_score < args.new_tag_threshold:
        background = Counter()
        for profile in profiles.values():
            background.update(profile)
        candidate_words = distinctive_words(draft_words, background)
        new_tag_candidate = "-".join(candidate_words[:2]) if candidate_words else None
        if new_tag_candidate:
            print(f"\nNo strong match against existing tags (best={best_score:.3f}).")
            print(f"Candidate new top-level tag: '{new_tag_candidate}' "
                  f"(distinctive words: {', '.join(candidate_words)})")

    print()
    for tag, score in top_level_scores:
        total = counts.get(tag, 0) + sum(
            counts.get(c, 0) for c in (hierarchy.get(tag, {}) or {}).get("children", []) or []
        )
        if total >= args.split_threshold and not (hierarchy.get(tag, {}) or {}).get("children"):
            tag_posts = [p for p in posts if tag in p["tags"]]
            merged = Counter()
            for p in tag_posts:
                merged.update(p["words"])
            words = distinctive_words(merged, Counter(), limit=8)
            print(f"Candidate for splitting '{tag}' ({total} posts) — "
                  f"frequent words: {', '.join(words)}")

    print()
    prompt = "Enter comma-separated tags to apply"
    if new_tag_candidate:
        prompt += f" (candidate new tag: {new_tag_candidate})"
    chosen_raw = input(f"{prompt}: ").strip()
    chosen = [t.strip() for t in chosen_raw.split(",") if t.strip()]

    if not chosen:
        print("No tags entered, leaving draft unchanged.")
        return

    draft_front_matter["tags"] = chosen
    new_text = "---\n" + yaml.safe_dump(draft_front_matter, sort_keys=False).strip() + "\n---\n" + draft_body
    args.draft.write_text(new_text)
    print(f"Wrote tags to {args.draft}: {chosen}")

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


if __name__ == "__main__":
    main()
