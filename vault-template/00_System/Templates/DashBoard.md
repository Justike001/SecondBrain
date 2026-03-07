---
type: system
status: active
area: system
created: {{date}}
updated: {{updated}}
owner: {{owner}}
authoring: mixed
tags: [dashboard, system]
---

# Dashboard

## Projects Health
```dataview
table status, updated
from "03_Projects"
where contains(file.path, "Active") or contains(file.path, "Backlog") or contains(file.path, "Closed")
sort updated desc
```

## Resource Pipeline
```dataview
table status, source_type, created
from "04_Resources"
sort created desc
```

## Articles Pipeline
```dataview
table status, publish_status, updated
from "07_Articles"
sort updated desc
```

## Memory / Thinking Evolution
```dataview
list
from "05_Thinking"
sort updated desc
limit 20
```

## Today Entry Points
- Today DailyNote: [[02_Daily]]
- Today DailyPlan: [[02_Daily]]

