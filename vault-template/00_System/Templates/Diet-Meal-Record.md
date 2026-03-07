---
type: diet-record
status: active
created: {{date}}
updated: {{updated}}
owner: {{owner}}
authoring: mixed
source_url: "{{source_url}}"
tags: [lifeproject, diet, log]
---

# 餐食记录

## Daily Targets

### 训练日（工作日）
- 热量：约 2550 kcal
- 碳水：约 320 g
- 蛋白：约 205 g
- 脂肪：<= 45 g

### 休息日（周日）
- 热量：约 2350 kcal
- 碳水：约 260 g
- 蛋白：约 205 g
- 脂肪：<= 50 g

## Recording Rules
- `kcal` 可直接填写；留空时由命令按 `carbs*4 + protein*4 + fat*9` 自动计算。
- 同一天同餐次重复写入会覆盖更新，避免重复记录。
- 每日总计由命令自动重算。

## CLI Quick Commands
```bash
python cli/secondbrain.py diet-log --day-type training --meal breakfast --carbs 44.5 --protein 32.4 --fat 18.2 --foods "55g燕麦+150g牛奶+100g全蛋+50g蛋白"
python cli/secondbrain.py diet-log --day-type rest --meal dinner --carbs 90 --protein 60 --fat 10 --foods "115g生大米+220g鸡胸肉+5g橄榄油"
```

## Daily Logs

