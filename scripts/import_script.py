#!/usr/bin/env python3
"""把现成剧本/小说初拆为 project.json 骨架。

用法:
    python import_script.py <剧本.txt|.md|.docx|.fountain> [--project 项目目录]
                            [--out 父目录] [--title 剧名]
                            [--episode E01] [--alias 别名=正名]
                            [--format auto|table|screenplay|novel|fountain]
                            [--split-dialogue] [--force] [--dry-run]

定位:
    * 只做结构初拆：集 / 场 / 镜 / 对白 / 动作，不续写、不改剧情。
    * 角色与场景会生成可编辑占位，appearance / image_prompt / anchor_en
      仍需 Agent 或人工补全。
    * 已有项目会按集合并；目标集已有镜头时默认跳过，--force 才覆盖。
    * 原剧本不修改；默认复制到 01_script/source.<ext> 供追溯。

支持格式:
    * Markdown 表格（表头含 镜号/景别/运镜/画面动作/对白/时长）
    * Word .docx（正文段落 + 表格，按文档顺序提取）
    * 中文剧本（第一集 / 场景1：... / 内景 ... / 林晚：... / △ 动作）
    * 场号格式：`1-1 夜 内 客厅` 与 `1-1 客厅 内 夜` 都支持
    * Fountain（INT./EXT. + 大写角色名）
    * 小说/散文（无场景标题时按段落切镜，自动建占位场景）
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import _common as C

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(errors="replace")
        except (OSError, ValueError):
            pass

SUPPORTED_SUFFIXES = {".txt", ".text", ".md", ".markdown", ".fountain", ".docx"}
UNSUPPORTED_SUFFIXES = {
    ".doc": "旧版 Word 文档（.doc）",
    ".pdf": "PDF",
    ".srt": "字幕文件",
}
MAX_DIALOGUE_CHARS = 20
DEFAULT_MAX_SHOT_SEC = 5.0

DIALOGUE_VERB_HINTS = (
    "翻开", "掏出", "摸", "站起", "坐下", "抬头", "皱眉", "沉默", "停顿",
    "翻口袋", "看向", "回头", "走进", "冲出", "拿起", "放下", "愣住", "叹气",
)

NON_CHARACTER_LABELS = {
    "场景", "地点", "时间", "人物", "道具", "音效", "特效", "炫技",
    "旁白", "画外音", "字幕", "备注", "镜头", "景别", "运镜", "构图",
    "动作", "画面", "标题", "钩子", "卡点", "系统", "os", "vo",
    "他", "她", "它", "我", "你", "他们", "她们", "我们", "你们",
}

TIME_WORDS = {
    "清晨": "清晨", "早晨": "清晨", "黎明": "清晨", "早上": "清晨",
    "上午": "日", "中午": "日", "下午": "日", "白天": "日", "日": "日",
    "黄昏": "黄昏", "傍晚": "黄昏", "日落": "黄昏",
    "夜": "夜", "晚上": "夜", "深夜": "夜", "雨夜": "夜",
    "day": "日", "morning": "清晨", "dawn": "清晨", "noon": "日",
    "afternoon": "日", "dusk": "黄昏", "evening": "黄昏",
    "night": "夜", "midnight": "夜",
}

LIGHTING = {
    "清晨": ("清晨冷调自然光，薄雾，低对比", "cool early-morning daylight, light haze, low contrast"),
    "日": ("日景自然光，柔和阴影", "natural daylight, soft shadows"),
    "黄昏": ("黄昏暖色侧逆光，长阴影", "warm golden-hour side backlight, long shadows"),
    "夜": ("夜景低照度，冷色边缘光", "low-key night lighting, cool rim light"),
}

EPISODE_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:"
    r"第\s*(?P<cn>[0-9零一二三四五六七八九十百]+)\s*[集话章]"
    r"|(?:E(?:P)?|Episode)\s*[._-]?\s*0*(?P<num>\d+)"
    r")\s*[：:、.\-—]?\s*(?P<title>.*?)\s*$",
    re.I,
)

# 真正的分集标题：行内剩余部分只能是短标题，不能带逗号/冒号/句号等长句标点。
# 用于避免把“大纲里写第30集……”这类正文误判成新的一集。
EPISODE_HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:"
    r"第\s*(?P<cn>[0-9零一二三四五六七八九十百]+)\s*[集话章]"
    r"|(?:E(?:P)?|Episode)\s*[._-]?\s*0*(?P<num>\d+)"
    r")\s*[：:、.\-—]?\s*(?P<title>[^，。！？；：:,.;!?]{0,24})\s*$",
    re.I,
)
SHOT_ID_RE = re.compile(r"^E(?:P)?\d+\s*-\s*S\d+\b", re.I)
SHOT_NO_RE = re.compile(r"^\s*(?:镜号|镜头|Shot)\s*[：:]?\s*(\d+)\s*$", re.I)
SHOT_S_RE = re.compile(r"^\s*S(\d+)\s*$", re.I)

SCENE_SHOT_RE = re.compile(
    r"^\s*\d+[-.]\d+\s+(?P<time>日|夜|清晨|早晨|黄昏|傍晚)\s+"
    r"(?P<io>内|外)\s+(?P<loc>.+?)\s*$")

SCENE_SHOT_CN_RE = re.compile(
    r"^\s*\d+[-.]\d+\s+(?P<loc>.+?)\s+(?P<io>内|外)\s+"
    r"(?P<time>日|夜|清晨|早晨|黄昏|傍晚)\s*$")

SCENE_LOC_RE = re.compile(
    r"^\s*(?P<time>日|夜|清晨|早晨|黄昏|傍晚)\s+(?P<io>内|外)\s+(?P<loc>.+?)\s*$")

CAST_RE = re.compile(r"^\s*(?:出场人物|人物|角色)\s*[：:]\s*(?P<cast>.+?)\s*$")

SCENE_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:\d+\s*[.、)]\s*)?(?:"
    r"(?:场景|Scene)\s*(?P<num>[0-9零一二三四五六七八九十百]*)\s*[：:、.\-—]?\s*(?P<rest>.*)"
    r"|(?:第\s*[0-9零一二三四五六七八九十百]+\s*[场幕])\s*[：:、.\-—]?\s*(?P<scene_rest>.*)"
    r"|(?:内景|外景|INT\.?|EXT\.?)\s*[：:、.\-—]?\s*(?P<inner>.*)"
    r"|【\s*(?:场景|地点)\s*[：:]?\s*(?P<bracket>.*?)】"
    r")\s*$",
    re.I,
)

LABEL_RE = re.compile(
    r"^\s*[【\[]?\s*(?P<label>音效|特效|炫技|道具|旁白|画外音|OS|VO)"
    r"\s*[】\]]?\s*[：:]?\s*(?P<text>.+?)\s*$",
    re.I,
)

DIALOGUE_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:[-*•]\s*)?(?:\d+\s*[.、)]\s*)?"
    r"(?P<name>[\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9_· .]{0,15}?)"
    r"\s*(?:[（(](?P<emotion>[^）)]{0,30})[）)])?"
    r"\s*[：:]\s*(?P<text>.+?)\s*$",
)
BRACKET_DIALOGUE_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?[【\[]\s*(?P<name>[^】\]]{1,20})\s*[】\]]"
    r"\s*[：:]?\s*(?P<text>.+?)\s*$",
)

COLUMN_ALIASES = {
    "shot_no": ("镜号", "镜头号", "镜头", "shotno", "shot", "no", "#"),
    "shot_size": ("景别", "shotsize", "size"),
    "camera": ("运镜", "镜头运动", "camera", "movement"),
    "composition": ("构图", "composition"),
    "action": ("画面动作", "画面", "动作", "内容", "action", "description"),
    "dialogue": ("对白", "台词", "dialogue", "line"),
    "narration": ("旁白", "内心os", "内心", "narration", "vo"),
    "duration": ("时长", "秒数", "duration", "time"),
    "scene": ("场景", "地点", "scene", "location"),
    "props": ("道具", "props"),
    "sfx": ("音效", "sfx"),
    "vfx": ("特效", "vfx"),
    "showcase": ("炫技", "showcase"),
}

CUE_RE = re.compile(r"^[A-Z][A-Z0-9 ._'-]{1,24}$")
TRANSITIONS = {"CUT TO", "CUT TO:", "FADE IN", "FADE IN:", "FADE OUT",
               "FADE OUT.", "FADE OUT:", "THE END"}


# ---------------------------------------------------------------- text input

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_paragraph_text(p: ET.Element) -> str:
    parts: list[str] = []
    for node in p.iter():
        if node.tag == f"{W_NS}t":
            parts.append(node.text or "")
        elif node.tag == f"{W_NS}tab":
            parts.append(" ")
        elif node.tag == f"{W_NS}br":
            # Word 里的 Shift+Enter 软换行按换行处理，保留剧本行结构
            parts.append("\n")
    return re.sub(r"[ \t]+", " ", "".join(parts)).strip()


def docx_table_rows(tbl: ET.Element) -> list[str]:
    rows: list[str] = []
    for tr in tbl.findall(f"{W_NS}tr"):
        cells: list[str] = []
        for tc in tr.findall(f"{W_NS}tc"):
            texts = [docx_paragraph_text(p) for p in tc.findall(f"{W_NS}p")]
            cell = " ".join(t for t in texts if t).replace("\n", " ")
            cells.append(cell.replace("|", "\\|"))
        if any(cells):
            rows.append("| " + " | ".join(cells) + " |")
    return rows


DOCX_BLOCK_CONTAINERS = {
    f"{W_NS}sdt", f"{W_NS}sdtContent", f"{W_NS}customXml", f"{W_NS}smartTag",
}


def iter_docx_blocks(parent: ET.Element):
    """按文档顺序产出正文段落/表格，穿透内容控件等容器。"""
    for child in list(parent):
        if child.tag in {f"{W_NS}p", f"{W_NS}tbl"}:
            yield child
        elif child.tag in DOCX_BLOCK_CONTAINERS:
            yield from iter_docx_blocks(child)


def docx_to_text(path: Path) -> str:
    """把 .docx 的正文段落与表格按文档顺序转成纯文本（仅标准库）。"""
    try:
        with zipfile.ZipFile(path) as zf:
            xml = zf.read("word/document.xml")
        root = ET.fromstring(xml)
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        C.die(f"无法读取 Word 文档（{path.name}）：{exc}。"
              "请确认是 .docx，或另存为 .txt 后重试")
    body = root.find(f"{W_NS}body")
    if body is None:
        C.die(f"Word 文档缺少正文结构: {path.name}")
    lines: list[str] = []
    for child in iter_docx_blocks(body):
        if child.tag == f"{W_NS}p":
            lines.append(docx_paragraph_text(child))
        elif child.tag == f"{W_NS}tbl":
            lines.extend(docx_table_rows(child))
            lines.append("")
    return "\n".join(lines)


def read_script(path: Path) -> tuple[str, str]:
    suffix = path.suffix.lower()
    if suffix in UNSUPPORTED_SUFFIXES:
        C.die(f"暂不支持 {UNSUPPORTED_SUFFIXES[suffix]}（{path.suffix}）。"
              "请先转成 .docx / .txt / .md / .fountain")
    if suffix not in SUPPORTED_SUFFIXES:
        C.die(f"不支持的剧本格式: {path.suffix}。支持 .txt / .md / .docx / .fountain")
    if not path.is_file():
        C.die(f"剧本不存在: {path}")

    if suffix == ".docx":
        text = docx_to_text(path)
        encoding = "docx"
    else:
        data = path.read_bytes()
        if b"\x00" in data:
            C.die("剧本看起来是二进制文件，请先转成纯文本")
        for encoding in ("utf-8-sig", "gb18030"):
            try:
                text = data.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            C.die("无法识别剧本编码（已尝试 UTF-8 / GB18030）")

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        C.die("剧本为空")
    return text, encoding


def strip_markup(text: str) -> str:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    return text


# ---------------------------------------------------------------- format

def detect_format(lines: list[str]) -> str:
    head = lines[:300]
    if any(is_table_header(ln) for ln in head):
        return "table"
    if any(CUE_RE.match(ln.strip()) and not SCENE_RE.match(ln.strip())
           and ln.strip() not in TRANSITIONS for ln in head):
        if any(re.match(r"^\s*(?:INT|EXT)\.", ln, re.I) for ln in head):
            return "fountain"
    if any(SCENE_RE.match(ln.strip()) or SCENE_SHOT_RE.match(ln.strip())
           or SCENE_SHOT_CN_RE.match(ln.strip())
           or SCENE_LOC_RE.match(ln.strip()) for ln in lines):
        return "screenplay"
    if sum(1 for ln in lines if parse_dialogue_line(ln.strip())) >= 3:
        return "screenplay"
    return "novel"


def normalize_fountain(lines: list[str]) -> list[str]:
    """把 Fountain 的「角色名独立一行 + 对白」压成「角色：对白」。"""
    out: list[str] = []
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if (CUE_RE.match(s) and s not in TRANSITIONS
                and not SCENE_RE.match(s) and not EPISODE_RE.match(s)):
            name = s
            i += 1
            buf: list[str] = []
            while i < len(lines) and lines[i].strip():
                if SCENE_RE.match(lines[i].strip()) or EPISODE_RE.match(lines[i].strip()):
                    break
                buf.append(lines[i].strip())
                i += 1
            if buf:
                out.append(f"{name}：{' '.join(buf)}")
                continue
        out.append(lines[i])
        i += 1
    return out


# ---------------------------------------------------------------- small helpers

def cn_to_int(text: str) -> int:
    if text.isdigit():
        return int(text)
    digits = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if "百" in text:
        left, _, right = text.partition("百")
        hundreds = digits.get(left, 1) if left else 1
        return hundreds * 100 + (cn_to_int(right) if right else 0)
    if "十" in text:
        left, _, right = text.partition("十")
        tens = digits.get(left, 1) if left else 1
        ones = digits.get(right, 0) if right else 0
        return tens * 10 + ones
    return digits.get(text, 0)


def clean_text(text: str) -> str:
    text = text.strip()
    text = text.strip('"“”「」『』')
    return re.sub(r"\s+", " ", text).strip()


def clean_action(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^[△▲·•\-—]+\s*", "", text)
    return clean_text(text)


def split_dialogue(text: str, limit: int = MAX_DIALOGUE_CHARS) -> list[str]:
    """按标点或字数切分长对白；只切句，不改字。"""
    chunks: list[str] = []
    buf = ""
    for ch in text:
        buf += ch
        if len(buf) >= limit or ch in "。！？!?；;":
            if buf.strip():
                chunks.append(buf.strip())
            buf = ""
    if buf.strip():
        chunks.append(buf.strip())
    return chunks or [text]


def estimate_duration(text: str, max_shot: float, dialogue: bool = False) -> float:
    rate = max(1.0, C.cjk_chars_per_sec())
    base = (len(text) / rate + 0.4) if dialogue else (1.0 + len(text) / 12.0)
    return round(max(1.0, min(max_shot, base)) * 2) / 2


def parse_number(value: str, default: float = 0.0) -> float:
    m = re.search(r"\d+(?:\.\d+)?", value or "")
    return float(m.group(0)) if m else default


# ---------------------------------------------------------------- dialogue

def parse_dialogue_line(line: str) -> dict | None:
    """返回 {speaker, text, emotion} 或 {narration: text}；不是对白返回 None。"""
    if not line or "://" in line:
        return None

    m = BRACKET_DIALOGUE_RE.match(line)
    if not m:
        m = DIALOGUE_RE.match(line)
    if not m:
        return None

    name = (m.group("name") or "").strip()
    text = clean_text(m.group("text") or "")
    if not text:
        return None
    if "：" in name or ":" in name:
        return None
    # “他翻口袋：…”“那一行字：…”是动作/说明，不是人物名
    if re.match(r"^[他她它我你这那]", name) and len(name) > 1:
        return None
    # “第一条：…”“第一行：…”是列表/字幕说明，不是人物名
    if re.match(r"^第[一二三四五六七八九十百0-9]", name):
        return None
    # “程叙翻开：…”这类“角色+动作”不是台词名
    if any(hint in name for hint in DIALOGUE_VERB_HINTS):
        return None
    # 方括号里是画面说明，不是人物名
    if line.lstrip().startswith(("【", "[")) and re.match(
            r"^(?:画面|闪回|回忆|镜头|特效)", name):
        return None
    if name in NON_CHARACTER_LABELS or name.lower() in NON_CHARACTER_LABELS:
        return {"narration": text}

    # “苏建业os/vo” → 人物仍是苏建业，标记为画外音
    delivery = ""
    m_suffix = re.match(r"^(.*?)(os|vo)$", name, re.I)
    if m_suffix and m_suffix.group(1).strip():
        name = m_suffix.group(1).strip()
        delivery = m_suffix.group(2).upper()

    # “林晚说：” / “赵衡说道：” → 去掉叙述动词（两字人名如“王道”保留）
    if len(name) >= 3:
        name = re.sub(r"(说道|说|道)$", "", name).strip()
    if len(name) < 1 or len(name) > 12:
        return None
    if name in NON_CHARACTER_LABELS or name.lower() in NON_CHARACTER_LABELS:
        return {"narration": text}
    if re.search(r"[，。！？!?；;、]", name):
        return None

    emotion = clean_text(m.groupdict().get("emotion") or "")
    return {"speaker": name, "text": text, "emotion": emotion, "delivery": delivery}


# ---------------------------------------------------------------- table

def split_table_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    cells = re.split(r"(?<!\\)\|", s)
    return [c.strip().replace("\\|", "|").replace("<br>", " ").replace("<br/>", " ")
            for c in cells]


def is_table_separator(line: str) -> bool:
    s = line.strip().strip("|")
    return bool(s) and "-" in s and bool(re.fullmatch(r"[\s:|-]+", s))


def norm_header(cell: str) -> str:
    return re.sub(r"[\s*_`]", "", cell or "").lower()


def match_column(cell: str) -> str | None:
    key = norm_header(cell)
    if not key:
        return None
    pairs = sorted(((alias, name) for name, aliases in COLUMN_ALIASES.items()
                    for alias in aliases), key=lambda x: -len(x[0]))
    for alias, name in pairs:
        if alias in key:
            return name
    return None


def is_table_header(line: str) -> bool:
    if "|" not in line:
        return False
    cells = split_table_row(line)
    return sum(1 for cell in cells if match_column(cell)) >= 2


def parse_table(lines: list[str], start: int):
    if "|" not in lines[start]:
        return None
    header = split_table_row(lines[start])
    mapping = {name: idx for idx, cell in enumerate(header)
               if (name := match_column(cell)) is not None}
    if len(mapping) < 2 or not ({"action", "dialogue", "narration"} & mapping.keys()):
        return None
    i = start + 1
    if i < len(lines) and is_table_separator(lines[i]):
        i += 1
    rows: list[tuple[list[str], int]] = []
    while i < len(lines):
        s = lines[i].strip()
        if not s or "|" not in s:
            break
        cells = split_table_row(s)
        if any(cells):
            rows.append((cells, i + 1))
        i += 1
    return mapping, rows, i


def table_value(cells: list[str], mapping: dict, key: str) -> str:
    idx = mapping.get(key)
    if idx is None or idx >= len(cells):
        return ""
    return cells[idx].strip()


def split_props(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"[、，,；;]", text or "") if p.strip()]


# ---------------------------------------------------------------- parser state

def new_state(max_shot: float, split_dialogue: bool = False) -> dict:
    return {
        "episode": {"num": None, "title": "", "shots": []},
        "episodes": [],
        "scenes": [],
        "scene_keys": {},
        "scene": None,
        "pending_action": [],
        "pending_emotion": "",
        "pending_meta": {},
        "last_speaker": "",
        "speakers": {},
        "next_shot_no": 1,
        "warnings": [],
        "no_scene_heading": True,
        "max_shot": max_shot,
        "split_dialogue": split_dialogue,
    }


def scene_key(name: str, time: str) -> str:
    return f"{name.strip()}|{time.strip()}"


def set_scene(state: dict, raw: str, heading: str) -> None:
    raw = (raw or "").strip()
    name = ""
    time = ""

    # “客厅-夜” / “COFFEE SHOP - DAY”：只把末尾的 hyphens 当作时间分隔符，
    # 保留 “青雾岭山脚-老松树下” 这类地点内部的连字符。
    m = re.match(r"^(.*?)\s*[-－—]\s*(%s)\s*$" % "|".join(TIME_WORDS.keys()), raw, re.I)
    if m:
        name = m.group(1).strip()
        time = TIME_WORDS.get(m.group(2).lower(), TIME_WORDS.get(m.group(2), ""))
        parts: list[str] = []
    else:
        parts = [p for p in re.split(r"\s+", raw) if p]

    for part in parts:
        if part in {"内", "外", "INT", "EXT"}:
            continue
        mapped = TIME_WORDS.get(part.lower(), TIME_WORDS.get(part, ""))
        if mapped:
            time = mapped
            continue
        m = re.match(r"^(.*?)\s+(%s)$" % "|".join(TIME_WORDS.keys()), part)
        if m:
            name = name or m.group(1).strip()
            time = TIME_WORDS.get(m.group(2).lower(), TIME_WORDS.get(m.group(2), ""))
        else:
            name = name or part

    if not name:
        name = "未命名场景"
    key = scene_key(name, time)
    sc = state["scene_keys"].get(key)
    if sc is None:
        sc = {
            "name": name,
            "time": time,
            "desc": re.sub(r"^#{1,6}\s*", "", heading).strip() or name,
            "anchor_en": name.lower() if re.fullmatch(r"[A-Za-z0-9 '&.,-]+", name) else "",
            "lighting": LIGHTING.get(time, ("", ""))[0],
            "lighting_en": LIGHTING.get(time, ("", ""))[1],
        }
        state["scene_keys"][key] = sc
        state["scenes"].append(sc)
    state["scene"] = sc
    state["no_scene_heading"] = False


def ensure_scene(state: dict) -> dict:
    if state["scene"] is None:
        set_scene(state, "未命名场景", "待补充（导入脚本未检测到场景标题）")
        # set_scene 会把 no_scene_heading 置 False；这里恢复，确保最终仍提示补场景
        state["no_scene_heading"] = True
    return state["scene"]


def add_shot(state: dict, *, action: str = "", dialogue: dict | None = None,
             narration: str = "", duration: float | None = None,
             shot_no: int | None = None, **extra) -> None:
    sc = ensure_scene(state)
    no = shot_no if shot_no and shot_no > 0 else state["next_shot_no"]
    text = ((dialogue or {}).get("text") or narration or action)
    if duration is None:
        max_shot = state.get("max_shot", DEFAULT_MAX_SHOT_SEC)
        est = estimate_duration(text, max_shot, dialogue=bool(dialogue))
        if action:
            # 同时有画面动作和台词时，取“动作”和“台词”里更长的那个估算，
            # 避免长动作被短台词压成 1-3 秒。
            est = max(est, estimate_duration(action, max_shot, dialogue=False))
        duration = est
    shot = {
        "shot_no": no,
        "_scene_key": scene_key(sc["name"], sc["time"]),
        "action": action.strip() or "待补充画面动作",
        "shot_size": extra.get("shot_size") or "中景",
        "camera": extra.get("camera") or guess_camera(action),
        "composition": extra.get("composition") or "中心",
        "duration_sec": duration,
        "transition_in": "硬切",
    }
    if dialogue:
        shot["dialogue"] = {k: v for k, v in dialogue.items() if v}
        if dialogue.get("speaker"):
            shot["_speaker"] = dialogue["speaker"]
    if narration:
        shot["narration"] = narration
    for key in ("sfx", "vfx", "showcase"):
        if extra.get(key):
            shot[key] = extra[key]
    if extra.get("props"):
        shot["props"] = extra["props"]

    state["episode"]["shots"].append(shot)
    state["next_shot_no"] = no + 1
    state["last_speaker"] = shot.get("_speaker") or state["last_speaker"]


def guess_camera(action: str) -> str:
    for word, cam in (("环绕", "环绕"), ("跟拍", "跟拍"), ("跟", "跟拍"),
                      ("推", "推镜"), ("拉", "拉镜"), ("摇", "摇镜"),
                      ("移", "移镜"), ("升", "升镜"), ("降", "降镜"),
                      ("手持", "手持")):
        if word in action:
            return cam
    return "固定"


def flush_action(state: dict) -> None:
    text = " ".join(state["pending_action"]).strip()
    state["pending_action"].clear()
    if not text:
        return
    if len(text) > 120:
        parts = [p.strip() for p in re.split(r"(?<=[。！？!?；;])", text) if p.strip()]
    else:
        parts = [text]
    for part in parts:
        add_shot(state, action=part, **state["pending_meta"])
        state["pending_meta"] = {}


def add_dialogue(state: dict, data: dict) -> None:
    if "narration" in data:
        action = " ".join(state["pending_action"]).strip()
        state["pending_action"].clear()
        add_shot(state, action=action, narration=data["narration"],
                 **state["pending_meta"])
        state["pending_meta"] = {}
        return

    speaker = data["speaker"]
    text = data["text"]
    emotion = data.get("emotion") or state["pending_emotion"]
    state["pending_emotion"] = ""
    if state.get("split_dialogue"):
        chunks = split_dialogue(text)
        if len(text) > MAX_DIALOGUE_CHARS:
            state["warnings"].append(
                f"超长对白已拆成 {len(chunks)} 句（≤{MAX_DIALOGUE_CHARS} 字）: {text[:30]}…")
    else:
        # 默认保留原台词，不改字、不拆句；导演分镜的硬规则优先
        chunks = [text]
        if len(text) > MAX_DIALOGUE_CHARS:
            # 聚合统计，不逐条罗列（上百条警告会污染 meta._import）
            agg = state.setdefault("long_dialogue", {"count": 0, "max": 0})
            agg["count"] += 1
            agg["max"] = max(agg["max"], len(text))

    action = " ".join(state["pending_action"]).strip()
    state["pending_action"].clear()
    for i, chunk in enumerate(chunks):
        add_shot(state, action=action if i == 0 else "", dialogue={
            "speaker": speaker, "text": chunk,
            "emotion": emotion if i == 0 else "",
            "delivery": data.get("delivery", "") if i == 0 else "",
        }, **state["pending_meta"])
        state["pending_meta"] = {}
    state["speakers"][speaker] = state["speakers"].get(speaker, 0) + 1


def add_meta_line(state: dict, label: str, text: str) -> None:
    label = label.lower()
    if label in {"旁白", "画外音", "os", "vo"}:
        add_dialogue(state, {"narration": text})
        return
    last = state["episode"]["shots"][-1] if state["episode"]["shots"] else None
    if last and state["scene"]:
        current_key = scene_key(state["scene"]["name"], state["scene"]["time"])
        if last.get("_scene_key") != current_key:
            last = None
    if label == "道具":
        props = split_props(text)
        if last is None:
            state["pending_meta"]["props"] = props
        else:
            last["props"] = list(dict.fromkeys((last.get("props") or []) + props))
        return
    key = {"音效": "sfx", "特效": "vfx", "炫技": "showcase"}.get(label, "")
    if not key:
        return
    if last is None:
        state["pending_meta"][key] = text
    else:
        last[key] = text


# ---------------------------------------------------------------- parse

def parse_script(text: str, fmt: str, max_shot: float = DEFAULT_MAX_SHOT_SEC,
                 split_dialogue: bool = False) -> dict:
    lines = [ln.strip() for ln in strip_markup(text).split("\n")]
    if fmt == "fountain":
        lines = normalize_fountain(lines)

    # 跳过片头：故事梗概 / 人物小传 / 简介等位于首个分集标题之前的内容。
    # 仅当确实存在分集标题时启用，避免把普通小说开头误删。
    preamble = 0
    for idx, line in enumerate(lines):
        if EPISODE_HEADING_RE.match(line) and not SHOT_ID_RE.match(line):
            if idx > 0:
                preamble = idx
                lines = lines[idx:]
            break

    state = new_state(max_shot, split_dialogue)
    if preamble:
        state["warnings"].append(
            f"已跳过首个分集标题前的 {preamble} 行（故事梗概/人物小传等），"
            "人物设定请从 01_script/source.* 提炼")
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line or line in {"---", "***", "==="} or line.startswith("```"):
            flush_action(state)
            i += 1
            continue

        m = EPISODE_HEADING_RE.match(line)
        if m and not SHOT_ID_RE.match(line):
            flush_action(state)
            num = cn_to_int(m.group("cn")) if m.group("cn") else int(m.group("num"))
            title = clean_text(m.group("title") or "")
            cur = state["episode"]
            if not cur["shots"] and not cur["title"]:
                cur["num"], cur["title"] = num, title
            else:
                state["episodes"].append(cur)
                state["episode"] = {"num": num, "title": title, "shots": []}
                state["next_shot_no"] = 1
                state["last_speaker"] = ""
                state["pending_emotion"] = ""
                state["pending_meta"] = {}
            i += 1
            continue

        m = SCENE_LOC_RE.match(line)
        if m:
            flush_action(state)
            set_scene(state, f"{m.group('loc')} {m.group('time')}", line)
            i += 1
            continue

        m = SCENE_SHOT_RE.match(line)
        if m:
            flush_action(state)
            set_scene(state, f"{m.group('loc')} {m.group('time')}", line)
            i += 1
            continue

        m = SCENE_SHOT_CN_RE.match(line)
        if m:
            flush_action(state)
            set_scene(state, f"{m.group('loc')} {m.group('time')}", line)
            i += 1
            continue

        m = CAST_RE.match(line)
        if m:
            # “出场人物：A、B” 是场景元信息，不是对白
            i += 1
            continue

        m = SCENE_RE.match(line)
        if m:
            flush_action(state)
            raw = (m.group("inner") or m.group("bracket") or m.group("rest")
                   or m.group("scene_rest") or "")
            raw = re.sub(r"^\s*(?:内景|外景|INT\.?|EXT\.?)\s*[：:、.\-—]?\s*",
                         "", raw, flags=re.I)
            set_scene(state, raw, line)
            i += 1
            continue

        table = parse_table(lines, i)
        if table:
            flush_action(state)
            mapping, rows, new_i = table
            for cells, line_no in rows:
                parse_table_row(state, mapping, cells, line_no)
            i = new_i
            continue

        m = LABEL_RE.match(line)
        if m:
            add_meta_line(state, m.group("label"), clean_text(m.group("text")))
            i += 1
            continue

        m = SHOT_NO_RE.match(line) or SHOT_S_RE.match(line)
        if m:
            flush_action(state)
            state["next_shot_no"] = int(m.group(1))
            i += 1
            continue

        data = parse_dialogue_line(line)
        if data:
            add_dialogue(state, data)
            i += 1
            continue

        # 剧本里每个 ▲/△ 通常是独立画面节拍；遇到新标记就切镜，
        # 避免多个动作段被并成一个超长镜头。
        if state["pending_action"] and re.match(r"^\s*[▲△]", line):
            flush_action(state)
        state["pending_action"].append(clean_action(line))
        if fmt == "novel":
            # 小说/散文没有分镜标记时，一行按一个段落/节拍处理
            flush_action(state)
        i += 1

    flush_action(state)
    if state["episode"]["shots"]:
        state["episodes"].append(state["episode"])
    state["episodes"] = [ep for ep in state["episodes"] if ep["shots"]]
    if not state["episodes"]:
        C.die("未解析出任何镜头：请确认剧本不是空文件，或改用 --format table/screenplay")

    if state["no_scene_heading"]:
        state["warnings"].append("未检测到场景标题，已创建「未命名场景」占位；请按实际场景拆分")
    if not state["speakers"]:
        state["warnings"].append("未检测到角色对白，characters 需手工补全")
    agg = state.get("long_dialogue")
    if agg and agg.get("count"):
        state["warnings"].append(
            f"长对白 {agg['count']} 处保留原文（最长 {agg['max']} 字），"
            "单镜时长可能不足；请调大 --max-shot-sec 或人工拆镜（不要改台词）")

    return {
        "format": fmt,
        "episodes": state["episodes"],
        "scenes": state["scenes"],
        "speakers": state["speakers"],
        "warnings": state["warnings"],
    }


def parse_table_row(state: dict, mapping: dict, cells: list[str], line_no: int) -> None:
    scene_val = table_value(cells, mapping, "scene")
    if scene_val:
        set_scene(state, scene_val, scene_val)

    action = table_value(cells, mapping, "action")
    dialogue_text = table_value(cells, mapping, "dialogue")
    narration = re.sub(r"^(旁白|画外音|OS|VO)\s*[：:]\s*", "",
                       table_value(cells, mapping, "narration"), flags=re.I)
    duration_text = table_value(cells, mapping, "duration")
    shot_no_text = table_value(cells, mapping, "shot_no")
    shot_no = int(parse_number(shot_no_text)) if parse_number(shot_no_text) else None
    duration = parse_number(duration_text) if duration_text else None

    speaker = ""
    emotion = ""
    delivery = ""
    if dialogue_text:
        parsed = parse_dialogue_line(dialogue_text)
        if parsed and "narration" in parsed:
            narration = narration or parsed["narration"]
            dialogue_text = ""
        elif parsed:
            speaker = parsed["speaker"]
            emotion = parsed.get("emotion") or ""
            delivery = parsed.get("delivery") or ""
            dialogue_text = parsed["text"]
        elif state["last_speaker"]:
            speaker = state["last_speaker"]

    if not action and not dialogue_text and not narration:
        return
    if duration is not None:
        duration = max(0.5, min(30.0, duration))

    add_shot(
        state,
        action=action,
        dialogue=({"speaker": speaker, "text": dialogue_text,
                   "emotion": emotion, "delivery": delivery}
                  if dialogue_text else None),
        narration=narration,
        duration=duration,
        shot_no=shot_no,
        shot_size=table_value(cells, mapping, "shot_size"),
        camera=table_value(cells, mapping, "camera"),
        composition=table_value(cells, mapping, "composition"),
        props=split_props(table_value(cells, mapping, "props")),
        sfx=table_value(cells, mapping, "sfx"),
        vfx=table_value(cells, mapping, "vfx"),
        showcase=table_value(cells, mapping, "showcase"),
    )
    if speaker:
        state["speakers"][speaker] = state["speakers"].get(speaker, 0) + 1
    if dialogue_text and len(dialogue_text) > MAX_DIALOGUE_CHARS:
        state["warnings"].append(
            f"第 {line_no} 行对白 {len(dialogue_text)} 字 > {MAX_DIALOGUE_CHARS}，建议拆句")


# ---------------------------------------------------------------- merge

def normalize_name(name: str) -> str:
    return re.sub(r"\s+", "", name or "").casefold()


def make_id(name: str, used: set[str], prefix: str) -> str:
    base = re.sub(r"[^A-Za-z0-9]", "", name or "").upper()[:10]
    if len(base) < 2:
        n = 1
        while f"{prefix}{n}" in used:
            n += 1
        candidate = f"{prefix}{n}"
    else:
        candidate = base
        n = 2
        while candidate in used:
            candidate = f"{base[:8]}{n}"
            n += 1
    used.add(candidate)
    return candidate


def brief_text(shot: dict, names: dict[str, str]) -> str:
    dlg = shot.get("dialogue") or {}
    if dlg.get("text"):
        who = names.get(dlg.get("character", ""), dlg.get("character", ""))
        text = f"{who}：{dlg['text']}" if who else dlg["text"]
    elif shot.get("narration"):
        text = f"旁白：{shot['narration']}"
    else:
        text = shot.get("action", "")
    return text.strip()[:80] or "待补充"


def episode_sort_key(ep: dict) -> tuple[int, str]:
    eid = ep.get("id", "")
    m = re.match(r"E(\d+)$", eid)
    return (int(m.group(1)) if m else 9999, eid)


def merge_into_project(project: dict, parsed: dict, args,
                       aliases: dict[str, str] | None = None) -> dict:
    chars = project.get("characters")
    scenes = project.get("scenes")
    episodes = project.get("episodes")
    if not isinstance(chars, list) or not isinstance(scenes, list) or not isinstance(episodes, list):
        C.die("project.json 的 characters/scenes/episodes 必须是数组")

    warnings: list[str] = list(parsed["warnings"])
    aliases = aliases or {}
    if aliases:
        merged_counts: dict[str, int] = {}
        for name, count in parsed["speakers"].items():
            canonical = aliases.get(name, name)
            merged_counts[canonical] = merged_counts.get(canonical, 0) + count
        parsed["speakers"] = merged_counts
        warnings.append("已合并角色别名: " + "、".join(
            f"{alias}→{canonical}" for alias, canonical in sorted(aliases.items())
            if alias in parsed["speakers"] or canonical in parsed["speakers"]))
    char_by_name = {normalize_name(c.get("name", "")): c for c in chars
                    if isinstance(c, dict) and c.get("name")}
    used_char_ids = {c.get("id") for c in chars if isinstance(c, dict) and c.get("id")}

    added_chars: list[dict] = []
    for name in parsed["speakers"]:
        if normalize_name(name) in char_by_name:
            continue
        cid = make_id(name, used_char_ids, "C")
        c = {
            "id": cid,
            "name": name,
            "role": "supporting",
            "appearance": "",
            "visual_anchors": [],
            "outfits": [],
            "image_prompt": "",
            "voice": {"timbre": "", "speed": 1.0, "emotion": ""},
        }
        chars.append(c)
        char_by_name[normalize_name(name)] = c
        added_chars.append(c)
    if added_chars:
        warnings.append("角色 role 均初设为 supporting，请确认主角/反派后再生成")
    for alias, canonical in aliases.items():
        c = char_by_name.get(normalize_name(canonical))
        if c:
            char_by_name.setdefault(normalize_name(alias), c)

    scene_by_name = {normalize_name(sc.get("name", "")): sc for sc in scenes
                     if isinstance(sc, dict) and sc.get("name")}
    used_scene_ids = {sc.get("id") for sc in scenes if isinstance(sc, dict) and sc.get("id")}
    scene_id_by_key: dict[str, str] = {}
    added_scenes: list[dict] = []
    for sc in parsed["scenes"]:
        key = scene_key(sc["name"], sc["time"])
        existing = scene_by_name.get(normalize_name(sc["name"]))
        if existing:
            scene_id_by_key[key] = existing["id"]
            continue
        nums = [int(x[1:]) for x in used_scene_ids
                if isinstance(x, str) and re.fullmatch(r"S\d+", x)]
        sid = f"S{max(nums, default=0) + 1}"
        while sid in used_scene_ids:
            sid = f"S{int(sid[1:]) + 1}"
        used_scene_ids.add(sid)
        row = {"id": sid, **sc}
        scenes.append(row)
        added_scenes.append(row)
        scene_by_name[normalize_name(sc["name"])] = row
        scene_id_by_key[key] = sid

    config = project.get("config") if isinstance(project.get("config"), dict) else {}
    target_duration = C.as_float(config.get("episode_duration_sec"), 90)
    if target_duration > 0:
        for ep in parsed["episodes"]:
            total = sum(C.as_float(s.get("duration_sec")) for s in ep["shots"])
            if abs(total - target_duration) / target_duration > 0.2:
                warnings.append(
                    f"第 {ep.get('num') or '?'} 集估算 {C.fmt_sec(total)}s，"
                    f"与目标 {C.fmt_sec(target_duration)}s 偏差较大")

    parsed_eps = parsed["episodes"]
    if len(parsed_eps) > 1 and args.episode:
        C.die("--episode 只能用于只解析出 1 集的剧本；多集剧本请按集号命名")
    imported: list[str] = []
    skipped: list[str] = []
    seen_eps: set[str] = set()

    for idx, ep in enumerate(parsed_eps):
        num = ep.get("num") or idx + 1
        eid = args.episode if (len(parsed_eps) == 1 and args.episode) else f"E{num:02d}"
        if not re.fullmatch(r"E\d+", eid):
            C.die(f"--episode 必须是 E01 这种格式: {eid}")
        if eid in seen_eps:
            warnings.append(f"重复集号 {eid}：后一个解析块已跳过")
            continue
        seen_eps.add(eid)

        existing = next((e for e in episodes if isinstance(e, dict) and e.get("id") == eid), None)
        old_shots = C.shots_of(existing) if existing else []
        if old_shots and not args.force:
            skipped.append(eid)
            warnings.append(f"{eid} 已有 {len(old_shots)} 个镜头，未覆盖（加 --force 覆盖）")
            continue

        # 先分配镜号 / 场景 id；角色 id 在下面统一映射
        final_shots: list[dict] = []
        last_scene = None
        used_nos: set[int] = set()
        for shot in ep["shots"]:
            no = int(shot.get("shot_no") or 1)
            if no in used_nos:
                no = max(used_nos) + 1
                warnings.append(f"{eid} 镜号 {shot.get('shot_no')} 重复，已顺延为 {no}")
            used_nos.add(no)
            sid = scene_id_by_key.get(shot["_scene_key"], "")
            cid_list: list[str] = []
            speaker = shot.pop("_speaker", "")
            speaker = aliases.get(speaker, speaker)
            if speaker:
                c = char_by_name.get(normalize_name(speaker))
                if c:
                    cid_list.append(c["id"])
            for name, c in char_by_name.items():
                if len(name) >= 2 and name in normalize_name(shot.get("action", "")):
                    if c["id"] not in cid_list:
                        cid_list.append(c["id"])

            out = {
                "id": f"{eid}-S{no:02d}",
                "shot_no": no,
                "scene_id": sid,
                "characters": cid_list,
                "shot_size": shot.get("shot_size") or "中景",
                "camera": shot.get("camera") or "固定",
                "composition": shot.get("composition") or "中心",
                "action": shot.get("action") or "待补充画面动作",
                "duration_sec": shot.get("duration_sec") or 1.0,
                "transition_in": shot.get("transition_in") or "硬切",
                "status": "pending",
                "assets": {"image": "", "video": "", "audio": ""},
            }
            if shot.get("dialogue"):
                dlg = dict(shot["dialogue"])
                if dlg.get("speaker"):
                    speaker_name = dlg.pop("speaker")
                    speaker_name = aliases.get(speaker_name, speaker_name)
                    c = char_by_name.get(normalize_name(speaker_name))
                    if c:
                        dlg["character"] = c["id"]
                out["dialogue"] = dlg
            for key in ("narration", "props", "sfx", "vfx", "showcase"):
                if shot.get(key):
                    out[key] = shot[key]
            if last_scene is not None and sid != last_scene:
                out["scene_marker"] = True
            last_scene = sid
            final_shots.append(out)

        title = ep.get("title") or (f"第{num}集" if num else eid)
        names = {c["id"]: c.get("name", "") for c in chars}
        hook = brief_text(final_shots[0], names) if final_shots else ""
        cliff = brief_text(final_shots[-1], names) if final_shots else ""
        payload = {
            "id": eid,
            "title": title,
            "hook": hook or "待补充钩子",
            "cliffhanger": cliff or "待补充卡点",
            "duration_sec": target_duration,
            "shots": final_shots,
        }
        if existing:
            existing.update(payload)
        else:
            episodes.append(payload)
        imported.append(eid)

    episodes.sort(key=episode_sort_key)
    project["characters"] = chars
    project["scenes"] = scenes
    project["episodes"] = episodes
    config = project.get("config")
    if isinstance(config, dict) and imported:
        needed = max(int(eid[1:]) for eid in imported if re.fullmatch(r"E\d+", eid))
        old_count = int(C.as_float(config.get("episode_count")))
        if old_count < needed:
            config["episode_count"] = needed
            warnings.append(f"集数配置从 {old_count} 调整为 {needed}（按导入集号）")
    meta = project.get("meta")
    if not isinstance(meta, dict):
        meta = {}
        project["meta"] = meta
    meta["_import"] = {
        "source": "",
        "format": parsed["format"],
        "imported_at": datetime.now().isoformat(timespec="seconds"),
        "warnings": warnings,
    }
    return {
        "warnings": warnings,
        "added_chars": added_chars,
        "added_scenes": added_scenes,
        "imported": imported,
        "skipped": skipped,
        "target_duration": target_duration,
    }


# ---------------------------------------------------------------- output

def write_source_copy(script: Path, root: Path) -> str:
    dest_dir = root / "01_script"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"source{script.suffix.lower()}"
    if dest.resolve() == script.resolve():
        return str(dest.relative_to(root)).replace("\\", "/")
    if dest.exists() and dest.read_bytes() != script.read_bytes():
        dest = dest_dir / f"source-{datetime.now().strftime('%Y%m%d-%H%M%S')}{script.suffix.lower()}"
    shutil.copy2(script, dest)
    return str(dest.relative_to(root)).replace("\\", "/")


def md_cell(text) -> str:
    return str(text or "").replace("|", "\\|").replace("\n", " ").strip()


def render_episode_md(ep: dict, names: dict[str, str], source: str) -> str:
    total = sum(C.as_float(s.get("duration_sec")) for s in ep.get("shots") or [])
    lines = [f"# {ep['id']}｜{ep.get('title') or '待定'}", "",
             f"> 导入自 `{source}`｜{len(ep.get('shots') or [])} 镜｜"
             f"估算 {C.fmt_sec(total)} 秒", "",
             "| 镜号 | 景别 | 运镜 | 构图 | 画面动作 | 对白/旁白 | 时长 |",
             "|---|---|---|---|---|---|---|"]
    for shot in ep.get("shots") or []:
        dlg = shot.get("dialogue") or {}
        speech = ""
        if dlg.get("text"):
            who = names.get(dlg.get("character", ""), "")
            speech = f"{who}：{dlg['text']}" if who else dlg["text"]
        elif shot.get("narration"):
            speech = f"旁白：{shot['narration']}"
        lines.append("| " + " | ".join([
            md_cell(shot.get("shot_no", "")),
            md_cell(shot.get("shot_size", "")),
            md_cell(shot.get("camera", "")),
            md_cell(shot.get("composition", "")),
            md_cell(shot.get("action", "")),
            md_cell(speech),
            md_cell(C.fmt_sec(shot.get("duration_sec"))),
        ]) + " |")
    return "\n".join(lines) + "\n"


def render_report(script: Path, project_path: Path, parsed: dict,
                  merged: dict, source_rel: str) -> str:
    chars = [c for c in merged["added_chars"]]
    scenes = [c for c in merged["added_scenes"]]
    total_shots = sum(len(e.get("shots") or []) for e in parsed["episodes"])
    lines = [
        "# 剧本导入报告", "",
        f"- 源文件：`{script}`",
        f"- 源备份：`{source_rel}`",
        f"- 目标项目：`{project_path}`",
        f"- 解析格式：`{parsed['format']}`（编码 `{parsed.get('encoding', '?')}`）",
        f"- 解析结果：{len(parsed['episodes'])} 集 / {len(parsed['scenes'])} 场 / "
        f"{total_shots} 镜 / {len(parsed['speakers'])} 个有台词角色",
        f"- 导入集数：{', '.join(merged['imported']) or '无'}",
    ]
    if merged["skipped"]:
        lines.append(f"- 跳过（已有镜头）：{', '.join(merged['skipped'])}")
    lines += ["", "## 需要补全", ""]
    if chars:
        lines.append("### 角色")
        for c in chars:
            lines.append(f"- `{c['id']}` {c['name']}（role={c.get('role', 'supporting')}）："
                         f"appearance、image_prompt、outfits、visual_anchors（当前为空）")
        lines.append("")
    if scenes:
        lines.append("### 场景")
        for s in scenes:
            lines.append(f"- `{s['id']}` {s['name']}：anchor_en"
                         + ("、lighting" if not s.get("lighting") else "")
                         + "（当前为空或缺省）")
        lines.append("")
    if not chars:
        lines.append("- 未检测到角色对白：请手工补 `characters`")
    if not scenes:
        lines.append("- 未检测到场景：请手工补 `scenes`")
    lines.append("")
    if parsed["warnings"] or merged["warnings"]:
        lines.append("## 警告")
        for w in dict.fromkeys(parsed["warnings"] + merged["warnings"]):
            lines.append(f"- {w}")
        lines.append("")
    lines += [
        "## 下一步", "",
        "1. 按 `references/prompt_recipes.md` 补全角色锚点、场景 `anchor_en` 与服装。",
        "2. 逐镜检查 hook / cliffhanger、景别、运镜、时长；必要时调 `project.json`。",
        "3. `python scripts/validate_project.py <项目>`",
        "4. `python scripts/build_prompts.py --type all --strict-en`",
        "", "> 本报告只记录结构初拆；剧情分析、人物动机与分集节奏见 `references/script_analysis.md`。",
    ]
    return "\n".join(lines) + "\n"


def write_episode_views(root: Path, project: dict, parsed: dict,
                        merged: dict, source_rel: str, force: bool) -> list[str]:
    names = {c["id"]: c.get("name", "") for c in project.get("characters", [])}
    written: list[str] = []
    for eid in merged["imported"]:
        ep = next((e for e in project["episodes"] if e.get("id") == eid), None)
        if not ep:
            continue
        target = root / "01_script" / f"{eid}.md"
        if target.exists() and not force:
            try:
                old = target.read_text(encoding="utf-8-sig")
            except OSError:
                old = ""
            template_like = ("| 1 |  |" in old or "（必须是动作" in old
                             or "{{" in old or not old.strip())
            if not template_like:
                target = root / "01_script" / f"{eid}.imported.md"
        C.write_text(target, render_episode_md(ep, names, source_rel))
        written.append(str(target.relative_to(root)).replace("\\", "/"))
    return written


# ---------------------------------------------------------------- init

def project_paths(args) -> tuple[Path | None, Path]:
    if args.project:
        p = Path(args.project).resolve()
        if p.is_file():
            return p, p.parent
        if (p / "project.json").is_file():
            return p / "project.json", p
        C.die(f"--project 下未找到 project.json: {p}（新建项目请用 --out，或先运行 init_drama.py）")
    out = Path(args.out).resolve()
    direct = out / "project.json"
    if direct.is_file():
        return direct, out
    return None, out


def init_project(args, script: Path, text: str, parent: Path) -> Path:
    title = (args.title or script.stem).strip() or "未命名短剧"
    existing = parent / C.safe_dirname(title) / "project.json"
    if existing.is_file():
        print(f"[使用已有项目] {existing}")
        return existing
    brief = (args.brief or text.strip())[:2000].replace("\n", " ")
    cmd = [sys.executable, str(SCRIPTS_DIR / "init_drama.py"),
           "--title", title, "--brief", brief, "--out", str(parent), "--force"]
    for flag, value in (("--genre", args.genre), ("--style", args.style),
                        ("--platform", args.platform), ("--episodes", args.episodes),
                        ("--duration", args.duration)):
        if value:
            cmd += [flag, str(value)]
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if r.stdout.strip():
        print(r.stdout.strip())
    if r.returncode != 0:
        if r.stderr.strip():
            print(r.stderr.strip(), file=sys.stderr)
        C.die("自动初始化项目失败")
    path = parent / C.safe_dirname(title) / "project.json"
    if not path.is_file():
        C.die(f"初始化后未找到 project.json: {path}")
    return path


# ---------------------------------------------------------------- main

def build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="把剧本/小说初拆为 project.json 骨架")
    ap.add_argument("script", help="剧本文件（.txt / .md / .docx / .fountain）")
    ap.add_argument("--project", help="已有 project.json 或项目目录")
    ap.add_argument("--out", default=".", help="自动初始化时的父目录（init 会在其下建 <剧名>/）")
    ap.add_argument("--title", help="自动初始化时的剧名（默认取文件名）")
    ap.add_argument("--brief", default="", help="自动初始化时的需求描述（默认取剧本开头）")
    ap.add_argument("--genre", help="题材 key（仅自动初始化时使用）")
    ap.add_argument("--style", help="视觉风格 key（仅自动初始化时使用）")
    ap.add_argument("--platform", help="平台 key（仅自动初始化时使用）")
    ap.add_argument("--episodes", type=int, help="总集数（仅自动初始化时使用）")
    ap.add_argument("--duration", type=int, help="单集时长（仅自动初始化时使用）")
    ap.add_argument("--episode", help="只解析出 1 集时，指定目标集号（如 E05）")
    ap.add_argument("--alias", action="append", default=[], metavar="别名=正名",
                    help="合并角色别名，可重复，如 --alias \"丫丫=苏沅禾\"")
    ap.add_argument("--format", choices=["auto", "table", "screenplay", "novel", "fountain"],
                    default="auto", help="强制解析格式（默认自动识别）")
    ap.add_argument("--max-shot-sec", type=float, default=DEFAULT_MAX_SHOT_SEC,
                    help=f"散文/剧本自动切镜的单镜上限（默认 {DEFAULT_MAX_SHOT_SEC:g}s）")
    ap.add_argument("--split-dialogue", action="store_true",
                    help="旧行为：把超长对白拆成多个≤20字镜头；默认保留原台词不拆")
    ap.add_argument("--force", action="store_true", help="覆盖目标集已有镜头与同名剧本 md")
    ap.add_argument("--no-copy", action="store_true", help="不复制源剧本到 01_script/")
    ap.add_argument("--dry-run", action="store_true", help="只解析并打印摘要，不写文件")
    return ap


def main() -> None:
    args = build_argparser().parse_args()
    if args.max_shot_sec < 0.5 or args.max_shot_sec > 30:
        C.die("--max-shot-sec 必须在 0.5-30 之间")
    script = Path(args.script).resolve()
    text, encoding = read_script(script)
    lines = [ln.strip() for ln in strip_markup(text).split("\n")]
    fmt = args.format if args.format != "auto" else detect_format(lines)
    if fmt == "table" and not any(is_table_header(ln) for ln in lines[:300]):
        C.die("指定了 --format table，但没有检测到含「镜号」的表格")
    parsed = parse_script(text, fmt, args.max_shot_sec, args.split_dialogue)
    parsed["encoding"] = encoding
    if args.episode and not re.fullmatch(r"E\d+", args.episode):
        C.die(f"--episode 必须是 E01 这种格式: {args.episode}")
    if args.episode and len(parsed["episodes"]) > 1:
        C.die("--episode 只能用于只解析出 1 集的剧本；多集剧本请按集号命名")

    total_shots = sum(len(e["shots"]) for e in parsed["episodes"])
    print(f"[解析] 格式={fmt} 编码={encoding} "
          f"集={len(parsed['episodes'])} 场={len(parsed['scenes'])} "
          f"镜={total_shots} 角色={len(parsed['speakers'])}")
    for w in parsed["warnings"]:
        print(f"  * {w}")

    project_path, root = project_paths(args)
    if project_path is None:
        if args.dry_run:
            print(f"[dry-run] 将自动初始化项目到 {root}（剧名: {args.title or script.stem}）")
            return
        title = (args.title or script.stem).strip() or "未命名短剧"
        print(f"[初始化] {title} → {Path(args.out).resolve()}")
        project_path = init_project(args, script, text, root)
        root = project_path.parent

    if args.dry_run:
        print(f"[dry-run] 目标项目: {project_path}；不写入任何文件")
        return

    try:
        project = C.load_project(project_path)
    except (OSError, json.JSONDecodeError) as exc:
        C.die(f"无法读取 project.json: {exc}")
    if not isinstance(project, dict):
        C.die("project.json 顶层必须是对象")
    aliases: dict[str, str] = {}
    for item in args.alias:
        if "=" not in item:
            C.die(f"--alias 格式应为 别名=正名: {item}")
        old, new = (x.strip() for x in item.split("=", 1))
        if not old or not new or old == new:
            C.die(f"--alias 格式应为 别名=正名: {item}")
        aliases[old] = new
    merged = merge_into_project(project, parsed, args, aliases)

    source_rel = ""
    if not args.no_copy:
        source_rel = write_source_copy(script, root)
        meta = project.get("meta")
        if isinstance(meta, dict) and isinstance(meta.get("_import"), dict):
            meta["_import"]["source"] = source_rel

    C.save_project(project, project_path)
    views = write_episode_views(root, project, parsed, merged, source_rel or script.name, args.force)
    report = render_report(script, project_path, parsed, merged, source_rel or "（未复制）")
    report_path = root / "01_script" / "import_report.md"
    C.write_text(report_path, report)

    C.ok(f"已导入 {', '.join(merged['imported']) or '无'} → {project_path}")
    if merged["skipped"]:
        print(f"  跳过已有镜头: {', '.join(merged['skipped'])}")
    print(f"  新增角色: {len(merged['added_chars'])} / 新增场景: {len(merged['added_scenes'])}")
    if views:
        print(f"  剧本视图: {', '.join(views)}")
    if source_rel:
        print(f"  源剧本备份: {source_rel}")
    print(f"  导入报告: {report_path.relative_to(root)}")
    if merged["added_chars"] or merged["added_scenes"]:
        print("  [提示] 角色/场景是初拆占位，请先补全 appearance/image_prompt/anchor_en 再 validate")


if __name__ == "__main__":
    main()
