# AGENTS.md

## Project Scope

This repository is the open-source SecondBrain CLI toolkit.

- Toolkit repo: `MySecondBrain-CLI`
- Default bundled vault: `vault-template/`
- Default CLI entry: `python cli/secondbrain.py --vault vault-template <command>`

The repository no longer assumes any private external vault path.

## Agent Objective

Use this repository in two layers:

1. Maintain the CLI and supporting docs/config in the toolkit root.
2. Treat `vault-template/` as the default sample vault for user workflows, templates, and architecture examples.

## Directory Contract

Agents should preserve these bundled vault folders:

- `vault-template/00_System/`: rules, templates, dashboards
- `vault-template/02_Daily/`: daily/session records
- `vault-template/03_Projects/`: ideas/active/backlog/closed
- `vault-template/04_Resources/`: inbox/library
- `vault-template/05_Thinking/`: insights and evergreen notes
- `vault-template/06_PersonalLife/`: personal planning and diet areas
- `vault-template/07_Articles/`: drafts/scheduled/published
- `vault-template/08_Attachments/`: binary assets
- `vault-template/99_Archive/`: historical archive

## Safety Rules

1. Do not delete user notes directly.
2. Prefer move-to-archive over destructive deletion.
3. Write UTF-8 markdown.
4. When changing structure, keep folder semantics consistent.
5. When editing defaults, prefer generic values over author-specific paths or usernames.

## Command Integration

Typical commands in this repository:

- `python cli/secondbrain.py --vault vault-template today`
- `python cli/secondbrain.py --vault vault-template start-session`
- `python cli/secondbrain.py --vault vault-template daily-wrapup --date today --archive`

If the user provides another vault path, use that explicit `--vault` value instead.

## Push Boundary

- `daily-wrapup --push` pushes the git repository that contains the effective `--vault` path.
- If `--vault vault-template` is used, push scope is this repository.
- If the user wants vault history isolated from toolkit history, they must first copy `vault-template/` to another directory or repository and run with that `--vault` path.

## Collaboration Notes

- Keep templates and system docs readable by both humans and agents.
- Prefer deterministic filenames and predictable headings.
- Keep metadata/frontmatter generic by default and locally overridable where possible.
