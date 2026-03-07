---
type: daily-plan
status: open
area: daily
created: {{date}}
updated: {{updated}}
owner: {{owner}}
authoring: mixed
tags: [daily-plan]
---

# Daily Plan - {{date}}

## From Yesterday
### Yesterday Summary
从昨日 DailyNote 提取：
- 

### Unfinished Tasks
- [ ] 

## Work Projects
```dataview
task
from "03_Projects"
where !completed
```

## Life Projects
```dataview
task
from "06_PersonalLife"
where !completed
```

## Resource Review
```dataview
table created, status
from "04_Resources/Inbox"
limit 10
```

## Today Focus
- [ ] 
- [ ] 
- [ ] 

## Time Blocks
### Morning

### Afternoon

### Evening

## Thinking Prompts
- 

## End of Day Checklist
- [ ] 今日计划是否完成
- [ ] Sessions 是否整理
- [ ] DailyNote 是否完成 Close

