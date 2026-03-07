# Install.md

## Purpose

This file is for agents and automation, not end users.

When operating this repository, assume the default vault is the bundled template at `./vault-template`.
Do not assume any separate private vault repository exists.

## Default Operating Rule

- Repository root: current working copy of `MySecondBrain-CLI`
- Default vault path: `vault-template`
- Default CLI entry: `python cli/secondbrain.py`

Preferred command pattern:

```bash
python cli/secondbrain.py --vault vault-template <command>
```

Examples:

```bash
python cli/secondbrain.py --vault vault-template today
python cli/secondbrain.py --vault vault-template start-session
python cli/secondbrain.py --vault vault-template capture --fetch --resource-type article https://example.com
python cli/secondbrain.py --vault vault-template doctor
```

## Agent Assumptions

- Treat `vault-template/` as the working vault unless the user explicitly provides another `--vault` path.
- Treat `vault-template/00_System/Templates/` as the template source of truth.
- Treat `vault-template/00_System/` as the system layer for dashboards, base files, memory, and agent-facing docs.
- Do not reference any private external vault path in docs, commands, or examples.
- Do not require a second repository just to run the CLI.
- If `config/local.json` exists, treat it as the local private override for `vault_path` and `owner`.

## Push Boundary

`daily-wrapup --push` pushes the git repository that contains the effective `--vault` path.

Implication:

- If `--vault vault-template` is used and `vault-template/` is inside this repository, a push targets this repository.
- If the user wants vault history isolated from CLI history, they must first copy `vault-template/` into a separate folder or separate repository and then pass that path with `--vault`.

## If a User Wants a Real Personal Vault

Use this migration model:

1. Copy `vault-template/` to a user-owned vault directory.
2. Keep the structure and templates intact.
3. Run the CLI with `--vault <user-vault-path>`.
4. Only use `--push` after confirming the target repository is the intended one.

Example:

```bash
python cli/secondbrain.py --vault D:/path/to/my-vault today
```

## Validation Checklist

Before reporting success, agents should verify:

1. `vault-template/00_System/Templates/` exists.
2. `python cli/secondbrain.py --vault vault-template doctor` runs.
3. Commands and docs do not mention private usernames, private paths, or private repository URLs.

## Non-Goals

- Do not recreate a “Repo A / Repo B” split in public-facing docs by default.
- Do not describe a private vault as if it were required for normal setup.
- Do not use author-specific filesystem paths in examples.
