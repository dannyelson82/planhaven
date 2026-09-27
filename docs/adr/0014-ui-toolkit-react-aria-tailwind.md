# ADR 0014: UI toolkit: React Aria Components with Tailwind CSS

- **Status:** Accepted
- **Date:** 2026-09-27
- **Resolves:** the UI component library question in ARCHITECTURE.md §19.2.

## Context

The frontend (ADR 0001) needs accessible, touch-friendly components (buttons, menus, dialogs,
date pickers, lists) that work equally well on phones and desktops (A§13.5) and under the strict
CSP (`style-src 'self'`, S§7.10), without runtime-injected `<style>` elements.

## Options considered

1. **React Aria Components** (Adobe, Apache-2.0) + **Tailwind CSS** (MIT). Unstyled
   components with best-in-class accessibility and touch/pointer handling; styles compile
   to a static CSS file. More styling work.
2. **Radix primitives + shadcn/ui on Tailwind** (MIT). Quick polished look; accessibility good;
   touch handling less thorough.
3. **Mantine** (MIT). Complete styled library, fastest to build; injects CSS variables at runtime
   (needs a CSP nonce); more generic look.

## Decision

Option 1, chosen by the maintainer. TanStack Query (already in A§5) handles data fetching.

## Consequences

- All styles ship as one static, hashed CSS file: the CSP stays `style-src 'self'`.
- Mobile-first Tailwind breakpoints implement A§13.5; React Aria provides keyboard, screen
  reader and touch behaviour.
- We maintain our own small design system (colours, spacing, component styles).
