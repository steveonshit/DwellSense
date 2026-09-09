# Cursor Token-Saving Tools — Research Notes

**Date:** July 2026  
**Project:** ZerMap  
**Goal:** Find tools that reduce Cursor token usage without hurting productivity.

This document summarizes deep research comparing Graphify, TrueCourse, Vexp, code-review-graph, and free Cursor hygiene — evaluated specifically for ZerMap (Next.js + FastAPI + Supabase, heavy `project.md`, dual-stack flows).

---

## 1. What burns tokens on ZerMap

| Cause | Why it costs money |
|-------|--------------------|
| Agent exploration | Agent greps/reads many files to rediscover address → `/api/scan` → Railway → PDF |
| Large `project.md` | Often re-read; acts as a second brain |
| Dual stack | Answers span `frontend/` and `backend/` |
| Long chat threads | Full history is re-sent every turn |

**Scale note:** ZerMap is a **small** repo (~65 source files). Marketing claims like “71× fewer tokens” are measured on larger/mixed corpora. On a small repo, **workflow hygiene** still wins first; tools help next.

---

## 2. Tools compared

### 2.1 Graphify

| Field | Detail |
|-------|--------|
| Site | [graphify.net](https://graphify.net/) · GitHub: Graphify-Labs / safishamsi |
| What it is | Builds a **knowledge graph** of code + docs (imports, calls, concepts) |
| Token claim | Up to ~71× fewer tokens vs reading raw files (best on bigger corpora) |
| Code indexing | Tree-sitter locally — **free, no API** |
| Docs indexing | LLM once for markdown/PDF/images — **costs tokens to build** |
| Cursor setup | `graphify cursor install` → `.cursor/rules/graphify.mdc` + optional MCP |
| License | MIT, open source |

**Pros for ZerMap**
- Maps `project.md` *and* code (`scan.py`, `HomeClient`, PDF path) into one graph
- Strong for architecture / “how does X work?” questions
- Python + TypeScript both supported
- After build, agents can query structure instead of re-reading the tree

**Cons**
- Cursor integration is weaker than Claude Code (rules nudge vs hard hooks)
- Always-on rules + MCP tool lists also **consume** some tokens
- Savings smaller on a tiny repo than on a huge monorepo

**Fit:** **Best primary tool** for this project.

---

### 2.2 TrueCourse (you said “TrueCrouse”)

| Field | Detail |
|-------|--------|
| Site | [truecourse.dev](https://truecourse.dev/) · GitHub: truecourse-ai/truecourse |
| What it is | Architecture / quality analyzer + “does code match the docs?” |
| Token saver? | **No — opposite.** `analyze` uses LLM review and **burns** tokens |
| Strengths | Circular deps, layer violations, drift vs PRDs/ADRs/READMEs |
| Fit for tokens | **Wrong tool for this goal** |

**When to use later:** Automated checks that implementation still matches `project.md` — not for saving Cursor spend.

---

### 2.3 Vexp

| Field | Detail |
|-------|--------|
| Site | [vexp.dev](https://vexp.dev/) |
| What it is | Local **context engine** — returns “capsules” (full pivot file + skeleton neighbors) |
| Token claim | ~65–70% fewer tokens per query |
| Privacy | Local-first, zero network calls for indexing |
| Cursor | VS Code / Cursor extension + MCP CLI |
| Pricing | Free tier (small projects); Pro ~$19/mo |

**Pros**
- Built for agent coding: less “map the product,” more “give me the right 3 files”
- Auto compression via MCP (`run_pipeline`, etc.)
- Repo may fit free tier given size

**Cons**
- Weaker at ingesting product docs the way Graphify does
- Less ideal if your main pain is architecture Q&A over `project.md`

**Fit:** **Best runner-up** if Agent mode reading too many files is the main cost.

---

### 2.4 code-review-graph (CRG)

| Field | Detail |
|-------|--------|
| Site | [code-review-graph.com](https://code-review-graph.com/) |
| What it is | Local AST graph + blast radius (“what breaks if I change this?”) |
| Token claim | ~8.2× average context reduction |
| Cursor | `code-review-graph install --platform cursor` |
| License | MIT |

**Fit:** Useful **add-on** for refactors / PR review — not the first install for daily token savings.

---

### 2.5 Free Cursor hygiene (no new product)

| Practice | Why it helps |
|----------|--------------|
| Add `.cursorignore` | Stop indexing `node_modules`, `.next`, `venv`, lockfiles, `.clerk/` |
| Use `@file` / `@folder` | Avoid whole-repo context by default |
| New chat per task | Stop paying for old Q&A history |
| Point at `project.md` sections | Don’t paste the whole doc every time |
| Prefer Ask / inline for small work | Agent mode is the expensive path |

**Status on this repo:** No `.cursorignore` yet — easy free win.

---

## 3. Side-by-side

| Tool | Saves Cursor tokens? | Best for | ZerMap ranking |
|------|----------------------|----------|--------------------|
| **Hygiene** (ignore + scope + short chats) | Yes | Everything | Do first |
| **Graphify** | Yes (after graph built) | Code + docs map, architecture Q&A | **#1 tool** |
| **Vexp** | Yes (auto capsules) | Agent implementation with less file spam | **#2 tool** |
| **code-review-graph** | Yes (blast radius) | PR / refactor impact | Optional later |
| **TrueCourse** | No (uses tokens) | Doc–code drift / architecture defects | Not for this goal |

---

## 4. Recommendation

### Do first (free)

1. Add a solid `.cursorignore`
2. Scope prompts with `@file` / `@folder`
3. Start a **new chat** when the topic changes
4. Keep `project.md` as the map; don’t reload it blindly every turn

### Primary tool: Graphify

**Why it wins for ZerMap**
- You ask a lot of **flow / architecture** questions
- You already maintain a rich **`project.md`**
- Work crosses frontend ↔ Next API ↔ Railway backend
- Open source, Cursor install path exists, polyglot

**How to use it well**
1. Index **code** regularly (free)
2. Include **`project.md`** so product truth sits in the graph (one-time LLM cost)
3. Prefer graph/MCP queries over “read everything”
4. Rebuild after big architecture changes

### Runner-up: Vexp

Choose Vexp instead (or later) if the pain is mostly:

> Agent mode opens 20 files and burns the budget while coding.

### Skip for token savings

- **TrueCourse** — different job (quality / drift), not a saver

---

## 5. Suggested next steps

| Step | Action |
|------|--------|
| 1 | Add `.cursorignore` for ZerMap |
| 2 | Install Graphify and wire Cursor (rules + MCP) |
| 3 | Build graph once (code + `project.md`) |
| 4 | Optionally evaluate Vexp if Agent still feels expensive |
| 5 | Consider TrueCourse later only for doc–code drift checks |

---

## 6. Quick links

- Graphify: https://graphify.net/
- Vexp: https://vexp.dev/
- TrueCourse: https://truecourse.dev/
- code-review-graph: https://code-review-graph.com/
- Cursor cost hygiene guides (external): Tokenwise / Markaicode articles on scoping context and avoiding Agent-first workflows

---

## 8. Setup status (ZerMap — July 2026)

**Graphify is installed locally on this machine.**

| Piece | Location |
|-------|----------|
| Python venv | `.venv-graphify/` (gitignored) |
| Cursor rule | `.cursor/rules/graphify.mdc` |
| MCP server | `.cursor/mcp.json` |
| Graph outputs | `graphify-out/` (~833 nodes, ~1536 edges after first build) |
| Cursor ignore | `.cursorignore` |

**Commands:**
```bash
# Rebuild after code changes (free, no LLM)
.venv-graphify/bin/graphify update .

# Ask the map
.venv-graphify/bin/graphify query "how does auth callback set cookies"
.venv-graphify/bin/graphify path "HomeClient" "scan"
.venv-graphify/bin/graphify explain "dossier_token"
```

**After install:** restart Cursor once so MCP loads. Start a **new chat** for new work (map does not replace that).

**Still true:** new chats + scoped `@file` save the most tokens from transcript bloat; Graphify saves tokens from codebase re-exploration.
