# Planhaven

**From idea to done.**

Self-hosted project manager for home, vehicle, and maker projects, from the first idea to done.
Shopping lists and tasks sync to your iPhone, local AI answers questions about your projects and
their documents, and commercial AI assistants can brainstorm with you through an MCP connector.

> **Status:** v0.1.0: secure foundation (sign-in, projects and tasks). Early; more features
> arrive phase by phase (see ARCHITECTURE.md §18).

## Planned features

- Projects with stages (Idea → Planning → Ready → In progress → Done), tasks, lists, notes,
  attachments, assets (vehicles, boat, house), contacts and quotes
- Multi-user with per-project sharing (owner / editor / viewer)
- Chores for the household: scheduled, assigned tasks with phone reminders and photo proof
- A time planner that works around a work rotation: rest first, finish what you started
- Works on phone and desktop: one responsive web app, installable as a PWA
- iPhone: Reminders sync via Apple Shortcuts, calendar feed, push notifications, installable PWA
- Local AI (Ollama / OpenAI-compatible) Q&A over projects and attachments
- MCP connector for Claude, ChatGPT, and other assistants (OAuth protected)
- Plugin system (first plugin: plywood / sheet-goods cut list optimizer)
- Single Docker image; Unraid Community Applications template
- Built to be exposed to the internet: mandatory 2FA, passkeys, row-level security, signed images

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — how it's built and why
- [SECURITY.md](SECURITY.md) — threat model, security controls, and how to report vulnerabilities
- [docs/backup-restore.md](docs/backup-restore.md) — backups and restoring them
- [docs/repo-setup.md](docs/repo-setup.md) — GitHub repository hardening checklist
- [docs/adr/](docs/adr/) — architecture decision records
- [docs/roadmap/phase-0.1.md](docs/roadmap/phase-0.1.md) — current phase checklist
- [docs/roadmap/](docs/roadmap/) — current phase checklist

## Reporting security issues

Please use GitHub private vulnerability reporting. See [SECURITY.md](SECURITY.md).

## License

Apache License 2.0; see [LICENSE](LICENSE) and [NOTICE](NOTICE). The Planhaven name and logo
are not covered by the license. Rationale: [ADR 0010](docs/adr/0010-license-apache-2.md).
