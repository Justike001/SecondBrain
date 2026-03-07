# Troubleshooting

## Obsidian CLI Not Available

This MVP uses filesystem operations only and does not require Obsidian CLI.

## Wrong Vault Path

- Pass `--vault <path>` explicitly, or
- set `VAULT_PATH`, or
- edit `config/default.json`.

## Unicode/Path Issues on Windows

- Project and file names are sanitized to avoid invalid characters.
- Keep vault path on a normal local path (avoid restricted/system dirs).

## Archive Command Moved Nothing

- Check date in filename (`YYYY-MM-DD`) for daily/session notes.
- Confirm `--older-than` threshold is lower than note age.
