---
type: system
status: active
area: system
owner: user
authoring: mixed
tags: [dashboard, system]
---

# Dashboard

## 用途
这个页面是 vault 的总览入口，不是静态说明页。
正常打开后，你应该把它当成一个查询面板，用来快速看项目、资源、文章和思考笔记的当前状态。

## Projects Health
```dataview
TABLE status, priority, updated, due, next_action
FROM "03_Projects"
WHERE contains(file.path, "Active") OR contains(file.path, "Backlog")
SORT due ASC
```

## Resource Pipeline
```dataview
TABLE status, source_type, signal, reliability, created, source_url
FROM "04_Resources"
SORT created DESC
```

## Articles Pipeline
```dataview
TABLE status, publish_status, updated
FROM "07_Articles"
SORT updated DESC
```

## Thinking Recent
```dataview
LIST
FROM "05_Thinking"
SORT updated DESC
LIMIT 20
```

## Daily Entry Points
- Daily Notes: [[02_Daily]]
- Today Dashboard Source: [[00_System/Dashboard]]
- Templates: [[00_System/Templates]]

