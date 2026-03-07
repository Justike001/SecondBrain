#!/usr/bin/env python3
import argparse
import hashlib
import json
import mimetypes
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


APP_TZ = "local"
APP_ZONE = None
APP_OWNER = "user"
EN_MONTHS = (
    "",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def set_app_timezone(tz_name: str | None) -> None:
    global APP_TZ, APP_ZONE
    candidate = (tz_name or "local").strip() or "local"
    APP_TZ = candidate
    if candidate.lower() in ("local", "system", "auto"):
        APP_ZONE = datetime.now().astimezone().tzinfo
        return
    try:
        APP_ZONE = ZoneInfo(candidate)
    except Exception:
        APP_ZONE = datetime.now().astimezone().tzinfo


def set_app_owner(owner_name: str | None) -> None:
    global APP_OWNER
    candidate = (owner_name or "").strip()
    APP_OWNER = candidate or "user"


def current_owner() -> str:
    return APP_OWNER


def now_localized() -> datetime:
    if APP_ZONE is None:
        return datetime.now().astimezone()
    return datetime.now(APP_ZONE)


def today_date() -> date:
    return now_localized().date()


def resolve_human_date(text: str | None) -> date:
    raw = (text or "today").strip()
    low = raw.lower()
    base = today_date()
    if low in ("today", "今天", "今日"):
        return base
    if low in ("yesterday", "昨天"):
        return base - timedelta(days=1)
    if low in ("day before yesterday", "前天"):
        return base - timedelta(days=2)
    m = re.match(r"^(\d+)\s*days?\s*ago$", low)
    if m:
        return base - timedelta(days=int(m.group(1)))
    m = re.match(r"^(\d+)\s*天前$", raw)
    if m:
        return base - timedelta(days=int(m.group(1)))
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except Exception:
            continue
    raise ValueError(f"unsupported date input: {text}")


def _default_config() -> dict:
    return {
        "vault_path": "vault-template",
        "timezone": "local",
        "archive_threshold_days": 30,
        "auto_archive_on_close": True,
        "graduate_window_days": 7,
        "templates_path": "00_System/Templates",
        "dashboards_mode": "dataview",
        "owner": "user",
    }


def load_config(config_path: Path, repo_root: Path) -> dict:
    config = _default_config()
    if config_path.exists():
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            config.update(raw)
    local_config_path = repo_root / "config" / "local.json"
    if local_config_path != config_path and local_config_path.exists():
        raw = json.loads(local_config_path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            config.update(raw)
    owner_from_env = (os.getenv("SECOND_BRAIN_OWNER") or "").strip()
    if owner_from_env:
        config["owner"] = owner_from_env
    return config


def load_agent_reach_config(repo_root: Path) -> dict:
    defaults = {
        "enabled": True,
        "command": "",
        "args": ["{url}"],
        "timeout": 45,
        "output_format": "auto",  # auto | markdown | text | json
        "json_field": "markdown",
    }
    cfg_path = repo_root / "config" / "agent-reach.json"
    if not cfg_path.exists():
        return defaults
    try:
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return defaults
    if not isinstance(raw, dict):
        return defaults
    merged = defaults.copy()
    merged.update(raw)
    command = merged.get("command")
    if isinstance(command, list):
        resolved: list[str] = []
        for idx, part in enumerate(command):
            piece = str(part)
            prev = str(command[idx - 1]).lower() if idx > 0 else ""
            if piece and not os.path.isabs(piece):
                if prev in ("-file", "/file"):
                    piece = str((repo_root / piece).resolve())
            resolved.append(piece)
        merged["command"] = resolved
    return merged


def resolve_vault(args, config: dict, repo_root: Path) -> Path:
    candidate = args.vault or os.getenv("VAULT_PATH") or config.get("vault_path", "vault-template")
    p = Path(candidate)
    if not p.is_absolute():
        p = (repo_root / p).resolve()
    return p


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(path.parent)) as tmp:
        tmp.write(content)
        tmp_name = tmp.name
    os.replace(tmp_name, path)


def today_str() -> str:
    return today_date().isoformat()


def now_iso() -> str:
    return now_localized().strftime("%Y-%m-%d")


def sanitize_name(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]+', "-", name).strip()


def slugify_topic(text: str) -> str:
    seed = sanitize_name((text or "").strip().lower())
    seed = seed.replace(" ", "-")
    seed = re.sub(r"[^a-z0-9\u4e00-\u9fff._-]+", "-", seed)
    seed = re.sub(r"-{2,}", "-", seed).strip("-._")
    return seed or "resource"


RESEARCH_ROUTE_MAP = {
    "inbox": ("04_Resources/Inbox", "resource", "inbox"),
    "library": ("04_Resources/Library", "resource", "active"),
    "thinking": ("05_Thinking", "thinking", "draft"),
}

DIET_RECORD_REL_PATH = "06_PersonalLife/Active/Diet/餐食记录.md"
DIET_TEMPLATE_NAME = "Diet-Meal-Record.md"
DIET_LOGS_HEADING = "## Daily Logs"
DIET_DAY_TYPE_ALIASES = {
    "training": ("training", "训练日"),
    "train": ("training", "训练日"),
    "workday": ("training", "训练日"),
    "训练": ("training", "训练日"),
    "训练日": ("training", "训练日"),
    "rest": ("rest", "休息日"),
    "off": ("rest", "休息日"),
    "休息": ("rest", "休息日"),
    "休息日": ("rest", "休息日"),
}
DIET_MEAL_ORDER = [
    "第一餐（早餐）",
    "第二餐（午餐）",
    "第三餐（练前/加餐）",
    "第四餐（晚餐）",
]
DIET_MEAL_ALIASES = {
    "meal1": "第一餐（早餐）",
    "breakfast": "第一餐（早餐）",
    "早餐": "第一餐（早餐）",
    "第一餐": "第一餐（早餐）",
    "meal2": "第二餐（午餐）",
    "lunch": "第二餐（午餐）",
    "午餐": "第二餐（午餐）",
    "第二餐": "第二餐（午餐）",
    "meal3": "第三餐（练前/加餐）",
    "preworkout": "第三餐（练前/加餐）",
    "snack": "第三餐（练前/加餐）",
    "练前": "第三餐（练前/加餐）",
    "加餐": "第三餐（练前/加餐）",
    "第三餐": "第三餐（练前/加餐）",
    "meal4": "第四餐（晚餐）",
    "dinner": "第四餐（晚餐）",
    "晚餐": "第四餐（晚餐）",
    "第四餐": "第四餐（晚餐）",
}
LIFE_AREAS = ("Diet", "Exercise", "Reading", "General")
ARTICLE_STATE_DIR = {
    "draft": "Drafts",
    "scheduled": "Scheduled",
    "published": "Published",
}


def _month_folder(d: date) -> str:
    return f"{d.year}-{EN_MONTHS[d.month]}"


def _daily_month_root(vault: Path, d: date, *, ensure: bool = False) -> Path:
    root = vault / "02_Daily" / f"{d.year}" / _month_folder(d)
    if ensure:
        for child in ("DailyNotes", "Sessions", "Weekly", "Monthly"):
            (root / child).mkdir(parents=True, exist_ok=True)
    return root


def daily_note_path(vault: Path, d: date, *, ensure: bool = False) -> Path:
    return _daily_month_root(vault, d, ensure=ensure) / "DailyNotes" / f"{d.isoformat()}.md"


def daily_sessions_dir(vault: Path, d: date, *, ensure: bool = False) -> Path:
    return _daily_month_root(vault, d, ensure=ensure) / "Sessions"


def daily_plan_path(vault: Path, d: date, *, ensure: bool = False) -> Path:
    root = _daily_month_root(vault, d, ensure=ensure)
    plan_dir = root / "DailyPlan"
    if ensure:
        plan_dir.mkdir(parents=True, exist_ok=True)
    return plan_dir / f"{d.isoformat()}.md"


def archive_daily_target_dir(vault: Path, d: date, kind: str, *, ensure: bool = False) -> Path:
    root = vault / "99_Archive" / "Daily" / f"{d.year}" / _month_folder(d)
    if ensure:
        for child in ("DailyNotes", "Sessions", "Weekly", "Monthly"):
            (root / child).mkdir(parents=True, exist_ok=True)
    if kind == "daily":
        return root / "DailyNotes"
    return root / "Sessions"


def slugify_url(url: str) -> str:
    parsed = urlparse(url)
    seed = (parsed.netloc + "-" + parsed.path).strip("-/ ")
    seed = re.sub(r"[^a-zA-Z0-9._-]+", "-", seed.lower())
    seed = re.sub(r"-{2,}", "-", seed).strip("-")
    digest = hashlib.sha1(url.strip().encode("utf-8")).hexdigest()[:10]
    return f"{seed or 'resource'}-{digest}"



def topic_from_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    host = (parsed.netloc or "").strip().lower()
    path = (parsed.path or "").strip("/")
    if path:
        last = path.split("/")[-1]
        seed = f"{host}-{last}" if host else last
    else:
        seed = host or "resource"
    seed = seed.replace(".", "-")
    return slugify_topic(seed)


def from_who_from_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    return (parsed.netloc or "").strip().lower()


def _strip_wrapped(v: str) -> str:
    s = (v or "").strip()
    if len(s) >= 2 and ((s[0] == s[-1] == '"') or (s[0] == s[-1] == "'")):
        return s[1:-1]
    return s

def is_http_url(text: str) -> bool:
    try:
        u = urlparse((text or "").strip())
        return u.scheme in ("http", "https") and bool(u.netloc)
    except Exception:
        return False


def render_template(template_path: Path, replacements: dict) -> str:
    content = template_path.read_text(encoding="utf-8")
    merged = {"owner": current_owner()}
    merged.update(replacements)
    for k, v in merged.items():
        content = content.replace("{{" + k + "}}", v)
    return content


def render_resource_from_template(
    vault: Path,
    templates_path: str,
    template_name: str,
    *,
    day: str,
    updated: str,
    topic: str,
    source_url: str,
    from_who: str,
    resource_type: str,
    source_type: str,
) -> str:
    t = vault / templates_path / template_name
    return render_template(
        t,
        {
            "date": day,
            "updated": updated,
            "topic": topic,
            "source_url": source_url,
            "from_who": from_who,
            "resource_type": resource_type,
            "source_type": source_type,
        },
    )


def render_report_template(*, day: str, updated: str, project_name: str) -> str:
    return (
        "---\n"
        "type: report\n"
        "status: closed\n"
        "area: projects\n"
        f"created: {day}\n"
        f"updated: {updated}\n"
        f"owner: {current_owner()}\n"
        "authoring: mixed\n"
        "tags: [report]\n"
        "---\n\n"
        f"# Report - {project_name} ({day})\n\n"
        "## Summary\n"
        "椤圭洰鏀跺熬姒傝堪锛歕n\n"
        "## Outcomes\n"
        "- 缁撴灉 1锛歕n"
        "- 缁撴灉 2锛歕n\n"
        "## Lessons Learned\n"
        "- \n\n"
        "## Follow-ups\n"
        "- [ ] \n"
    )


def ensure_section(content: str, heading: str, default_block: str) -> str:
    if f"\n{heading}\n" in f"\n{content}\n":
        return content
    return content.rstrip() + "\n\n" + default_block.rstrip() + "\n"


def section_span(content: str, heading: str) -> tuple[int, int, int] | None:
    m = re.search(rf"(?m)^{re.escape(heading)}\s*$", content)
    if not m:
        return None
    body_start = m.end()
    if body_start < len(content) and content[body_start : body_start + 1] == "\n":
        body_start += 1
    nxt = re.search(r"(?m)^##\s+", content[body_start:])
    body_end = body_start + nxt.start() if nxt else len(content)
    return (m.start(), body_start, body_end)


def get_section_body(content: str, heading: str) -> str:
    span = section_span(content, heading)
    if not span:
        return ""
    return content[span[1] : span[2]]


def replace_section_body(content: str, heading: str, body: str) -> str:
    span = section_span(content, heading)
    if not span:
        return ensure_section(content, heading, f"{heading}\n{body.rstrip()}\n")
    before = content[: span[1]]
    after = content[span[2] :]
    if not body.endswith("\n"):
        body += "\n"
    return before + body + after


def markdown_bullets(text: str) -> list[str]:
    out = []
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("- "):
            out.append(s)
    return out


def replace_or_add_frontmatter_fields(content: str, fields: dict) -> str:
    bom = "\ufeff" if content.startswith("\ufeff") else ""
    head = content[len(bom) :] if bom else content
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", head, flags=re.S)
    if not m:
        return content
    newline = "\r\n" if "\r\n" in head[:300] else "\n"
    fm = m.group(1)
    body = head[m.end() :]
    lines = fm.splitlines()
    keys = set(fields.keys())
    seen = set()
    out = []
    for line in lines:
        matched = False
        for k, v in fields.items():
            prefix = f"{k}:"
            if line.startswith(prefix):
                out.append(f"{k}: {v}")
                seen.add(k)
                matched = True
                break
        if not matched:
            out.append(line)
    for k in keys - seen:
        out.append(f"{k}: {fields[k]}")
    return bom + f"---{newline}" + newline.join(out) + f"{newline}---{newline}" + body


def remove_frontmatter_fields(content: str, keys: list[str] | tuple[str, ...] | set[str]) -> str:
    bom = "\ufeff" if content.startswith("\ufeff") else ""
    head = content[len(bom) :] if bom else content
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", head, flags=re.S)
    if not m:
        return content
    newline = "\r\n" if "\r\n" in head[:300] else "\n"
    fm = m.group(1)
    body = head[m.end() :]
    deny = {str(k).strip().lower() for k in keys if str(k).strip()}
    out = []
    for line in fm.splitlines():
        if ":" in line:
            k = line.split(":", 1)[0].strip().lower()
            if k in deny:
                continue
        out.append(line)
    return bom + f"---{newline}" + newline.join(out) + f"{newline}---{newline}" + body


def diet_record_path(vault: Path) -> Path:
    return vault / DIET_RECORD_REL_PATH


def render_diet_record_template(*, day: str, updated: str, source_url: str) -> str:
    return (
        "---\n"
        "type: diet-record\n"
        "status: active\n"
        f"created: {day}\n"
        f"updated: {updated}\n"
        f"owner: {current_owner()}\n"
        "authoring: mixed\n"
        f"source_url: \"{source_url}\"\n"
        "tags: [lifeproject, diet, log]\n"
        "---\n\n"
        "# 餐食记录\n\n"
        "## Daily Targets\n\n"
        "### 训练日（工作日）\n"
        "- 热量：约 2550 kcal\n"
        "- 碳水：约 320 g\n"
        "- 蛋白：约 205 g\n"
        "- 脂肪：<= 45 g\n\n"
        "### 休息日（周日）\n"
        "- 热量：约 2350 kcal\n"
        "- 碳水：约 260 g\n"
        "- 蛋白：约 205 g\n"
        "- 脂肪：<= 50 g\n\n"
        "## Recording Rules\n"
        "- `kcal` 可直接填，留空时由宏量自动计算：`carbs*4 + protein*4 + fat*9`\n"
        "- 命令幂等：同一天同餐次会覆盖更新，不会重复追加\n"
        "- 每日总计由系统自动重算\n\n"
        "## CLI Quick Commands\n"
        "```bash\n"
        "python cli/secondbrain.py diet-log --day-type training --meal breakfast --carbs 44.5 --protein 32.4 --fat 18.2 --foods \"55g燕麦+150g牛奶+100g全蛋+50g蛋白\"\n"
        "python cli/secondbrain.py diet-log --day-type rest --meal dinner --carbs 90 --protein 60 --fat 10 --foods \"115g生大米+220g鸡胸肉+5g橄榄油\"\n"
        "```\n\n"
        "## Daily Logs\n"
    )


def ensure_diet_record_note(vault: Path, templates_path: str, source_url: str) -> Path:
    note = diet_record_path(vault)
    if note.exists():
        return note
    template_path = vault / templates_path / DIET_TEMPLATE_NAME
    if template_path.exists():
        content = render_template(
            template_path,
            {
                "date": today_str(),
                "updated": now_iso(),
                "source_url": source_url,
            },
        )
    else:
        content = render_diet_record_template(day=today_str(), updated=now_iso(), source_url=source_url)
    atomic_write(note, content)
    return note


def _parse_numeric_cell(cell: str) -> float | None:
    s = re.sub(r"\*\*", "", (cell or "")).strip()
    if not s:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _fmt_num(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.1f}"


def _escape_table_text(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", "<br>")


def _normalize_day_type(day_type: str) -> tuple[str, str]:
    key = (day_type or "").strip().lower()
    if key in DIET_DAY_TYPE_ALIASES:
        return DIET_DAY_TYPE_ALIASES[key]
    key_raw = (day_type or "").strip()
    if key_raw in DIET_DAY_TYPE_ALIASES:
        return DIET_DAY_TYPE_ALIASES[key_raw]
    raise ValueError(f"unsupported day type: {day_type}")


def _normalize_meal_label(meal: str) -> str:
    raw = (meal or "").strip()
    low = raw.lower()
    if low in DIET_MEAL_ALIASES:
        return DIET_MEAL_ALIASES[low]
    if raw in DIET_MEAL_ALIASES:
        return DIET_MEAL_ALIASES[raw]
    raise ValueError(f"unsupported meal: {meal}")


def _diet_blank_rows() -> dict:
    rows = {}
    for label in DIET_MEAL_ORDER:
        rows[label] = {
            "kcal": None,
            "carbs": None,
            "protein": None,
            "fat": None,
            "foods": "",
        }
    return rows


def _parse_diet_rows(block: str) -> dict:
    rows = _diet_blank_rows()
    for ln in (block or "").splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if len(parts) < 6:
            continue
        meal_cell = re.sub(r"\*\*", "", parts[0]).strip()
        if meal_cell not in rows:
            continue
        rows[meal_cell] = {
            "kcal": _parse_numeric_cell(parts[1]),
            "carbs": _parse_numeric_cell(parts[2]),
            "protein": _parse_numeric_cell(parts[3]),
            "fat": _parse_numeric_cell(parts[4]),
            "foods": parts[5].strip(),
        }
    return rows


def _render_diet_table(rows: dict) -> str:
    total_kcal = 0.0
    total_carbs = 0.0
    total_protein = 0.0
    total_fat = 0.0
    has_any = False
    lines = [
        "| 餐次 | 热量 (kcal) | 碳水 (g) | 蛋白质 (g) | 脂肪 (g) | 具体餐食 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for label in DIET_MEAL_ORDER:
        row = rows.get(label) or {}
        kcal = row.get("kcal")
        carbs = row.get("carbs")
        protein = row.get("protein")
        fat = row.get("fat")
        foods = row.get("foods", "")
        if any(v is not None for v in (kcal, carbs, protein, fat)) or str(foods).strip():
            has_any = True
        total_kcal += float(kcal or 0.0)
        total_carbs += float(carbs or 0.0)
        total_protein += float(protein or 0.0)
        total_fat += float(fat or 0.0)
        lines.append(
            f"| {label} | {_fmt_num(kcal)} | {_fmt_num(carbs)} | {_fmt_num(protein)} | {_fmt_num(fat)} | {_escape_table_text(str(foods))} |"
        )
    lines.append(
        f"| **每日总计** | {_fmt_num(total_kcal) if has_any else ''} | {_fmt_num(total_carbs) if has_any else ''} | {_fmt_num(total_protein) if has_any else ''} | {_fmt_num(total_fat) if has_any else ''} | |"
    )
    return "\n".join(lines) + "\n"


def _diet_day_title(day: str, day_type_label: str) -> str:
    return f"{day} | {day_type_label}"


def _upsert_diet_day_block(logs_body: str, day_title: str, rows: dict) -> str:
    heading = f"### {day_title}"
    new_block = f"{heading}\n" + _render_diet_table(rows)
    body = logs_body or ""
    m = re.search(rf"(?m)^{re.escape(heading)}\s*$", body)
    if not m:
        stripped = body.rstrip()
        if stripped:
            return stripped + "\n\n" + new_block
        return new_block
    block_start = m.start()
    block_body_start = m.end()
    if block_body_start < len(body) and body[block_body_start : block_body_start + 1] == "\n":
        block_body_start += 1
    nxt = re.search(r"(?m)^###\s+", body[block_body_start:])
    block_end = block_body_start + nxt.start() if nxt else len(body)
    return body[:block_start] + new_block + body[block_end:]


def command_diet_log(
    vault: Path,
    templates_path: str,
    *,
    day: str | None,
    day_type: str,
    meal: str,
    foods: str,
    carbs: float,
    protein: float,
    fat: float,
    kcal: float | None,
    source_url: str,
) -> Path:
    day_value = (day or today_str()).strip()
    try:
        datetime.strptime(day_value, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"invalid date format: {day_value}; expected YYYY-MM-DD")

    _, day_type_label = _normalize_day_type(day_type)
    meal_label = _normalize_meal_label(meal)
    kcal_value = float(kcal) if kcal is not None else float(carbs) * 4 + float(protein) * 4 + float(fat) * 9

    note = ensure_diet_record_note(vault, templates_path, source_url=source_url)
    content = note.read_text(encoding="utf-8")
    content = ensure_section(content, DIET_LOGS_HEADING, f"{DIET_LOGS_HEADING}\n")
    logs_body = get_section_body(content, DIET_LOGS_HEADING)

    day_title = _diet_day_title(day_value, day_type_label)
    heading = f"### {day_title}"
    m = re.search(rf"(?m)^{re.escape(heading)}\s*$", logs_body or "")
    if m:
        block_body_start = m.end()
        if block_body_start < len(logs_body) and logs_body[block_body_start : block_body_start + 1] == "\n":
            block_body_start += 1
        nxt = re.search(r"(?m)^###\s+", logs_body[block_body_start:])
        block_end = block_body_start + nxt.start() if nxt else len(logs_body)
        current_block = logs_body[block_body_start:block_end]
        rows = _parse_diet_rows(current_block)
    else:
        rows = _diet_blank_rows()

    rows[meal_label] = {
        "kcal": round(kcal_value, 1),
        "carbs": round(float(carbs), 1),
        "protein": round(float(protein), 1),
        "fat": round(float(fat), 1),
        "foods": (foods or "").strip(),
    }
    logs_body = _upsert_diet_day_block(logs_body, day_title, rows)
    content = replace_section_body(content, DIET_LOGS_HEADING, logs_body.rstrip() + "\n")
    content = replace_or_add_frontmatter_fields(content, {"updated": now_iso()})
    atomic_write(note, content)
    return note


def _split_h3_blocks(body: str) -> list[tuple[str, str]]:
    text = body or ""
    blocks: list[tuple[str, str]] = []
    matches = list(re.finditer(r"(?m)^###\s+(.+?)\s*$", text))
    for i, m in enumerate(matches):
        title = (m.group(1) or "").strip()
        start = m.end()
        if start < len(text) and text[start : start + 1] == "\n":
            start += 1
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        blocks.append((title, text[start:end].strip()))
    return blocks


def _parse_diet_targets_from_block(block: str) -> dict | None:
    nums = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)", block or "")]
    if len(nums) < 4:
        return None
    return {
        "kcal": nums[0],
        "carbs": nums[1],
        "protein": nums[2],
        "fat": nums[3],
    }


def _load_diet_targets(vault: Path) -> dict:
    defaults = {
        "training": {"kcal": 2550.0, "carbs": 320.0, "protein": 205.0, "fat": 45.0},
        "rest": {"kcal": 2350.0, "carbs": 260.0, "protein": 205.0, "fat": 50.0},
    }
    candidates = [
        vault / "06_PersonalLife" / "Active" / "Diet" / "饮食计划（初期版）.md",
        vault / DIET_RECORD_REL_PATH,
    ]
    for p in candidates:
        if not p.exists():
            continue
        try:
            txt = p.read_text(encoding="utf-8")
        except Exception:
            continue
        body = get_section_body(txt, "## Daily Targets")
        blocks = _split_h3_blocks(body)
        parsed: list[dict] = []
        for _, block in blocks:
            target = _parse_diet_targets_from_block(block)
            if target:
                parsed.append(target)
        if len(parsed) >= 2:
            defaults["training"] = parsed[0]
            defaults["rest"] = parsed[1]
            return defaults
    return defaults


def _diet_day_rows_from_logs(logs_body: str, day_title: str) -> dict:
    heading = f"### {day_title}"
    m = re.search(rf"(?m)^{re.escape(heading)}\s*$", logs_body or "")
    if not m:
        return _diet_blank_rows()
    block_body_start = m.end()
    if block_body_start < len(logs_body) and logs_body[block_body_start : block_body_start + 1] == "\n":
        block_body_start += 1
    nxt = re.search(r"(?m)^###\s+", logs_body[block_body_start:])
    block_end = block_body_start + nxt.start() if nxt else len(logs_body)
    current_block = logs_body[block_body_start:block_end]
    return _parse_diet_rows(current_block)


def _diet_totals(rows: dict) -> dict:
    total = {"kcal": 0.0, "carbs": 0.0, "protein": 0.0, "fat": 0.0}
    for label in DIET_MEAL_ORDER:
        row = rows.get(label) or {}
        total["kcal"] += float(row.get("kcal") or 0.0)
        total["carbs"] += float(row.get("carbs") or 0.0)
        total["protein"] += float(row.get("protein") or 0.0)
        total["fat"] += float(row.get("fat") or 0.0)
    return total


def _upsert_subheading_block(body: str, heading: str, new_block: str) -> str:
    text = body or ""
    m = re.search(rf"(?m)^{re.escape(heading)}\s*$", text)
    full = f"{heading}\n{new_block.strip()}\n"
    if not m:
        stripped = text.rstrip()
        return (stripped + "\n\n" + full).strip() + "\n" if stripped else full
    block_start = m.start()
    block_body_start = m.end()
    if block_body_start < len(text) and text[block_body_start : block_body_start + 1] == "\n":
        block_body_start += 1
    nxt = re.search(r"(?m)^###\s+", text[block_body_start:])
    block_end = block_body_start + nxt.start() if nxt else len(text)
    return text[:block_start] + full + text[block_end:]


def command_diet_capture(
    vault: Path,
    templates_path: str,
    *,
    day: str | None,
    day_type: str,
    meal: str,
    foods: str,
    carbs: float,
    protein: float,
    fat: float,
    kcal: float | None,
) -> tuple[Path, str]:
    source_url = "https://www.notion.so/2eee2419152180a3b245d146538c1cff?source=copy_link"
    note = command_diet_log(
        vault=vault,
        templates_path=templates_path,
        day=day,
        day_type=day_type,
        meal=meal,
        foods=foods,
        carbs=carbs,
        protein=protein,
        fat=fat,
        kcal=kcal,
        source_url=source_url,
    )
    content = note.read_text(encoding="utf-8")
    content = ensure_section(content, DIET_LOGS_HEADING, f"{DIET_LOGS_HEADING}\n")
    day_value = (day or today_str()).strip()
    _, day_type_label = _normalize_day_type(day_type)
    day_key = "rest" if day_type_label == "休息日" else "training"
    day_title = _diet_day_title(day_value, day_type_label)
    logs_body = get_section_body(content, DIET_LOGS_HEADING)
    rows = _diet_day_rows_from_logs(logs_body, day_title)
    totals = _diet_totals(rows)
    targets = _load_diet_targets(vault)[day_key]

    def _pct_diff(current: float, target: float) -> float:
        if target <= 0:
            return 0.0
        return (current - target) / target * 100.0

    kcal_ok = abs(_pct_diff(totals["kcal"], targets["kcal"])) <= 15
    carbs_ok = abs(_pct_diff(totals["carbs"], targets["carbs"])) <= 20
    protein_ok = totals["protein"] >= targets["protein"] * 0.85
    fat_ok = totals["fat"] <= targets["fat"] * 1.15
    qualified = kcal_ok and carbs_ok and protein_ok and fat_ok
    verdict = "合格" if qualified else "需调整"

    eval_lines = [
        f"- Verdict: **{verdict}**",
        f"- kcal: {totals['kcal']:.1f} / target {targets['kcal']:.1f} ({_pct_diff(totals['kcal'], targets['kcal']):+.1f}%)",
        f"- carbs: {totals['carbs']:.1f} / target {targets['carbs']:.1f} ({_pct_diff(totals['carbs'], targets['carbs']):+.1f}%)",
        f"- protein: {totals['protein']:.1f} / target {targets['protein']:.1f} ({_pct_diff(totals['protein'], targets['protein']):+.1f}%)",
        f"- fat: {totals['fat']:.1f} / target {targets['fat']:.1f} ({_pct_diff(totals['fat'], targets['fat']):+.1f}%)",
        "- Rule: kcal ±15%, carbs ±20%, protein >=85% target, fat <=115% target.",
    ]
    content = ensure_section(content, "## Daily Evaluation", "## Daily Evaluation\n")
    eval_body = get_section_body(content, "## Daily Evaluation")
    eval_body = _upsert_subheading_block(eval_body, f"### {day_title}", "\n".join(eval_lines))
    content = replace_section_body(content, "## Daily Evaluation", eval_body.rstrip() + "\n")
    content = replace_or_add_frontmatter_fields(content, {"updated": now_iso()})
    atomic_write(note, content)
    return note, f"{day_title}: {verdict}"


def next_available_path(path: Path, stamp: str | None = None) -> Path:
    if not path.exists():
        return path
    base = path.with_suffix("")
    suffix = path.suffix
    mark = stamp or now_localized().strftime("%Y%m%d-%H%M%S")
    candidate = base.parent / f"{base.name} - {mark}{suffix}"
    if not candidate.exists():
        return candidate
    idx = 2
    while True:
        candidate = base.parent / f"{base.name} - {mark}-{idx:02d}{suffix}"
        if not candidate.exists():
            return candidate
        idx += 1


def next_available_dir(path: Path, stamp: str | None = None) -> Path:
    if not path.exists():
        return path
    mark = stamp or now_localized().strftime("%Y%m%d-%H%M%S")
    candidate = path.parent / f"{path.name} - {mark}"
    if not candidate.exists():
        return candidate
    idx = 2
    while True:
        candidate = path.parent / f"{path.name} - {mark}-{idx:02d}"
        if not candidate.exists():
            return candidate
        idx += 1


def _resource_topic_filename(topic: str, limit: int = 120) -> str:
    cleaned = sanitize_name((topic or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .-_")
    if not cleaned:
        cleaned = "resource"
    return cleaned[:limit].rstrip(" .-_") or "resource"


def _retitle_resource_note_path(note: Path, day: str, topic: str) -> Path:
    desired_name = f"{day} - {_resource_topic_filename(topic)}.md"
    desired_path = note.parent / desired_name
    if desired_path == note:
        return note
    if desired_path.exists():
        desired_path = next_available_path(desired_path, "capture")
    if note.exists():
        os.replace(note, desired_path)
    return desired_path


def _wikilink_rel(vault: Path, p: Path) -> str:
    rel = p.relative_to(vault).as_posix()
    if rel.lower().endswith(".md"):
        rel = rel[:-3]
    return f"[[{rel}]]"


def _project_note_links(vault: Path, status_dir: str) -> list[str]:
    root = vault / "03_Projects" / status_dir
    if not root.exists():
        return []
    links: list[str] = []
    for p in sorted(root.rglob("Project.md")):
        links.append(_wikilink_rel(vault, p))
    for p in sorted(root.rglob("Project - *.md")):
        rel = _wikilink_rel(vault, p)
        if rel not in links:
            links.append(rel)
    return links


def generate_projects_base(vault: Path) -> Path:
    active_links = _project_note_links(vault, "Active")
    backlog_links = _project_note_links(vault, "Backlog")
    payload = {
        "name": "Projects",
        "description": "Auto-generated by SecondBrain CLI. Contains On Progress and Backlog snapshots.",
        "source": "03_Projects",
        "views": [
            {
                "name": "On Progress",
                "scope": "03_Projects/Active",
                "columns": ["status", "priority", "due", "next_action", "updated"],
            },
            {
                "name": "Backlog",
                "scope": "03_Projects/Backlog",
                "columns": ["status", "priority", "next_action", "updated"],
            },
        ],
        "snapshots": {
            "on_progress": active_links,
            "backlog": backlog_links,
            "updated": now_localized().isoformat(timespec="seconds"),
        },
    }
    out = vault / "00_System" / "Projects.base"
    atomic_write(out, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return out


def dashboard_embed_block(dashboards_mode: str) -> str:
    mode = (dashboards_mode or "dataview").lower()
    if mode == "bases":
        return (
            "![[00_System/Projects.base]]\n"
            "![[00_System/Resources.base]]\n"
            "![[00_System/Articles.base]]"
        )
    return "![[00_System/Dashboard]]"


def ensure_dashboards_section(content: str, dashboards_mode: str) -> str:
    body = "绯荤粺鐘舵€佷笌褰撴棩璁″垝鍏ュ彛锛歕n"
    required_lines = [ln for ln in dashboard_embed_block(dashboards_mode).splitlines() if ln.strip()]
    required_lines.append("![[00_System/Dashboard]]")
    for ln in required_lines:
        body += ln + "\n"
    span = section_span(content, "## Dashboards")
    if not span:
        return ensure_section(content, "## Dashboards", f"## Dashboards\n{body}")
    current = get_section_body(content, "## Dashboards")
    required_lines = [ln for ln in required_lines if ln.strip()]
    if all(ln in current for ln in required_lines):
        return content
    merged = current.rstrip() + "\n"
    for ln in required_lines:
        if ln not in merged:
            merged += ln + "\n"
    return replace_section_body(content, "## Dashboards", merged)


def _note_matches_day(path: Path, day: date) -> bool:
    by_name = parse_note_date_from_filename(path.name)
    if by_name:
        return by_name == day
    try:
        txt = path.read_text(encoding="utf-8")
    except Exception:
        return False
    fm = _extract_frontmatter_map(txt)
    for k in ("created", "captured_at", "updated", "date"):
        v = fm.get(k)
        if not v:
            continue
        dd = _parse_loose_date(v)
        if dd and dd == day:
            return True
    return False


def _collect_day_links(vault: Path, roots: list[Path], day: date) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    for root in roots:
        if not root.exists():
            continue
        for p in sorted(root.rglob("*.md")):
            if not _note_matches_day(p, day):
                continue
            w = _wikilink_rel(vault, p)
            if w in seen:
                continue
            seen.add(w)
            links.append(w)
    return links


def _set_links_section(content: str, heading: str, intro: str, links: list[str]) -> str:
    body = intro.rstrip() + "\n"
    if links:
        body += "\n".join(f"- {x}" for x in links) + "\n"
    else:
        body += "-\n"
    return replace_section_body(content, heading, body)


def _refresh_daily_indexes(
    content: str,
    vault: Path,
    day: date,
    session_links: list[str],
    plan_link: str | None,
) -> str:
    resources_links = _collect_day_links(
        vault,
        [vault / "04_Resources" / "Inbox", vault / "04_Resources" / "Library"],
        day,
    )
    thinking_links = _collect_day_links(vault, [vault / "05_Thinking"], day)
    article_links = _collect_day_links(vault, [vault / "07_Articles"], day)
    personal_links = _collect_day_links(vault, [vault / "06_PersonalLife"], day)

    content = _set_links_section(
        content,
        "## Sessions Index",
        "Today's session links:",
        session_links,
    )
    content = _set_links_section(
        content,
        "## Resource Notes",
        "Today's captured/reviewed resources:",
        resources_links,
    )
    content = _set_links_section(
        content,
        "## Thinking Notes",
        "Today's thinking notes:",
        thinking_links,
    )
    content = _set_links_section(
        content,
        "## Article Notes",
        "Today's article notes:",
        article_links,
    )
    content = _set_links_section(
        content,
        "## PersonalLife",
        "Today's personal-life related notes:",
        personal_links,
    )

    if plan_link:
        dash_body = get_section_body(content, "## Dashboards")
        line = f"- DailyPlan: {plan_link}"
        if line not in dash_body:
            merged = dash_body.rstrip() + "\n" + line + "\n"
            content = replace_section_body(content, "## Dashboards", merged)
    return content


def command_today(vault: Path, templates_path: str, dashboards_mode: str) -> Path:
    d = today_date()
    day = d.isoformat()
    daily = daily_note_path(vault, d, ensure=True)
    daily_plan = daily_plan_path(vault, d, ensure=True)
    plan_link: str | None = None
    if not daily_plan.exists():
        plan_t = vault / templates_path / "DailyPlan.md"
        if plan_t.exists():
            plan_content = render_template(plan_t, {"date": day, "updated": now_iso()})
            atomic_write(daily_plan, plan_content)
    if daily_plan.exists():
        plan_link = _wikilink_rel(vault, daily_plan)
    if not daily.exists():
        t = vault / templates_path / "DailyNote.md"
        content = render_template(t, {"date": day, "updated": now_iso()})
        atomic_write(daily, content)
    content = daily.read_text(encoding="utf-8")
    content = ensure_dashboards_section(content, dashboards_mode)
    content = ensure_section(content, "## Sessions Index", "## Sessions Index\n")
    sdir = daily_sessions_dir(vault, d, ensure=False)
    session_links = []
    if sdir.exists():
        session_links = [_wikilink_rel(vault, p) for p in sorted(sdir.glob(f"{day} session - *.md"))]
    content = _refresh_daily_indexes(content, vault, d, session_links, plan_link)
    content = replace_or_add_frontmatter_fields(content, {"updated": now_iso()})
    atomic_write(daily, content)
    generate_projects_base(vault)
    return daily


def command_plan_today(vault: Path, templates_path: str, dashboards_mode: str) -> Path:
    d = today_date()
    day = d.isoformat()
    plan = daily_plan_path(vault, d, ensure=True)
    if not plan.exists():
        t = vault / templates_path / "DailyPlan.md"
        if t.exists():
            plan_content = render_template(t, {"date": day, "updated": now_iso()})
            atomic_write(plan, plan_content)
        else:
            atomic_write(
                plan,
                (
                    "---\n"
                    "type: daily\n"
                    "status: active\n"
                    "area: daily\n"
                    f"created: {day}\n"
                    f"updated: {now_iso()}\n"
                    f"owner: {current_owner()}\n"
                    "authoring: mixed\n"
                    "tags: [daily, plan]\n"
                    "---\n\n"
                    f"# DailyPlan - {day}\n\n"
                    "## Priorities\n- \n\n"
                    "## Time Blocks\n- \n\n"
                    "## Must Finish\n- [ ] \n"
                ),
            )
    # Ensure daily note also exists and references plan.
    command_today(vault, templates_path, dashboards_mode)
    return plan


def insert_session_link(daily_path: Path, session_link: str) -> None:
    content = daily_path.read_text(encoding="utf-8")
    if session_link in content:
        return
    marker = "## Sessions Index\n"
    if marker not in content:
        content = ensure_section(content, "## Sessions Index", "## Sessions Index\n")
    idx = content.find(marker)
    start = idx + len(marker)
    next_heading = content.find("\n## ", start)
    if next_heading == -1:
        next_heading = len(content)
    section = content[start:next_heading]
    if section and not section.endswith("\n"):
        section += "\n"
    section += f"- {session_link}\n"
    content = content[:start] + section + content[next_heading:]
    content = replace_or_add_frontmatter_fields(content, {"updated": now_iso()})
    atomic_write(daily_path, content)


def command_start_session(vault: Path, templates_path: str, dashboards_mode: str) -> Path:
    d = today_date()
    day = d.isoformat()
    sessions_dir = daily_sessions_dir(vault, d, ensure=True)
    sessions_dir.mkdir(parents=True, exist_ok=True)
    pattern = re.compile(rf"^{re.escape(day)} session - session-(\d{{3}})\.md$")
    max_n = 0
    for p in sessions_dir.glob(f"{day} session - session-*.md"):
        m = pattern.match(p.name)
        if m:
            max_n = max(max_n, int(m.group(1)))
    n = max_n + 1
    filename = f"{day} session - session-{n:03d}.md"
    session_path = sessions_dir / filename
    t = vault / templates_path / "Session.md"
    content = render_template(
        t,
        {"date": day, "updated": now_iso(), "session_id": f"session-{n:03d}"},
    )
    atomic_write(session_path, content)
    daily = command_today(vault, templates_path, dashboards_mode)
    insert_session_link(daily, _wikilink_rel(vault, session_path))
    return session_path


def ensure_daily_note_for_date(vault: Path, templates_path: str, d: date, dashboards_mode: str) -> Path:
    day = d.isoformat()
    daily = daily_note_path(vault, d, ensure=True)
    if not daily.exists():
        t = vault / templates_path / "DailyNote.md"
        if t.exists():
            content = render_template(t, {"date": day, "updated": now_iso()})
        else:
            content = (
                "---\n"
                "type: daily\n"
                "status: active\n"
                "area: daily\n"
                f"created: {day}\n"
                f"updated: {now_iso()}\n"
                f"owner: {current_owner()}\n"
                "authoring: mixed\n"
                "tags: [daily]\n"
                "---\n\n"
                f"# DailyNote - {day}\n\n"
                "## Sessions Index\n-\n"
            )
        atomic_write(daily, content)

    content = daily.read_text(encoding="utf-8")
    content = ensure_dashboards_section(content, dashboards_mode)
    content = ensure_section(content, "## Sessions Index", "## Sessions Index\n")
    sdir = daily_sessions_dir(vault, d, ensure=False)
    session_links = [_wikilink_rel(vault, p) for p in sorted(sdir.glob(f"{day} session - *.md"))] if sdir.exists() else []
    content = _refresh_daily_indexes(content, vault, d, session_links, plan_link=None)
    content = replace_or_add_frontmatter_fields(content, {"updated": now_iso()})
    atomic_write(daily, content)
    return daily


def command_daily_open(
    vault: Path,
    templates_path: str,
    date_input: str,
    dashboards_mode: str,
    *,
    create_if_missing: bool = False,
    search_archive: bool = True,
) -> Path:
    d = resolve_human_date(date_input)
    p = daily_note_path(vault, d, ensure=False)
    if p.exists():
        return p
    if create_if_missing:
        if d == today_date():
            return command_today(vault, templates_path, dashboards_mode)
        return ensure_daily_note_for_date(vault, templates_path, d, dashboards_mode)
    if search_archive:
        ap = archive_daily_target_dir(vault, d, "daily", ensure=False) / f"{d.isoformat()}.md"
        if ap.exists():
            return ap
    raise FileNotFoundError(f"daily note not found for {d.isoformat()}")


def command_session_log(
    vault: Path,
    templates_path: str,
    title: str,
    summary: str,
    date_input: str,
    dashboards_mode: str,
) -> Path:
    d = resolve_human_date(date_input)
    day = d.isoformat()
    sessions_dir = daily_sessions_dir(vault, d, ensure=True)
    slug = slugify_topic(title)[:80] or "conversation-summary"
    session_path = next_available_path(sessions_dir / f"{day} session - {slug}.md", "session")

    t = vault / templates_path / "Session.md"
    if t.exists():
        content = render_template(
            t,
            {"date": day, "updated": now_iso(), "session_id": slug},
        )
    else:
        content = (
            "---\n"
            "type: session\n"
            "status: active\n"
            "area: daily\n"
            f"created: {day}\n"
            f"updated: {now_iso()}\n"
            f"owner: {current_owner()}\n"
            "authoring: mixed\n"
            "tags: [session]\n"
            "---\n\n"
            f"# Session - {slug} ({day})\n\n"
            "## Goal\n\n## Work Log\n\n## Outputs\n- \n\n## Open Questions\n- \n\n## Next Actions\n- [ ] \n"
        )

    summary_text = (summary or "").strip() or "Summary pending."
    output_lines = [f"- {ln.strip()}" for ln in summary_text.splitlines() if ln.strip()]
    if not output_lines:
        output_lines = ["- Summary recorded."]
    content = replace_section_body(content, "## Goal", f"{title.strip() or slug}\n")
    content = replace_section_body(content, "## Work Log", summary_text + "\n")
    content = replace_section_body(content, "## Outputs", "\n".join(output_lines[:12]) + "\n")
    content = replace_section_body(content, "## Next Actions", "- [ ] Review and refine this session summary.\n")
    content = replace_or_add_frontmatter_fields(content, {"updated": now_iso()})
    atomic_write(session_path, content)

    if d == today_date():
        daily = command_today(vault, templates_path, dashboards_mode)
    else:
        daily = ensure_daily_note_for_date(vault, templates_path, d, dashboards_mode)
    insert_session_link(daily, _wikilink_rel(vault, session_path))
    return session_path


def infer_source_type(url: str) -> str:
    netloc = urlparse(url).netloc.lower()
    if "youtube.com" in netloc or "youtu.be" in netloc:
        return "youtube"
    if "github.com" in netloc or "gitlab.com" in netloc:
        return "repo"
    if "arxiv.org" in netloc:
        return "paper"
    return "web"


def infer_resource_type_from_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    netloc = (parsed.netloc or "").lower()
    path = (parsed.path or "").lower()
    query = (parsed.query or "").lower()
    if any(x in netloc for x in ("youtube.com", "youtu.be", "bilibili.com", "vimeo.com")):
        return "video"
    if re.search(r"\.(png|jpe?g|gif|webp|bmp|svg)$", path):
        return "image"
    merged = f"{netloc} {path} {query}"
    if "prompt" in merged or "提示词" in merged:
        return "prompt"
    return "article"


def _extract_markdown_heading(md: str) -> str:
    for line in md.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
    return ""


def _collect_paragraph_lines(md: str) -> list[str]:
    lines = []
    for ln in md.splitlines():
        s = ln.strip()
        if not s:
            continue
        if s.startswith("#"):
            continue
        if s.startswith("```"):
            continue
        if s.startswith(">"):
            continue
        if s.startswith("- ") or s.startswith("* "):
            continue
        if re.match(r"^\d+\.\s+", s):
            continue
        lines.append(s)
    return lines


def _collect_bullet_lines(md: str) -> list[str]:
    out = []
    for ln in md.splitlines():
        s = ln.strip()
        if s.startswith("- "):
            out.append(s[2:].strip())
        elif s.startswith("* "):
            out.append(s[2:].strip())
    return out


def _extract_code_blocks(md: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    pattern = re.compile(r"```([^\n`]*)\n(.*?)```", flags=re.DOTALL)
    for m in pattern.finditer(md or ""):
        lang = (m.group(1) or "").strip().lower()
        body = (m.group(2) or "").strip()
        if body:
            blocks.append((lang, body))
    return blocks


def _extract_prompt_candidates(md: str, max_items: int = 4) -> list[str]:
    candidates: list[str] = []
    seen = set()

    for lang, body in _extract_code_blocks(md):
        if lang in ("prompt", "text", "md", "markdown", "") and 20 <= len(body) <= 3000:
            key = body.strip().lower()
            if key not in seen:
                seen.add(key)
                candidates.append(body.strip())
        if len(candidates) >= max_items:
            return candidates

    for ln in (md or "").splitlines():
        s = ln.strip()
        if not s:
            continue
        low = s.lower()
        if any(k in low for k in ("prompt:", "提示词", "system prompt", "user prompt", "instruction:")):
            cleaned = re.sub(r"^\s*[-*]\s*", "", s).strip()
            if len(cleaned) < 12:
                continue
            key = cleaned.lower()
            if key not in seen:
                seen.add(key)
                candidates.append(cleaned)
        if len(candidates) >= max_items:
            break
    return candidates


def _format_prompt_candidates(candidates: list[str]) -> str:
    if not candidates:
        return "> No prompt candidates extracted."
    lines: list[str] = []
    for i, item in enumerate(candidates, start=1):
        lines.append(f"> Prompt Candidate {i}")
        lines.append("```text")
        lines.append(item.strip())
        lines.append("```")
    return "\n".join(lines)


def _extract_source_title(md: str) -> str:
    m = re.search(r"(?im)^title:\s*(.+)$", md or "")
    if not m:
        return ""
    title = m.group(1).strip()
    title = re.sub(r"\s*/\s*X\s*$", "", title, flags=re.IGNORECASE).strip()
    return title


def _is_summary_noise(line: str) -> bool:
    s = " ".join((line or "").strip().split())
    if not s:
        return True
    low = s.lower()
    if low in {".", "-", ">", "markdown content:"}:
        return True
    if low.startswith(("title:", "url source:", "markdown content:", "description source:")):
        return True
    if low.startswith(("[![image", "![image", "image ", "video ")):
        return True
    return False


def _clean_summary_lines(lines: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for line in lines:
        s = " ".join((line or "").strip().split())
        if _is_summary_noise(s):
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(s)
    return cleaned


def _summarize_markdown_heuristic(md: str, fallback_title: str) -> dict:
    title = _extract_markdown_heading(md) or _extract_source_title(md) or fallback_title
    paras = _clean_summary_lines(_collect_paragraph_lines(md))
    bullets = _clean_summary_lines(_collect_bullet_lines(md))

    if paras:
        tldr = paras[0]
    elif bullets:
        tldr = bullets[0]
    else:
        tldr = "No summary extracted from source content."
    tldr = tldr[:280]

    key_points: list[str] = []
    for b in bullets:
        if b and b not in key_points:
            key_points.append(b)
        if len(key_points) >= 6:
            break
    if not key_points:
        for p in paras[:6]:
            if p and p not in key_points:
                key_points.append(p[:220])

    quote_lines = []
    for p in paras[:8]:
        quote_lines.append(f"> {p[:280]}")
    quotes = "\n".join(quote_lines) if quote_lines else "> No quote extracted."

    return {
        "title": title,
        "tldr": tldr,
        "key_points": key_points,
        "quotes": quotes,
        "open_questions": [],
    }


def _summary_api_config() -> dict | None:
    kimi_api_key = (os.getenv("KIMI_API_KEY") or "").strip()
    if kimi_api_key:
        return {
            "provider": "kimi",
            "api_key": kimi_api_key,
            "base_url": (os.getenv("KIMI_API_BASE") or "https://api.moonshot.cn/v1").strip(),
            "model": (os.getenv("KIMI_MODEL") or "kimi-k2.5").strip(),
        }

    openai_api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if openai_api_key:
        return {
            "provider": "openai-compatible",
            "api_key": openai_api_key,
            "base_url": (os.getenv("OPENAI_API_BASE") or "https://api.openai.com/v1").strip(),
            "model": (os.getenv("OPENAI_MODEL") or "gpt-4o-mini").strip(),
        }
    return None


def _summary_api_endpoint(base_url: str) -> str:
    normalized = (base_url or "").strip().rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return normalized + "/chat/completions"


def _strip_code_fence(text: str) -> str:
    s = (text or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _truncate_summary_source(md: str, limit: int = 16000) -> str:
    lines: list[str] = []
    total = 0
    for raw in (md or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("[![Image") or line.startswith("![]("):
            continue
        if total + len(line) + 1 > limit:
            remain = max(0, limit - total)
            if remain > 80:
                lines.append(line[:remain])
            break
        lines.append(line)
        total += len(line) + 1
    return "\n".join(lines).strip()


def _normalize_summary_payload(payload: dict, fallback_title: str) -> dict:
    title = str(payload.get("title") or "").strip() or fallback_title
    tldr = str(payload.get("tldr") or "").strip()
    key_points_raw = payload.get("key_points") or []
    quotes_raw = payload.get("quotes") or []
    questions_raw = payload.get("open_questions") or []

    key_points = [str(x).strip() for x in key_points_raw if str(x).strip()]
    quotes = [str(x).strip() for x in quotes_raw if str(x).strip()]
    open_questions = [str(x).strip() for x in questions_raw if str(x).strip()]

    if not tldr and key_points:
        tldr = key_points[0]
    if not tldr:
        raise ValueError("summary payload missing tldr")
    if not key_points:
        raise ValueError("summary payload missing key_points")

    quote_block = "\n".join(f"> {q}" for q in quotes[:6]) if quotes else "> No quote extracted."
    return {
        "title": title,
        "tldr": tldr[:280],
        "key_points": key_points[:8],
        "quotes": quote_block,
        "open_questions": open_questions[:5],
    }


def _summarize_markdown_via_llm(md: str, fallback_title: str, timeout: int = 60) -> dict | None:
    cfg = _summary_api_config()
    if not cfg:
        return None

    source_text = _truncate_summary_source(md)
    if len(source_text) < 200:
        return None

    system_prompt = (
        "You are a research note summarizer for a personal knowledge base. "
        "Read the source text and return strict JSON only. "
        "The output language must be Simplified Chinese. "
        "Preserve technical identifiers such as API names, model names, prompt names, and code symbols. "
        "Focus on the source's core claims, mechanism, evidence, limitations, and practical implications. "
        "Do not output markdown fences."
    )
    user_prompt = (
        "请把下面抓取到的网页/线程内容总结成适合 SecondBrain 资源笔记写入的中文 JSON。\n"
        "要求：\n"
        "1. 必须输出合法 JSON，不要输出任何额外说明。\n"
        "2. 字段固定为 title, tldr, key_points, quotes, open_questions。\n"
        "3. title 用中文概括标题；保留必要英文专有名词。\n"
        "4. tldr 为 1 段中文，80-180 字。\n"
        "5. key_points 为 5-8 条中文要点，每条都要有信息密度，不要写空话。\n"
        "6. quotes 为 2-4 条关键证据或原文意思的中文转述；不要长抄原文。\n"
        "7. open_questions 为 2-4 条值得后续追问的问题。\n"
        "8. 如果内容是技术线程，优先总结其机制、实验方法、证据链、局限和启发。\n\n"
        f"回退标题：{fallback_title}\n\n"
        "源内容如下：\n"
        f"{source_text}"
    )
    body = {
        "model": cfg["model"],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    req = Request(
        _summary_api_endpoint(cfg["base_url"]),
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg['api_key']}",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None

    try:
        obj = json.loads(raw)
        choices = obj.get("choices") or []
        msg = choices[0].get("message", {}) if choices else {}
        content = msg.get("content", "")
        if isinstance(content, list):
            text_parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(str(item.get("text", "")))
            content = "\n".join(text_parts)
        payload = json.loads(_strip_code_fence(str(content)))
        if not isinstance(payload, dict):
            return None
        return _normalize_summary_payload(payload, fallback_title)
    except Exception:
        return None


def summarize_markdown(md: str, fallback_title: str) -> dict:
    llm_summary = _summarize_markdown_via_llm(md, fallback_title=fallback_title)
    if llm_summary:
        return llm_summary
    return _summarize_markdown_heuristic(md, fallback_title)


def _normalize_agent_reach_command(value) -> list[str]:
    if isinstance(value, list):
        return [str(x) for x in value if str(x).strip()]
    if isinstance(value, str) and value.strip():
        if "\n" in value:
            return [value.strip()]
        try:
            parts = shlex.split(value, posix=False if os.name == "nt" else True)
            return [x for x in parts if x.strip()]
        except Exception:
            return [value.strip()]
    return []


def _extract_agent_reach_markdown(text: str, output_format: str, json_field: str) -> str:
    content = (text or "").strip()
    if not content:
        return ""
    fmt = (output_format or "auto").lower()
    if fmt in ("markdown", "md", "text"):
        return content

    def from_json(raw: str) -> str:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            if json_field and json_field in obj and isinstance(obj[json_field], str):
                return obj[json_field].strip()
            for k in ("markdown", "content", "text", "summary"):
                v = obj.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
        return ""

    if fmt == "json":
        return from_json(content)
    try:
        candidate = from_json(content)
        if candidate:
            return candidate
    except Exception:
        pass
    return content


def fetch_via_agent_reach_command(
    url: str,
    agent_reach_cfg: dict,
    *,
    cmd_override: str | None = None,
    args_override: list[str] | None = None,
    timeout_override: int | None = None,
) -> tuple[str | None, str | None]:
    if agent_reach_cfg.get("enabled", True) is False:
        return None, "Agent-Reach is disabled in config."

    command = _normalize_agent_reach_command(cmd_override) if cmd_override else []
    if not command:
        command = _normalize_agent_reach_command(agent_reach_cfg.get("command"))
    if not command:
        env_path = (os.getenv("AGENT_REACH_PATH") or "").strip()
        if env_path:
            command = [env_path]
    if not command:
        return None, "Agent-Reach command is not configured. Use --agent-reach-cmd or config/agent-reach.json."

    arg_tpl = args_override if args_override else agent_reach_cfg.get("args", ["{url}"])
    if isinstance(arg_tpl, str):
        arg_tpl = [arg_tpl]
    arg_tpl = [str(x) for x in (arg_tpl or [])]
    if not arg_tpl:
        arg_tpl = ["{url}"]

    args: list[str] = []
    has_placeholder = False
    for item in arg_tpl:
        if "{url}" in item:
            has_placeholder = True
            args.append(item.replace("{url}", url))
        else:
            args.append(item)
    if not has_placeholder:
        args.append(url)

    timeout = timeout_override if timeout_override is not None else int(agent_reach_cfg.get("timeout", 45))
    run_cmd = command + args
    try:
        r = subprocess.run(
            run_cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except Exception as e:
        return None, f"Agent-Reach command execution failed: {e}"

    if r.returncode != 0:
        msg = (r.stderr or r.stdout or "").strip()
        return None, f"Agent-Reach 鍛戒护杩斿洖闈為浂鐘舵€侊紙{r.returncode}锛夛細{msg or 'unknown error'}"

    output_format = str(agent_reach_cfg.get("output_format", "auto"))
    json_field = str(agent_reach_cfg.get("json_field", "markdown"))
    md = _extract_agent_reach_markdown(r.stdout or "", output_format, json_field).strip()
    if not md:
        return None, "Agent-Reach command returned empty output."
    return md, None


def fetch_via_agent_reach_stack(url: str, timeout: int) -> str:
    errors: list[str] = []

    target = f"https://r.jina.ai/{url}"
    r = subprocess.run(
        ["curl", "-L", "-sS", target, "-H", "Accept: text/markdown"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if r.returncode == 0:
        content = (r.stdout or "").strip()
        if content:
            return content
        errors.append("empty response from r.jina.ai")
    else:
        errors.append(r.stderr.strip() or f"curl failed with code {r.returncode}")

    netloc = urlparse(url).netloc.lower()
    is_twitter = "x.com" in netloc or "twitter.com" in netloc
    if is_twitter and shutil.which("bird"):
        env = os.environ.copy()
        if not env.get("AUTH_TOKEN") or not env.get("CT0"):
            cfg_path = Path.home() / ".agent-reach" / "config.yaml"
            if cfg_path.exists():
                cfg = cfg_path.read_text(encoding="utf-8")
                for line in cfg.splitlines():
                    if line.startswith("twitter_auth_token:") and not env.get("AUTH_TOKEN"):
                        env["AUTH_TOKEN"] = line.split(":", 1)[1].strip()
                    if line.startswith("twitter_ct0:") and not env.get("CT0"):
                        env["CT0"] = line.split(":", 1)[1].strip()
        rb = subprocess.run(
            ["bird", "read", url, "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
        if rb.returncode == 0 and (rb.stdout or "").strip():
            data = json.loads(rb.stdout)
            text = data.get("text", "").strip()
            author = data.get("author", {}).get("username", "")
            created = data.get("createdAt", "")
            likes = data.get("likeCount", 0)
            rts = data.get("retweetCount", 0)
            replies = data.get("replyCount", 0)
            article = data.get("article", {}) if isinstance(data.get("article"), dict) else {}
            article_title = article.get("title", "")
            article_preview = article.get("previewText", "")
            md = [
                f"# {article_title or 'Tweet'}",
                "",
                f"Source: {url}",
                f"Author: @{author}" if author else "",
                f"Created: {created}" if created else "",
                f"Engagement: likes={likes}, retweets={rts}, replies={replies}",
                "",
                "## Content",
                text or "(empty)",
            ]
            if article_preview:
                md.extend(["", "## Article Preview", article_preview])
            return "\n".join([x for x in md if x != ""])
        errors.append(rb.stderr.strip() or "bird read failed")

    raise RuntimeError("; ".join([e for e in errors if e]))


def _clean_subtitle_text(raw: str) -> str:
    out: list[str] = []
    for ln in (raw or "").splitlines():
        s = ln.strip()
        if not s:
            continue
        if s.upper().startswith("WEBVTT"):
            continue
        if re.match(r"^\d+$", s):
            continue
        if "-->" in s:
            continue
        s = re.sub(r"<[^>]+>", "", s).strip()
        if not s:
            continue
        if out and out[-1] == s:
            continue
        out.append(s)
    return "\n".join(out)


def fetch_video_transcript(url: str, timeout: int) -> tuple[str | None, str | None]:
    if not shutil.which("yt-dlp"):
        return None, "yt-dlp not found in PATH."
    try:
        with tempfile.TemporaryDirectory() as td:
            cmd = [
                "yt-dlp",
                "--skip-download",
                "--write-auto-subs",
                "--write-subs",
                "--sub-langs",
                "zh-Hans,zh-CN,zh,en.*",
                "--convert-subs",
                "srt",
                "-o",
                "capture.%(ext)s",
                url,
            ]
            r = subprocess.run(
                cmd,
                cwd=td,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
            if r.returncode != 0:
                msg = (r.stderr or r.stdout or "").strip()
                return None, f"yt-dlp failed: {msg or 'unknown error'}"

            files = sorted(Path(td).glob("*.srt")) + sorted(Path(td).glob("*.vtt"))
            if not files:
                return None, "No subtitle files generated."
            subtitle = files[0]
            raw = subtitle.read_text(encoding="utf-8", errors="replace")
            cleaned = _clean_subtitle_text(raw)
            if not cleaned:
                return None, "Subtitle file found but no usable text extracted."
            md = (
                "# Video Transcript\n\n"
                f"Source: {url}\n"
                f"Subtitle File: {subtitle.name}\n\n"
                "## Transcript\n"
                f"{cleaned}\n"
            )
            return md, None
    except Exception as e:
        return None, f"Transcript extraction failed: {e}"


def _image_ext_from_content_type(content_type: str | None) -> str:
    ct = (content_type or "").split(";", 1)[0].strip().lower()
    if not ct:
        return ""
    ext = mimetypes.guess_extension(ct) or ""
    if ext == ".jpe":
        ext = ".jpg"
    return ext


def download_image_attachment(
    vault: Path,
    url: str,
    *,
    topic: str,
    day: str,
    timeout: int,
) -> tuple[Path | None, str | None]:
    attachments_dir = vault / "08_Attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)
    guessed_ext = Path(urlparse(url).path).suffix.lower()
    if len(guessed_ext) > 6:
        guessed_ext = ""
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            ct = (resp.headers.get("Content-Type") or "").strip()
    except Exception as e:
        return None, f"Image download failed: {e}"

    if not data:
        return None, "Image download returned empty content."
    if not guessed_ext:
        guessed_ext = _image_ext_from_content_type(ct)
    if not guessed_ext:
        guessed_ext = ".jpg"

    safe_topic = slugify_topic(topic)[:80]
    digest = hashlib.sha1(data).hexdigest()[:10]
    filename = f"{day} - {safe_topic}-{digest}{guessed_ext}"
    out = attachments_dir / filename
    if not out.exists():
        out.write_bytes(data)
    return out, None


def ocr_image_attachment(image_path: Path, timeout: int) -> tuple[str | None, str | None]:
    if not shutil.which("tesseract"):
        return None, "tesseract not found in PATH."
    langs = ["chi_sim+eng", "eng"]
    for lang in langs:
        try:
            r = subprocess.run(
                ["tesseract", str(image_path), "stdout", "-l", lang],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except Exception as e:
            return None, f"OCR execution failed: {e}"
        if r.returncode != 0:
            continue
        text = re.sub(r"\n{3,}", "\n\n", (r.stdout or "").strip())
        if len(text) < 40:
            continue
        md = f"# OCR Extracted Text\n\nSource Image: {image_path.name}\n\n## Content\n{text}\n"
        return md, None
    return None, "OCR returned no usable text."


def command_capture_url(
    vault: Path,
    templates_path: str,
    url: str,
    fetch: bool,
    fetch_timeout: int,
    *,
    agent_reach_cfg: dict,
    no_agent_reach: bool = False,
    agent_reach_cmd: str | None = None,
    agent_reach_args: list[str] | None = None,
    resource_type: str = "article",
) -> Path:
    day = today_str()
    topic = topic_from_url(url)
    source_type = infer_source_type(url)
    if resource_type == "image":
        source_type = "image"
    elif resource_type == "video" and source_type == "web":
        source_type = "video"
    from_who = from_who_from_url(url)
    notes: list[str] = []
    inbox_dir = vault / "04_Resources" / "Inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    for p in inbox_dir.glob("*.md"):
        try:
            txt = p.read_text(encoding="utf-8")
        except Exception:
            continue
        if f'source_url: "{url}"' in txt or f"source_url: {url}" in txt:
            return p
    note = next_available_path(inbox_dir / f"{day} - {topic}.md", "capture")
    content = render_resource_from_template(
        vault,
        templates_path,
        "Resource-Inbox.md",
        day=day,
        updated=now_iso(),
        topic=topic,
        source_url=url,
        from_who=from_who,
        resource_type=resource_type,
        source_type=source_type,
    )
    attachment_path: Path | None = None
    if resource_type == "image":
        attachment_path, attach_err = download_image_attachment(
            vault,
            url,
            topic=topic,
            day=day,
            timeout=fetch_timeout,
        )
        if attachment_path:
            rel_attach = attachment_path.relative_to(vault).as_posix()
            content = replace_or_add_frontmatter_fields(
                content,
                {"attachment_path": f"\"{rel_attach}\""},
            )
            content = replace_section_body(content, "## Attachments", f"- [[{rel_attach}]]\n")
        if attach_err:
            notes.append(attach_err)

    if fetch:
        md: str | None = None
        if resource_type == "video":
            md, tx_err = fetch_video_transcript(url, timeout=fetch_timeout)
            if tx_err:
                notes.append(f"Transcript path failed: {tx_err}")
        elif resource_type == "image" and attachment_path:
            md, ocr_err = ocr_image_attachment(attachment_path, timeout=fetch_timeout)
            if ocr_err:
                notes.append(f"OCR path failed: {ocr_err}")

        if not md and not no_agent_reach:
            md, ar_err = fetch_via_agent_reach_command(
                url,
                agent_reach_cfg,
                cmd_override=agent_reach_cmd,
                args_override=agent_reach_args,
                timeout_override=fetch_timeout,
            )
            if ar_err:
                notes.append(f"Agent-Reach fetch failed; using fallback. error={ar_err}")
        if not md:
            try:
                md = fetch_via_agent_reach_stack(url, timeout=fetch_timeout)
            except Exception as e:
                md = None
                notes.append(f"Fallback fetch failed: {e}")

        if md:
            try:
                s = summarize_markdown(md, fallback_title=topic)
                note_topic = str(s.get("title") or topic).strip() or topic
                content = content.replace(f"# Resource Inbox - {topic}", f"# Resource Inbox - {s['title']}")
                content = replace_or_add_frontmatter_fields(
                    content,
                    {
                        "topic": f"\"{s['title']}\"",
                        "updated": now_iso(),
                    },
                )
                content = replace_section_body(content, "## TL;DR", s["tldr"] + "\n")
                kp_items = [f"- {x}" for x in s["key_points"]] if s["key_points"] else ["- No key points extracted."]
                for n in notes:
                    kp_items.append(f"- {n}")
                kp = "\n".join(kp_items)
                content = replace_section_body(content, "## Key Points", kp + "\n")
                oq_items = [f"- {x}" for x in s.get("open_questions", []) if str(x).strip()]
                if oq_items:
                    content = replace_section_body(content, "## Open Questions", "\n".join(oq_items) + "\n")
                if resource_type == "prompt":
                    prompts = _extract_prompt_candidates(md)
                    content = replace_or_add_frontmatter_fields(
                        content,
                        {"prompt_count": str(len(prompts))},
                    )
                    if prompts:
                        kp += "\n- Prompt candidates extracted and stored in evidence section."
                        content = replace_section_body(content, "## Key Points", kp + "\n")
                        content = replace_section_body(content, "## Quotes / Evidence", _format_prompt_candidates(prompts) + "\n")
                        content = replace_section_body(
                            content,
                            "## TL;DR",
                            f"Prompt-focused capture completed. Extracted {len(prompts)} prompt candidate(s).\n",
                        )
                    else:
                        content = replace_section_body(content, "## Quotes / Evidence", s["quotes"] + "\n")
                        content = replace_section_body(
                            content,
                            "## TL;DR",
                            "Prompt-focused capture completed but no explicit prompt block was detected.\n",
                        )
                else:
                    content = replace_section_body(content, "## Quotes / Evidence", s["quotes"] + "\n")
            except Exception as e:
                fallback = (
                    f"- Summary processing failed: {str(e)}\n"
                    "- Check capture output format and retry.\n"
                )
                content = replace_section_body(content, "## Key Points", fallback)
        else:
            fallback = "- Fetch failed; no usable source content retrieved.\n"
            if notes:
                fallback += "\n".join(f"- {x}" for x in notes) + "\n"
            fallback += "- Check Agent-Reach config and network connectivity, then retry.\n"
            content = replace_section_body(content, "## Key Points", fallback)
    elif notes:
        existing_kp = get_section_body(content, "## Key Points").strip()
        kp_lines = [ln for ln in existing_kp.splitlines() if ln.strip()] if existing_kp else []
        kp_lines.extend([f"- {n}" for n in notes])
        content = replace_section_body(content, "## Key Points", "\n".join(kp_lines) + "\n")

    note_topic = _strip_wrapped(_parse_frontmatter(content)[0].get("topic", "")) or topic
    note = _retitle_resource_note_path(note, day, note_topic)
    atomic_write(note, content)
    return note


def _is_http_url(text: str) -> bool:
    try:
        parsed = urlparse(text.strip())
    except Exception:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def find_staging_note_by_ref(vault: Path, ref: str) -> Path:
    staging_dir = vault / "04_Resources" / "Inbox"
    if not staging_dir.exists():
        raise FileNotFoundError(f"inbox folder not found: {staging_dir}")

    raw = (ref or "").strip()
    probes = []
    if raw:
        p = Path(raw)
        probes.extend([p, vault / raw, staging_dir / raw, staging_dir / f"{raw}.md"])
    for p in probes:
        if p.exists() and p.is_file():
            return p.resolve()

    matches: list[Path] = []
    if _is_http_url(raw):
        for p in staging_dir.glob("*.md"):
            try:
                txt = p.read_text(encoding="utf-8")
            except Exception:
                continue
            if f'source_url: "{raw}"' in txt or f"source_url: {raw}" in txt:
                matches.append(p)
    else:
        needle = raw.lower().removesuffix(".md")
        for p in staging_dir.glob("*.md"):
            stem = p.stem.lower()
            if needle and (needle in stem or stem in needle):
                matches.append(p)

    if not matches:
        raise FileNotFoundError(f"no inbox resource note matched: {ref}")
    if len(matches) == 1:
        return matches[0]

    # Deterministic fallback: newest filename lexicographically (date-prefixed).
    matches.sort(key=lambda x: x.name, reverse=True)
    return matches[0]


def command_promote_resource(
    vault: Path,
    templates_path: str,
    ref: str,
    *,
    status: str = "active",
    authoring: str = "mixed",
) -> tuple[Path, Path]:
    src = find_staging_note_by_ref(vault, ref)
    staging_dir = (vault / "04_Resources" / "Inbox").resolve()
    try:
        src.resolve().relative_to(staging_dir)
    except Exception:
        raise ValueError(f"resource must come from inbox: {src}")

    src_content = src.read_text(encoding="utf-8")
    fm = _extract_frontmatter_map(src_content)
    created = _strip_wrapped(fm.get("created", today_str())) or today_str()
    topic = _strip_wrapped(fm.get("topic", src.stem))
    source_url = _strip_wrapped(fm.get("source_url", ""))
    from_who = _strip_wrapped(fm.get("from_who", from_who_from_url(source_url)))
    resource_type = _strip_wrapped(fm.get("type", "article")) or "article"
    source_type = _strip_wrapped(fm.get("source_type", infer_source_type(source_url) if source_url else "web"))
    attachment_path = _strip_wrapped(fm.get("attachment_path", ""))

    content = render_resource_from_template(
        vault,
        templates_path,
        "Resource-Library.md",
        day=created,
        updated=now_iso(),
        topic=topic,
        source_url=source_url,
        from_who=from_who,
        resource_type=resource_type,
        source_type=source_type,
    )
    content = replace_or_add_frontmatter_fields(content, {"status": status, "authoring": authoring, "updated": now_iso()})
    if attachment_path:
        content = replace_or_add_frontmatter_fields(content, {"attachment_path": f"\"{attachment_path}\""})
    for heading in ("## TL;DR", "## Key Points", "## Quotes / Evidence", "## Open Questions", "## Attachments"):
        body = get_section_body(src_content, heading)
        if body.strip():
            content = replace_section_body(content, heading, body)

    library_dir = vault / "04_Resources" / "Library"
    library_dir.mkdir(parents=True, exist_ok=True)
    dst = next_available_path(library_dir / src.name, "promoted")
    atomic_write(dst, content)
    src.unlink(missing_ok=True)
    return src, dst


def parse_note_date_from_filename(name: str) -> date | None:
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d").date()
    except ValueError:
        return None


def archive_one_file(src: Path, dst_dir: Path) -> None:
    content = src.read_text(encoding="utf-8")
    content = replace_or_add_frontmatter_fields(content, {"status": "archived", "updated": now_iso()})
    atomic_write(src, content)
    dst_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst_dir / src.name))


def command_archive_daily(vault: Path, older_than: int) -> tuple[int, int]:
    cutoff = today_date() - timedelta(days=older_than)
    moved_daily = 0
    moved_sess = 0
    for p in (vault / "02_Daily").rglob("DailyNotes/*.md"):
        d = parse_note_date_from_filename(p.name)
        if d and d < cutoff:
            dst = archive_daily_target_dir(vault, d, "daily", ensure=True)
            archive_one_file(p, dst)
            moved_daily += 1
    for p in (vault / "02_Daily").rglob("Sessions/*.md"):
        d = parse_note_date_from_filename(p.name)
        if d and d < cutoff:
            dst = archive_daily_target_dir(vault, d, "session", ensure=True)
            archive_one_file(p, dst)
            moved_sess += 1
    return moved_daily, moved_sess


def next_archive_target(archive_root: Path, project_dir_name: str, day: str) -> Path:
    base = archive_root / project_dir_name
    if not base.exists():
        return base
    dated = archive_root / f"{project_dir_name} - archived-{day}"
    if not dated.exists():
        return dated
    idx = 2
    while True:
        candidate = archive_root / f"{project_dir_name} - archived-{day}-{idx:02d}"
        if not candidate.exists():
            return candidate
        idx += 1


def command_project_new(vault: Path, templates_path: str, name: str) -> Path:
    day = today_str()
    safe = sanitize_name(name)
    proj_dir = vault / "03_Projects" / "Active" / safe
    proj_dir.mkdir(parents=True, exist_ok=True)
    project_file = proj_dir / "Project.md"
    agents_file = proj_dir / "AGENTS.md"
    log_file = proj_dir / "Log.md"

    if not project_file.exists():
        t = vault / templates_path / "Project.md"
        atomic_write(project_file, render_template(t, {"date": day, "updated": now_iso(), "project_name": safe}))
    if not agents_file.exists():
        t = vault / templates_path / "AGENTS-Project.md"
        atomic_write(agents_file, render_template(t, {"date": day, "updated": now_iso(), "project_name": safe}))
    if not log_file.exists():
        t = vault / templates_path / "Log.md"
        atomic_write(log_file, render_template(t, {"date": day, "updated": now_iso(), "project_name": safe}))
    return proj_dir


def _find_project_dir_by_status(vault: Path, status_dir: str, name: str) -> Path | None:
    root = vault / "03_Projects" / status_dir
    if not root.exists():
        return None
    raw = (name or "").strip()
    safe = sanitize_name(raw)
    direct = root / safe
    if direct.exists():
        return direct

    candidates = [p for p in root.iterdir() if p.is_dir()]
    lower_raw = raw.lower()
    lower_safe = safe.lower()
    for p in candidates:
        n = p.name.lower()
        if n == lower_raw or n == lower_safe:
            return p
    for p in candidates:
        n = p.name.lower()
        if lower_raw and (lower_raw in n or n in lower_raw):
            return p
    return None


def command_project_start(vault: Path, name: str) -> Path:
    src = _find_project_dir_by_status(vault, "Backlog", name)
    if not src:
        raise FileNotFoundError(f"backlog project not found: {name}")
    active_root = vault / "03_Projects" / "Active"
    active_root.mkdir(parents=True, exist_ok=True)
    dst = next_available_dir(active_root / src.name, "active")
    shutil.move(str(src), str(dst))

    project_note = dst / "Project.md"
    if project_note.exists():
        txt = project_note.read_text(encoding="utf-8")
        txt = replace_or_add_frontmatter_fields(txt, {"status": "active", "updated": now_iso()})
        atomic_write(project_note, txt)

    generate_projects_base(vault)
    return dst


def _extract_title_for_listing(content: str, fallback: str) -> str:
    for ln in content.splitlines():
        s = ln.strip()
        if s.startswith("# "):
            return s[2:].strip() or fallback
    return fallback


def _extract_brief_for_listing(content: str) -> str:
    body = _strip_frontmatter(content)
    for ln in body.splitlines():
        s = ln.strip()
        if not s:
            continue
        if s.startswith("#") or s.startswith("---"):
            continue
        return s[:120]
    return "-"


def command_idea_list(vault: Path, top_k: int = 30) -> str:
    ideas_root = vault / "03_Projects" / "Ideas"
    if not ideas_root.exists():
        return f"ideas folder not found: {ideas_root}"

    rows: list[tuple[str, str, str, str]] = []
    for p in sorted(ideas_root.rglob("*.md")):
        try:
            txt = p.read_text(encoding="utf-8")
        except Exception:
            continue
        fm = _extract_frontmatter_map(txt)
        created = _strip_wrapped(fm.get("created", ""))
        if not created:
            d = parse_note_date_from_filename(p.name)
            created = d.isoformat() if d else ""
        title = _extract_title_for_listing(txt, p.stem)
        brief = _extract_brief_for_listing(txt)
        rows.append((created, _wikilink_rel(vault, p), title, brief))

    if not rows:
        return "No ideas found under 03_Projects/Ideas."
    rows.sort(key=lambda x: (x[0], x[2]), reverse=True)

    out: list[str] = []
    out.append(f"Ideas ({min(len(rows), top_k)}/{len(rows)}):")
    for created, link, title, brief in rows[: max(1, top_k)]:
        out.append(f"- {link} | {created or 'n/a'} | {title}")
        out.append(f"  {brief}")
    return "\n".join(out)


def command_idea_capture(vault: Path, title: str, content: str, tags_csv: str) -> Path:
    day = today_str()
    safe_title = slugify_topic(title)[:80] or "untitled-idea"
    ideas_root = vault / "03_Projects" / "Ideas"
    ideas_root.mkdir(parents=True, exist_ok=True)
    note = next_available_path(ideas_root / f"{day} - idea - {safe_title}.md", "idea")

    tags = ["idea"]
    if tags_csv.strip():
        tags.extend([t.strip() for t in tags_csv.split(",") if t.strip()])
    tags = list(dict.fromkeys(tags))
    body = (content or "").strip()
    if not body:
        body = "-"

    md = (
        "---\n"
        "type: project\n"
        "status: draft\n"
        "area: projects\n"
        f"created: {day}\n"
        f"updated: {now_iso()}\n"
        f"owner: {current_owner()}\n"
        "authoring: mixed\n"
        f"tags: [{', '.join(tags)}]\n"
        f"idea_title: \"{title.strip() or safe_title}\"\n"
        "---\n\n"
        f"# Idea - {title.strip() or safe_title}\n\n"
        "## Description\n"
        f"{body}\n\n"
        "## Why It Matters\n"
        "- \n\n"
        "## Potential Next Steps\n"
        "- [ ] Clarify scope and expected value.\n"
        "- [ ] Decide whether to move into Backlog as a project.\n\n"
        "## Related Notes\n"
        "- \n"
    )
    atomic_write(note, md)
    return note


def _first_meaningful_line(text: str) -> str:
    body = _strip_frontmatter(text)
    for ln in body.splitlines():
        s = ln.strip()
        if not s:
            continue
        if s.startswith("#"):
            continue
        if s.startswith("---"):
            continue
        return s[:220]
    return "-"


def _merge_tags(base: list[str], tags_csv: str) -> str:
    tags = list(base)
    if tags_csv.strip():
        tags.extend([t.strip() for t in tags_csv.split(",") if t.strip()])
    tags = list(dict.fromkeys(tags))
    return "[" + ", ".join(tags) + "]"


def command_thinking_capture(vault: Path, templates_path: str, title: str, content: str, tags_csv: str) -> Path:
    day = today_str()
    safe_title = slugify_topic(title)[:80] or "thinking"
    thinking_dir = vault / "05_Thinking"
    thinking_dir.mkdir(parents=True, exist_ok=True)
    note = next_available_path(thinking_dir / f"{day} - {safe_title}.md", "thinking")

    tpl = vault / templates_path / "Thinking.md"
    if tpl.exists():
        md = render_template(tpl, {"date": day, "updated": now_iso()})
    else:
        md = (
            "---\n"
            "type: thinking\n"
            "status: draft\n"
            "area: thinking\n"
            f"created: {day}\n"
            f"updated: {now_iso()}\n"
            f"owner: {current_owner()}\n"
            "authoring: mixed\n"
            "tags: [thinking]\n"
            "---\n\n"
            f"# Thinking - {title}\n\n"
            "## Insight\n-\n\n"
            "## Why It Matters\n-\n\n"
            "## Linked Sources\n-\n\n"
            "## Actionable Rule\n- [ ] \n"
        )

    custom_title = title.strip() or safe_title
    md = re.sub(r"(?m)^#\s*Thinking\s*-\s*.*$", f"# Thinking - {custom_title}", md, count=1)
    body = (content or "").strip() or "-"
    md = replace_section_body(md, "## Insight", body + "\n")
    md = replace_or_add_frontmatter_fields(
        md,
        {
            "updated": now_iso(),
            "authoring": "mixed",
            "tags": _merge_tags(["thinking"], tags_csv),
        },
    )
    atomic_write(note, md)
    return note


def _normalize_life_area(area: str | None, fallback_text: str = "") -> str:
    raw = (area or "").strip().lower()
    if raw:
        if raw in ("diet", "饮食", "餐食"):
            return "Diet"
        if raw in ("exercise", "fitness", "workout", "训练", "运动"):
            return "Exercise"
        if raw in ("reading", "read", "阅读"):
            return "Reading"
        if raw in ("general", "memo", "notes", "备忘", "通用"):
            return "General"
    merged = (fallback_text or "").lower()
    if any(x in merged for x in ("饮食", "餐", "diet", "kcal", "卡路里")):
        return "Diet"
    if any(x in merged for x in ("训练", "运动", "exercise", "workout", "fitness")):
        return "Exercise"
    if any(x in merged for x in ("阅读", "读书", "reading", "book")):
        return "Reading"
    return "General"


def _life_bucket_dir(vault: Path, status: str, area: str | None = None) -> Path:
    bucket = {
        "active": "Active",
        "backlog": "Backlog",
        "closed": "Closed",
    }.get((status or "active").strip().lower(), "Active")
    base = vault / "06_PersonalLife" / bucket
    if bucket == "Active":
        folder = _normalize_life_area(area)
        if folder != "General":
            return base / folder
    return base


def command_life_memo(vault: Path, title: str, content: str, tags_csv: str) -> Path:
    day = today_str()
    safe_title = slugify_topic(title)[:80] or "memo"
    backlog = _life_bucket_dir(vault, "backlog")
    backlog.mkdir(parents=True, exist_ok=True)
    note = next_available_path(backlog / f"{day} - {safe_title}.md", "memo")
    body = (content or "").strip() or "-"
    md = (
        "---\n"
        "type: personal-life\n"
        "status: backlog\n"
        "area: personal-life\n"
        f"created: {day}\n"
        f"updated: {now_iso()}\n"
        f"owner: {current_owner()}\n"
        "authoring: mixed\n"
        f"tags: {_merge_tags(['personal-life', 'memo'], tags_csv)}\n"
        "---\n\n"
        f"# Personal Memo - {title.strip() or safe_title}\n\n"
        "## Memo\n"
        f"{body}\n\n"
        "## Next Actions\n"
        "- [ ] Review and decide whether to promote to Active.\n"
    )
    atomic_write(note, md)
    return note


def command_life_status(vault: Path, top_k: int = 20) -> str:
    root = vault / "06_PersonalLife" / "Active"
    if not root.exists():
        return f"personal-life active folder not found: {root}"
    notes: list[tuple[str, Path, str]] = []
    for p in root.rglob("*.md"):
        try:
            txt = p.read_text(encoding="utf-8")
        except Exception:
            continue
        fm = _extract_frontmatter_map(txt)
        updated = _strip_wrapped(fm.get("updated", "")) or _strip_wrapped(fm.get("created", ""))
        notes.append((updated, p, _first_meaningful_line(txt)))
    if not notes:
        return "No active personal-life notes found."
    notes.sort(key=lambda x: ((x[0] or ""), x[1].as_posix()), reverse=True)
    lines = ["PersonalLife Active Snapshot:"]
    for updated, p, brief in notes[: max(1, top_k)]:
        lines.append(f"- {_wikilink_rel(vault, p)} | updated={updated or 'n/a'}")
        lines.append(f"  {brief}")
    return "\n".join(lines)


def command_life_plan_set(vault: Path, title: str, content: str, area: str, status: str, tags_csv: str) -> Path:
    day = today_str()
    safe_title = slugify_topic(title)[:80] or "plan"
    target_dir = _life_bucket_dir(vault, status, area=area or title + " " + content)
    target_dir.mkdir(parents=True, exist_ok=True)
    existing = []
    for p in target_dir.glob("*.md"):
        stem = p.stem.lower()
        if safe_title in stem or stem in safe_title:
            existing.append(p)
    if existing:
        note = sorted(existing, key=lambda x: x.name)[-1]
        md = note.read_text(encoding="utf-8")
        md = ensure_section(md, "## Plan", "## Plan\n")
        body = get_section_body(md, "## Plan").rstrip()
        add = (content or "").strip() or "-"
        if add not in body:
            body = (body + "\n- " + add).strip() + "\n"
        md = replace_section_body(md, "## Plan", body)
        md = replace_or_add_frontmatter_fields(md, {"updated": now_iso()})
        atomic_write(note, md)
        return note

    note = next_available_path(target_dir / f"{day} - {safe_title}.md", "lifeplan")
    merged_tags = _merge_tags(["personal-life", "plan"], tags_csv)
    bucket_status = (status or "active").strip().lower()
    bucket_status = "active" if bucket_status not in ("active", "backlog", "closed") else bucket_status
    body = (content or "").strip() or "-"
    md = (
        "---\n"
        "type: personal-life\n"
        f"status: {bucket_status}\n"
        "area: personal-life\n"
        f"created: {day}\n"
        f"updated: {now_iso()}\n"
        f"owner: {current_owner()}\n"
        "authoring: mixed\n"
        f"tags: {merged_tags}\n"
        "---\n\n"
        f"# Life Plan - {title.strip() or safe_title}\n\n"
        "## Goal\n"
        "- \n\n"
        "## Plan\n"
        f"- {body}\n\n"
        "## Milestones\n"
        "- [ ] \n"
    )
    atomic_write(note, md)
    return note


def command_article_draft(vault: Path, templates_path: str, title: str, content: str, tags_csv: str) -> Path:
    day = today_str()
    safe_title = slugify_topic(title)[:80] or "article"
    drafts = vault / "07_Articles" / "Drafts"
    drafts.mkdir(parents=True, exist_ok=True)
    note = next_available_path(drafts / f"{day} - {safe_title}.md", "draft")

    tpl = vault / templates_path / "Article.md"
    if tpl.exists():
        md = render_template(tpl, {"date": day, "updated": now_iso()})
    else:
        md = (
            "---\n"
            "type: article\n"
            "status: draft\n"
            "area: articles\n"
            f"created: {day}\n"
            f"updated: {now_iso()}\n"
            f"owner: {current_owner()}\n"
            "authoring: mixed\n"
            "tags: [article]\n"
            "platforms: [xhs, zhihu, twitter, medium]\n"
            "publish_status: draft\n"
            "publish_url: \"\"\n"
            "---\n\n"
            f"# Article - {title}\n\n"
            "## Working Title\n-\n\n"
            "## Outline\n- \n\n"
            "## Draft\n-\n"
        )

    custom_title = title.strip() or safe_title
    md = re.sub(r"(?m)^#\s*Article\s*-\s*.*$", f"# Article - {custom_title}", md, count=1)
    md = replace_section_body(md, "## Working Title", f"{custom_title}\n")
    draft_body = (content or "").strip() or "-"
    md = replace_section_body(md, "## Draft", draft_body + "\n")
    md = replace_or_add_frontmatter_fields(
        md,
        {
            "updated": now_iso(),
            "status": "draft",
            "publish_status": "draft",
            "tags": _merge_tags(["article", "draft"], tags_csv),
        },
    )
    atomic_write(note, md)
    return note


def find_article_note_by_ref(vault: Path, ref: str) -> Path:
    roots = [
        vault / "07_Articles" / "Drafts",
        vault / "07_Articles" / "Scheduled",
        vault / "07_Articles" / "Published",
    ]
    raw = (ref or "").strip()
    probes = []
    if raw:
        p = Path(raw)
        probes.extend([p, vault / raw])
        for r in roots:
            probes.append(r / raw)
            probes.append(r / f"{raw}.md")
    for p in probes:
        if p.exists() and p.is_file():
            return p.resolve()

    needle = raw.lower().removesuffix(".md")
    matches: list[Path] = []
    for r in roots:
        if not r.exists():
            continue
        for p in r.glob("*.md"):
            if needle and (needle in p.stem.lower() or p.stem.lower() in needle):
                matches.append(p)
                continue
            if not needle:
                continue
            try:
                txt = p.read_text(encoding="utf-8")
            except Exception:
                continue
            fm = _extract_frontmatter_map(txt)
            cands = [
                (fm.get("title", "") or "").lower(),
                (fm.get("topic", "") or "").lower(),
                _first_meaningful_line(txt).lower(),
            ]
            if any(needle in c for c in cands if c):
                matches.append(p)
                continue
            for ln in txt.splitlines():
                s = ln.strip().lower()
                if not s:
                    continue
                if s.startswith("# article -") or s.startswith("## working title"):
                    if needle in s:
                        matches.append(p)
                        break
    if not matches:
        raise FileNotFoundError(f"no article note matched: {ref}")
    matches.sort(key=lambda x: x.name, reverse=True)
    return matches[0]


def command_article_move(
    vault: Path,
    ref: str,
    to_state: str,
    *,
    when: str | None = None,
    publish_url: str = "",
) -> tuple[Path, Path]:
    src = find_article_note_by_ref(vault, ref)
    state = (to_state or "").strip().lower()
    if state not in ("scheduled", "published"):
        raise ValueError("article move target must be scheduled or published")
    target_dir = vault / "07_Articles" / ARTICLE_STATE_DIR[state]
    target_dir.mkdir(parents=True, exist_ok=True)

    md = src.read_text(encoding="utf-8")
    fields = {
        "status": state,
        "publish_status": state,
        "updated": now_iso(),
    }
    if when:
        d = resolve_human_date(when)
        if state == "scheduled":
            fields["scheduled_for"] = d.isoformat()
        else:
            fields["published_at"] = d.isoformat()
    elif state == "published":
        fields["published_at"] = today_str()
    if publish_url.strip():
        fields["publish_url"] = f"\"{publish_url.strip()}\""
    md = replace_or_add_frontmatter_fields(md, fields)
    if state == "published":
        md = remove_frontmatter_fields(md, ["scheduled_for"])
    if state == "scheduled":
        md = remove_frontmatter_fields(md, ["published_at"])

    dst = next_available_path(target_dir / src.name, state)
    atomic_write(dst, md)
    src.unlink(missing_ok=True)
    return src, dst


def _project_scope_from_path(vault: Path, p: Path) -> str:
    try:
        rel = p.relative_to(vault).as_posix().lower()
    except Exception:
        rel = p.as_posix().lower()
    if "03_projects/active/" in rel:
        return "active"
    if "03_projects/backlog/" in rel:
        return "backlog"
    if "03_projects/closed/" in rel:
        return "closed"
    if "03_projects/ideas/" in rel:
        return "ideas"
    return "projects"


def command_project_query(vault: Path, keyword: str, top_k: int = 10) -> str:
    tokens = tokenize_query(keyword)
    if not tokens:
        return "No valid project query keywords detected."

    root = vault / "03_Projects"
    if not root.exists():
        return f"projects folder not found: {root}"

    hits: list[tuple[int, Path, str, str, str]] = []
    for p in root.rglob("*.md"):
        try:
            txt = p.read_text(encoding="utf-8")
        except Exception:
            continue
        s = score_note(p, txt, tokens)
        if s <= 0:
            continue
        fm = _extract_frontmatter_map(txt)
        status = _strip_wrapped(fm.get("status", "")) or _project_scope_from_path(vault, p)
        next_action = _strip_wrapped(fm.get("next_action", ""))
        snippet = pick_snippet(txt, tokens)
        hits.append((s, p, status, next_action, snippet))

    if not hits:
        return f"No project notes matched '{keyword}'."
    hits.sort(key=lambda x: x[0], reverse=True)

    lines: list[str] = []
    lines.append(f"Project Query: {keyword}")
    for s, p, status, next_action, snippet in hits[: max(1, top_k)]:
        lines.append(f"- {_wikilink_rel(vault, p)} | status={status} | score={s}")
        if next_action:
            lines.append(f"  next_action: {next_action}")
        lines.append(f"  snippet: {snippet}")
    return "\n".join(lines)


def _semantic_domain_of_path(vault: Path, p: Path) -> str:
    rel = p.relative_to(vault).as_posix().lower()
    if rel.startswith("03_projects/ideas/"):
        return "ideas"
    if rel.startswith("04_resources/"):
        return "resources"
    if rel.startswith("05_thinking/"):
        return "thinking"
    return "other"


def command_brainstorm(vault: Path, topic: str, top_k: int = 12) -> str:
    tokens = tokenize_query(topic)
    if not tokens:
        return "No valid brainstorm topic keywords detected."

    roots = [
        vault / "03_Projects" / "Ideas",
        vault / "04_Resources" / "Inbox",
        vault / "04_Resources" / "Library",
        vault / "05_Thinking",
    ]
    domain_bonus = {"ideas": 4, "resources": 2, "thinking": 3, "other": 0}
    hits: list[tuple[int, Path, str, str]] = []

    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*.md"):
            try:
                txt = p.read_text(encoding="utf-8")
            except Exception:
                continue
            domain = _semantic_domain_of_path(vault, p)
            score = score_note(p, txt, tokens) + domain_bonus.get(domain, 0)
            if score <= 0:
                continue
            snippet = pick_snippet(txt, tokens)
            hits.append((score, p, domain, snippet))

    if not hits:
        return f"No brainstorm context found for '{topic}'."

    hits.sort(key=lambda x: x[0], reverse=True)
    selected = hits[: max(3, top_k)]
    by_domain = {"ideas": [], "resources": [], "thinking": []}
    for item in selected:
        by_domain.setdefault(item[2], []).append(item)

    lines: list[str] = []
    lines.append(f"Brainstorm Topic: {topic}")
    lines.append("Context blend: Ideas + Resources + Thinking")
    lines.append("")
    lines.append("## Relevant Notes")
    for score, p, domain, snippet in selected:
        lines.append(f"- {_wikilink_rel(vault, p)} | domain={domain} | score={score}")
        lines.append(f"  {snippet}")

    lines.append("")
    lines.append("## Candidate Directions")
    i = 1
    for domain in ("ideas", "thinking", "resources"):
        if not by_domain.get(domain):
            continue
        _, p, _, snippet = by_domain[domain][0]
        lines.append(f"{i}. Start from {domain}: {_wikilink_rel(vault, p)}")
        lines.append(f"   Hypothesis: {snippet}")
        i += 1
    if i == 1:
        lines.append("1. Collect more relevant notes before brainstorming.")

    lines.append("")
    lines.append("## Next Actions")
    lines.append("- [ ] Pick one candidate direction.")
    lines.append("- [ ] Define one 2-hour experiment with measurable output.")
    lines.append("- [ ] Create or update a project note if direction is accepted.")
    return "\n".join(lines)


def command_close(vault: Path, templates_path: str, dashboards_mode: str) -> Path:
    d = today_date()
    day = d.isoformat()
    daily_path = command_today(vault, templates_path, dashboards_mode)
    sessions_dir = daily_sessions_dir(vault, d, ensure=False)
    session_files = sorted(sessions_dir.glob(f"{day} session - *.md")) if sessions_dir.exists() else []

    actions: list[str] = []
    memories: list[str] = []
    session_links: list[str] = []
    seen = set()

    for s in session_files:
        text = s.read_text(encoding="utf-8")
        session_links.append(_wikilink_rel(vault, s))
        for b in markdown_bullets(get_section_body(text, "## Next Actions")):
            if b not in seen:
                actions.append(b)
                seen.add(b)
        for b in markdown_bullets(get_section_body(text, "## Outputs"))[:2]:
            if b not in seen:
                memories.append(b)
                seen.add(b)

    if not actions:
        actions = ["- [ ] No next actions extracted from today's sessions."]
    if not memories:
        memories = ["- No key outputs extracted; review sessions manually."]

    close_body = (
        "### Consolidated Actions\n"
        + "\n".join(actions)
        + "\n\n### Memory Candidates\n"
        + "\n".join(memories)
        + "\n\n### Source Sessions\n"
        + ("\n".join(f"- {x}" for x in session_links) if session_links else "- None")
        + "\n"
    )
    daily_text = daily_path.read_text(encoding="utf-8")
    daily_text = replace_section_body(daily_text, "## Close", close_body)
    daily_text = replace_or_add_frontmatter_fields(daily_text, {"updated": now_iso()})
    atomic_write(daily_path, daily_text)
    return daily_path


def _session_rollup_for_day(vault: Path, session_paths: list[Path]) -> str:
    lines: list[str] = []
    lines.append("### Session Rollup")
    lines.append(f"- Session count: {len(session_paths)}")
    if not session_paths:
        lines.append("- No sessions recorded for this date.")
        return "\n".join(lines) + "\n"

    outputs: list[str] = []
    actions: list[str] = []
    for p in session_paths:
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        outputs.extend(markdown_bullets(get_section_body(text, "## Outputs"))[:2])
        actions.extend(markdown_bullets(get_section_body(text, "## Next Actions"))[:2])
        lines.append(f"- {_wikilink_rel(vault, p)}")

    lines.append("")
    lines.append("### Key Outputs")
    if outputs:
        uniq = list(dict.fromkeys(outputs))
        lines.extend(uniq[:12])
    else:
        lines.append("- No explicit outputs found.")

    lines.append("")
    lines.append("### Key Next Actions")
    if actions:
        uniq_a = list(dict.fromkeys(actions))
        lines.extend(uniq_a[:12])
    else:
        lines.append("- [ ] No explicit next actions found.")
    return "\n".join(lines) + "\n"


def command_daily_wrapup(
    vault: Path,
    templates_path: str,
    dashboards_mode: str,
    date_input: str,
    *,
    push: bool = False,
) -> tuple[Path, str | None]:
    d = resolve_human_date(date_input)
    day = d.isoformat()

    if d == today_date():
        daily = command_today(vault, templates_path, dashboards_mode)
    else:
        daily = ensure_daily_note_for_date(vault, templates_path, d, dashboards_mode)

    content = daily.read_text(encoding="utf-8")
    sdir = daily_sessions_dir(vault, d, ensure=False)
    sessions = sorted(sdir.glob(f"{day} session - *.md")) if sdir.exists() else []
    session_links = [_wikilink_rel(vault, p) for p in sessions]
    plan = daily_plan_path(vault, d, ensure=False)
    plan_link = _wikilink_rel(vault, plan) if plan.exists() else None
    content = _refresh_daily_indexes(content, vault, d, session_links, plan_link)
    notes_body = _session_rollup_for_day(vault, sessions)
    content = replace_section_body(content, "## Notes", notes_body)
    content = replace_or_add_frontmatter_fields(content, {"updated": now_iso()})
    atomic_write(daily, content)

    sync_msg = None
    if push:
        sync_msg = sync_vault_git(vault, f"chore(vault): daily wrapup {day}")
    return daily, sync_msg


def _clean_signal_line(line: str) -> str:
    s = line.strip()
    if not s:
        return ""
    if s.startswith("---"):
        return ""
    if s.startswith("#"):
        return ""
    s = re.sub(r"^[-*]\s+", "", s)
    s = re.sub(r"^\d+\.\s+", "", s)
    s = re.sub(r"^\[[ xX]\]\s*", "", s)
    s = re.sub(r"^>\s*", "", s)
    s = re.sub(r"\[\[([^\]|#]+)(?:[^\]]*)\]\]", r"\1", s)
    s = s.replace("`", "").strip()
    if len(s) < 8:
        return ""
    return s


def _collect_signal_lines(text: str, heading: str) -> list[str]:
    body = get_section_body(text, heading)
    if not body:
        return []
    out: list[str] = []
    for ln in body.splitlines():
        cleaned = _clean_signal_line(ln)
        if cleaned:
            out.append(cleaned)
    return out


def _collect_graduate_signals(text: str) -> tuple[list[str], list[str]]:
    lines: list[str] = []
    actions: list[str] = []
    for heading in ("## Close", "## Outputs", "## TL;DR", "## Key Points", "## Notes"):
        lines.extend(_collect_signal_lines(text, heading))

    next_actions = _collect_signal_lines(text, "## Next Actions")
    actions.extend(next_actions)
    lines.extend(next_actions)

    if lines:
        return lines, actions

    for ln in text.splitlines():
        cleaned = _clean_signal_line(ln)
        if cleaned:
            lines.append(cleaned)
        if len(lines) >= 80:
            break
    return lines, actions


def _tokens_for_graduate(text: str) -> list[str]:
    raw = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9_-]{2,}", text.lower())
    stop = {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "have",
        "will",
        "into",
        "your",
        "about",
        "today",
        "session",
        "daily",
        "notes",
    }
    return [t for t in raw if t not in stop]


def command_graduate(vault: Path, templates_path: str, days: int, force: bool) -> tuple[int, int]:
    start_day = today_date() - timedelta(days=days - 1)
    end_day = today_date()
    thinking_dir = vault / "05_Thinking"
    lib_dir = vault / "04_Resources" / "Library"
    thinking_template = vault / templates_path / "Thinking.md"

    created = 0
    skipped = 0
    d = start_day
    while d <= end_day:
        day = d.isoformat()
        source_paths: list[Path] = []

        dp = daily_note_path(vault, d, ensure=False)
        if dp.exists():
            source_paths.append(dp)
        sdir = daily_sessions_dir(vault, d, ensure=False)
        if sdir.exists():
            for s in sorted(sdir.glob(f"{day} session - *.md")):
                source_paths.append(s)
        for r in sorted(lib_dir.glob(f"{day} - *.md")):
            source_paths.append(r)
        if not source_paths:
            d += timedelta(days=1)
            continue

        name = f"{day} - insight-from-recent-notes.md"
        out_path = thinking_dir / name
        if out_path.exists() and not force:
            skipped += 1
            d += timedelta(days=1)
            continue

        source_links = [_wikilink_rel(vault, p) for p in source_paths]
        signal_lines: list[str] = []
        action_lines: list[str] = []
        for p in source_paths:
            try:
                text = p.read_text(encoding="utf-8")
            except Exception:
                continue
            lines, actions = _collect_graduate_signals(text)
            signal_lines.extend(lines)
            action_lines.extend(actions)

        if not signal_lines:
            signal_lines = ["No strong recurring signals were extracted; review linked sources manually."]

        line_freq = Counter(signal_lines)
        token_freq = Counter()
        for ln in signal_lines:
            token_freq.update(_tokens_for_graduate(ln))

        def line_score(line: str) -> int:
            score = line_freq[line] * 3
            for t in _tokens_for_graduate(line):
                score += min(token_freq[t], 4)
            return score

        ranked_lines = sorted(line_freq.keys(), key=lambda ln: (line_score(ln), len(ln)), reverse=True)
        top_lines = ranked_lines[:3]
        top_tokens = [t for t, _ in token_freq.most_common(5)]

        insight_parts: list[str] = []
        if top_tokens:
            insight_parts.append("Recurring themes: " + ", ".join(top_tokens) + ".")
        for ln in top_lines:
            insight_parts.append(f"- {ln}")
        insight_body = "\n".join(insight_parts) + "\n"

        why_body = (
            f"This draft distills {len(source_paths)} notes for {day}. "
            f"Top signal recurrence: {max(line_freq.values())}."
            "\n"
        )

        if action_lines:
            action_seed = action_lines[0]
        elif top_lines:
            action_seed = top_lines[0]
        else:
            action_seed = "Review linked notes and define one reusable operating rule."
        action_body = f"- [ ] {action_seed}\n"

        draft = render_template(thinking_template, {"date": day, "updated": now_iso()})
        draft = replace_or_add_frontmatter_fields(draft, {"authoring": "human", "status": "draft", "updated": now_iso()})
        draft = replace_section_body(draft, "## Insight", insight_body)
        draft = replace_section_body(draft, "## Why It Matters", why_body)
        draft = replace_section_body(draft, "## Linked Sources", "\n".join(f"- {x}" for x in source_links) + "\n")
        draft = replace_section_body(draft, "## Actionable Rule", action_body)
        atomic_write(out_path, draft)
        created += 1
        d += timedelta(days=1)
    return created, skipped


def find_active_project_dir(vault: Path, name: str) -> Path | None:
    safe = sanitize_name(name)
    direct = vault / "03_Projects" / "Active" / safe
    if direct.exists():
        return direct
    for p in (vault / "03_Projects" / "Active").glob("*"):
        if p.is_dir() and p.name.lower() == safe.lower():
            return p
    legacy = vault / "03_Projects" / "Active" / f"Project - {safe}"
    if legacy.exists():
        return legacy
    return None


def command_project_close(vault: Path, templates_path: str, name: str) -> tuple[Path, Path]:
    day = today_str()
    proj_dir = find_active_project_dir(vault, name)
    if not proj_dir:
        raise FileNotFoundError(f"active project not found: {name}")

    safe = sanitize_name(name)
    project_note = proj_dir / "Project.md"
    if project_note.exists():
        txt = project_note.read_text(encoding="utf-8")
        txt = replace_or_add_frontmatter_fields(txt, {"status": "closed", "updated": now_iso()})
        atomic_write(project_note, txt)

    archive_root = vault / "03_Projects" / "Closed"
    archive_root.mkdir(parents=True, exist_ok=True)
    archive_target = next_archive_target(archive_root, proj_dir.name, day)
    shutil.move(str(proj_dir), str(archive_target))

    archived_project_note = archive_target / "Project.md"
    if archived_project_note.exists():
        txt = archived_project_note.read_text(encoding="utf-8")
        txt = replace_or_add_frontmatter_fields(txt, {"status": "closed", "updated": now_iso()})
        atomic_write(archived_project_note, txt)

    report_path = archive_target / "Report.md"
    if not report_path.exists():
        report = render_report_template(day=day, updated=now_iso(), project_name=safe)
        archive_rel = archive_target.relative_to(vault).as_posix()
        report += (
            "\n## Project Links\n"
            f"- [[{archive_rel}/Project]]\n"
            f"- [[{archive_rel}/AGENTS]]\n"
        )
        atomic_write(report_path, report)
    return report_path, archive_target


def sync_vault_git(vault: Path, commit_message: str) -> str:
    if not (vault / ".git").exists():
        return "git sync skipped: vault is not a git repository."
    try:
        st = subprocess.run(
            ["git", "-C", str(vault), "status", "--porcelain"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        if st.returncode != 0:
            return f"git sync failed: {st.stderr.strip() or st.stdout.strip()}"
        if not (st.stdout or "").strip():
            return "git sync: no changes."

        subprocess.run(
            ["git", "-C", str(vault), "add", "-A"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=True,
        )
        c = subprocess.run(
            ["git", "-C", str(vault), "commit", "-m", commit_message],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if c.returncode != 0:
            msg = (c.stderr or c.stdout or "").strip().lower()
            if "nothing to commit" in msg:
                return "git sync: no changes."
            return f"git commit failed: {(c.stderr or c.stdout).strip()}"

        p = subprocess.run(
            ["git", "-C", str(vault), "push"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        if p.returncode != 0:
            return f"git push failed: {(p.stderr or p.stdout).strip()}"
        return "git sync: committed and pushed."
    except Exception as e:
        return f"git sync failed: {e}"


def resolve_obsidian_cli_cmd() -> list[str] | None:
    env_cmd = (os.getenv("OBSIDIAN_CLI_CMD") or "").strip()
    if env_cmd:
        try:
            parts = shlex.split(env_cmd, posix=False)
            if parts:
                return parts
        except Exception:
            pass

    env_path = (os.getenv("OBSIDIAN_CLI_PATH") or "").strip()
    if env_path:
        p = Path(env_path)
        if p.exists():
            return [str(p)]

    for name in ("obsidian", "obsidian-cli"):
        p = shutil.which(name)
        if p:
            return [p]

    candidates = [
        Path.home() / "AppData" / "Local" / "Programs" / "Obsidian" / "Obsidian.com",
        Path.home() / "AppData" / "Local" / "Programs" / "Obsidian" / "obsidian.com",
    ]
    for c in candidates:
        if c.exists():
            return [str(c)]
    return None


def run_obsidian_cli(args: list[str], timeout: int = 45) -> tuple[subprocess.CompletedProcess[str] | None, str | None]:
    cmd = resolve_obsidian_cli_cmd()
    if not cmd:
        return None, "Obsidian CLI command not found."
    try:
        r = subprocess.run(
            cmd + args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return r, None
    except Exception as e:
        return None, f"Obsidian CLI execution error: {e}"


def is_obsidian_running() -> bool:
    try:
        if os.name == "nt":
            r = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq Obsidian.exe"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            out = (r.stdout or "").lower()
            return "obsidian.exe" in out
        r = subprocess.run(
            ["ps", "-A"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        return "obsidian" in (r.stdout or "").lower()
    except Exception:
        return False


def find_obsidian_desktop() -> str | None:
    candidates = [
        Path.home() / "AppData" / "Local" / "Programs" / "Obsidian" / "Obsidian.exe",
        Path("/Applications/Obsidian.app"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def command_doctor(vault: Path) -> str:
    lines: list[str] = []
    ok = 0
    warn = 0

    def line(flag: str, text: str) -> None:
        nonlocal ok, warn
        if flag == "OK":
            ok += 1
        else:
            warn += 1
        lines.append(f"[{flag}] {text}")

    desktop = find_obsidian_desktop()
    if desktop:
        line("OK", f"Detected Obsidian desktop: {desktop}")
    else:
        line("WARN", "Obsidian desktop install path not detected.")

    if is_obsidian_running():
        line("OK", "Obsidian is running.")
    else:
        line("WARN", "Obsidian is not running. Open it once before using CLI integrations.")

    if vault.exists():
        line("OK", f"Vault path exists: {vault}")
    else:
        line("WARN", f"Vault path does not exist: {vault}")

    obsidian_dir = vault / ".obsidian"
    if obsidian_dir.exists():
        line("OK", f"Detected vault config folder: {obsidian_dir}")
    else:
        line("WARN", f".obsidian folder not found: {obsidian_dir}")

    cmd = resolve_obsidian_cli_cmd()
    if cmd:
        line("OK", f"Detected Obsidian CLI command: {' '.join(cmd)}")
        r_help, err = run_obsidian_cli(["help"], timeout=20)
        if err:
            line("WARN", err)
        elif r_help and r_help.returncode == 0:
            line("OK", "Obsidian CLI `help` call succeeded.")
        else:
            msg = ((r_help.stderr if r_help else "") or (r_help.stdout if r_help else "")).strip()
            line("WARN", f"Obsidian CLI `help` call failed: {msg or 'unknown error'}")

        r_search, err2 = run_obsidian_cli(["search", "query=SecondBrain", "limit=1"], timeout=20)
        if err2:
            line("WARN", err2)
        elif r_search and r_search.returncode == 0:
            line("OK", "Obsidian CLI `search` call succeeded.")
        else:
            msg = ((r_search.stderr if r_search else "") or (r_search.stdout if r_search else "")).strip()
            line("WARN", f"Obsidian CLI `search` call failed: {msg or 'unknown error'}")
    else:
        line("WARN", "No executable Obsidian CLI command detected.")
        if os.name == "nt":
            line("WARN", "On Windows, confirm `Obsidian.com` exists with `Obsidian.exe`, or set `OBSIDIAN_CLI_PATH`.")

    lines.append("")
    lines.append(f"Result: OK={ok}, WARN={warn}")
    lines.append('Next: if WARN > 0, fix warnings first, then run `python cli/secondbrain.py ask "test" --engine obsidian`.')
    return "\n".join(lines)


def tokenize_query(text: str) -> list[str]:
    parts = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_-]{2,}", text.lower())
    uniq: list[str] = []
    seen = set()
    for p in parts:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def pick_snippet(content: str, tokens: list[str]) -> str:
    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    if not lines:
        return ""
    lowered = [ln.lower() for ln in lines]
    for i, ln in enumerate(lowered):
        if any(t in ln for t in tokens):
            return lines[i][:280]
    return lines[0][:280]


def score_note(path: Path, content: str, tokens: list[str]) -> int:
    s = 0
    stem = path.stem.lower()
    body = content.lower()
    for t in tokens:
        if t in stem:
            s += 10
        cnt = body.count(t)
        if cnt:
            s += min(cnt, 10) * 2
    return s


def vault_wikilink(vault: Path, p: Path) -> str:
    rel = p.relative_to(vault).as_posix()
    if rel.lower().endswith(".md"):
        rel = rel[:-3]
    return f"[[{rel}]]"


def command_ask_fs(vault: Path, question: str, top_k: int, tokens: list[str]) -> list[dict]:
    hits: list[tuple[int, Path, str]] = []
    for p in vault.rglob("*.md"):
        rel = p.relative_to(vault).as_posix().lower()
        if rel.startswith(".obsidian/"):
            continue
        try:
            content = p.read_text(encoding="utf-8")
        except Exception:
            continue
        score = score_note(p, content, tokens)
        if score <= 0:
            continue
        snippet = pick_snippet(content, tokens)
        hits.append((score, p, snippet))

    if not hits:
        return []
    hits.sort(key=lambda x: x[0], reverse=True)
    top = hits[: max(1, top_k)]
    out: list[dict] = []
    for score, p, snippet in top:
        out.append(
            {
                "score": score,
                "ref": vault_wikilink(vault, p),
                "snippet": snippet,
                "source": "fs",
            }
        )
    return out


def command_ask_obsidian(question: str, top_k: int, tokens: list[str]) -> tuple[list[dict], str | None]:
    r, err = run_obsidian_cli(["search", f"query={question}", f"limit={max(5, top_k * 2)}"], timeout=45)
    if err:
        return [], f"Obsidian 妫€绱㈠け璐ワ細{err}"
    if r.returncode != 0:
        msg = (r.stderr or r.stdout or "").strip()
        return [], f"Obsidian 妫€绱㈠け璐ワ細{msg or 'unknown error'}"

    lines = []
    for ln in (r.stdout or "").splitlines():
        s = ln.strip()
        if not s:
            continue
        if s.lower().startswith("usage:"):
            continue
        lines.append(s)
    if not lines:
        return [], None

    scored = []
    for ln in lines:
        low = ln.lower()
        score = 1
        for t in tokens:
            if t in low:
                score += 2
        scored.append((score, ln))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[: max(1, top_k)]
    out: list[dict] = []
    for score, ln in top:
        out.append(
            {
                "score": score,
                "ref": "obsidian-search",
                "snippet": ln[:280],
                "source": "obsidian",
            }
        )
    return out, None


def command_ask(vault: Path, question: str, top_k: int, engine: str) -> str:
    tokens = tokenize_query(question)
    if not tokens:
        return "No valid query keywords detected. Please rephrase your question."

    notices: list[str] = []
    hits: list[dict] = []
    if engine in ("fs", "hybrid"):
        hits.extend(command_ask_fs(vault, question, top_k, tokens))
    if engine in ("obsidian", "hybrid"):
        ohits, notice = command_ask_obsidian(question, top_k, tokens)
        if notice:
            notices.append(notice)
        hits.extend(ohits)

    if not hits:
        if notices:
            return f"No usable results found. Notes: {'; '.join(notices)}"
        return f"No notes related to '{question}' were found in the vault."

    hits.sort(key=lambda x: int(x.get("score", 0)), reverse=True)
    top = hits[: max(1, top_k)]

    lines: list[str] = []
    lines.append(f"Route: {engine}")
    lines.append(f"Question: {question}")
    lines.append(f"Keywords: {', '.join(tokens)}")
    if notices:
        lines.append(f"Notes: {'; '.join(notices)}")
    lines.append("")
    lines.append("Synthesis:")
    lines.append("Most relevant information from matched notes:")
    for i, h in enumerate(top[:3], start=1):
        snippet = h.get("snippet", "")
        lines.append(f"{i}. {snippet}")
    lines.append("")
    lines.append("Related Notes:")
    for h in top:
        score = h.get("score", 0)
        ref = h.get("ref", "unknown")
        src = h.get("source", "fs")
        snippet = h.get("snippet", "")
        lines.append(f"- {ref} (score={score}, source={src})")
        lines.append(f"  Snippet: {snippet}")
    return "\n".join(lines)


def _extract_frontmatter_map(content: str) -> dict:
    if not content.startswith("---\n"):
        return {}
    end = content.find("\n---\n", 4)
    if end == -1:
        return {}
    block = content[4:end]
    data = {}
    for ln in block.splitlines():
        if ":" not in ln:
            continue
        k, v = ln.split(":", 1)
        data[k.strip().lower()] = v.strip()
    return data


def _parse_loose_date(value: str) -> date | None:
    m = re.search(r"(\d{4}-\d{2}-\d{2})", value or "")
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d").date()
    except ValueError:
        return None


def _note_primary_date(path: Path, content: str) -> date:
    d = parse_note_date_from_filename(path.name)
    if d:
        return d
    fm = _extract_frontmatter_map(content)
    for k in ("created", "updated", "captured_at"):
        if k in fm:
            dd = _parse_loose_date(fm[k])
            if dd:
                return dd
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).date()
    except Exception:
        return date.today()


def _iter_vault_markdowns(vault: Path):
    for p in vault.rglob("*.md"):
        rel = p.relative_to(vault).as_posix().lower()
        if rel.startswith(".obsidian/"):
            continue
        yield p


def _extract_wikilink_targets(content: str) -> list[str]:
    out: list[str] = []
    for m in re.finditer(r"\[\[([^\]]+)\]\]", content):
        raw = m.group(1).strip()
        raw = raw.split("|", 1)[0].split("#", 1)[0].strip()
        if raw:
            out.append(raw)
    return out


def _normalize_link_target(raw: str) -> str:
    t = (raw or "").strip().replace("\\", "/").lstrip("/")
    if t.lower().endswith(".md"):
        t = t[:-3]
    return t


def _build_note_graph(vault: Path) -> dict:
    notes: dict = {}
    stem_index: dict[str, list[str]] = {}

    for p in _iter_vault_markdowns(vault):
        try:
            content = p.read_text(encoding="utf-8")
        except Exception:
            continue
        rel = p.relative_to(vault).as_posix()
        rel_no_ext = rel[:-3] if rel.lower().endswith(".md") else rel
        nid = rel_no_ext.lower()
        notes[nid] = {
            "id": nid,
            "ref": f"[[{rel_no_ext}]]",
            "rel": rel_no_ext,
            "path": p,
            "content": content,
            "date": _note_primary_date(p, content),
            "links_raw": _extract_wikilink_targets(content),
        }
        stem = Path(rel_no_ext).stem.lower()
        stem_index.setdefault(stem, []).append(nid)

    def resolve_target(raw: str) -> str | None:
        t = _normalize_link_target(raw)
        if not t:
            return None
        key = t.lower()
        if key in notes:
            return key
        stem = Path(t).stem.lower()
        cands = stem_index.get(stem, [])
        if not cands:
            return None
        if len(cands) == 1:
            return cands[0]
        for c in cands:
            if c == key or c.endswith("/" + key):
                return c
        return sorted(cands, key=len)[0]

    out_links: dict[str, set[str]] = {nid: set() for nid in notes}
    in_links: dict[str, set[str]] = {nid: set() for nid in notes}
    for nid, note in notes.items():
        for raw in note["links_raw"]:
            tgt = resolve_target(raw)
            if not tgt or tgt == nid:
                continue
            out_links[nid].add(tgt)
            in_links[tgt].add(nid)
    return {"notes": notes, "out": out_links, "in": in_links}


def _score_note_ids(graph: dict, tokens: list[str]) -> list[tuple[int, str]]:
    scored: list[tuple[int, str]] = []
    for nid, note in graph["notes"].items():
        s = score_note(note["path"], note["content"], tokens)
        if s > 0:
            scored.append((s, nid))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


def command_trace(vault: Path, topic: str, top_k: int) -> str:
    tokens = tokenize_query(topic)
    if not tokens:
        return "No valid topic keywords detected."
    graph = _build_note_graph(vault)
    if not graph["notes"]:
        return "No markdown notes found in vault."

    scored = _score_note_ids(graph, tokens)
    if not scored:
        return f"No notes related to '{topic}' were found."

    anchor_id = scored[0][1]
    anchor = graph["notes"][anchor_id]
    score_map = {nid: s for s, nid in scored}

    selected: set[str] = set()
    selected.add(anchor_id)
    for _, nid in scored[: max(top_k, 8)]:
        selected.add(nid)
    selected.update(graph["in"].get(anchor_id, set()))
    selected.update(graph["out"].get(anchor_id, set()))

    timeline = sorted(
        list(selected),
        key=lambda nid: (graph["notes"][nid]["date"], -score_map.get(nid, 0), graph["notes"][nid]["rel"]),
    )

    lines: list[str] = []
    lines.append(f"Trace Topic: {topic}")
    lines.append("Method: keyword match + link graph (backlinks) + timeline sort")
    lines.append(f"Anchor Note: {anchor['ref']}")
    lines.append("")
    lines.append("Evolution Timeline:")
    for nid in timeline[: max(top_k * 2, top_k)]:
        note = graph["notes"][nid]
        dt = note["date"].isoformat()
        snippet = pick_snippet(note["content"], tokens)
        backlinks = len(graph["in"].get(nid, set()))
        lines.append(f"- {dt} | {note['ref']} | score={score_map.get(nid, 0)}, backlinks={backlinks}")
        lines.append(f"  Snippet: {snippet}")
    lines.append("")
    lines.append(f"Anchor backlinks: {len(graph['in'].get(anchor_id, set()))}")
    lines.append(f"Anchor outlinks: {len(graph['out'].get(anchor_id, set()))}")
    return "\n".join(lines)


def command_connect(vault: Path, domain_a: str, domain_b: str, top_k: int) -> str:
    tokens_a = tokenize_query(domain_a)
    tokens_b = tokenize_query(domain_b)
    if not tokens_a or not tokens_b:
        return "Provide two valid domain keywords."

    graph = _build_note_graph(vault)
    if not graph["notes"]:
        return "No markdown notes found in vault."

    scored_a = _score_note_ids(graph, tokens_a)
    scored_b = _score_note_ids(graph, tokens_b)
    if not scored_a or not scored_b:
        return f"Not enough notes found for domains: A={domain_a}, B={domain_b}."

    set_a = {nid for _, nid in scored_a[:20]}
    set_b = {nid for _, nid in scored_b[:20]}
    neighbors = {nid: (graph["out"].get(nid, set()) | graph["in"].get(nid, set())) for nid in graph["notes"]}

    candidates: list[tuple[int, str, int, int, int]] = []
    for nid, note in graph["notes"].items():
        conn_a = (1 if nid in set_a else 0) + len(neighbors[nid] & set_a)
        conn_b = (1 if nid in set_b else 0) + len(neighbors[nid] & set_b)
        if conn_a <= 0 or conn_b <= 0:
            continue
        body = note["content"].lower()
        dual_text = 1 if any(t in body for t in tokens_a) and any(t in body for t in tokens_b) else 0
        score = conn_a * 3 + conn_b * 3 + dual_text * 4
        candidates.append((score, nid, conn_a, conn_b, dual_text))

    if not candidates:
        return f"No bridge candidates found between '{domain_a}' and '{domain_b}'."

    candidates.sort(key=lambda x: x[0], reverse=True)
    lines: list[str] = []
    lines.append(f"Connect Domains: {domain_a} <-> {domain_b}")
    lines.append("Method: keyword search + link-graph bridge node detection")
    lines.append("")
    lines.append("Possible Bridge Points:")
    for score, nid, conn_a, conn_b, dual in candidates[:top_k]:
        note = graph["notes"][nid]
        snippet = pick_snippet(note["content"], tokens_a + tokens_b)
        reason = f"A杩炴帴={conn_a}, B杩炴帴={conn_b}, 鍙屽煙鏂囨湰鍛戒腑={dual}"
        lines.append(f"- {note['ref']} | score={score} | {reason}")
        lines.append(f"  Snippet: {snippet}")
    lines.append("")
    lines.append("Exploration Questions:")
    lines.append(f"- If you transfer methods from '{domain_a}' to '{domain_b}', what is the smallest viable experiment?")
    lines.append("- Which bridge note already contains evidence from both domains and is ready for a PoC?")
    lines.append("- Which bridge point has the lowest dependency and validation cost this week?")
    return "\n".join(lines)


def _strip_frontmatter(content: str) -> str:
    text = content.lstrip("\ufeff")
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            return text[end + 5 :]
    m = re.match(r"^\ufeff?---\n.*?\n---\n", content, flags=re.DOTALL)
    if m:
        return content[m.end() :]
    return content


def _extract_theme_tokens(content: str) -> list[str]:
    body = _strip_frontmatter(content)
    raw = re.findall(r"[\u4e00-\u9fff]{2,6}|[A-Za-z][A-Za-z0-9_-]{2,}", body)
    stop = {
        "today",
        "session",
        "daily",
        "project",
        "resource",
        "thinking",
        "report",
        "article",
        "tags",
        "owner",
        "status",
        "created",
        "updated",
        "notes",
        "focus",
        "outputs",
        "next",
        "actions",
        "source",
        "sources",
        "summary",
        "close",
        "dashboards",
        "https",
        "http",
        "www",
        "com",
        "source_url",
        "captured_at",
        "related_projects",
        "reliability",
        "signal",
        "status",
        "owner",
        "type",
        "authoring",
        "created",
        "updated",
        "闂",
        "璁板綍",
        "鐩稿叧",
        "浠ュ強",
        "鎴戜滑",
        "浣犱滑",
        "杩欎釜",
        "閭ｄ釜",
        "杩涜",
        "one",
        "鍙互",
        "need",
        "鍥犱负",
        "鐒跺悗",
        "鐜板湪",
        "浠婂ぉ",
    }
    out: list[str] = []
    for t in raw:
        tok = t.lower() if re.match(r"^[A-Za-z]", t) else t
        if tok in stop:
            continue
        if tok.startswith("http") or tok.endswith(".com"):
            continue
        if tok.isdigit():
            continue
        out.append(tok)
    return out


def _is_user_knowledge_note(rel_path: str) -> bool:
    rel = (rel_path or "").replace("\\", "/").lower()
    if rel.startswith("00_system/") or rel.startswith("99_archive/"):
        return False
    roots = (
        "01_inbox/",
        "02_daily/",
        "03_projects/",
        "04_resources/",
        "05_thinking/",
        "06_personallife/",
        "07_articles/",
    )
    return rel.startswith(roots)


def command_emerge(vault: Path, days: int, top_k: int) -> str:
    graph = _build_note_graph(vault)
    if not graph["notes"]:
        return "No markdown notes found in vault."

    cutoff = date.today() - timedelta(days=max(days, 1) - 1)
    recent_ids = [
        nid
        for nid, n in graph["notes"].items()
        if n["date"] >= cutoff and _is_user_knowledge_note(n["rel"])
    ]
    if not recent_ids:
        return f"No usable notes found in the last {days} days; cannot run emerge."

    df: dict[str, int] = {}
    token_to_notes: dict[str, set[str]] = {}
    note_tokens_map: dict[str, set[str]] = {}
    for nid in recent_ids:
        toks = set(_extract_theme_tokens(graph["notes"][nid]["content"]))
        if not toks:
            continue
        note_tokens_map[nid] = toks
        for t in toks:
            df[t] = df.get(t, 0) + 1
            token_to_notes.setdefault(t, set()).add(nid)

    if not df:
        return f"Notes exist in last {days} days, but no valid theme tokens were extracted."

    themes = sorted(df.items(), key=lambda x: (-x[1], x[0]))[: max(top_k, 6)]
    top_term_set = {t for t, _ in sorted(df.items(), key=lambda x: (-x[1], x[0]))[:30]}

    pair_df: dict[tuple[str, str], int] = {}
    for nid, toks in note_tokens_map.items():
        cand = sorted([t for t in toks if t in top_term_set])[:12]
        for i in range(len(cand)):
            for j in range(i + 1, len(cand)):
                a, b = cand[i], cand[j]
                pair_df[(a, b)] = pair_df.get((a, b), 0) + 1
    pair_top = sorted(pair_df.items(), key=lambda x: (-x[1], x[0][0], x[0][1]))[: max(top_k, 4)]

    lines: list[str] = []
    lines.append(f"Emerge Window: last {days} days (matched notes: {len(recent_ids)})")
    lines.append("Method: theme-term frequency + co-occurrence + evidence backlinks")
    lines.append("")
    lines.append("Latent Themes:")
    for term, cnt in themes:
        refs = sorted(token_to_notes.get(term, set()), key=lambda nid: graph["notes"][nid]["date"], reverse=True)[:2]
        ref_text = ", ".join(graph["notes"][rid]["ref"] for rid in refs) if refs else "none"
        lines.append(f"- {term}锛堝嚭鐜颁簬 {cnt} 鏉★級")
        lines.append(f"  Evidence: {ref_text}")

    lines.append("")
    lines.append("Opportunity Pairs:")
    if not pair_top:
        lines.append("- Co-occurrence signal is weak; add more tagged notes first.")
    else:
        for (a, b), cnt in pair_top:
            lines.append(f"- {a} x {b} (co-occurred in {cnt} notes): good candidate for a cross-domain test.")
    lines.append("")
    lines.append("Suggested Actions:")
    lines.append("- Pick the highest-frequency theme and define one executable weekly goal.")
    lines.append("- For the top co-occurring pair, create one bridge project or experiment note.")
    return "\n".join(lines)


def _challenge_lines(content: str, tokens: list[str]) -> list[tuple[int, str]]:
    cues = [
        "浣嗘槸",
        "涓嶈繃",
        "椋庨櫓",
        "闂",
        "澶辫触",
        "闄愬埗",
        "鍋囪",
        "浠ｄ环",
        "鍐茬獊",
        "鍙嶄緥",
        "璐ㄧ枒",
        "tradeoff",
        "risk",
        "limit",
        "failure",
        "assumption",
    ]
    out: list[tuple[int, str]] = []
    for ln in content.splitlines():
        s = ln.strip()
        if not s or s.startswith("---"):
            continue
        low = s.lower()
        score = 0
        if any(c in low for c in cues):
            score += 2
        if any(t in low for t in tokens):
            score += 1
        if score > 0:
            out.append((score, s[:280]))
    out.sort(key=lambda x: x[0], reverse=True)
    return out


def command_challenge(vault: Path, belief: str, top_k: int) -> str:
    tokens = tokenize_query(belief)
    if not tokens:
        return "No challengeable belief keywords detected."

    graph = _build_note_graph(vault)
    if not graph["notes"]:
        return "No markdown notes found in vault."

    scored = _score_note_ids(graph, tokens)
    candidate_ids = [nid for _, nid in scored[: max(top_k * 3, 12)]]
    if not candidate_ids:
        candidate_ids = list(graph["notes"].keys())[:20]

    evidences: list[tuple[int, str, str]] = []
    for nid in candidate_ids:
        note = graph["notes"][nid]
        for s, line in _challenge_lines(note["content"], tokens)[:2]:
            evidences.append((s, note["ref"], line))
    evidences.sort(key=lambda x: x[0], reverse=True)

    lines: list[str] = []
    lines.append(f"Challenge Belief: {belief}")
    lines.append("Method: historical-note search + counter-evidence extraction")
    lines.append("")
    lines.append("Counter-evidence from past notes:")
    if not evidences:
        lines.append("- No direct counter-evidence extracted. Broaden keywords or add more retrospectives.")
    else:
        for _, ref, line in evidences[:top_k]:
            lines.append(f"- {ref}: {line}")
    lines.append("")
    lines.append("Possibly ignored assumptions:")
    lines.append("- Does this belief depend on ideal preconditions (time/resources/collaboration)?")
    lines.append("- Are there counterexamples you've recorded but not integrated into decisions?")
    lines.append("- If this belief is wrong, where is the largest downside?")
    lines.append("")
    lines.append("Suggested falsification experiments:")
    lines.append("- Design one 7-day test that validates outcomes, not feelings.")
    lines.append("- Define a clear failure criterion that triggers belief revision.")
    return "\n".join(lines)


def _gather_research_hits(vault: Path, topic: str, top_k: int, engine: str) -> tuple[list[dict], list[str]]:
    tokens = tokenize_query(topic)
    notices: list[str] = []
    hits: list[dict] = []
    if engine in ("fs", "hybrid"):
        hits.extend(command_ask_fs(vault, topic, top_k, tokens))
    if engine in ("obsidian", "hybrid"):
        ohits, notice = command_ask_obsidian(topic, top_k, tokens)
        if notice:
            notices.append(notice)
        hits.extend(ohits)
    hits.sort(key=lambda x: int(x.get("score", 0)), reverse=True)
    return hits[: max(1, top_k)], notices


def _curl_fetch_text(url: str, timeout: int, *, accept_markdown: bool = False) -> tuple[str | None, str | None]:
    cmd = ["curl", "-L", "-sS", url]
    if accept_markdown:
        cmd.extend(["-H", "Accept: text/markdown"])
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except Exception as e:
        return None, str(e)
    if r.returncode != 0:
        return None, (r.stderr or r.stdout or "").strip() or f"curl exit={r.returncode}"
    text = (r.stdout or "").strip()
    if not text:
        return None, "empty response"
    return text, None


def _normalize_search_result_url(raw_url: str) -> str:
    url = (raw_url or "").strip()
    if url.startswith("//"):
        url = f"https:{url}"
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if "duckduckgo.com" in host and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [None])[0]
        if target:
            url = unquote(target)
    return url


def _is_search_engine_nav_url(url: str) -> bool:
    try:
        p = urlparse(url)
    except Exception:
        return True
    host = p.netloc.lower()
    if not host:
        return True
    if "duckduckgo.com" in host:
        return True
    if "google." in host and p.path.startswith("/search"):
        return True
    if "bing.com" in host and p.path.startswith("/search"):
        return True
    return False


def _extract_web_search_hits(text: str, top_k: int) -> list[dict]:
    hits: list[dict] = []
    seen: set[str] = set()

    # Prefer Markdown-style links from r.jina.ai wrapped search pages.
    link_pat = re.compile(r"\[([^\]]{1,220})\]\(([^)\s]+)\)")
    for m in link_pat.finditer(text):
        title = re.sub(r"\s+", " ", m.group(1)).strip()
        title = title.replace("**", "").replace("__", "").strip()
        low_title = title.lower()
        if not title:
            continue
        if low_title.startswith("image "):
            continue
        if "duckduckgo" in low_title:
            continue
        # Skip bare domain/path lines, keep article-like titles.
        if "/" in title and " " not in title and "." in title:
            continue
        url = _normalize_search_result_url(m.group(2))
        if not is_http_url(url) or _is_search_engine_nav_url(url):
            continue
        if url in seen:
            continue
        seen.add(url)
        snippet = ""
        tail = text[m.end() : min(len(text), m.end() + 460)]
        for ln in tail.splitlines():
            s = ln.strip()
            if not s:
                continue
            if s.startswith("---"):
                continue
            if s.startswith("[![Image"):
                continue
            mm = re.search(r"\[([^\]]{12,320})\]\(([^)\s]+)\)", s)
            if not mm:
                continue
            candidate = re.sub(r"\s+", " ", mm.group(1)).strip()
            candidate = candidate.replace("**", "").replace("__", "").strip()
            lc = candidate.lower()
            if not candidate or "duckduckgo" in lc:
                continue
            if "/" in candidate and " " not in candidate and "." in candidate:
                continue
            if candidate.lower() == title.lower():
                continue
            snippet = candidate
            break
        if not snippet:
            snippet = title
        if len(snippet) > 240:
            snippet = snippet[:240].rstrip() + "..."
        hits.append({"title": title or url, "url": url, "snippet": snippet, "source": "web"})
        if len(hits) >= max(1, top_k):
            return hits

    # Fallback for plain-url output.
    if len(hits) < max(1, top_k):
        for ln in text.splitlines():
            m = re.search(r"https?://[^\s)\]>\"']+", ln)
            if not m:
                continue
            url = _normalize_search_result_url(m.group(0))
            if not is_http_url(url) or _is_search_engine_nav_url(url) or url in seen:
                continue
            seen.add(url)
            snippet = re.sub(r"\s+", " ", ln).strip()
            if len(snippet) > 240:
                snippet = snippet[:240].rstrip() + "..."
            hits.append({"title": urlparse(url).netloc, "url": url, "snippet": snippet or url, "source": "web"})
            if len(hits) >= max(1, top_k):
                return hits
    return hits


def _gather_research_web_hits(topic: str, top_k: int, timeout: int) -> tuple[list[dict], list[str]]:
    q = quote_plus(topic.strip())
    candidates = [
        f"https://r.jina.ai/http://duckduckgo.com/html/?q={q}",
        f"https://r.jina.ai/http://duckduckgo.com/?q={q}",
    ]
    notices: list[str] = []
    merged: list[dict] = []
    seen: set[str] = set()

    for idx, target in enumerate(candidates, start=1):
        text, err = _curl_fetch_text(target, timeout=max(15, timeout), accept_markdown=True)
        if err:
            notices.append(f"WebSearch source #{idx} failed: {err}")
            continue
        parsed_hits = _extract_web_search_hits(text or "", top_k=max(8, top_k * 2))
        for hit in parsed_hits:
            url = hit.get("url", "")
            if not url or url in seen:
                continue
            seen.add(url)
            merged.append(hit)
            if len(merged) >= max(1, top_k):
                break
        if len(merged) >= max(1, top_k):
            break

    for i, hit in enumerate(merged, start=1):
        hit["score"] = max(top_k - i + 1, 1)
    return merged[: max(1, top_k)], notices


def _compose_research_note_content(
    *,
    topic: str,
    route: str,
    note_type: str,
    status: str,
    source_url: str,
    tldr: str,
    findings: list[str],
    evidence: list[str],
    open_questions: list[str],
    next_actions: list[str],
) -> str:
    day = today_str()
    tags = ["research", route]
    lines: list[str] = []
    lines.append("---")
    lines.append(f"type: {note_type}")
    lines.append(f"status: {status}")
    lines.append(f"created: {day}")
    lines.append(f"updated: {now_iso()}")
    lines.append(f"owner: {current_owner()}")
    lines.append("authoring: agent")
    lines.append(f"tags: [{', '.join(tags)}]")
    lines.append(f"research_topic: \"{topic}\"")
    lines.append(f"research_route: \"{route}\"")
    if source_url:
        lines.append(f"source_url: \"{source_url}\"")
    lines.append("---")
    lines.append("")
    lines.append(f"# Research - {topic} ({day})")
    lines.append("")
    lines.append("## Research Topic")
    lines.append(topic)
    lines.append("")
    lines.append("## TL;DR")
    lines.append(tldr or "No summary available.")
    lines.append("")
    lines.append("## Key Findings")
    if findings:
        lines.extend(f"- {x}" for x in findings)
    else:
        lines.append("- No clear findings extracted yet.")
    lines.append("")
    lines.append("## Evidence and Sources")
    if evidence:
        lines.extend(f"- {x}" for x in evidence)
    else:
        lines.append("- No evidence sources yet.")
    lines.append("")
    lines.append("## Open Questions")
    if open_questions:
        lines.extend(f"- {x}" for x in open_questions)
    else:
        lines.append("- No unresolved questions currently.")
    lines.append("")
    lines.append("## Next Actions")
    if next_actions:
        lines.extend(f"- [ ] {x}" for x in next_actions)
    else:
        lines.append("- [ ] Define the next validation task based on this note.")
    lines.append("")
    return "\n".join(lines)


def _write_note_via_obsidian_cli(vault: Path, rel_path: str, content: str) -> tuple[bool, str]:
    vault_name = vault.name
    args = [
        "create",
        f"vault={vault_name}",
        f"path={rel_path}",
        f"content={content}",
        "silent",
        "overwrite",
    ]
    r, err = run_obsidian_cli(args, timeout=60)
    if err:
        return False, err
    if not r or r.returncode != 0:
        msg = ((r.stderr if r else "") or (r.stdout if r else "")).strip()
        return False, msg or "unknown error"
    return True, "ok"


def _next_available_rel_path(vault: Path, rel_dir: str, base_name: str) -> str:
    rel = f"{rel_dir}/{base_name}.md"
    p = vault / rel
    if not p.exists():
        return rel
    idx = 2
    while True:
        rel2 = f"{rel_dir}/{base_name} ({idx}).md"
        if not (vault / rel2).exists():
            return rel2
        idx += 1


def command_research(
    vault: Path,
    topic: str,
    route: str,
    top_k: int,
    engine: str,
    fetch_timeout: int,
    agent_reach_cfg: dict,
    no_agent_reach: bool,
    agent_reach_cmd: str | None,
    agent_reach_args: list[str] | None,
    force_fs_write: bool,
) -> tuple[Path, str]:
    route_key = (route or "inbox").strip().lower()
    if route_key not in RESEARCH_ROUTE_MAP:
        raise ValueError(f"unsupported route: {route}")
    rel_dir, note_type, status = RESEARCH_ROUTE_MAP[route_key]

    source_url = topic if is_http_url(topic) else ""
    tldr = ""
    findings: list[str] = []
    evidence: list[str] = []
    open_questions: list[str] = []
    next_actions: list[str] = []
    notices: list[str] = []

    if source_url:
        md: str | None = None
        if not no_agent_reach:
            md, ar_err = fetch_via_agent_reach_command(
                source_url,
                agent_reach_cfg,
                cmd_override=agent_reach_cmd,
                args_override=agent_reach_args,
                timeout_override=fetch_timeout,
            )
            if ar_err:
                notices.append(f"Agent-Reach fetch failed; using fallback. error={ar_err}")
        if not md:
            try:
                md = fetch_via_agent_reach_stack(source_url, timeout=fetch_timeout)
            except Exception as e:
                notices.append(f"Fallback fetch failed: {e}")
                md = None

        if md:
            s = summarize_markdown(md, fallback_title=slugify_topic(topic))
            tldr = s.get("tldr", "")
            findings = list(s.get("key_points", []))[: max(3, top_k)]
            quotes = [ln.strip("> ").strip() for ln in (s.get("quotes", "") or "").splitlines() if ln.strip()]
            evidence = quotes[: max(3, top_k)]
            open_questions = list(s.get("open_questions", []))[: max(2, min(4, top_k))]
            if not open_questions:
                open_questions = [
                    "What boundary conditions apply to this conclusion?",
                    "Are there counterexamples or lower-cost alternatives?",
                ]
            next_actions = [
                "Pick one key point and run a small validation test.",
                "Add at least one high-trust source for cross-checking.",
            ]
        else:
            tldr = "No usable source content was retrieved; research result is incomplete."
            findings = ["Fetch failed. Check network and Agent-Reach config, then retry."]
            evidence = notices[:] if notices else ["No evidence was captured."]
            open_questions = [
                "Is the Agent-Reach command configured correctly?",
                "Is the target site reachable from the current network?",
            ]
            next_actions = ["Fix fetch path and rerun the research command."]
    else:
        hits, notices = _gather_research_web_hits(topic, top_k=top_k, timeout=fetch_timeout)
        if hits:
            top = hits[0]
            tldr = top.get("snippet", "") or f"Web search returned relevant external sources for '{topic}'."
            findings = []
            for h in hits[:top_k]:
                title = h.get("title", "").strip()
                snippet = h.get("snippet", "").strip()
                if title and snippet and snippet.lower() != title.lower():
                    findings.append(f"{title}: {snippet}")
                elif title:
                    findings.append(title)
                elif snippet:
                    findings.append(snippet)
            evidence = [f"[{h.get('title', 'source')}]({h.get('url', '')})" for h in hits if h.get("url")]
            open_questions = [
                "Do these sources conflict on any key claims?",
                "Which points need second-pass validation in your own context?",
            ]
            next_actions = [
                "Cross-check 2-3 high-trust sources.",
                "Distill actionable conclusions into thinking or project notes.",
            ]
        else:
            tldr = f"No usable web-search results found for '{topic}'."
            findings = ["Search did not return parseable results, or the network is unavailable."]
            evidence = notices[:] if notices else ["No source evidence available."]
            open_questions = [
                "Should we rewrite the query with more specific terms?",
                "Are the current network and target search endpoints available?",
            ]
            next_actions = [
                "Retry with narrower keywords.",
                "If you have a URL, run research directly against that URL.",
            ]

    if notices:
        evidence.extend(notices)

    day = today_str()
    base = f"{day} - research - {slugify_topic(topic)}"
    rel_path = _next_available_rel_path(vault, rel_dir, base)
    full_path = vault / rel_path

    content = _compose_research_note_content(
        topic=topic,
        route=route_key,
        note_type=note_type,
        status=status,
        source_url=source_url,
        tldr=tldr,
        findings=findings,
        evidence=evidence,
        open_questions=open_questions,
        next_actions=next_actions,
    )

    write_mode = "filesystem"
    if not force_fs_write:
        ok, msg = _write_note_via_obsidian_cli(vault, rel_path, content)
        if ok:
            write_mode = "obsidian-cli"
        else:
            atomic_write(full_path, content)
            write_mode = f"filesystem-fallback ({msg})"
    else:
        atomic_write(full_path, content)
        write_mode = "filesystem"

    return full_path, write_mode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SecondBrain CLI (filesystem-first)")
    parser.add_argument("--config", default="config/default.json", help="Path to config JSON")
    parser.add_argument("--vault", default=None, help="Vault path override")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("today")
    sub.add_parser("plan-today")
    sub.add_parser("start-session")
    p_daily_open = sub.add_parser("daily-open")
    p_daily_open.add_argument("date", nargs="?", default="today", help="today|yesterday|前天|YYYY-MM-DD|N天前")
    p_daily_open.add_argument("--create-if-missing", action="store_true", help="Create daily note if missing.")
    p_daily_open.add_argument("--no-archive-search", action="store_true", help="Do not search 99_Archive for target date.")

    p_session_log = sub.add_parser("session-log")
    p_session_log.add_argument("--title", required=True, help="Session title/topic")
    p_session_log.add_argument("--summary", required=True, help="Session summary text")
    p_session_log.add_argument("--date", default="today", help="today|yesterday|YYYY-MM-DD")

    p_close = sub.add_parser("close")
    p_close.add_argument("--no-auto-archive", action="store_true")
    p_wrap = sub.add_parser("daily-wrapup")
    p_wrap.add_argument("--date", default="today", help="today|yesterday|前天|YYYY-MM-DD|N天前")
    p_wrap.add_argument(
        "--push",
        action="store_true",
        help="Commit and push the git repository at --vault (not toolkit root).",
    )
    p_wrap.add_argument("--archive", action="store_true", help="Also archive old daily/session notes after wrapup.")
    p_wrap.add_argument(
        "--archive-older-than",
        type=int,
        default=None,
        help="Override archive threshold days when --archive is set.",
    )

    p_capture = sub.add_parser("capture-url", aliases=["capture"])
    p_capture.add_argument("url")
    p_capture.add_argument(
        "--fetch",
        action="store_true",
        help="Fetch URL content and summarize it in Chinese when an API key is available; otherwise use heuristic fallback.",
    )
    p_capture.add_argument("--fetch-timeout", type=int, default=45, help="Fetch timeout in seconds (default: 45)")
    p_capture.add_argument("--resource-type", choices=["prompt", "article", "video", "image"], default="article")
    p_capture.add_argument("--no-agent-reach", action="store_true", help="Skip Agent-Reach and use fallback fetch path.")
    p_capture.add_argument("--agent-reach-cmd", default=None, help="Override Agent-Reach command path/name.")
    p_capture.add_argument(
        "--agent-reach-arg",
        action="append",
        default=None,
        help="Override Agent-Reach arg template (repeatable, supports {url}).",
    )

    p_promote = sub.add_parser("promote-resource", aliases=["promote"])
    p_promote.add_argument("ref", help="inbox note path/name or source URL")
    p_promote.add_argument("--status", default="active")
    p_promote.add_argument("--authoring", choices=["human", "agent", "mixed"], default="mixed")

    p_archive = sub.add_parser("archive-daily")
    p_archive.add_argument("--older-than", type=int, default=None)

    p_proj = sub.add_parser("project-new")
    p_proj.add_argument("name")

    p_proj_start = sub.add_parser("project-start")
    p_proj_start.add_argument("name")
    p_proj_query = sub.add_parser("project-query")
    p_proj_query.add_argument("name", help="Project keyword/name to search under 03_Projects")
    p_proj_query.add_argument("--top-k", type=int, default=10)

    p_grad = sub.add_parser("graduate")
    p_grad.add_argument("--days", type=int, default=None)
    p_grad.add_argument("--force", action="store_true")

    p_close_proj = sub.add_parser("project-close")
    p_close_proj.add_argument("name")

    p_thinking = sub.add_parser("thinking-capture")
    p_thinking.add_argument("title")
    p_thinking.add_argument("--content", default="")
    p_thinking.add_argument("--tags", default="", help="Comma-separated tags")

    p_life_memo = sub.add_parser("life-memo")
    p_life_memo.add_argument("title")
    p_life_memo.add_argument("--content", default="")
    p_life_memo.add_argument("--tags", default="", help="Comma-separated tags")

    p_life_status = sub.add_parser("life-status")
    p_life_status.add_argument("--top-k", type=int, default=20)

    p_life_set = sub.add_parser("life-plan-set")
    p_life_set.add_argument("title")
    p_life_set.add_argument("--content", default="")
    p_life_set.add_argument("--area", default="", help="Diet|Exercise|Reading|General")
    p_life_set.add_argument("--status", default="active", choices=["active", "backlog", "closed"])
    p_life_set.add_argument("--tags", default="", help="Comma-separated tags")

    p_article_draft = sub.add_parser("article-draft")
    p_article_draft.add_argument("title")
    p_article_draft.add_argument("--content", default="")
    p_article_draft.add_argument("--tags", default="", help="Comma-separated tags")

    p_article_move = sub.add_parser("article-move")
    p_article_move.add_argument("ref", help="Article note path/name")
    p_article_move.add_argument("--to", required=True, choices=["scheduled", "published"])
    p_article_move.add_argument("--date", default=None, help="today|yesterday|YYYY-MM-DD")
    p_article_move.add_argument("--url", default="", help="Publish URL (for published state)")

    p_idea_capture = sub.add_parser("idea-capture")
    p_idea_capture.add_argument("title")
    p_idea_capture.add_argument("--content", default="")
    p_idea_capture.add_argument("--tags", default="", help="Comma-separated tags")

    p_idea_list = sub.add_parser("idea-list")
    p_idea_list.add_argument("--top-k", type=int, default=30)

    p_ask = sub.add_parser("ask")
    p_ask.add_argument("question")
    p_ask.add_argument("--top-k", type=int, default=6)
    p_ask.add_argument("--engine", choices=["fs", "obsidian", "hybrid"], default="hybrid")
    p_brainstorm = sub.add_parser("brainstorm")
    p_brainstorm.add_argument("topic")
    p_brainstorm.add_argument("--top-k", type=int, default=12)

    p_trace = sub.add_parser("trace")
    p_trace.add_argument("topic")
    p_trace.add_argument("--top-k", type=int, default=8)

    p_connect = sub.add_parser("connect")
    p_connect.add_argument("domain_a")
    p_connect.add_argument("domain_b")
    p_connect.add_argument("--top-k", type=int, default=6)

    p_emerge = sub.add_parser("emerge")
    p_emerge.add_argument("--days", type=int, default=30)
    p_emerge.add_argument("--top-k", type=int, default=6)

    p_challenge = sub.add_parser("challenge")
    p_challenge.add_argument("belief")
    p_challenge.add_argument("--top-k", type=int, default=6)

    p_research = sub.add_parser("research")
    p_research.add_argument("topic", help="Research topic or URL")
    p_research.add_argument("--route", choices=["inbox", "library", "thinking"], default="inbox")
    p_research.add_argument("--top-k", type=int, default=6)
    p_research.add_argument(
        "--engine",
        choices=["fs", "obsidian", "hybrid"],
        default="hybrid",
        help="Compatibility arg; for non-URL research the command uses web search.",
    )
    p_research.add_argument("--fetch-timeout", type=int, default=45)
    p_research.add_argument("--no-agent-reach", action="store_true", help="Skip Agent-Reach for URL research.")
    p_research.add_argument("--agent-reach-cmd", default=None, help="Override Agent-Reach command for URL research.")
    p_research.add_argument(
        "--agent-reach-arg",
        action="append",
        default=None,
        help="Override Agent-Reach arg template for URL research (repeatable, supports {url}).",
    )
    p_research.add_argument("--force-fs-write", action="store_true", help="Always use filesystem write (skip Obsidian CLI).")
    p_research.add_argument(
        "--url-mode",
        choices=["auto", "research"],
        default="auto",
        help="For URL topics: auto delegates inbox route to capture --fetch; research forces research pipeline.",
    )

    p_diet = sub.add_parser("diet-log")
    p_diet.add_argument("--date", default=None, help="Log date in YYYY-MM-DD (default: today)")
    p_diet.add_argument(
        "--day-type",
        default="training",
        help="training|rest|训练日|休息日",
    )
    p_diet.add_argument(
        "--meal",
        required=True,
        help="meal1|meal2|meal3|meal4|breakfast|lunch|preworkout|dinner|早餐|午餐|练前|晚餐",
    )
    p_diet.add_argument("--foods", required=True, help="Food description text")
    p_diet.add_argument("--carbs", type=float, required=True, help="Carbs in grams")
    p_diet.add_argument("--protein", type=float, required=True, help="Protein in grams")
    p_diet.add_argument("--fat", type=float, required=True, help="Fat in grams")
    p_diet.add_argument("--kcal", type=float, default=None, help="Optional kcal override; auto-calculated if omitted")

    p_diet_capture = sub.add_parser("diet-capture")
    p_diet_capture.add_argument("--date", default=None, help="Log date in YYYY-MM-DD (default: today)")
    p_diet_capture.add_argument(
        "--day-type",
        default="training",
        help="training|rest|训练日|休息日",
    )
    p_diet_capture.add_argument(
        "--meal",
        required=True,
        help="meal1|meal2|meal3|meal4|breakfast|lunch|preworkout|dinner|早餐|午餐|练前|晚餐",
    )
    p_diet_capture.add_argument("--foods", required=True, help="Food description text")
    p_diet_capture.add_argument("--carbs", type=float, required=True, help="Carbs in grams")
    p_diet_capture.add_argument("--protein", type=float, required=True, help="Protein in grams")
    p_diet_capture.add_argument("--fat", type=float, required=True, help="Fat in grams")
    p_diet_capture.add_argument("--kcal", type=float, default=None, help="Optional kcal override; auto-calculated if omitted")

    sub.add_parser("doctor")
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = build_parser()
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = repo_root / config_path
    config = load_config(config_path, repo_root)
    set_app_timezone(config.get("timezone", "local"))
    set_app_owner(config.get("owner", "user"))
    agent_reach_cfg = load_agent_reach_config(repo_root)
    vault = resolve_vault(args, config, repo_root)
    templates_path = config.get("templates_path", "00_System/Templates")
    dashboards_mode = str(config.get("dashboards_mode", "dataview"))

    if args.command == "today":
        p = command_today(vault, templates_path, dashboards_mode)
        print(str(p))
        return 0
    if args.command == "plan-today":
        print("deprecated: plan-today is a compatibility command; prefer `today`.", file=sys.stderr)
        p = command_plan_today(vault, templates_path, dashboards_mode)
        print(str(p))
        return 0
    if args.command == "start-session":
        p = command_start_session(vault, templates_path, dashboards_mode)
        print(str(p))
        return 0
    if args.command == "daily-open":
        p = command_daily_open(
            vault,
            templates_path,
            args.date,
            dashboards_mode,
            create_if_missing=args.create_if_missing,
            search_archive=not args.no_archive_search,
        )
        print(str(p))
        return 0
    if args.command == "session-log":
        p = command_session_log(
            vault,
            templates_path,
            title=args.title,
            summary=args.summary,
            date_input=args.date,
            dashboards_mode=dashboards_mode,
        )
        print(str(p))
        return 0
    if args.command in ("capture-url", "capture"):
        p = command_capture_url(
            vault,
            templates_path,
            args.url,
            fetch=args.fetch,
            fetch_timeout=args.fetch_timeout,
            agent_reach_cfg=agent_reach_cfg,
            no_agent_reach=args.no_agent_reach,
            agent_reach_cmd=args.agent_reach_cmd,
            agent_reach_args=args.agent_reach_arg,
            resource_type=args.resource_type,
        )
        print(str(p))
        return 0
    if args.command in ("promote-resource", "promote"):
        src, dst = command_promote_resource(
            vault,
            templates_path,
            args.ref,
            status=args.status,
            authoring=args.authoring,
        )
        print(f"source={src}")
        print(f"library={dst}")
        return 0
    if args.command == "close":
        print("deprecated: close is a compatibility command; prefer `daily-wrapup --date today --archive --push`.", file=sys.stderr)
        p = command_close(vault, templates_path, dashboards_mode)
        day = today_str()
        if not args.no_auto_archive and bool(config.get("auto_archive_on_close", True)):
            older = int(config.get("archive_threshold_days", 30))
            d, s = command_archive_daily(vault, older)
            print(f"auto-archive daily={d}, sessions={s}, older-than={older}")
        sync_msg = sync_vault_git(vault, f"chore(vault): close session {day}")
        print(str(p))
        print(sync_msg)
        return 0
    if args.command == "daily-wrapup":
        p, sync_msg = command_daily_wrapup(
            vault=vault,
            templates_path=templates_path,
            dashboards_mode=dashboards_mode,
            date_input=args.date,
            push=args.push,
        )
        print(str(p))
        if args.archive:
            older = args.archive_older_than if args.archive_older_than is not None else int(config.get("archive_threshold_days", 30))
            d, s = command_archive_daily(vault, older)
            print(f"archive daily={d}, sessions={s}, older-than={older}")
        if sync_msg:
            print(sync_msg)
        return 0
    if args.command == "graduate":
        days = args.days if args.days is not None else int(config.get("graduate_window_days", 7))
        c, s = command_graduate(vault, templates_path, days=days, force=args.force)
        print(f"graduate created={c}, skipped={s}")
        return 0
    if args.command == "archive-daily":
        older = args.older_than if args.older_than is not None else int(config.get("archive_threshold_days", 30))
        d, s = command_archive_daily(vault, older)
        print(f"archived daily={d}, sessions={s}")
        return 0
    if args.command == "project-new":
        p = command_project_new(vault, templates_path, args.name)
        generate_projects_base(vault)
        print(str(p))
        return 0
    if args.command == "project-start":
        p = command_project_start(vault, args.name)
        print(str(p))
        return 0
    if args.command == "project-query":
        out = command_project_query(vault, args.name, args.top_k)
        print(out)
        return 0
    if args.command == "project-close":
        report, archived = command_project_close(vault, templates_path, args.name)
        generate_projects_base(vault)
        print(f"report={report}")
        print(f"archived={archived}")
        return 0
    if args.command == "thinking-capture":
        p = command_thinking_capture(vault, templates_path, args.title, args.content, args.tags)
        print(str(p))
        return 0
    if args.command == "life-memo":
        p = command_life_memo(vault, args.title, args.content, args.tags)
        print(str(p))
        return 0
    if args.command == "life-status":
        out = command_life_status(vault, args.top_k)
        print(out)
        return 0
    if args.command == "life-plan-set":
        p = command_life_plan_set(
            vault,
            args.title,
            args.content,
            args.area,
            args.status,
            args.tags,
        )
        print(str(p))
        return 0
    if args.command == "article-draft":
        p = command_article_draft(vault, templates_path, args.title, args.content, args.tags)
        print(str(p))
        return 0
    if args.command == "article-move":
        src, dst = command_article_move(vault, args.ref, args.to, when=args.date, publish_url=args.url)
        print(f"source={src}")
        print(f"target={dst}")
        return 0
    if args.command == "idea-capture":
        p = command_idea_capture(vault, args.title, args.content, args.tags)
        print(str(p))
        return 0
    if args.command == "idea-list":
        print(command_idea_list(vault, args.top_k))
        return 0
    if args.command == "ask":
        out = command_ask(vault, args.question, args.top_k, args.engine)
        print(out)
        return 0
    if args.command == "brainstorm":
        out = command_brainstorm(vault, args.topic, args.top_k)
        print(out)
        return 0
    if args.command == "trace":
        out = command_trace(vault, args.topic, args.top_k)
        print(out)
        return 0
    if args.command == "connect":
        out = command_connect(vault, args.domain_a, args.domain_b, args.top_k)
        print(out)
        return 0
    if args.command == "emerge":
        out = command_emerge(vault, args.days, args.top_k)
        print(out)
        return 0
    if args.command == "challenge":
        out = command_challenge(vault, args.belief, args.top_k)
        print(out)
        return 0
    if args.command == "research":
        if is_http_url(args.topic) and args.url_mode == "auto" and args.route == "inbox":
            inferred_type = infer_resource_type_from_url(args.topic)
            p = command_capture_url(
                vault=vault,
                templates_path=templates_path,
                url=args.topic,
                fetch=True,
                fetch_timeout=args.fetch_timeout,
                agent_reach_cfg=agent_reach_cfg,
                no_agent_reach=args.no_agent_reach,
                agent_reach_cmd=args.agent_reach_cmd,
                agent_reach_args=args.agent_reach_arg,
                resource_type=inferred_type,
            )
            print(str(p))
            print("write_mode=delegated-capture")
            return 0
        p, mode = command_research(
            vault=vault,
            topic=args.topic,
            route=args.route,
            top_k=args.top_k,
            engine=args.engine,
            fetch_timeout=args.fetch_timeout,
            agent_reach_cfg=agent_reach_cfg,
            no_agent_reach=args.no_agent_reach,
            agent_reach_cmd=args.agent_reach_cmd,
            agent_reach_args=args.agent_reach_arg,
            force_fs_write=args.force_fs_write,
        )
        print(str(p))
        print(f"write_mode={mode}")
        return 0
    if args.command == "diet-log":
        print("deprecated: diet-log is a compatibility command; prefer `diet-capture`.", file=sys.stderr)
        p = command_diet_log(
            vault=vault,
            templates_path=templates_path,
            day=args.date,
            day_type=args.day_type,
            meal=args.meal,
            foods=args.foods,
            carbs=args.carbs,
            protein=args.protein,
            fat=args.fat,
            kcal=args.kcal,
            source_url="https://www.notion.so/2eee2419152180a3b245d146538c1cff?source=copy_link",
        )
        print(str(p))
        return 0
    if args.command == "diet-capture":
        p, verdict = command_diet_capture(
            vault=vault,
            templates_path=templates_path,
            day=args.date,
            day_type=args.day_type,
            meal=args.meal,
            foods=args.foods,
            carbs=args.carbs,
            protein=args.protein,
            fat=args.fat,
            kcal=args.kcal,
        )
        print(str(p))
        print(verdict)
        return 0
    if args.command == "doctor":
        print(command_doctor(vault))
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())





