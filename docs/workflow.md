# Workflow

## Core Flow

1. `today` to create/open the daily note.
2. `start-session` to capture focused work sessions.
3. `capture-url <url>` to put web resources into inbox for review.
4. `promote-resource <ref>` to move reviewed inbox resources into library/canonical folders.
5. `close` to consolidate daily signals and auto-run archive (configurable).
6. `archive-daily --older-than <days>` remains available for manual runs.

## Personal Diet Logging

1. Use `diet-log` whenever you finish a meal.
2. Provide `meal`, `foods`, `carbs`, `protein`, `fat`; kcal is auto-calculated if omitted.
3. Entries are written to `06_PersonalLife/Active/Diet/餐食记录.md`.
4. Same day + same meal updates in place (idempotent), and daily totals are auto-recomputed.

## Canonical vs Inbox

- Inbox: `04_Resources/Inbox`
- Canonical: `04_Resources/Library`, `05_Thinking`

## Project Lifecycle (MVP)

1. `project-new "Name"` scaffolds project folder/docs.
2. Work inside `03_Projects/Active`.
3. `project-close "Name"` archives the project and creates a report note.
