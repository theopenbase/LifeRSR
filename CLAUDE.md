# CLAUDE.md

## gstack

Use the `/browse` skill from gstack for all web browsing. Never use `mcp__Claude_in_Chrome__*` tools.

### Available skills

- `/office-hours` — YC-style brainstorming and idea validation
- `/plan-ceo-review` — CEO/founder-mode plan review
- `/plan-eng-review` — Engineering manager plan review
- `/plan-design-review` — Designer's eye plan review
- `/design-consultation` — Create a design system and DESIGN.md
- `/review` — Pre-landing PR code review
- `/ship` — Ship workflow (test, review, bump, push, PR)
- `/browse` — Fast headless browser for QA and dogfooding
- `/qa` — Systematic QA testing with automatic bug fixes
- `/qa-only` — Report-only QA testing (no fixes)
- `/design-review` — Visual design audit with fixes
- `/setup-browser-cookies` — Import cookies for authenticated testing
- `/retro` — Weekly engineering retrospective
- `/debug` — Systematic debugging with root cause analysis
- `/document-release` — Post-ship documentation updates
- `/codex` — Second opinion via OpenAI Codex CLI
- `/careful` — Safety guardrails for destructive commands
- `/freeze` — Restrict edits to a specific directory
- `/guard` — Maximum safety mode (careful + freeze)
- `/unfreeze` — Remove edit restrictions
- `/gstack-upgrade` — Upgrade gstack to latest version

### Troubleshooting

If gstack skills aren't working, run `cd .claude/skills/gstack && ./setup` to build the binary and register skills.
