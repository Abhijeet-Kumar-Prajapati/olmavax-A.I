"""
Olmavax Agent - Internet tools
=============================
Search, fetch, read and learn from the web, plus YouTube transcripts so the
agent can study from video the same way a person would.

Every page that arrives from the internet is passed through the security
scanner first.  Untrusted page text is stored as *reference material* and is
never treated as instructions - that is the whole point of the sanitize step.
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import PATHS, ensure_dirs
from ..logger import log_warn
from ..security import get_security
from ..utils import (
    domain_of,
    extract_title,
    html_to_text,
    http_get,
    is_url,
    net_available,
    truncate,
)
from . import tool

SEC = get_security()
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)


def _online() -> bool:
    return net_available()


# --------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------

DDG_LITE = "https://lite.duckduckgo.com/lite/?q={query}"
WIKI_API = "https://en.wikipedia.org/w/api.php?action=query&list=search&format=json&srlimit=6&srsearch={query}"
WIKI_PAGE = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
DDG_HTML_RESULT = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>', re.S
)


def _ddg_search(query: str, limit: int) -> List[Dict[str, str]]:
    url = DDG_LITE.format(query=urllib.parse.quote_plus(query))
    status, html = http_get(url, headers={"User-Agent": USER_AGENT})
    if status != 200 or not html:
        return []

    results: List[Dict[str, str]] = []
    # lite layout: links contain the target in the href
    for match in re.finditer(r'href="(https?://[^"]+)"[^>]*>(.+?)</a>', html, re.S):
        link, title = match.group(1), re.sub(r"<[^>]+>", "", match.group(2)).strip()
        if "duckduckgo.com" in link:
            continue
        if not title:
            continue
        results.append({"title": title, "url": link, "domain": domain_of(link)})
        if len(results) >= limit:
            break
    return results


@tool("web.search", "Search the internet and return ranked results",
      capabilities=["net.fetch"], risk=0.20, tags=["web", "research"])
def web_search(query: str, limit: int = 6) -> Dict[str, Any]:
    if not query.strip():
        return {"ok": False, "error": "empty query"}
    if not _online():
        return {"ok": False, "error": "no internet connection right now", "results": []}

    results = _ddg_search(query, limit)
    if not results:
        # Wikipedia fallback keeps research useful with no scraping allowed
        status, body = http_get(
            WIKI_API.format(query=urllib.parse.quote_plus(query)), headers={"User-Agent": USER_AGENT}
        )
        if status == 200 and body:
            try:
                for item in json.loads(body).get("query", {}).get("search", []):
                    title = item.get("title", "")
                    results.append(
                        {
                            "title": title,
                            "url": f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}",
                            "domain": "wikipedia.org",
                            "snippet": re.sub(r"<[^>]+>", "", item.get("snippet", "")),
                        }
                    )
            except json.JSONDecodeError:
                pass
    return {"ok": bool(results), "query": query, "count": len(results), "results": results}


@tool("web.fetch", "Download a page and return clean readable text",
      capabilities=["net.fetch"], risk=0.30, tags=["web", "read"])
def web_fetch(url: str, max_chars: int = 12000) -> Dict[str, Any]:
    if not is_url(url):
        return {"ok": False, "error": "that is not a valid http(s) address"}

    status, raw = http_get(url, headers={"User-Agent": USER_AGENT}, timeout=25)
    if status != 200 or not raw:
        return {"ok": False, "status": status, "error": "could not read that page"}

    text = html_to_text(raw)
    scan = SEC.scan_text(text)
    return {
        "ok": True,
        "url": url,
        "title": extract_title(raw),
        "chars": len(text),
        "safety": scan["verdict"],
        "content": text[:max_chars],
    }


@tool("web.wikipedia", "Quick summary from Wikipedia",
      capabilities=["net.fetch"], risk=0.15, tags=["web", "research"])
def wikipedia(topic: str) -> Dict[str, Any]:
    title = urllib.parse.quote(topic.strip().replace(" ", "_"), safe="")
    status, body = http_get(
        WIKI_PAGE.format(title=title), headers={"User-Agent": USER_AGENT}
    )
    if status != 200 or not body:
        return {"ok": False, "error": f"no Wikipedia article for '{topic}'"}
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return {"ok": False, "error": "unexpected response from Wikipedia"}
    return {
        "ok": True,
        "title": data.get("title", topic),
        "summary": data.get("extract", ""),
        "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
    }


# --------------------------------------------------------------------------
# YouTube - learning from video
# --------------------------------------------------------------------------

TIMEDTEXT_LANGS = ("en", "hi", "en-US", "hi-IN")


def _youtube_transcript(video_id: str, langs=TIMEDTEXT_LANGS) -> List[Dict[str, str]]:
    """
    Pull the caption track without an API key.

    Fetches the watch page, reads ``captionTracks`` out of the player
    response, downloads the timed-text XML and flattens it into cues.
    """
    watch = f"https://www.youtube.com/watch?v={video_id}"
    status, html = http_get(watch, headers={"User-Agent": USER_AGENT}, timeout=25)
    if status != 200 or "captionTracks" not in html:
        return []

    match = re.search(r'"captionTracks":(\[.*?\])', html, re.S)
    if not match:
        return []
    try:
        tracks = json.loads(match.group(1).replace("\\u0026", "&"))
    except json.JSONDecodeError:
        return []

    chosen = None
    for lang in langs:
        for track in tracks:
            if track.get("languageCode", "").startswith(lang):
                chosen = track
                break
        if chosen:
            break
    if not chosen:
        return []

    base = chosen.get("baseUrl", "")
    if not base:
        return []
    status, xml = http_get(f"{base}&fmt=json3", headers={"User-Agent": USER_AGENT}, timeout=25)
    if status != 200 or not xml:
        status, xml = http_get(base, headers={"User-Agent": USER_AGENT}, timeout=25)
    if status != 200 or not xml:
        return []

    cues: List[Dict[str, str]] = []
    try:
        data = json.loads(xml)
        for event in data.get("events", []):
            text = "".join(seg.get("utf8", "") for seg in event.get("segs", []))
            text = text.replace("\n", " ").strip()
            if text:
                cues.append({"start": event.get("tStartMs", 0) // 1000, "text": text})
    except json.JSONDecodeError:
        for seg in re.findall(r"<text[^>]*>(.*?)</text>", xml, re.S):
            clean = re.sub(r"&#39;|&#34;|&quot;|&amp;", "'", seg).strip()
            if clean:
                cues.append({"start": 0, "text": clean})
    return cues


@tool("web.youtube_info", "Title, channel and duration of a YouTube video",
      capabilities=["net.fetch"], risk=0.15, tags=["web", "youtube"])
def youtube_info(url_or_id: str) -> Dict[str, Any]:
    video_id = _video_id(url_or_id)
    if not video_id:
        return {"ok": False, "error": "could not find a video id in that link"}
    status, html = http_get(
        f"https://www.youtube.com/watch?v={video_id}", headers={"User-Agent": USER_AGENT}
    )
    if status != 200:
        return {"ok": False, "error": f"could not load the video page ({status})"}
    title = _meta(html, "title") or ""
    author = _meta(html, "author") or ""
    length = _meta(html, "lengthSeconds") or ""
    return {
        "ok": True,
        "video_id": video_id,
        "title": title,
        "channel": author,
        "length_seconds": int(length) if length.isdigit() else None,
        "url": f"https://youtu.be/{video_id}",
    }


@tool("web.youtube_learn", "Read a YouTube video's captions and store them as study notes",
      capabilities=["net.fetch", "memory.write"], risk=0.25, tags=["web", "youtube", "learn"])
def youtube_learn(url_or_id: str, topic: str = "", store: bool = True) -> Dict[str, Any]:
    """
    Watch a video the way you would: pull the transcript, clean it up,
    summarise it into memory so the agent can answer about it later.
    """
    video_id = _video_id(url_or_id)
    if not video_id:
        return {"ok": False, "error": "could not find a video id in that link"}

    cues = _youtube_transcript(video_id)
    if not cues:
        return {
            "ok": False,
            "error": "no captions available for that video (some videos have none)",
            "video_id": video_id,
        }

    transcript = " ".join(c["text"] for c in cues)
    info = youtube_info(video_id)
    words = len(transcript.split())

    summary = _summarize(transcript, cues)
    stored = None
    if store:
        from ..memory import get_memory

        label = topic or (info.get("title") if info.get("ok") else video_id)
        stored = get_memory().add(
            f"YouTube study notes - {label}\n\n{summary}\n\nKey transcript excerpt: "
            f"{truncate(transcript, 1200)}",
            kind="knowledge",
            tags=["youtube", "transcript", str(video_id)],
            importance=0.55,
            source=f"youtube:{video_id}",
            meta={"video_id": video_id, "url": f"https://youtu.be/{video_id}", "words": words},
        )

    return {
        "ok": True,
        "video_id": video_id,
        "title": info.get("title") if info.get("ok") else "",
        "channel": info.get("channel") if info.get("ok") else "",
        "cues": len(cues),
        "words": words,
        "summary": summary,
        "stored": bool(stored),
        "transcript_preview": truncate(transcript, 600),
    }


def _video_id(value: str) -> str:
    value = (value or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        return value
    patterns = [
        r"(?:v=|youtu\.be/|/embed/|/shorts/)([A-Za-z0-9_-]{11})",
        r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{6,})",
    ]
    for pattern in patterns:
        match = re.search(pattern, value)
        if match:
            return match.group(1)
    return ""


def _meta(html: str, key: str) -> str:
    patterns = {
        "title": [r'<meta name="title" content="([^"]+)"', r'"title":"([^"]{3,120})"'],
        "author": [r'"author":"([^"]{2,80})"', r'<link itemprop="name" content="([^"]+)"'],
        "lengthSeconds": [r'"lengthSeconds":"(\d+)"'],
    }
    for pattern in patterns.get(key, []):
        match = re.search(pattern, html)
        if match:
            return match.group(1)
    return ""


def _summarize(transcript: str, cues: List[Dict[str, str]]) -> str:
    """
    Extractive summary: score sentences by cue frequency and keep the best.

    No model needed, so video learning works with zero API keys.
    """
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", transcript) if len(s.strip()) > 40]
    if not sentences:
        return truncate(transcript, 700)
    if len(sentences) <= 5:
        return " ".join(sentences)

    words = re.findall(r"[a-zA-Z]{4,}", transcript.lower())
    stop = {
        "this", "that", "with", "from", "they", "have", "been", "were", "will",
        "what", "your", "about", "there", "their", "would", "could", "just",
        "like", "some", "more", "than", "then", "them", "these", "those", "also",
        "very", "here", "when", "where", "which", "while", "because", "going",
        "know", "think", "people", "video", "channel", "subscribe",
    }
    frequency: Dict[str, int] = {}
    for word in words:
        if word not in stop:
            frequency[word] = frequency.get(word, 0) + 1

    scored = []
    for index, sentence in enumerate(sentences):
        tokens = [w for w in re.findall(r"[a-zA-Z]{4,}", sentence.lower()) if w not in stop]
        score = sum(frequency.get(t, 0) for t in tokens) / (len(tokens) ** 0.5 or 1)
        position_bonus = 1.2 if index < 3 else 1.0
        scored.append((score * position_bonus, index, sentence))
    scored.sort(reverse=True)
    keep = sorted(scored[:6], key=lambda item: item[1])
    return " ".join(item[2] for item in keep)


# --------------------------------------------------------------------------
# Learning
# --------------------------------------------------------------------------


@tool("web.learn", "Study a topic online and store notes in permanent memory",
      capabilities=["net.fetch", "memory.write"], risk=0.30, tags=["web", "learn"])
def learn_topic(topic: str, depth: int = 3) -> Dict[str, Any]:
    """
    Build a mini curriculum on any topic from documentation and Wikipedia,
    then remember it.  Restricted to trusted documentation domains by
    default so the agent studies real sources.
    """
    from ..config import get_config

    cfg = get_config()
    if not _online():
        return {"ok": False, "error": "no internet connection right now"}

    pages: List[Dict[str, Any]] = []
    search = web_search(f"{topic} tutorial documentation", limit=max(2, depth))

    for result in search.get("results", [])[: max(2, depth)]:
        domain = result.get("domain", "")
        if cfg.learning.allowed_learn_domains and not any(
            domain.endswith(d) or d in domain for d in cfg.learning.allowed_learn_domains
        ):
            continue
        page = web_fetch(result["url"], max_chars=8000)
        if page.get("ok"):
            scan = SEC.scan_text(page["content"])
            pages.append(
                {
                    "title": page.get("title") or result.get("title", ""),
                    "url": result["url"],
                    "domain": domain,
                    "safety": scan["verdict"],
                    "notes": truncate(scan["clean_text"], 2500),
                }
            )

    wiki = wikipedia(topic)
    if wiki.get("ok"):
        pages.append(
            {
                "title": wiki["title"],
                "url": wiki["url"],
                "domain": "wikipedia.org",
                "safety": "clean",
                "notes": wiki["summary"],
            }
        )

    if not pages:
        return {"ok": False, "error": "no usable sources found", "topic": topic}

    digest = f"# {topic}\n\n" + "\n\n".join(
        f"## {p['title']}\nSource: {p['url']}\n{p['notes']}" for p in pages
    )

    from ..memory import get_memory

    stored = get_memory().add(
        digest, kind="knowledge", tags=["learned", topic.lower()[:30]],
        importance=0.6, source="internet",
        meta={"topic": topic, "pages": len(pages)},
    )

    ensure_dirs()
    curriculum_file = PATHS["curriculum"] / f"{topic[:40].replace(' ', '_')}.md"
    try:
        curriculum_file.write_text(digest, encoding="utf-8")
    except OSError as exc:
        log_warn(f"could not write curriculum file: {exc}", "learn")

    return {
        "ok": True,
        "topic": topic,
        "pages": len(pages),
        "sources": [p["url"] for p in pages],
        "saved_to": str(curriculum_file),
        "remembered": bool(stored),
        "preview": truncate(digest, 800),
    }


@tool("web.online", "Check whether the machine has internet access",
      capabilities=["net.fetch"], risk=0.05, tags=["web", "system"])
def online_check() -> Dict[str, bool]:
    return {"online": _online()}


# --------------------------------------------------------------------------
# Saved pages
# --------------------------------------------------------------------------


@tool("web.library_add", "Save a page to the personal library",
      capabilities=["net.fetch", "files.write"], risk=0.25, tags=["library", "web"])
def library_add(url: str, title: str = "") -> Dict[str, Any]:
    page = web_fetch(url, max_chars=60000)
    if not page.get("ok"):
        return page
    ensure_dirs()
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", (title or page.get("title") or url))[:60].strip("-")
    target = PATHS["library"] / f"{slug or 'page'}.md"
    body = f"# {page.get('title') or slug}\n\nSource: {url}\nFetched: {time.strftime('%Y-%m-%d %H:%M')}\n\n{page['content']}\n"
    target.write_text(body, encoding="utf-8")

    from ..memory import get_memory

    get_memory().add(
        f"Library page saved: {page.get('title') or slug} from {url}",
        kind="reference", tags=["library", slug[:20]], importance=0.35, source=url,
    )
    return {"ok": True, "path": str(target), "title": page.get("title")}


@tool("web.library_list", "List everything in the personal library",
      capabilities=["files.read"], risk=0.10, tags=["library"])
def library_list(limit: int = 100) -> List[Dict[str, Any]]:
    ensure_dirs()
    items = []
    for item in sorted(PATHS["library"].glob("*.md"))[:limit]:
        try:
            size = item.stat().st_size
        except OSError:
            size = 0
        items.append({"name": item.name, "size_kb": round(size / 1024, 1)})
    return items