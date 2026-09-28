# ADR 0008: Plugins: trusted in-process v1 with a serializable async boundary; sandboxed iframe UIs

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

PlanHaven must be extensible (first plugin: a cut-list optimizer; later a vehicle log, a Home
Assistant bridge, and so on) (A§1.1, A§14). Fully isolating plugins from day one (separate
processes or containers, RPC, resource limits) is a lot of work before a single plugin exists.
In-process plugins with free access to internals, however, can never be isolated later
without rewriting them.

## Options considered

1. **In-process plugins with direct access to app internals.** Fastest to build. Plugins
   couple to internal models and can never be isolated.
2. **Out-of-process plugins from v1** (subprocess or sidecar with RPC). Real isolation. Large
   upfront cost; a single-container install makes sidecars awkward.
3. **In-process in v1, behind an isolation-ready boundary.** Plugins see only `PluginContext`:
   async methods, serializable data. That interface can later be backed by RPC without
   changing plugin code. In v1 the boundary is advisory against malicious code.

## Decision

Option 3 (A§14):

- Plugins are trusted, installed only by an admin, and loaded from the bundled `plugins/`
  directory and `/config/plugins`. There is no marketplace or install-from-URL.
- Plugins use only `PluginContext`, and import only the published SDK (`sdk/python`), never
  `backend/app/**`. Enforced with `import-linter`.
- A `plugin.toml` manifest declares permissions; `PluginContext` enforces them.
- Plugin data lives in `plugin_data` JSON documents under RLS. Plugins create no tables in v1.
- Plugin UIs run in `<iframe sandbox="allow-scripts">` **without** `allow-same-origin`, and
  talk to the app only through a validated `postMessage` bridge (`sdk/js`), under a strict
  per-plugin CSP.

## Consequences

- Plugin backend code runs with full app privileges in v1. Accepted risk in S§10; mitigated
  by admin-only install and first-party plugins.
- Plugin UIs can't read cookies, storage or the parent page.
- The path to isolation (separate UID and socket RPC, then sidecars, then signing) needs no
  plugin rewrites (A§14.8).
- The plugin API is frozen as v1 with the cut-list plugin (phase 0.7 since ADR 0013), with
  `docs/plugin-api.md`. Plugins declare
  `api_version`.
- The SDK is Apache-2.0 (ADR 0010), so plugin authors can pick any license.
