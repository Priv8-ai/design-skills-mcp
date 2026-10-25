"""
Design/UI Skills MCP Server
============================
Serves a curated pack of 274 design / UI/UX / frontend skills from a zip archive,
plus the UIUX Research Atlas dataset (400+ references, images, palettes).

Self-contained: the only data dependency is data/skills-pack.zip (79MB), read
in place — no extraction step. Binary assets (images, pptx) are unpacked to a
cache dir on first access.

Tools
  search_skills      full-text search across all SKILL.md + references
  get_skill          full skill content (SKILL.md, optionally bundled references)
  list_skills        browse the catalog by source/category
  get_skill_file     read any single file inside the pack
  search_atlas       query the UI/UX research atlas (101 evidence references)
  get_atlas_palette  palette data for an atlas reference
  get_skill_stats    pack statistics
  download_skill_export  URL to a downloadable markdown bundle of a skill

Resources (mcp://skills/...)
  mcp://skills/catalog          full catalog JSON
  mcp://skills/index            INDEX.md
  mcp://skills/{name}/SKILL.md  every skill's main file as a resource
"""
from __future__ import annotations

import io
import json
import os
import re
import zipfile
from collections import defaultdict
from functools import lru_cache
from pathlib import PurePosixPath

from fastmcp import FastMCP

# ---------------------------------------------------------------------------
# zip access layer
# ---------------------------------------------------------------------------

ZIP_PATH = os.environ.get(
    "SKILLS_PACK_ZIP",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "skills-pack.zip"),
)
CACHE_DIR = os.environ.get(
    "SKILLS_CACHE_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache"),
)


@lru_cache(maxsize=1)
def _archive() -> zipfile.ZipFile:
    if not os.path.exists(ZIP_PATH):
        raise FileNotFoundError(f"skills pack not found: {ZIP_PATH}")
    return zipfile.ZipFile(ZIP_PATH)


@lru_cache(maxsize=None)
def _names() -> list[str]:
    return [i.filename for i in _archive().infolist() if not i.is_dir()]


@lru_cache(maxsize=None)
def _name_set() -> frozenset[str]:
    return frozenset(_names())


def _read(name: str) -> bytes:
    return _archive().read(name)


def _read_text(name: str) -> str:
    return _read(name).decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# catalog: skills, atlas, tags
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _catalog() -> dict:
    """Parse skill_pack into an in-memory catalog."""
    skills = {}
    prefix = "skill_pack/skills/"
    for name in _names():
        if not name.startswith(prefix) or not name.endswith("SKILL.md"):
            continue
        skill_name = name[len(prefix):].split("/")[0]
        skill_md_path = name
        # files under this skill
        base = f"{prefix}{skill_name}/"
        files = [n for n in _names() if n.startswith(base) and n != skill_md_path]
        # infer category from skill name conventions
        category = _classify(skill_name, _read_text(skill_md_path))
        skills[skill_name] = {
            "name": skill_name,
            "category": category,
            "skill_md": skill_md_path,
            "files": files,
            "file_count": len(files) + 1,
            "total_bytes": sum(_archive().getinfo(n).file_size for n in files)
            + _archive().getinfo(skill_md_path).file_size,
            "description": _extract_description(_read_text(skill_md_path)),
            "references": [f for f in files if "/references/" in f],
            "scripts": [f for f in files if "/scripts/" in f],
            "assets": [
                f for f in files
                if "/references/" not in f and "/scripts/" not in f
            ],
        }
    # atlas references
    atlas_refs = []
    for name in _names():
        if "/atlas/" in name and name.endswith(".json"):
            pass
    atlas = _load_atlas()
    return {
        "skills": skills,
        "atlas": atlas,
        "pack_file_count": len(_names()),
        "pack_bytes": sum(i.file_size for i in _archive().infolist()),
    }


def _classify(name: str, skill_md: str) -> str:
    n = name.lower()
    head = skill_md[:1500].lower()
    if any(k in n for k in ("ui", "ux", "design")) or "design" in head[:400]:
        return "design"
    if "front" in n or "react" in n or "css" in n or "web" in n:
        return "frontend"
    if any(k in n for k in ("figma", "canvas", "pixel", "art", "theme", "skin", "icon")):
        return "visual"
    return "product"


def _extract_description(skill_md_text: str) -> str:
    fm = re.match(r"\A---\s*\n(.*?)\n---", skill_md_text, re.S)
    if not fm:
        return ""
    body = fm.group(1)
    m = re.search(r"^description:\s*(.+?)$", body, re.M)
    if not m:
        return ""
    desc = m.group(1).strip()
    # YAML block scalars / multi-line: cut at next key
    desc = re.split(r"\n[a-z_-]+:", desc)[0]
    return desc[:400]


@lru_cache(maxsize=1)
def _atlas_catalogs() -> list[dict]:
    """Parse the atlas per-platform catalogs (web / mobile / motion)."""
    out = []
    for name in _names():
        m = re.match(r"skill_pack/atlas/data/raw/([a-z_]+)/catalog\.json$", name)
        if not m:
            continue
        try:
            data = json.loads(_read_text(name))
        except (json.JSONDecodeError, OSError):
            continue
        items = data.get("items", []) if isinstance(data, dict) else data
        for it in items:
            it["_platform_group"] = m.group(1)
        out.extend(items)
    return out


def _load_atlas() -> list[dict]:
    return _atlas_catalogs()


# ---------------------------------------------------------------------------
# search index: tokenize SKILL.md + reference markdown
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _search_index() -> dict:
    index = defaultdict(dict)   # term -> {skill_name: count}
    docs = {}                   # skill_name -> raw combined text
    for sname, skill in _catalog()["skills"].items():
        text = _read_text(skill["skill_md"])
        for ref in skill["references"]:
            if ref.endswith((".md", ".txt")):
                try:
                    text += "\n" + _read_text(ref)
                    if len(text) > 400_000:
                        break
                    index  # no-op
                except OSError:
                    pass
        docs[sname] = text
        for term in set(_tokenize(text[:200_000])):
            index[term][sname] = index[term].get(sname, 0) + 1
    return {"index": dict(index), "docs": docs}


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_]{3,}", text.lower())


# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "design-skills",
    instructions=(
        "Curated pack of 274 design/UI/UX/frontend skills + the UIUX Research Atlas. "
        "Start with search_skills or list_skills, then get_skill for full content."
    ),
)


@mcp.tool
def search_skills(query: str, limit: int = 10, category: str | None = None) -> str:
    """Full-text search across every SKILL.md and reference doc in the pack.

    Args:
        query: search terms (space-separated, OR semantics, prefix matching)
        limit: max results (default 10)
        category: optional filter — design | frontend | visual | product
    """
    terms = [t for t in _tokenize(query) if len(t) >= 3]
    if not terms:
        return json.dumps({"error": "query too short"}, ensure_ascii=False)
    index = _search_index()["index"]
    scores: dict[str, int] = defaultdict(int)
    matched_terms = defaultdict(set)
    for t in terms:
        for term, postings in index.items():
            if t in term:  # substring match for recall
                for sname, cnt in postings.items():
                    scores[sname] += cnt
                    matched_terms[sname].add(term)
    if category:
        cat = category.lower()
        scores = {s: sc for s, sc in scores.items()
                  if _catalog()["skills"].get(s, {}).get("category") == cat}
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])[:limit]
    results = []
    for sname, score in ranked:
        sk = _catalog()["skills"][sname]
        snippet = _snippet(_search_index()["docs"][sname], terms)
        results.append({
            "name": sname,
            "score": score,
            "category": sk["category"],
            "matched": sorted(matched_terms[sname])[:8],
            "description": sk["description"][:200],
            "snippet": snippet,
        })
    return json.dumps({"query": query, "count": len(results), "results": results},
                      ensure_ascii=False)


def _snippet(doc: str, terms: list[str]) -> str:
    low = doc.lower()
    for t in terms:
        i = low.find(t)
        if i >= 0:
            start = max(0, i - 120)
            return doc[start:i + 260].replace("\n", " ").strip()
    return doc[:200].replace("\n", " ").strip()


@mcp.tool
def list_skills(category: str | None = None, limit: int = 100) -> str:
    """List skills in the pack, optionally filtered by category.

    Args:
        category: design | frontend | visual | product (omit for all)
        limit: max entries returned
    """
    skills = _catalog()["skills"]
    rows = []
    for sname, sk in sorted(skills.items()):
        if category and sk["category"] != category.lower():
            continue
        rows.append({
            "name": sname,
            "category": sk["category"],
            "files": sk["file_count"],
            "bytes": sk["total_bytes"],
            "description": sk["description"][:160],
        })
    rows = rows[:limit]
    by_cat = defaultdict(int)
    for sk in skills.values():
        by_cat[sk["category"]] += 1
    return json.dumps({
        "total": len(skills),
        "categories": dict(by_cat),
        "returned": len(rows),
        "skills": rows,
    }, ensure_ascii=False)


@mcp.tool
def get_skill(name: str, include_references: bool = False) -> str:
    """Read the full SKILL.md for a skill by name.

    Args:
        name: skill name (see list_skills / search_skills)
        include_references: also inline all reference docs (can be large)
    """
    sk = _catalog()["skills"].get(name)
    if not sk:
        # fuzzy: case-insensitive / substring
        cands = [s for s in _catalog()["skills"] if name.lower() in s.lower()]
        if len(cands) == 1:
            sk = _catalog()["skills"][cands[0]]
        elif cands:
            return json.dumps({"error": f"ambiguous name; candidates: {cands[:10]}"},
                              ensure_ascii=False)
        else:
            return json.dumps({"error": f"unknown skill '{name}'"}, ensure_ascii=False)
    out = {
        "name": sk["name"],
        "category": sk["category"],
        "description": sk["description"],
        "content": _read_text(sk["skill_md"]),
    }
    if include_references:
        refs = {}
        for ref in sk["references"]:
            if ref.endswith((".md", ".txt", ".json")):
                try:
                    refs[ref.split("/skills/", 1)[1]] = _read_text(ref)[:50_000]
                except OSError:
                    pass
        out["references"] = refs
    return json.dumps(out, ensure_ascii=False)


@mcp.tool
def get_skill_file(path: str) -> str:
    """Read a single file from inside the pack by zip path.

    Paths look like skill_pack/skills/<name>/scripts/foo.py. Text files are
    returned as string; binaries (images/fonts/pptx) are extracted to the
    local cache dir and the absolute path is returned.
    """
    path = path.strip("/")
    if not path.startswith("skill_pack/"):
        path = "skill_pack/" + path
    if path not in _name_set():
        return json.dumps({"error": f"not found: {path}"}, ensure_ascii=False)
    ext = os.path.splitext(path)[1].lower()
    if ext in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".ttf", ".otf",
               ".pptx", ".docx", ".xlsx", ".pdf", ".woff", ".woff2", ".pb"}:
        # binary: unpack to cache
        dest = os.path.join(CACHE_DIR, path.removeprefix("skill_pack/"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if not os.path.exists(dest):
            with open(dest, "wb") as f:
                f.write(_read(path))
        return json.dumps({"binary": True, "path": dest, "bytes": os.path.getsize(dest)},
                          ensure_ascii=False)
    return json.dumps({"binary": False, "path": path,
                       "content": _read_text(path)}, ensure_ascii=False)


@mcp.tool
def search_atlas(query: str, limit: int = 8, group: str | None = None) -> str:
    """Search the UIUX Research Atlas: curated web/mobile/motion design references
    each with dominant color palettes, typography notes, and layout analysis.
    These are aesthetic hypotheses for inspiration, never proof.

    Args:
        query: keywords e.g. 'dashboard', '3d', 'fitness', 'dark'
        limit: max results
        group: optional atlas group filter — web | mobile | motion
    """
    docs = _atlas_catalogs()
    terms = [t for t in _tokenize(query) if len(t) >= 3]
    scored = []
    for ref in docs:
        if group and ref.get("_platform_group") != group.lower():
            continue
        blob = json.dumps(ref, ensure_ascii=False).lower()
        sc = sum(blob.count(t) for t in terms)
        if sc:
            scored.append((sc, ref))
    scored.sort(key=lambda x: -x[0])
    out = []
    for sc, ref in scored[:limit]:
        out.append({
            "score": sc,
            "id": ref.get("id"),
            "title": ref.get("title"),
            "group": ref.get("_platform_group"),
            "platform": ref.get("platform"),
            "category": ref.get("category"),
            "colors": ref.get("dominant_colors", [])[:5],
            "live_url": ref.get("live_url"),
        })
    return json.dumps({"query": query, "count": len(out), "results": out}, ensure_ascii=False)


@mcp.tool
def get_atlas_entry(entry_id: str) -> str:
    """Full detail for one atlas reference: palette hexes, typography rationale,
    layout analysis, key components, and both live/local image paths.

    Args:
        entry_id: atlas id e.g. 'web-001' (see search_atlas)
    """
    for ref in _atlas_catalogs():
        if ref.get("id") == entry_id:
            clean = {k: v for k, v in ref.items() if not k.startswith("_")}
            group = ref.get("_platform_group", "web")
            # field name differs per catalog: local_image (web) vs local_image_paths (mobile/motion)
            local = ref.get("local_image") or (ref.get("local_image_paths") or [None])[0]
            if local:
                base = os.path.normpath(local).lstrip("/")
                guess = f"skill_pack/atlas/assets/{group}/{base}"
                if guess in _name_set():
                    clean["pack_path"] = guess
                else:
                    # images may have been re-encoded (.png->.jpg); match by stem
                    stem = os.path.splitext(os.path.basename(base))[0]
                    for n in _name_set():
                        if n.endswith(f"/{stem}.jpg") or n.endswith(f"/{stem}.png") \
                                or n.endswith(f"/{stem}.webp"):
                            clean["pack_path"] = n
                            break
            clean["pack_extraction_note"] = (
                "use get_skill_file with pack_path to extract the image"
            )
            return json.dumps(clean, ensure_ascii=False)
    return json.dumps({"error": f"unknown atlas entry '{entry_id}'"}, ensure_ascii=False)


@mcp.tool
def get_skill_stats() -> str:
    """Pack statistics: skill count per category, total files, overall size."""
    c = _catalog()
    by_cat = defaultdict(int)
    for sk in c["skills"].values():
        by_cat[sk["category"]] += 1
    return json.dumps({
        "skills": len(c["skills"]),
        "categories": dict(by_cat),
        "files": c["pack_file_count"],
        "pack_mb": round(c["pack_bytes"] / 1e6, 1),
        "atlas_refs": len(c["atlas"]),
    }, ensure_ascii=False)


@mcp.tool
def download_skill_export(name: str) -> str:
    """Generate a standalone markdown bundle (skill + references) and return a
    local file:// path the user can open/share. Good for handoff to other tools.

    Args:
        name: skill name
    """
    sk = _catalog()["skills"].get(name)
    if not sk:
        return json.dumps({"error": f"unknown skill '{name}'"}, ensure_ascii=False)
    dest_dir = os.path.join(CACHE_DIR, "exports")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, f"{name}.md")
    parts = [f"# {name}\n", _read_text(sk["skill_md"])]
    for ref in sk["references"]:
        if ref.endswith((".md", ".txt")):
            parts.append(f"\n\n---\n\n## {ref.split('/skills/', 1)[1]}\n\n" + _read_text(ref))
    with open(dest, "w", encoding="utf-8") as f:
        f.write("".join(parts))
    return json.dumps({"path": dest, "bytes": os.path.getsize(dest)}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# MCP resources
# ---------------------------------------------------------------------------

@mcp.resource("mcp://skills/catalog")
def resource_catalog() -> str:
    """Full catalog: every skill + metadata as JSON."""
    return json.dumps({
        name: {k: v for k, v in sk.items() if k != "files"}
        for name, sk in _catalog()["skills"].items()
    }, ensure_ascii=False)


@mcp.resource("mcp://skills/index")
def resource_index() -> str:
    """The pack's INDEX.md — human-readable inventory."""
    return _read_text("skill_pack/INDEX.md")


@mcp.resource("mcp://skills/stats")
def resource_stats() -> str:
    """Quick pack statistics."""
    return get_skill_stats()


# Auto-generated per-skill resources: mcp://skills/{name}/SKILL.md
def _register_skill_resources() -> None:
    for sname, sk in _catalog()["skills"].items():
        path = sk["skill_md"]

        def _make(p=path):
            def _get() -> str:
                return _read_text(p)
            return _get

        mcp.resource(f"mcp://skills/{sname}/SKILL.md",
                     description=sk["description"][:200] or f"SKILL.md for {sname}")(_make())


_register_skill_resources()


if __name__ == "__main__":
    mcp.run()