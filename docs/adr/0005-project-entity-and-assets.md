# ADR 0005: Single Project entity with stages; Assets as first-class

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

PlanHaven must handle both one-off work (remodel the garage) and recurring work tied to a
durable thing (oil change on the truck, winterizing the boat) (A§1). Ideas often become
projects later. A separate "Job" or "Idea" entity would split the same kind of work across
two models and complicate sharing, AI context and plugins.

## Options considered

1. **One Project entity with a lifecycle stage.** One model for ideas through archived work;
   sharing, notes, attachments and AI context work the same everywhere. Stages must stay
   informational to avoid a rigid workflow.
2. **Separate Idea, Project and Job entities.** Each can be tailored. Converting between them
   duplicates data and multiplies authz rules and API routes.
3. **Assets as free-text tags only.** Simple. Loses service history, meters (mileage) and
   sharing of the asset itself.

## Decision

- A single **Project** entity with stages Idea → Planning → Ready → In progress → Done →
  Archived, reopenable. Stages are informational and never block transitions; a stage change
  is a domain event (A§7.3).
- **Asset** is a first-class, shareable entity (vehicle, boat, house, dock, home lab, tool)
  with a kind and free-form metadata. Projects optionally relate to an asset (A§7.1).
- Recurrence lives on the Project as a template (RRULE subset or an asset meter) (A§7.4).

## Consequences

- One membership model (owner / editor / viewer) and one RLS helper covers all work (ADR 0004).
- An asset's projects form its service history without an extra entity.
- Asset metadata is free-form JSON; validation per asset kind may be added later.
- Recurrence by asset meter (e.g. every 8,000 km) needs meter readings; scheduled after v1
  (A§18 "Later").
