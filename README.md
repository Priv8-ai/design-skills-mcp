# Design Skills MCP

A self-contained **MCP server** exposing a curated pack of **254 design / UI/UX /
frontend skills** plus the **UIUX Research Atlas** (77 structured design
references with palettes, typography and layout analysis).

Everything ships in one archive — `data/skills-pack.zip` (79 MB) — and the server
reads it in place, no extraction step. Binary assets (images, fonts, Office
templates) are unpacked to a cache dir on first access.

## The skill pack

- 254 unique skill trees, deduplicated from 585 source directories spread across
  Claude / Codex / Cursor / Kimi / Manus / Gemini agent caches.
- Categories: **design** (128), **product** (80), **visual** (34), **frontend** (12).
- The **UIUX Research Atlas**: 77 curated web / mobile / motion references
  (Awwwards, Dribbble, Behance, Pinterest) with dominant color palettes,
  typography rationale, and layout analysis. Aesthetic hypotheses, never proof.
- `skill_pack/INDEX.md` inside the archive is the human-readable inventory.

## MCP tools

| Tool | Purpose |
|------|---------|
| `search_skills` | full-text search across all SKILL.md + references |
| `list_skills` | browse catalog, filter by category |
| `get_skill` | full SKILL.md, optionally bundle references |
| `get_skill_file` | read any file in the pack (text or binary) |
| `search_atlas` | query the UI/UX research atlas |
| `get_atlas_entry` | full palette/typography/layout detail + image path |
| `get_skill_stats` | pack statistics |
| `download_skill_export` | standalone markdown bundle of a skill |

Plus **257 MCP resources** (`mcp://skills/<name>/SKILL.md` for every skill,
`mcp://skills/catalog`, `mcp://skills/index`, `mcp://skills/stats`).

## Run it

Requires Python 3.10+.

```bash
# stdio (for MCP clients)
uvx --from git+https://github.com/Priv8-ai/design-skills-mcp.git \
  fastmcp run server.py:mcp

# or clone and run locally
git clone https://github.com/Priv8-ai/design-skills-mcp.git
cd design-skills-mcp
uv venv --python 3.12 .venv && uv pip install -e .
.venv/bin/fastmcp run server.py:mcp

# HTTP transport (remote MCP / SSE)
.venv/bin/fastmcp run server.py:mcp --transport http --host 0.0.0.0 --port 8000
```

Client config (`mcp.json` for Claude Code / Cursor / Roo, or the `mcpServers`
block of your client):

```json
{
  "mcpServers": {
    "design-skills": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/Priv8-ai/design-skills-mcp.git",
               "fastmcp", "run", "server.py:mcp"]
    }
  }
}
```

## Static catalog site (GitHub Pages / Cloudflare Pages)

`site/` is a fully static, no-build catalog UI: searchable skill browser with
lazy-loaded content. Deploy it anywhere static files are served.

### GitHub Pages

Push to `main`; the workflow in `.github/workflows/pages.yml` builds `site/`
and deploys via `actions/deploy-pages`. Enable Pages → "GitHub Actions" in repo
Settings.

### Cloudflare Pages

```bash
npx wrangler pages deploy site --project-name design-skills
```

Or connect the repo in the Cloudflare dashboard (build command:
`python3 scripts/build_site.py`, output dir: `site`). `site/_headers` sets
`Access-Control-Allow-Origin: *` so the catalog can be fetched cross-origin.

## Regenerating the site

```bash
python3 scripts/build_site.py
```

## Environment variables

| Var | Default | Purpose |
|-----|---------|---------|
| `SKILLS_PACK_ZIP` | `data/skills-pack.zip` | path to the pack archive |
| `SKILLS_CACHE_DIR` | `.cache/` | where binary assets are unpacked |
