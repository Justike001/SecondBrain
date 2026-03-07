# Metadata Schema

## Common Frontmatter

```yaml
---
type: system | daily | session | project | resource | thinking | report | article | agents | personal | diet-record
status: inbox | active | backlog | closed | draft | review | scheduled | published | done | archived
created: YYYY-MM-DD
updated: YYYY-MM-DD
owner: user
authoring: human | agent | mixed
tags: []
---
```

## Hierarchy Mapping (Recommended)

```yaml
area: system | inbox | daily | projects | resources | thinking | personal | articles | archive
```

- `03_Projects/Active|Backlog|Closed` -> `type: project`, `status: active|backlog|closed`, `area: projects`
- `04_Resources/Inbox|Library` -> `type: resource`, `status: inbox|active`, `area: resources`
- `06_PersonalLife/Active|Backlog|Closed` -> `type: personal`, `status: active|backlog|closed`, `area: personal`
- `06_PersonalLife/Active/Diet/餐食记录.md` -> `type: diet-record`, `status: active`, `area: personal`
- `07_Articles/Drafts|Scheduled|Published` -> `type: article`, `status: draft|scheduled|published`, `area: articles`
- `99_Archive/**` -> keep original `type`, set `status: archived`, `area: archive`

## Resource Fields

```yaml
source_url: "https://..."
captured_at: YYYY-MM-DD
source_type: web | youtube | paper | repo | tweet | rss | book | podcast | note | other
signal: 1-5
reliability: A | B | C
related_projects: []
```

## Project Fields

```yaml
goal: "one-line goal"
next_action: "next step"
priority: P0 | P1 | P2
due: YYYY-MM-DD
agents_doc: "[[AGENTS]]"
```

## Article Fields

```yaml
platforms: [xhs, zhihu, twitter, medium]
publish_status: draft | review | scheduled | published
publish_url: ""
```
