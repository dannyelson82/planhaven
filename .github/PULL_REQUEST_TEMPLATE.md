## What does this change?

<!-- Short description and linked issue -->

## Architecture

- [ ] Consistent with ARCHITECTURE.md (or this PR updates it)
- [ ] New significant decision recorded as an ADR in `docs/adr/`
- [ ] User guide (`docs/user-guide/`) updated: features added, changed or removed

## Security checklist

- [ ] New/changed routes added to the authz test matrix
- [ ] Any new user-content table has RLS enabled **and** forced, with policies
- [ ] Input validated with explicit limits; no raw SQL string building
- [ ] No secrets, tokens, or user content written to logs
- [ ] No new outbound network destinations (or documented in SECURITY.md §7.8)
- [ ] New dependencies reviewed (maintenance, license, known CVEs)
- [ ] Threat model in SECURITY.md updated, or "no new threats" explained below

<!-- Explain any unchecked items -->
