#!/usr/bin/env python3
"""
Generate the static catalog site for GitHub Pages / Cloudflare Pages.

Reads data/skills-pack.zip and emits:
  site/index.html          single-page searchable catalog (vanilla JS, no build)
  site/catalog.json        skill list + metadata + search index
  site/skills/<name>.json  full SKILL.md + references for lazy loading
  site/mcp.json            MCP server config for clients (claude/cursor/etc.)
  site/_headers            Cloudflare Pages headers (CORS for remote MCP)
"""
from __future__ import annotations

import json
import os
import re
import zipfile
from collections import defaultdict
from pathlib import PurePosixPath

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ZIP = os.path.join(ROOT, "data", "skills-pack.zip")
SITE = os.path.join(ROOT, "site")


def read_zip():
    z = zipfile.ZipFile(ZIP)
    names = [i.filename for i in z.infolist() if not i.is_dir()]
    return z, names


def extract_description(md: str) -> str:
    fm = re.match(r"\A---\s*\n(.*?)\n---", md, re.S)
    if not fm:
        return ""
    m = re.search(r"^description:\s*(.+?)$", fm.group(1), re.M)
    if not m:
        return ""
    return m.group(1).strip()[:400]


def classify(name: str, md: str) -> str:
    n = name.lower()
    if any(k in n for k in ("ui", "ux", "design")) or "design" in md[:400].lower():
        return "design"
    if any(k in n for k in ("front", "react", "css", "web")):
        return "frontend"
    if any(k in n for k in ("figma", "canvas", "pixel", "art", "theme", "skin", "icon")):
        return "visual"
    return "product"


def tokenize(text: str) -> list[str]:
    return list(set(re.findall(r"[a-z0-9_]{3,}", text.lower())))


def main():
    z, names = read_zip()
    prefix = "skill_pack/skills/"
    skills = {}
    for name in names:
        if not name.startswith(prefix) or not name.endswith("SKILL.md"):
            continue
        sname = name[len(prefix):].split("/")[0]
        base = f"{prefix}{sname}/"
        files = [n[len(base):] for n in names if n.startswith(base) and n != name]
        md = z.read(name).decode("utf-8", errors="replace")
        desc = extract_description(md)
        skills[sname] = {
            "name": sname,
            "category": classify(sname, md),
            "description": desc,
            "files": files,
            "file_count": len(files) + 1,
            "refs": [f for f in files if f.startswith("references/") and f.endswith(".md")],
        }

    os.makedirs(SITE, exist_ok=True)
    os.makedirs(os.path.join(SITE, "skills"), exist_ok=True)

    # ---- catalog.json + search index ----
    catalog = []
    search_index = defaultdict(dict)  # term -> {name: count}
    for sname, sk in sorted(skills.items()):
        catalog.append({
            "name": sname,
            "category": sk["category"],
            "description": sk["description"],
            "file_count": sk["file_count"],
        })
        # tokenize name + description + file names for search
        blob = f"{sname} {sk['description']} {' '.join(sk['files'])}"
        for t in tokenize(blob):
            search_index[t][sname] = search_index[t].get(sname, 0) + 1

    with open(os.path.join(SITE, "catalog.json"), "w", encoding="utf-8") as f:
        json.dump({"skills": catalog, "index": dict(search_index),
                   "total": len(catalog)}, f, ensure_ascii=False)

    # ---- per-skill content for lazy loading ----
    for sname, sk in skills.items():
        md = z.read(f"{prefix}{sname}/SKILL.md").decode("utf-8", errors="replace")
        refs = {}
        for r in sk["refs"]:
            try:
                refs[r] = z.read(f"{prefix}{sname}/{r}").decode("utf-8", errors="replace")
            except KeyError:
                pass
        with open(os.path.join(SITE, "skills", f"{sname}.json"), "w", encoding="utf-8") as f:
            json.dump({"name": sname, "category": sk["category"],
                       "description": sk["description"], "content": md,
                       "references": refs, "files": sk["files"]}, f, ensure_ascii=False)

    # ---- mcp.json (client config: claude code / cursor / generic) ----
    mcp_cfg = {
        "mcpServers": {
            "design-skills": {
                "command": "uvx",
                "args": ["--from", "git+https://github.com/Priv8-ai/design-skills-mcp.git",
                         "fastmcp", "run", "server.py:mcp"],
                "env": {},
            }
        }
    }
    with open(os.path.join(SITE, "mcp.json"), "w", encoding="utf-8") as f:
        json.dump(mcp_cfg, f, indent=2)

    # ---- _headers for Cloudflare Pages (CORS for remote HTTP MCP) ----
    with open(os.path.join(SITE, "_headers"), "w", encoding="utf-8") as f:
        f.write("/*\n  Access-Control-Allow-Origin: *\n")

    # ---- index.html ----
    index_html = INDEX_HTML_TEMPLATE
    with open(os.path.join(SITE, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_html)

    print(f"wrote {len(catalog)} skills -> {SITE}")
    print(f"  catalog.json, {len(catalog)} skills/*.json, index.html, mcp.json, _headers")


INDEX_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Design Skills — MCP Catalog</title>
<style>
:root{--bg:#0f1115;--panel:#171a21;--panel2:#1e222b;--ink:#e7e9ee;--mut:#9aa1ad;
--acc:#7c5cff;--acc2:#4f8cff;--line:#2a2f3a;--ok:#3fb950;--warn:#d29922}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
header{padding:22px 28px;border-bottom:1px solid var(--line);
background:linear-gradient(180deg,#14161d,#0f1115)}
h1{font-size:22px;margin:0 0 4px}
.tagline{color:var(--mut);margin:0;font-size:13px}
.wrap{display:grid;grid-template-columns:340px 1fr;gap:0;min-height:calc(100vh - 89px)}
aside{border-right:1px solid var(--line);padding:16px;overflow-y:auto;max-height:calc(100vh - 89px)}
main{padding:20px 28px;overflow-y:auto;max-height:calc(100vh - 89px)}
#search{width:100%;padding:11px 13px;border-radius:9px;border:1px solid var(--line);
background:var(--panel2);color:var(--ink);font-size:14px;margin-bottom:12px}
#search:focus{outline:2px solid var(--acc);border-color:transparent}
.filters{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px}
.chip{padding:4px 11px;border-radius:20px;border:1px solid var(--line);cursor:pointer;
font-size:12px;color:var(--mut);background:transparent}
.chip.active{background:var(--acc);color:#fff;border-color:var(--acc)}
#list{display:flex;flex-direction:column;gap:2px}
.item{padding:9px 11px;border-radius:8px;cursor:pointer;border:1px solid transparent}
.item:hover{background:var(--panel)}
.item.active{background:var(--panel2);border-color:var(--acc)}
.item .n{font-weight:600;font-size:13.5px}
.item .d{color:var(--mut);font-size:12px;display:-webkit-box;-webkit-line-clamp:2;
-webkit-box-orient:vertical;overflow:hidden;margin-top:2px}
.badge{display:inline-block;font-size:10px;padding:1px 7px;border-radius:10px;margin-left:6px;
vertical-align:1px}
.b-design{background:#1f2430;color:#8ab4ff}
.b-frontend{background:#12251d;color:#56d364}
.b-visual{background:#2a1f35;color:#c792ea}
.b-product{background:#33251a;color:#e3b341}
#detail .h2{font-size:19px;margin:0 0 2px}
#detail .meta{color:var(--mut);font-size:12px;margin-bottom:16px}
.markdown{background:var(--panel);border:1px solid var(--line);border-radius:12px;
padding:18px 22px;white-space:pre-wrap;word-break:break-word;font:13.5px/1.6 ui-monospace,
SFMono-Regular,Menlo,Consolas,monospace}
.ref-title{margin:20px 0 8px;color:var(--mut);font-size:12px;text-transform:uppercase;
letter-spacing:.06em}
.empty{color:var(--mut);padding:40px;text-align:center}
a{color:var(--acc2)}
footer{padding:14px 28px;border-top:1px solid var(--line);color:var(--mut);font-size:12px}
code{background:var(--panel2);padding:1px 5px;border-radius:4px;font-size:12px}
</style>
</head>
<body>
<header>
<h1>Design Skills <span style="color:var(--acc)">MCP</span></h1>
<p class="tagline">Curated pack of design / UI/UX / frontend skills + UIUX Research Atlas.
Connect as an MCP server, or browse the catalog here.</p>
</header>
<div class="wrap">
<aside>
<input id="search" type="search" placeholder="Search skills… (e.g. dashboard, figma)">
<div class="filters" id="filters"></div>
<div id="list"></div>
</aside>
<main><div id="detail"><div class="empty">Select a skill, or search above.</div></div></main>
</div>
<footer>served from <code id="host"></code> · skill content loaded lazily from <code>skills/&lt;name&gt;.json</code>
· <a href="mcp.json">mcp.json</a> for client config</footer>
<script>
let CATALOG=null, INDEX=null, activeCat=null, current=null;
const $=id=>document.getElementById(id);
async function boot(){
  const r=await fetch('catalog.json'); const d=await r.json();
  CATALOG=d.skills; INDEX=d.index;
  $('host').textContent=location.hostname||'local';
  buildFilters(); render();
}
function buildFilters(){
  const cats=[...new Set(CATALOG.map(s=>s.category))].sort();
  const f=$('filters');
  const all=document.createElement('span');all.className='chip active';all.textContent='all';
  all.onclick=()=>{activeCat=null;syncChips();render()};
  f.appendChild(all);
  cats.forEach(c=>{const s=document.createElement('span');s.className='chip';
    s.textContent=c;s.onclick=()=>{activeCat=c;syncChips();render()};
    f.appendChild(s);});
}
function syncChips(){document.querySelectorAll('.chip').forEach(ch=>{
  ch.classList.toggle('active', ch.textContent===(activeCat||'all'));});}
function search(q){
  const terms=q.toLowerCase().split(/\\s+/).filter(t=>t.length>=3);
  if(!terms.length) return CATALOG.map(s=>s.name);
  const scores={};
  terms.forEach(t=>{
    for(const term in INDEX){ if(term.startsWith(t)){
      for(const n in INDEX[term]) scores[n]=(scores[n]||0)+INDEX[term][n];
    }}
  });
  return Object.entries(scores).sort((a,b)=>b[1]-a[1]).map(e=>e[0]);
}
function render(){
  const q=$('search').value.trim();
  let names=q?search(q):CATALOG.map(s=>s.name);
  if(activeCat) names=names.filter(n=>CATALOG.find(s=>s.name===n).category===activeCat);
  const list=$('list');list.innerHTML='';
  names.forEach(n=>{
    const s=CATALOG.find(x=>x.name===n);
    const el=document.createElement('div');el.className='item'+(n===current?' active':'');
    el.innerHTML=`<div class="n">${s.name}<span class="badge b-${s.category}">${s.category}</span></div>
      <div class="d">${s.description||''}</div>`;
    el.onclick=()=>{current=n;render();load(n)};
    list.appendChild(el);
  });
  if(!names.length) list.innerHTML='<div class="empty">no matches</div>';
}
async function load(name){
  const r=await fetch('skills/'+name+'.json');
  const sk=await r.json();
  let html=`<div class="h2">${sk.name}</div>
    <div class="meta"><span class="badge b-${sk.category}">${sk.category}</span>
    · ${sk.file_count} files · ${sk.description||''}</div>`;
  html+=`<div class="markdown">${escapeHtml(sk.content||'')}</div>`;
  if(sk.references && Object.keys(sk.references).length){
    html+=`<div class="ref-title">references</div>`;
    for(const [p,c] of Object.entries(sk.references)){
      html+=`<div class="ref-title" style="margin-top:10px;color:var(--acc2)">${p}</div>
        <div class="markdown">${escapeHtml(c)}</div>`;
    }
  }
  $('detail').innerHTML=html;
}
function escapeHtml(s){return s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
$('search').addEventListener('input',render);
boot();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
