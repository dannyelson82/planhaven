# ADR 0010: License the project under Apache-2.0

- **Status:** Accepted
- **Date:** 2026-09-27

## Context

The repository is public and needs a license before it accepts contributions or publishes an
image. ARCHITECTURE.md §19.2 left two linked questions open: the project license, and which
PDF extraction library we may use (the leading high-performance option, PyMuPDF, is AGPL-3.0
unless a commercial license is bought).

Relevant constraints:

- PlanHaven is a self-hosted household app, distributed as a Docker image and an Unraid
  Community Applications template. There is no hosted service to protect.
- Plugins run in-process in v1 (A§14) and import the Python SDK. Their authors should not face
  licensing surprises.
- The name "PlanHaven" should stay protected independently of the code license.

Licenses of the planned dependencies, checked on PyPI and npm on 2026-09-27:

| License | Packages |
|---|---|
| MIT / BSD / ISC / Apache-2.0 | FastAPI, Pydantic, SQLAlchemy, Alembic, asyncpg, procrastinate, argon2-cffi, webauthn, pyotp, cryptography, mcp, pypdf, pdfplumber, pdfminer.six, pypdfium2, python-docx, openpyxl, pytesseract, Pillow (MIT-CMU), Uvicorn, import-linter, pgvector, React, TanStack Query, Vite, vite-plugin-pwa, Radix, Mantine |
| LGPL-3.0 | psycopg |
| AGPL-3.0 (or commercial) | PyMuPDF |

## Options considered

1. **AGPL-3.0.** Anyone offering a modified PlanHaven as a network service must publish their
   changes. Allows PyMuPDF. But in-process plugins would likely have to be AGPL (unless the
   SDK is licensed separately), many companies forbid AGPL contributions, and relicensing
   later needs every contributor's consent. The threat it guards against, a closed hosted
   fork, is unlikely for a household project tracker.
2. **MIT.** Simplest and most widely accepted. No patent grant; says nothing about trademarks.
3. **Apache-2.0.** Permissive like MIT, plus an explicit patent grant and patent-retaliation
   clause (§3), an explicit exclusion of trademark rights (§6), and inbound = outbound
   contribution terms (§5). Compatible with GPL-3.0/AGPL-3.0 if that is ever needed. Costs a
   `NOTICE` file.

## Decision

**Apache-2.0** for the whole repository: core, `sdk/`, bundled plugins, the Apple Shortcut and
deployment files. The copyright holder is recorded in `NOTICE`.

No CLA: contributions are accepted under Apache-2.0 §5.

Dependency license policy:

- **Allowed:** MIT, MIT-0, BSD (any clause count), ISC, Apache-2.0, PSF, Zlib, MIT-CMU, and
  similar permissive licenses; MPL-2.0 for unmodified use.
- **Allowed with care:** LGPL, used unmodified as a separately installed library (e.g.
  psycopg; asyncpg is the Apache alternative). Record it in the PR.
- **Not allowed as dependencies:** GPL, AGPL, SSPL, BUSL, "Commons Clause", non-commercial or
  other source-available licenses.
- Programs bundled in the image as separate executables (PostgreSQL, Tesseract, Debian base
  packages, some of which are GPL) are aggregation, not linking. They are allowed, and their
  licenses are listed in the SBOM.

PDF extraction: **PyMuPDF is excluded.** Use pypdfium2 (PDFium; BSD/Apache) for text and page
rendering for OCR, with pypdf/pdfplumber where they fit. The final choice is made in phase 0.5.

## Consequences

- Plugin authors can use any license for their plugins; the SDK is Apache-2.0.
- Anyone may run a closed, modified fork, including as a hosted service. Accepted.
- The name is protected by trademark (owner's CIPO/USPTO checks pending), not by the license.
- A license check (e.g. `pip-licenses` and `license-checker` against the policy above) is
  added to CI in phase 0.1, alongside the dependency review in the PR template.
- Security impact: none directly. The patent clause and a clear dependency policy reduce
  supply-chain and legal risk; see SECURITY.md §8.
