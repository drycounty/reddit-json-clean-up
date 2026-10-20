#!/usr/bin/env python3
"""
reddit_clean.py — strip a Reddit thread's JSON down to what carries meaning.

Input:  a saved .json file, a Reddit thread URL, or stdin.
Output: Markdown (default, good for reading / LLM context) or compact JSON.

Usage:
  python3 reddit_clean.py thread.json
  python3 reddit_clean.py "https://www.reddit.com/r/selfhosted/comments/abc123/some_title/"
  curl -s -A "cleaner/1.0" "<thread-url>.json" | python3 reddit_clean.py -
  python3 reddit_clean.py thread.json --format json --min-score 2 --max-depth 4 -o clean.json
"""
import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

DROP_AUTHORS = {"AutoModerator"}
DEAD_BODIES = {"[deleted]", "[removed]", ""}


def load(src):
    if src == "-":
        return json.load(sys.stdin)
    if src.startswith("http"):
        url = src.split("?")[0].rstrip("/")
        if not url.endswith(".json"):
            url += ".json"
        url += "?limit=500&raw_json=1"  # raw_json=1 avoids &amp; style escaping
        ua = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
        tries = [url, url.replace("://www.reddit.com", "://old.reddit.com", 1)]
        last = None
        for u in dict.fromkeys(tries):
            req = urllib.request.Request(u, headers={"User-Agent": ua, "Accept": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    return json.load(r)
            except urllib.error.HTTPError as e:
                last = e
        sys.exit(
            f"Reddit refused the request (HTTP {last.code}). It blocks most scripted fetches.\n"
            f"Workaround: open this in your browser, save the page as thread.json, then run\n"
            f"  python3 reddit_clean.py thread.json -o thread.md\n\n  {url}"
        )
    with open(src, encoding="utf-8") as f:
        return json.load(f)


def ts(utc):
    if not utc:
        return None
    return datetime.fromtimestamp(utc, tz=timezone.utc).strftime("%Y-%m-%d")


def clean_post(p):
    out = {
        "title": p.get("title"),
        "subreddit": p.get("subreddit"),
        "author": p.get("author"),
        "score": p.get("score"),
        "date": ts(p.get("created_utc")),
        "url": "https://www.reddit.com" + p.get("permalink", ""),
        "text": (p.get("selftext") or "").strip(),
    }
    link = p.get("url_overridden_by_dest")
    if link and "reddit.com" not in link:
        out["link"] = link
    return out


def clean_comments(children, args, depth=0, skipped=None):
    out = []
    for c in children or []:
        if c.get("kind") == "more":
            skipped["more"] += len(c.get("data", {}).get("children", []))
            continue
        if c.get("kind") != "t1":
            continue
        d = c["data"]
        body = (d.get("body") or "").strip()
        replies_raw = d.get("replies")
        kids = replies_raw["data"]["children"] if isinstance(replies_raw, dict) else []

        dead = body in DEAD_BODIES or d.get("author") in DROP_AUTHORS or d.get("stickied") and d.get("distinguished") == "moderator"
        low = args.min_score is not None and (d.get("score") or 0) < args.min_score
        too_deep = args.max_depth is not None and depth >= args.max_depth

        if too_deep:
            skipped["depth"] += 1
            continue

        replies = clean_comments(kids, args, depth + 1, skipped)

        if dead or low:
            skipped["dead" if dead else "low"] += 1
            # keep the branch alive if it has worthwhile replies; drop the husk
            out.extend(replies) if args.flatten_orphans else (
                out.append({"author": None, "score": None, "text": "[removed]", "replies": replies}) if replies else None
            )
            continue

        node = {
            "author": d.get("author"),
            "score": d.get("score"),
            "text": body,
        }
        if d.get("is_submitter"):
            node["op"] = True
        if replies:
            node["replies"] = replies
        out.append(node)

    if args.sort == "score":
        out.sort(key=lambda n: n.get("score") or 0, reverse=True)
    return out


def to_markdown(post, comments, skipped):
    lines = [f"# {post['title']}", ""]
    meta = f"r/{post['subreddit']} · u/{post['author']} · {post['score']} pts · {post['date']}"
    lines += [meta, post["url"], ""]
    if post.get("link"):
        lines += [f"Link: {post['link']}", ""]
    if post["text"]:
        lines += [post["text"], ""]
    lines += ["---", "## Comments", ""]

    def walk(nodes, depth):
        for n in nodes:
            indent = "  " * depth
            who = f"u/{n['author']}" + (" (OP)" if n.get("op") else "") if n["author"] else "[removed]"
            score = f" [{n['score']}]" if n["score"] is not None else ""
            text = n["text"].replace("\n", f"\n{indent}  ")
            lines.append(f"{indent}- **{who}**{score}: {text}")
            walk(n.get("replies", []), depth + 1)

    walk(comments, 0)
    lines += ["", f"_Dropped: {skipped['dead']} deleted/bot, {skipped['low']} low-score, "
                  f"{skipped['depth']} too deep, {skipped['more']} not loaded (collapsed 'more')._"]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Clean a Reddit thread JSON.")
    ap.add_argument("src", help="file path, thread URL, or - for stdin")
    ap.add_argument("--format", choices=["md", "json"], default="md")
    ap.add_argument("--min-score", type=int, default=None, help="drop comments below this score")
    ap.add_argument("--max-depth", type=int, default=None, help="drop replies nested deeper than this")
    ap.add_argument("--sort", choices=["thread", "score"], default="thread")
    ap.add_argument("--flatten-orphans", action="store_true",
                    help="promote replies of removed comments up a level instead of keeping a [removed] stub")
    ap.add_argument("-o", "--out", help="write to file instead of stdout")
    args = ap.parse_args()

    data = load(args.src)
    if not (isinstance(data, list) and len(data) >= 2):
        sys.exit("Doesn't look like a Reddit thread JSON (expected a 2-item list).")

    post = clean_post(data[0]["data"]["children"][0]["data"])
    skipped = {"dead": 0, "low": 0, "depth": 0, "more": 0}
    comments = clean_comments(data[1]["data"]["children"], args, 0, skipped)

    if args.format == "json":
        result = json.dumps({"post": post, "comments": comments, "dropped": skipped},
                            ensure_ascii=False, indent=1)
    else:
        result = to_markdown(post, comments, skipped)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(result)
    else:
        print(result)


if __name__ == "__main__":
    main()
