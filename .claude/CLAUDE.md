# CLAUDE.md — EndpointGraph V2

Read this entire file before every response. It defines the project, every decision made, the exact stack, schema, API contract, auth flow, coding conventions, and the spec-driven workflow. Do not suggest alternatives to decisions already made. Do not implement v3 features unless explicitly asked.

---

## What this project is

**EndpointGraph** is an internal API consumer dependency graph and breaking-change impact analyzer.

It answers one question: **"If I change this API endpoint, what breaks?"**

A user logs in with GitHub. They see a list of their own repos and click **Track** on any repo. EndpointGraph clones it, runs static analysis, builds a dependency graph scoped to that repo and that user, and shows an interactive visualization where clicking any endpoint reveals every service that calls it.

---

## Problem being solved

Companies break internal APIs because nobody tracks who calls what. Manual consumer lists are error-prone and rarely maintained. This project discovers consumer relationships automatically — no manual tracking, no opt-in required from consumers.

---

## .claude folder — how this project is built

All Claude context, specs, commands, and agents live in `.claude/`. Never build everything at once. The workflow is:

```
1. Pick a spec from .claude/specs/
2. Ask Claude to implement it
3. Run the test command from .claude/commands/
4. Fix failures
5. Move to the next spec
```

```
.claude/
├── CLAUDE.md          ← this file — read every time
├── specs/             ← one file per feature, implement in order
├── commands/          ← slash commands for testing, linting, running
└── agents/            ← agents for test running, spec validation
```

### V1 specs (shipped — do not re-implement)

```
specs/
├── 01-db-schema.md
├── 02-github-auth.md
├── 03-repo-cloner.md
├── 04-openapi-parser.md
├── 05-treesitter-extractor.md
├── 06-url-matcher.md
├── 07-analyze-route.md
├── 08-api-routes.md
├── 09-frontend-graph.md
├── 10-impact-panel.md
└── 11-search.md
```

### V2 specs (implement in this order)

```
specs/
├── v2-01-db-migration.md      ← add user_id + repo_id to services, unique constraints, RLS
├── v2-02-backend-auth.md      ← verify Supabase ES256 JWT, extract user_id from sub claim, set RLS context per DB transaction
├── v2-03-upsert.md            ← upsert services + endpoints on re-analysis (no duplicates)
├── v2-04-recursive-scan.md    ← full-depth service discovery, skip IGNORED_DIRS
├── v2-05-js-parser.md         ← extend code_parser.py for .js/.jsx/.ts/.tsx
├── v2-06-repos-route.md       ← GET /repos — GitHub repo list with tracked status
├── v2-07-repos-page.md        ← frontend /repos page — Track / Re-analyze buttons
├── v2-08-scoped-graph.md      ← GET /graph?repo_id=... scoped per repo + user; persist on refresh
└── v2-09-delete-service.md    ← DELETE /services/{id} — untrack a repo
```

### Command files

```
commands/
├── test-backend.md     ← runs pytest on backend
├── test-frontend.md    ← runs jest on frontend
├── lint.md             ← runs ruff (Python) + eslint (JS)
└── dev.md              ← starts FastAPI + Next.js locally without Docker
```

### Agent files

```
agents/
├── test-runner.md      ← runs tests and reports failures with context
└── spec-checker.md     ← validates implementation matches the spec
```

---

## Tech stack

| Layer | Tool | Version | Purpose |
|---|---|---|---|
| Frontend framework | Next.js | 16.2 (App Router) | Pages, routing, UI |
| Frontend language | JavaScript | ES2022 | No TypeScript — all .js and .jsx files |
| Styling | Tailwind CSS | v4.3 | Utility-first CSS, CSS-first config |
| Graph visualization | React Flow | @xyflow/react latest | Interactive dependency graph |
| Auth (frontend) | Supabase JS client | v2 | GitHub OAuth only — not for DB queries |
| Auth (backend) | PyJWT + cryptography | latest | Verify Supabase ES256 JWT via JWKS, extract user_id |
| Backend framework | FastAPI | latest | REST API + analysis engine |
| Backend language | Python | 3.11+ | All backend code |
| Static analysis | tree-sitter + tree-sitter-languages | latest | Parse Python + JS/TS code |
| Spec parsing | PyYAML | latest | Parse openapi.yaml files |
| Repo cloning | subprocess (stdlib) | — | git clone with GitHub token |
| DB driver | asyncpg | latest | Async PostgreSQL driver |
| Database | Supabase | PostgreSQL 15 | Hosted DB + Auth provider + RLS |
| Testing (backend) | pytest + pytest-asyncio | latest | Backend unit + integration tests |
| Testing (frontend) | Jest | latest | Frontend component tests |
| Linting (Python) | ruff | latest | Fast Python linter |
| Linting (JS) | eslint | latest | JS linter |

### Not in the stack — do not suggest

- No TypeScript anywhere in the frontend
- No Docker or docker-compose
- No SQLAlchemy or any ORM — raw asyncpg queries only
- No Neo4j or graph database
- No Redis, Celery, or background jobs
- No GraphQL
- No NextAuth — Supabase Auth handles GitHub OAuth
- No separate Express or other Node backend — FastAPI is the only backend

---

## Architecture

```
Browser
  ↓
Next.js 16 — App Router, JavaScript, Tailwind v4
  ├── Supabase JS client (auth ONLY — login, logout, get session + GitHub token)
  └── fetch() to FastAPI (all data — graph, impact analysis, trigger analysis, repo list)
        ↓
FastAPI — Python, asyncpg
  ├── Reads Authorization: Bearer <supabase-jwt> header → verifies ES256 → extracts user_id (sub claim)
  ├── Reads X-GitHub-Token header → used for repo cloning and GitHub API calls only
  ├── Sets request.jwt.claims + role=authenticated per DB transaction → RLS enforces auth.uid()
  ├── Clones private/public repos using the GitHub token
  ├── Runs tree-sitter + PyYAML analysis on cloned code (Python + JS/TS)
  └── asyncpg → Supabase (RLS enforces per-user isolation at DB layer — including FastAPI queries)
        ↓
Supabase — PostgreSQL 15
  ├── auth.users (managed by Supabase Auth — do not touch directly)
  ├── public.services  (user_id + repo_id scoped)
  ├── public.endpoints (cascades from services)
  └── public.consumer_edges (cascades from services)
```

**Rules that must never be broken:**
1. Next.js uses the Supabase JS client for auth only. All graph/analysis data goes through FastAPI.
2. FastAPI never imports Supabase JS client. It connects to PostgreSQL directly via asyncpg using `DATABASE_URL`.
3. Every DB transaction from FastAPI calls `set_rls_context(conn, user_id)` before any query. `user_id` is always the Supabase UUID extracted from the `sub` claim of the verified ES256 JWT — never from the GitHub API.
4. `GET /graph` always takes a `repo_id` query param — never returns all repos mixed together.
5. Every FastAPI route that touches the DB requires both `X-GitHub-Token` (for GitHub operations) and `Authorization: Bearer <supabase-jwt>` (for user identity + RLS).

---

## Deployment

| Service | Platform | What runs there |
|---|---|---|
| Frontend | Vercel | Next.js 16 |
| Backend | Railway or Render | FastAPI (uvicorn) |
| Database + Auth | Supabase | PostgreSQL + GitHub OAuth |

No Docker. No containers. Direct deployments.

---

## Project structure

```
endpointgraph/
├── .claude/
│   ├── CLAUDE.md              ← this file
│   ├── specs/                 ← feature specs
│   ├── commands/              ← test/lint/dev commands
│   └── agents/                ← test runner, spec checker
│
├── backend/
│   ├── .venv/                 ← virtual environment. Never committed. In .gitignore.
│   ├── main.py                ← FastAPI app, lifespan, router registration
│   ├── database.py            ← asyncpg pool (create once, reuse)
│   ├── models.py              ← Pydantic request/response models
│   ├── auth.py                ← GitHub token extraction + Supabase JWT (ES256) verification + RLS context setter
│   ├── routers/
│   │   ├── services.py        ← GET /services, DELETE /services/{id}
│   │   ├── endpoints.py       ← GET /endpoints, GET /endpoints/{id}/impact-analysis
│   │   ├── graph.py           ← GET /graph?repo_id=...
│   │   ├── repos.py           ← GET /repos (proxies GitHub API + annotates tracked status)
│   │   └── analyze.py         ← POST /analyze
│   ├── analysis/
│   │   ├── cloner.py          ← git clone repo using GitHub token into tmp dir
│   │   ├── spec_parser.py     ← PyYAML: openapi.yaml → endpoints list
│   │   ├── code_parser.py     ← tree-sitter: route decorators + HTTP call sites (Python + JS/TS)
│   │   └── url_matcher.py     ← match /users/123 → /users/{id}
│   ├── tests/
│   │   ├── test_spec_parser.py
│   │   ├── test_code_parser.py
│   │   ├── test_url_matcher.py
│   │   └── test_routes.py
│   ├── requirements.txt       ← all packages pinned with ==. Updated after every pip install.
│   └── .env                   ← DATABASE_URL only. Never committed.
│
├── frontend/
│   ├── app/
│   │   ├── layout.js
│   │   ├── page.js            ← redirect to /repos if logged in, else /login
│   │   ├── login/
│   │   │   └── page.js        ← GitHub OAuth login button
│   │   ├── repos/
│   │   │   └── page.js        ← repo browser (protected route)
│   │   ├── graph/
│   │   │   └── page.js        ← graph view for one repo: /graph?repo=owner/name
│   │   └── auth/
│   │       └── callback/
│   │           └── route.js   ← OAuth callback handler
│   ├── components/
│   │   ├── DependencyGraph.jsx   ← React Flow (dynamic import, ssr:false)
│   │   ├── ImpactPanel.jsx       ← side panel: consumers on node click
│   │   ├── SearchBar.jsx         ← filter nodes by endpoint path
│   │   ├── RepoList.jsx          ← repo browser: Track / Re-analyze per repo
│   │   └── AuthGuard.jsx         ← redirect to /login if no session
│   ├── lib/
│   │   ├── supabase.js           ← createClient — used for auth ONLY
│   │   └── api.js                ← all fetch() calls to FastAPI
│   ├── globals.css               ← @import "tailwindcss" + @theme block
│   ├── package.json
│   └── .env.local                ← NEXT_PUBLIC vars. Never committed.
│
└── v2.md                         ← full v2 plan (reference doc)
```

Note: `sample-services/` has been moved to its own repo at `github.com/iamaryan07/sample-services`.

---

## Database schema

All tables are in the `public` schema in Supabase. The `auth.users` table is managed by Supabase Auth — never create or alter it. RLS is enabled on all three tables.

### Table: `services`

```sql
CREATE TABLE public.services (
  id                SERIAL PRIMARY KEY,
  name              VARCHAR(100) NOT NULL,
  language          VARCHAR(50),
  repo_url          VARCHAR(255),
  user_id           UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  repo_id           VARCHAR(255),           -- e.g. "iamaryan07/sample-services"
  last_analyzed_at  TIMESTAMP DEFAULT NOW(),
  created_at        TIMESTAMP DEFAULT NOW(),
  UNIQUE (user_id, repo_id, name)           -- re-analysis upserts, never duplicates
);
```

### Table: `endpoints`

```sql
CREATE TABLE public.endpoints (
  id           SERIAL PRIMARY KEY,
  service_id   INT NOT NULL REFERENCES public.services(id) ON DELETE CASCADE,
  method       VARCHAR(10) NOT NULL,    -- GET | POST | PUT | DELETE
  path         VARCHAR(255) NOT NULL,   -- /users/{id}
  spec_source  VARCHAR(50),            -- openapi | decorator | decorator_js | nextjs_route
  created_at   TIMESTAMP DEFAULT NOW(),
  UNIQUE (service_id, method, path)    -- re-analysis upserts, never duplicates
);
```

### Table: `consumer_edges`

```sql
CREATE TABLE public.consumer_edges (
  id                 SERIAL PRIMARY KEY,
  caller_service_id  INT NOT NULL REFERENCES public.services(id) ON DELETE CASCADE,
  endpoint_id        INT NOT NULL REFERENCES public.endpoints(id) ON DELETE CASCADE,
  last_seen_at       TIMESTAMP DEFAULT NOW(),
  call_count         INT DEFAULT 0,
  source             VARCHAR(20) NOT NULL,  -- static | logs
  created_at         TIMESTAMP DEFAULT NOW(),
  UNIQUE(caller_service_id, endpoint_id)
);
```

### RLS policies

```sql
ALTER TABLE public.services ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.endpoints ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.consumer_edges ENABLE ROW LEVEL SECURITY;

CREATE POLICY "users see own services"
  ON public.services FOR ALL
  USING (user_id = auth.uid());

CREATE POLICY "users see own endpoints"
  ON public.endpoints FOR ALL
  USING (
    service_id IN (SELECT id FROM public.services WHERE user_id = auth.uid())
  );

CREATE POLICY "users see own edges"
  ON public.consumer_edges FOR ALL
  USING (
    caller_service_id IN (SELECT id FROM public.services WHERE user_id = auth.uid())
  );
```

### Why each column exists

| Column | Why |
|---|---|
| `services.user_id` | Scopes all data to the logged-in user — enforced by RLS |
| `services.repo_id` | Scopes graph view to one repo (e.g. `iamaryan07/sample-services`) |
| `services.last_analyzed_at` | Shows when a repo was last analyzed in the repo browser |
| `services UNIQUE(user_id, repo_id, name)` | Re-analysis upserts rows instead of creating duplicates |
| `endpoints UNIQUE(service_id, method, path)` | Same — re-analysis is idempotent |
| `consumer_edges.last_seen_at` | Dependency seen 8 months ago vs 2 minutes ago = very different risk |
| `consumer_edges.call_count` | 1 call/day vs 10,000/min = very different blast radius |
| `consumer_edges.source` | `static` = found in code. `logs` = confirmed live traffic (v3 only) |
| `endpoints.spec_source` | Tracks how the endpoint was discovered — affects confidence shown in UI |

### spec_source values

| Value | Meaning |
|---|---|
| `openapi` | Found in openapi.yaml |
| `decorator` | Python route decorator (FastAPI / Flask) |
| `decorator_js` | JS/TS Express route handler |
| `nextjs_route` | Next.js file-based routing |

---

## Auth flow — GitHub OAuth via Supabase

### Full flow step by step

```
1. User visits the app → /login page
2. Clicks "Login with GitHub"
3. Supabase Auth redirects to GitHub OAuth consent screen
4. User approves → GitHub redirects back to /auth/callback
5. Supabase exchanges code for tokens, stores session
6. session.access_token  = Supabase JWT (ES256, sub = Supabase user UUID) — used for RLS
7. session.provider_token = GitHub OAuth token — used for cloning + GitHub API only
8. Frontend stores session in memory (Supabase handles this)
9. User is redirected to /repos
10. Every FastAPI request from the frontend sends two headers:
    - Authorization: Bearer <session.access_token>   ← FastAPI verifies ES256, extracts sub → user_id
    - X-GitHub-Token: <session.provider_token>        ← used only for git clone + GitHub API calls
11. For every DB transaction FastAPI:
    - Calls set_rls_context(conn, user_id) which sets request.jwt.claims + role=authenticated
    - auth.uid() now returns the correct Supabase UUID → RLS enforced at DB layer
    - user_id in every INSERT comes from the JWT sub claim, not from GitHub API
```

### Supabase JWT configuration (one-time setup)

Supabase signs JWTs with HS256 by default. To use ES256:
1. Supabase Dashboard → Project Settings → API → JWT Settings
2. Change signing algorithm to ES256
3. Add the JWKS discovery URL to `backend/.env` as `SUPABASE_JWKS_URL`

The JWKS URL is always: `https://[ref].supabase.co/auth/v1/.well-known/jwks.json`

FastAPI uses `PyJWKClient` which fetches the JWKS endpoint once, caches the key set, and uses the `kid` in each JWT header to select the correct key. Key rotation is handled automatically — no manual key copying ever needed.

### Frontend auth setup

```javascript
// lib/supabase.js — auth client ONLY, never used for DB queries
import { createClient } from '@supabase/supabase-js'

export const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
)
```

```javascript
// app/login/page.js
'use client'
import { supabase } from '@/lib/supabase'

export default function LoginPage() {
  const login = async () => {
    await supabase.auth.signInWithOAuth({
      provider: 'github',
      options: {
        scopes: 'repo',   // 'repo' scope = access to private repos
        redirectTo: `${window.location.origin}/auth/callback`
      }
    })
  }

  return <button onClick={login}>Login with GitHub</button>
}
```

```javascript
// app/auth/callback/route.js — Next.js route handler
import { supabase } from '@/lib/supabase'
import { NextResponse } from 'next/server'

export async function GET(request) {
  const { searchParams } = new URL(request.url)
  const code = searchParams.get('code')
  await supabase.auth.exchangeCodeForSession(code)
  return NextResponse.redirect(new URL('/repos', request.url))
}
```

```javascript
// lib/api.js — attach both auth headers to every FastAPI request
import { supabase } from './supabase'

// Returns both headers required by every FastAPI route
async function getAuthHeaders() {
  const { data: { session } } = await supabase.auth.getSession()
  return {
    'X-GitHub-Token': session?.provider_token,   // for git clone + GitHub API
    'Authorization': `Bearer ${session?.access_token}`, // for JWT verification + RLS
  }
}

export async function fetchUserRepos() {
  const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/repos`, {
    headers: await getAuthHeaders()
  })
  if (!res.ok) throw new Error(await extractError(res))
  return res.json()  // [{ name, full_name, private, updated_at, tracked, last_analyzed_at }]
}

export async function triggerAnalysis(repoUrl) {
  const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/analyze`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...await getAuthHeaders()
    },
    body: JSON.stringify({ repo_url: repoUrl })
  })
  if (!res.ok) throw new Error(await extractError(res))
  return res.json()
}

export async function fetchGraph(repoId) {
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_API_URL}/graph?repo_id=${encodeURIComponent(repoId)}`,
    { headers: await getAuthHeaders() }
  )
  if (!res.ok) throw new Error(await extractError(res))
  return res.json()
}

export async function fetchImpactAnalysis(endpointId) {
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_API_URL}/endpoints/${endpointId}/impact-analysis`,
    { headers: await getAuthHeaders() }
  )
  if (!res.ok) throw new Error(await extractError(res))
  return res.json()
}

export async function deleteService(serviceId) {
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_API_URL}/services/${serviceId}`,
    { method: 'DELETE', headers: await getAuthHeaders() }
  )
  if (!res.ok) throw new Error(await extractError(res))
}

async function extractError(res) {
  const text = await res.text()
  try {
    const json = JSON.parse(text)
    if (typeof json.detail === 'string') return json.detail
    if (Array.isArray(json.detail)) return json.detail.map((e) => e.msg ?? String(e)).join(', ')
    return text
  } catch {
    return text
  }
}
```

### Backend JWT verification + RLS context

```python
# auth.py
import os, json
import jwt  # PyJWT
from jwt import PyJWKClient
from fastapi import Header, HTTPException

# JWKS client fetches https://[ref].supabase.co/auth/v1/.well-known/jwks.json
# once at startup and caches keys — handles key rotation automatically
_jwks_client = PyJWKClient(os.getenv("SUPABASE_JWKS_URL"))

async def get_github_token(x_github_token: str = Header(alias="X-GitHub-Token")) -> str:
    if not x_github_token:
        raise HTTPException(status_code=401, detail="GitHub token required")
    return x_github_token

async def get_current_user_id(authorization: str = Header()) -> str:
    """Verify Supabase ES256 JWT via JWKS, return the Supabase user UUID (sub claim)."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = authorization[7:]
    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256"],
            audience="authenticated",
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")
    return payload["sub"]  # Supabase UUID — matches auth.users.id and services.user_id

async def set_rls_context(conn, user_id: str) -> None:
    """Set JWT claims + role for this transaction so RLS auth.uid() is enforced."""
    claims = json.dumps({"sub": user_id, "role": "authenticated"})
    await conn.execute("SELECT set_config('request.jwt.claims', $1, true)", claims)
    await conn.execute("SELECT set_config('role', 'authenticated', true)")
```

```python
# routers/analyze.py — both dependencies required on every DB-touching route
from fastapi import APIRouter, Depends
from auth import get_github_token, get_current_user_id, set_rls_context
from database import get_pool
from analysis.cloner import clone_repo

router = APIRouter()

@router.post("/analyze")
async def analyze(
    request: AnalyzeRequest,
    token: str = Depends(get_github_token),
    user_id: str = Depends(get_current_user_id),
):
    tmp_dir = clone_repo(request.repo_url, token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await set_rls_context(conn, user_id)  # must be first — enables RLS for this tx
            # now run all DB writes; auth.uid() returns user_id; RLS enforces isolation
```

---

## Repo cloning

```python
# analysis/cloner.py
import subprocess, tempfile, uuid, shutil, re, os

def clone_repo(repo_url: str, github_token: str) -> str:
    repo_url = repo_url.strip()
    repo_url = re.sub(r'^https?://', '', repo_url)
    if not repo_url.startswith('github.com/'):
        raise ValueError(f"Invalid GitHub URL: {repo_url}")

    auth_url = f"https://{github_token}@{repo_url}"
    tmp_dir = os.path.join(tempfile.gettempdir(), str(uuid.uuid4()))

    try:
        result = subprocess.run(
            ["git", "clone", "--depth", "1", auth_url, tmp_dir],
            capture_output=True, text=True, timeout=60,
        )
    except subprocess.TimeoutExpired:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise RuntimeError("Clone timed out after 60 seconds")

    if result.returncode != 0:
        raise RuntimeError(f"Clone failed: {result.stderr}")

    return tmp_dir

def delete_repo(tmp_dir: str) -> None:
    shutil.rmtree(tmp_dir, ignore_errors=True)
```

`--depth 1` clones only the latest commit. Always delete the temp dir after analysis — use try/finally.

---

## Static analysis

### Service discovery — recursive, no depth limit

```python
IGNORED_DIRS = {'.git', 'node_modules', '.venv', '__pycache__', 'dist', 'build', '.next', 'coverage'}

def find_service_folders(root: str) -> list[str]:
    results = []
    def walk(path):
        for entry in os.listdir(path):
            full = os.path.join(path, entry)
            if not os.path.isdir(full) or entry in IGNORED_DIRS:
                continue
            if _is_service_folder(full):
                results.append(full)
            else:
                walk(full)   # recurse — no depth cap
    walk(root)
    return results
```

No hardcoded depth limit. `IGNORED_DIRS` is what bounds the traversal. Once a folder is identified as a service, its subdirectories are not recursed into — a service folder is a leaf.

### Endpoint discovery priority

When analyzing a service folder:

1. `openapi.yaml` or `openapi.json` exists → parse with PyYAML (most reliable)
2. No spec file → scan `.py`, `.js`, `.jsx`, `.ts`, `.tsx` files with tree-sitter for route decorators

### tree-sitter — two jobs, Python + JS/TS

**Job 1 — Find what a service EXPOSES (route decorators → endpoints table)**

```python
# Python:  @app.get("/users/{id}")  → method=GET, path=/users/{id}
# Express: app.get('/users/:id', ...) → method=GET, path=/users/:id
# Next.js: /app/api/users/route.js → GET /api/users (filename-based)
```

**Job 2 — Find what a service CALLS (HTTP client calls → consumer_edges)**

```python
# Python: requests.get("http://user-service/users/1")
# JS:     fetch("http://user-service/users/1")
# JS:     axios.get("http://user-service/users/1")
```

The URL matcher operates on the extracted URL string — it works regardless of source language.

### URL matching

```python
# analysis/url_matcher.py
import re

def match_url_to_endpoint(url_path: str, known_paths: list[str]) -> str | None:
    url_path = url_path.strip('/')
    for path in known_paths:
        pattern = re.sub(r'\{[^}]+\}', r'[^/]+', path.strip('/'))
        if re.fullmatch(pattern, url_path):
            return path
    return None
```

---

## FastAPI API contract

Base URL local: `http://localhost:8000`
All routes require both headers: `X-GitHub-Token` and `Authorization: Bearer <supabase-jwt>`.

| Method | Route | Request body / params | Returns |
|---|---|---|---|
| POST | `/analyze` | `{repo_url: string}` | `{status: "ok", services: int, endpoints: int, edges: int}` |
| GET | `/graph` | `?repo_id=owner/name` | `{nodes: [...], edges: [...]}` |
| GET | `/repos` | — | `[{name, full_name, private, updated_at, tracked, last_analyzed_at}]` |
| GET | `/services` | — | `[{id, name, language, repo_url, repo_id, last_analyzed_at}]` |
| DELETE | `/services/{id}` | — | `{status: "deleted"}` |
| GET | `/endpoints` | `?service_id=1` (optional) | `[{id, service_id, method, path, spec_source}]` |
| GET | `/endpoints/{id}/impact-analysis` | — | `[{service_name, call_count, last_seen_at, source}]` |

### Pydantic models

```python
# models.py
from pydantic import BaseModel
from datetime import datetime

class AnalyzeRequest(BaseModel):
    repo_url: str

class AnalyzeResponse(BaseModel):
    status: str
    services: int
    endpoints: int
    edges: int

class ServiceOut(BaseModel):
    id: int
    name: str
    language: str | None
    repo_url: str | None
    repo_id: str | None
    last_analyzed_at: datetime | None

class RepoOut(BaseModel):
    name: str
    full_name: str
    private: bool
    updated_at: str
    tracked: bool
    last_analyzed_at: datetime | None

class EndpointOut(BaseModel):
    id: int
    service_id: int
    method: str
    path: str
    spec_source: str | None

class ConsumerOut(BaseModel):
    service_name: str
    call_count: int
    last_seen_at: datetime
    source: str

class GraphNode(BaseModel):
    id: str
    name: str

class GraphEdge(BaseModel):
    source: str
    target: str
    endpoint_path: str
    endpoint_method: str
    call_count: int
    last_seen_at: datetime

class GraphOut(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
```

---

## Core SQL queries

```sql
-- Upsert service (re-analysis updates last_analyzed_at, never creates duplicate)
INSERT INTO services (name, language, repo_url, user_id, repo_id, last_analyzed_at)
VALUES ($1, $2, $3, $4, $5, NOW())
ON CONFLICT (user_id, repo_id, name)
DO UPDATE SET last_analyzed_at = NOW(), language = EXCLUDED.language
RETURNING id;

-- Upsert endpoint (re-analysis is idempotent)
INSERT INTO endpoints (service_id, method, path, spec_source)
VALUES ($1, $2, $3, $4)
ON CONFLICT (service_id, method, path)
DO NOTHING
RETURNING id;

-- Upsert edge (on re-analysis, update timestamp)
INSERT INTO consumer_edges (caller_service_id, endpoint_id, last_seen_at, call_count, source)
VALUES ($1, $2, NOW(), 1, $3)
ON CONFLICT (caller_service_id, endpoint_id)
DO UPDATE SET last_seen_at = NOW(), source = EXCLUDED.source;

-- Graph: nodes + edges for one repo, one user (RLS also enforces user filter)
SELECT
  s.id, s.name,
  ce.caller_service_id, ce.endpoint_id,
  e.path, e.method,
  ce.call_count, ce.last_seen_at
FROM consumer_edges ce
JOIN services s ON s.id = ce.caller_service_id
JOIN endpoints e ON e.id = ce.endpoint_id
WHERE s.repo_id = $1;

-- Impact analysis: who calls endpoint X
SELECT s.name AS service_name, ce.call_count, ce.last_seen_at, ce.source
FROM consumer_edges ce
JOIN services s ON s.id = ce.caller_service_id
WHERE ce.endpoint_id = $1
ORDER BY ce.call_count DESC;
```

---

## asyncpg pool setup

```python
# database.py
import asyncpg, os
from dotenv import load_dotenv

load_dotenv()
_pool = None

async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            os.getenv("DATABASE_URL"),
            min_size=2,
            max_size=10,
            statement_cache_size=0,   # required for Supabase PgBouncer
        )
    return _pool

# main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from database import get_pool

@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()
    yield

app = FastAPI(lifespan=lifespan)
```

`statement_cache_size=0` is required — Supabase uses PgBouncer in transaction mode which does not support prepared statements.

---

## Frontend conventions (JavaScript)

### No TypeScript — all files are .js or .jsx

- Pages: `.js` (in `app/` directory)
- Components: `.jsx` (React components)
- Utilities: `.js`
- No `tsconfig.json`, no type annotations, no `.ts` or `.tsx` files

### Tailwind v4 setup

```css
/* globals.css */
@import "tailwindcss";

@theme {
  /* add custom tokens here only if needed */
}
```

No `tailwind.config.js`. No `content` array. No `@tailwind` directives.

### React Flow in Next.js 16

```jsx
// components/DependencyGraph.jsx
'use client'
import { ReactFlow, Background, Controls, MiniMap } from '@xyflow/react'
import '@xyflow/react/dist/style.css'

export default function DependencyGraph({ nodes, edges, onNodeClick }) {
  return (
    <div style={{ width: '100%', height: '100vh' }}>
      <ReactFlow nodes={nodes} edges={edges} onNodeClick={onNodeClick} fitView>
        <Background />
        <Controls />
        <MiniMap />
      </ReactFlow>
    </div>
  )
}
```

```jsx
// app/graph/page.js — dynamic import REQUIRED
import dynamic from 'next/dynamic'

const DependencyGraph = dynamic(
  () => import('@/components/DependencyGraph'),
  { ssr: false }   // React Flow uses window/document — no SSR
)
```

### Graph page reads repo from URL, fetches on mount

```javascript
// app/graph/page.js
'use client'
import { useSearchParams } from 'next/navigation'
import { useEffect, useState } from 'react'
import { fetchGraph } from '@/lib/api'

export default function GraphPage() {
  const searchParams = useSearchParams()
  const repoId = searchParams.get('repo')  // e.g. "iamaryan07/sample-services"
  const [nodes, setNodes] = useState([])
  const [edges, setEdges] = useState([])

  useEffect(() => {
    if (!repoId) return
    fetchGraph(repoId).then(/* build rfNodes + rfEdges, call setNodes/setEdges */)
  }, [repoId])
  // ...
}
```

Graph persists on refresh because `repoId` comes from the URL, not component state.

### All API calls live in lib/api.js

No inline `fetch()` inside components or pages. Every call to FastAPI goes through `lib/api.js`.

---

## Environment variables

### backend/.env (never commit)
```
DATABASE_URL=postgresql://postgres:[password]@db.[ref].supabase.co:5432/postgres
SUPABASE_JWKS_URL=https://[ref].supabase.co/auth/v1/.well-known/jwks.json
```

### frontend/.env.local (never commit)
```
NEXT_PUBLIC_SUPABASE_URL=https://[ref].supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=[anon-key]
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### Vercel environment variables (production frontend)
```
NEXT_PUBLIC_SUPABASE_URL
NEXT_PUBLIC_SUPABASE_ANON_KEY
NEXT_PUBLIC_API_URL=https://your-fastapi-app.railway.app
```

### Railway environment variables (production backend)
```
DATABASE_URL
SUPABASE_JWKS_URL
```

---

## Python virtual environment

All Python work happens inside `.venv`. No exceptions.

- Lives at `backend/.venv` — never at the project root
- Always activate before running any Python command
- `.venv` is in `.gitignore` — never commit it
- Every package installed must be added to `requirements.txt` with a pinned version (`==`)

```bash
# Windows — activate
backend\.venv\Scripts\activate

# macOS / Linux — activate
source backend/.venv/bin/activate

# Run backend
uvicorn main:app --reload --port 8000

# Run tests
python -m pytest tests/ -v

# Lint
ruff check .

# After any pip install
pip freeze > requirements.txt
```

---

## Running locally (no Docker)

```bash
# Terminal 1 — backend
cd backend
python3 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend
npm install
npm run dev                     # runs on localhost:3000
```

---

## Key decisions — do not re-litigate

### PostgreSQL over Neo4j
The core query is 1 hop: "who calls endpoint X" = one JOIN on `consumer_edges`. PostgreSQL handles this trivially with RLS on top.

### Endpoint-level only
EndpointGraph tracks that Service A calls `GET /users/{id}`. It does NOT track which response fields Service A reads. Field-level impact analysis is v3.

### Static analysis only
Only tree-sitter + OpenAPI parsing. No log ingestion (Envoy/NGINX). The `source` column will only ever be `'static'` in v2.

### No ORM
Raw asyncpg queries. No SQLAlchemy. Queries are simple enough that an ORM adds no value.

### JavaScript not TypeScript (frontend)
The frontend is straightforward enough that TypeScript would add friction without meaningful benefit. All frontend files are `.js` or `.jsx`. The backend parses JS/TS source files with tree-sitter but the backend itself is Python.

### No Docker
Deploying to Vercel + Railway + Supabase. Docker is not needed.

### RLS at the DB layer via JWT (ES256)
User isolation is enforced at two independent layers:
1. **Application layer** — every query includes `WHERE user_id = $n` explicitly.
2. **DB layer** — every asyncpg transaction calls `set_rls_context(conn, user_id)` which sets `request.jwt.claims` and `role = authenticated`. This makes `auth.uid()` return the correct Supabase UUID, and the RLS policies enforce it. Even if FastAPI had a bug that forgot the WHERE clause, the DB would reject the query.

The `user_id` is always the Supabase UUID from the `sub` claim of the verified ES256 JWT — never from the GitHub API. This means `services.user_id` always matches `auth.users.id` exactly, and `auth.uid()` works correctly in RLS policies.

### Repo browser replaces URL input
Users can only track repos they own (what the GitHub token can see). This removes the attack surface of users cloning arbitrary public repos through the backend and makes the UX self-evident.

### No depth limit on service discovery
`IGNORED_DIRS` is what bounds the traversal, not an arbitrary depth number. A well-structured monorepo at depth 5 should be fully discovered.

---

## V2 scope

### In v2
- [x] V1 fully shipped (login, analyze, graph, impact panel, search)
- [ ] DB migration: add `user_id`, `repo_id`, `last_analyzed_at` to services; unique constraints; RLS on all tables
- [ ] Backend: verify Supabase ES256 JWT, extract user_id from sub claim, set RLS context per DB transaction
- [ ] Upsert services + endpoints on re-analysis (no duplicate rows)
- [ ] Recursive service discovery — full depth, `IGNORED_DIRS` only
- [ ] JS/TS parser — extend `code_parser.py` for `.js`, `.jsx`, `.ts`, `.tsx`
- [ ] `GET /repos` — proxy GitHub repo list, annotate with `tracked` + `last_analyzed_at`
- [ ] Frontend `/repos` page — repo browser with Track / Re-analyze buttons
- [ ] `GET /graph?repo_id=...` scoped per repo + user; graph persists on page refresh
- [ ] `DELETE /services/{id}` — untrack a repo

### Not in v2 — do not implement
- [ ] Field-level impact analysis (v3)
- [ ] Log ingestion (Envoy, NGINX, Istio) (v3)
- [ ] gRPC .proto parsing (v3)
- [ ] GitHub PR comment bot (v3)
- [ ] Teams / org-level sharing (v3)
- [ ] Deprecation tracking (v3)
- [ ] Background job processing (v3)

---

## Sample services (demo graph)

Live at `github.com/iamaryan07/sample-services` (separate repo, not in this repo).

| Service | Exposes | Calls |
|---|---|---|
| `order-service` | `POST /orders/create`, `GET /orders/{id}` | `GET /users/{id}`, `POST /payments/charge` |
| `payment-service` | `POST /payments/charge`, `GET /payments/{id}` | `GET /users/{id}` |
| `user-service` | `GET /users/{id}`, `GET /users/profile` | nothing |

Demo flow: Track `iamaryan07/sample-services` → `GET /users/{id}` shows 2 consumers (order + payment).

---

## What "done" looks like for v2

1. User visits the deployed app → sees login page
2. Clicks "Login with GitHub" → authenticates → redirected to /repos
3. Sees list of their GitHub repos with Track buttons
4. Clicks Track on `iamaryan07/sample-services`
5. Graph renders at `/graph?repo=iamaryan07/sample-services`
6. User refreshes — graph is still there (fetched from DB on mount)
7. User tracks a second repo — goes to its own separate graph, doesn't mix with the first
8. User clicks `GET /users/{id}` node → side panel shows 2 consumers
9. User can Re-analyze to pick up code changes, or untrack to remove the repo
