# Spec v2-01 — DB Migration: user_id, repo_id, last_analyzed_at, unique constraints, RLS

## Goal
Alter the `services` table to add `user_id`, `repo_id`, and `last_analyzed_at` columns; add unique constraints on `services(user_id, repo_id, name)` and `endpoints(service_id, method, path)`; and enable RLS on all three tables (`services`, `endpoints`, `consumer_edges`) with policies that scope every row to the authenticated user.

## Depends on
Specs 01–11 (v1 fully shipped). This is the first v2 spec and must be done before any other v2 spec.

## Context
V1 shipped with no per-user isolation — all services, endpoints, and edges were globally visible. V2 introduces multi-user support. This migration is purely at the database layer. It does not change any Python or JavaScript code (that is handled in v2-02 and later). Once this migration runs:
- Every row in `services` is stamped with the `user_id` of whoever tracked it.
- The `repo_id` column (e.g. `"iamaryan07/sample-services"`) groups all services from one analysis run so `GET /graph?repo_id=...` can filter correctly.
- `last_analyzed_at` is shown in the repo browser (`/repos`) so the user can see when a repo was last scanned.
- Unique constraints make re-analysis idempotent — upserts update existing rows instead of inserting duplicates.
- RLS ensures the DB itself enforces per-user isolation, so even a bug in FastAPI cannot leak User A's data to User B.

`auth.users` is managed by Supabase Auth — do not create or alter it.

**RLS enforcement in this architecture:** FastAPI calls `set_rls_context(conn, user_id)` at the start of every DB transaction (implemented in v2-02). This sets `request.jwt.claims` and switches to `role = authenticated`, so `auth.uid()` returns the correct Supabase UUID and RLS policies are enforced even for asyncpg connections. The policies created in this migration are fully active for all FastAPI queries once v2-02 is implemented.

## Files to create
None. This spec is executed entirely as SQL against the Supabase project via the Supabase MCP tool (`apply_migration`). No Python or JavaScript files are created.

## Files to edit
None. No application code changes in this spec.

## Implementation details

All SQL must be executed as a single migration. Use the Supabase MCP `apply_migration` tool to apply it.

### Migration name
`v2_db_migration`

### Full SQL

```sql
-- 1. Add new columns to services
ALTER TABLE public.services
  ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  ADD COLUMN IF NOT EXISTS repo_id VARCHAR(255),
  ADD COLUMN IF NOT EXISTS last_analyzed_at TIMESTAMP DEFAULT NOW();

-- 2. Unique constraint on services: one row per (user, repo, service name)
--    Use IF NOT EXISTS pattern via a DO block to make it re-runnable
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint c
    JOIN pg_class t ON c.conrelid = t.oid
    JOIN pg_namespace n ON t.relnamespace = n.oid
    WHERE c.conname = 'services_user_id_repo_id_name_key'
      AND n.nspname = 'public'
  ) THEN
    ALTER TABLE public.services
      ADD CONSTRAINT services_user_id_repo_id_name_key
      UNIQUE (user_id, repo_id, name);
  END IF;
END $$;

-- 3. Unique constraint on endpoints: one row per (service, method, path)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint c
    JOIN pg_class t ON c.conrelid = t.oid
    JOIN pg_namespace n ON t.relnamespace = n.oid
    WHERE c.conname = 'endpoints_service_id_method_path_key'
      AND n.nspname = 'public'
  ) THEN
    ALTER TABLE public.endpoints
      ADD CONSTRAINT endpoints_service_id_method_path_key
      UNIQUE (service_id, method, path);
  END IF;
END $$;

-- 4. Unique constraint on consumer_edges: one row per (caller_service, endpoint)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint c
    JOIN pg_class t ON c.conrelid = t.oid
    JOIN pg_namespace n ON t.relnamespace = n.oid
    WHERE c.conname = 'consumer_edges_caller_service_id_endpoint_id_key'
      AND n.nspname = 'public'
  ) THEN
    ALTER TABLE public.consumer_edges
      ADD CONSTRAINT consumer_edges_caller_service_id_endpoint_id_key
      UNIQUE (caller_service_id, endpoint_id);
  END IF;
END $$;

-- 5. Enable RLS on all three tables
ALTER TABLE public.services ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.endpoints ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.consumer_edges ENABLE ROW LEVEL SECURITY;

-- 6. RLS policy: users see only their own services
DROP POLICY IF EXISTS "users see own services" ON public.services;
CREATE POLICY "users see own services"
  ON public.services FOR ALL
  USING (user_id = auth.uid());

-- 7. RLS policy: users see only endpoints belonging to their services
DROP POLICY IF EXISTS "users see own endpoints" ON public.endpoints;
CREATE POLICY "users see own endpoints"
  ON public.endpoints FOR ALL
  USING (
    service_id IN (SELECT id FROM public.services WHERE user_id = auth.uid())
  );

-- 8. RLS policy: users see only edges where the caller service is theirs
DROP POLICY IF EXISTS "users see own edges" ON public.consumer_edges;
CREATE POLICY "users see own edges"
  ON public.consumer_edges FOR ALL
  USING (
    caller_service_id IN (SELECT id FROM public.services WHERE user_id = auth.uid())
  );
```

### Column details

| Table | Column | Type | Constraint | Default |
|---|---|---|---|---|
| `services` | `user_id` | `UUID` | FK → `auth.users(id)` ON DELETE CASCADE, nullable | — |
| `services` | `repo_id` | `VARCHAR(255)` | nullable | — |
| `services` | `last_analyzed_at` | `TIMESTAMP` | nullable | `NOW()` |

`user_id` and `repo_id` are nullable in the migration because existing v1 rows have no values for them. The application code (v2-02) will always supply them going forward.

### Why nullable not NOT NULL
Existing v1 rows in `services` have no `user_id` or `repo_id`. Adding a NOT NULL column without a default would fail immediately. Nullable is correct — the application enforces presence at write time, and the unique constraint skips NULL values (standard SQL behavior), so old NULL rows do not conflict with new real rows.

### Old v1 rows after migration
V1 rows will have `user_id = NULL` and `repo_id = NULL`. They become effectively orphaned:
- RLS hides them from any anon-role query (`user_id = auth.uid()` is never true for NULL)
- FastAPI's future `WHERE user_id = $n` queries (v2-02/v2-03) will skip them

They cause no harm but take up space. Once v2-02 is deployed and the app is working, optionally clean them up:
```sql
DELETE FROM services WHERE user_id IS NULL;
-- Cascades to endpoints and consumer_edges via ON DELETE CASCADE
```
Do not run this cleanup as part of this migration — wait until v2-02 is verified.

### Idempotency
All `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` and `DO $$ ... $$` blocks are safe to run more than once. `DROP POLICY IF EXISTS` before `CREATE POLICY` makes the RLS setup re-runnable.

## Test cases

There are no automated pytest or Jest tests for this spec — it is a pure database migration. Verification is manual using the Supabase MCP tool (`execute_sql`) or the Supabase dashboard.

Manual checks to confirm the migration succeeded:

1. **Columns exist** — run:
   ```sql
   SELECT column_name, data_type, is_nullable
   FROM information_schema.columns
   WHERE table_schema = 'public' AND table_name = 'services'
   ORDER BY ordinal_position;
   ```
   Expected: `user_id`, `repo_id`, `last_analyzed_at` appear in the result.

2. **Unique constraints exist** — run:
   ```sql
   SELECT conname, contype
   FROM pg_constraint
   WHERE conrelid IN (
     'public.services'::regclass,
     'public.endpoints'::regclass,
     'public.consumer_edges'::regclass
   );
   ```
   Expected: `services_user_id_repo_id_name_key`, `endpoints_service_id_method_path_key`, `consumer_edges_caller_service_id_endpoint_id_key` all appear with `contype = 'u'`.

3. **RLS is enabled** — run:
   ```sql
   SELECT tablename, rowsecurity
   FROM pg_tables
   WHERE schemaname = 'public'
     AND tablename IN ('services', 'endpoints', 'consumer_edges');
   ```
   Expected: `rowsecurity = true` for all three tables.

4. **Policies exist** — run:
   ```sql
   SELECT policyname, tablename, cmd
   FROM pg_policies
   WHERE schemaname = 'public';
   ```
   Expected: three policies — `"users see own services"`, `"users see own endpoints"`, `"users see own edges"`.

5. **Upsert works** — first look up a real user UUID, then run the upsert twice and confirm the same `id` is returned both times:
   ```sql
   -- Step 1: get a real user UUID (requires at least one user to exist in auth.users)
   SELECT id FROM auth.users LIMIT 1;

   -- Step 2: run this twice, substituting the UUID from step 1 for <uuid>
   INSERT INTO services (name, language, repo_url, user_id, repo_id, last_analyzed_at)
   VALUES ('test-svc', 'python', 'https://github.com/x/y', '<uuid>', 'x/y', NOW())
   ON CONFLICT (user_id, repo_id, name)
   DO UPDATE SET last_analyzed_at = NOW(), language = EXCLUDED.language
   RETURNING id;
   ```
   Both runs must return the same `id`. If `auth.users` is empty, skip this check and verify it after logging in once via the app.

   After verifying, clean up the test row:
   ```sql
   DELETE FROM services WHERE name = 'test-svc' AND repo_id = 'x/y';
   ```

## Done when

- [ ] `services` table has `user_id UUID`, `repo_id VARCHAR(255)`, and `last_analyzed_at TIMESTAMP` columns
- [ ] `UNIQUE (user_id, repo_id, name)` constraint exists on `services`
- [ ] `UNIQUE (service_id, method, path)` constraint exists on `endpoints`
- [ ] `UNIQUE (caller_service_id, endpoint_id)` constraint exists on `consumer_edges`
- [ ] RLS is enabled on `services`, `endpoints`, and `consumer_edges`
- [ ] `"users see own services"` policy exists on `services`
- [ ] `"users see own endpoints"` policy exists on `endpoints`
- [ ] `"users see own edges"` policy exists on `consumer_edges`
- [ ] All five manual checks above pass
- [ ] No application code was changed (this spec is DB-only)
