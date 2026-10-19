"""AI 短剧 skill 共享工具库。

被 init_drama.py / validate_project.py / build_prompts.py / preview.py / assemble.py 引用。
仅依赖 Python 标准库。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPTS_DIR.parent
PRESETS_DIR = SKILL_DIR / "assets" / "presets"
TEMPLATES_DIR = SKILL_DIR / "assets" / "templates"

_PRESET_CACHE: dict = {}
_REVIEW_CACHE: dict = {}


# ---------------------------------------------------------------- json io

def load_json(path: Path | str) -> dict:
    path = Path(path)
    # utf-8-sig 兼容 Windows 编辑器保存的 BOM，同时正常读取无 BOM 的 UTF-8
    with path.open("r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def dump_json(data: dict, path: Path | str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def read_text(path: Path | str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write_text(path: Path | str, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------- presets

def load_presets() -> dict:
    """读取 assets/presets 下题材/风格/制作参数三份库，带进程内缓存。"""
    if _PRESET_CACHE:
        return _PRESET_CACHE
    production = load_json(PRESETS_DIR / "production.json")
    data = {
        "genres": load_json(PRESETS_DIR / "genres.json")["genres"],
        "styles": load_json(PRESETS_DIR / "styles.json")["styles"],
        "platforms": production["platforms"],
        "production": production,
        "default_genre": production.get("default_genre", "underdog"),
    }
    _PRESET_CACHE.update(data)
    return _PRESET_CACHE


def load_review_rules() -> dict:
    """读取 assets/presets/review_rules.json（平台卡审规则库），带进程内缓存。

    人读版见 references/review_rules.md；validate_project.py 与
    build_prompts.py 依据本文件强制执行。
    """
    if not _REVIEW_CACHE:
        _REVIEW_CACHE.update(load_json(PRESETS_DIR / "review_rules.json"))
    return _REVIEW_CACHE


def genre(key: str) -> dict:
    presets = load_presets()
    if key not in presets["genres"]:
        raise SystemExit(f"未知题材 '{key}'。可用题材: {', '.join(sorted(presets['genres']))}")
    return presets["genres"][key]


def style(key: str) -> dict:
    presets = load_presets()
    if key not in presets["styles"]:
        raise SystemExit(f"未知风格 '{key}'。可用风格: {', '.join(sorted(presets['styles']))}")
    return presets["styles"][key]


def platform(key: str) -> dict:
    presets = load_presets()
    if key not in presets["platforms"]:
        raise SystemExit(f"未知平台 '{key}'。可用平台: {', '.join(sorted(presets['platforms']))}")
    return presets["platforms"][key]


def negative_prompt(style_key: str, for_video: bool = False, lang: str = "en") -> str:
    prod = load_presets()["production"]
    base = prod.get("negative_prompt", {})
    st = style(style_key)
    parts = [
        base.get("base_en" if lang == "en" else "base_zh", ""),
        (st.get("negative_extra_en") if lang == "en" else st.get("negative_extra_zh")) or "",
    ]
    if for_video:
        parts.append(base.get("video_extra_en" if lang == "en" else "video_extra_zh", ""))
    # 卡审规则库：画面/视频禁用元素自动注入负面词
    rr = load_review_rules()
    parts.append((rr.get("video_negative" if for_video else "image_negative") or {}).get(lang, ""))
    return ", ".join(p.strip() for p in parts if p and p.strip())


def _keyword_spans(text: str, kw: str) -> list[tuple[int, int]]:
    """关键词在文本中的全部命中区间。

    中文按子串；纯 ASCII 按词边界且忽略大小写（与卡审规则口径一致）。
    """
    if not text or not kw:
        return []
    if kw.isascii():
        pat = re.compile(r"(?<![A-Za-z])" + re.escape(kw.lower()) + r"(?![A-Za-z])")
        return [(m.start(), m.end()) for m in pat.finditer(text.lower())]
    out, start = [], text.find(kw)
    while start != -1:
        out.append((start, start + len(kw)))
        start = text.find(kw, start + 1)
    return out


def review_whitelist(project: dict | None = None) -> list[str]:
    """合并卡审豁免短语：presets 内置（review_rules.text_whitelist）
    + 项目级（meta.review_whitelist）。用于剧名/固定台词等合法语境，
    避免中文子串匹配误伤（如剧名「杀疯了」豁免后「杀」不再单独命中）。
    """
    items = [*(load_review_rules().get("text_whitelist") or []),
             *(((project or {}).get("meta") or {}).get("review_whitelist") or [])]
    return [s.strip() for s in items if isinstance(s, str) and s.strip()]


def scan_review_text(text: str, whitelist: list[str] | None = None) -> list[dict]:
    """扫描文本命中的卡审规则，返回 [{id, level, title, keyword, fix}]。

    forbidden=禁止（必须改写，ERROR 级）；avoid=避免或少量出现（WARN 级，
    出现时该集结尾须回正）。中文关键词按子串匹配；纯 ASCII 英文关键词按
    词边界匹配（忽略大小写），避免 "cash" 命中 "cashier" 之外的误判扩展。

    whitelist：豁免短语列表（review_whitelist(project)）。关键词命中区间
    完全落在某个豁免短语内时不计；短语外的命中照常报出。
    """
    if not text:
        return []
    exempt: list[tuple[int, int]] = []
    for phrase in whitelist or []:
        exempt.extend(_keyword_spans(text, phrase))

    def covered(start: int, end: int) -> bool:
        return any(ws <= start and end <= we for ws, we in exempt)

    def first_live_keyword(keywords: list) -> str | None:
        for kw in keywords:
            if not kw:
                continue
            if any(not covered(s, e) for s, e in _keyword_spans(text, kw)):
                return kw
        return None

    hits: list[dict] = []
    for rule in load_review_rules().get("text_checks", []):
        matched = first_live_keyword(rule.get("keywords_zh", []))
        if matched is None:
            matched = first_live_keyword(rule.get("keywords_en", []))
        if matched:
            hits.append({
                "id": rule.get("id", "?"),
                "level": rule.get("level", "forbidden"),
                "title": rule.get("title", ""),
                "keyword": matched,
                "fix": rule.get("fix", ""),
            })
    return hits


# ---------------------------------------------------------------- 题材推断

def infer_genre(text: str) -> str | None:
    """从自由文本中推断题材 key：按匹配到的别名长度累计得分，取最高。"""
    presets = load_presets()
    text = (text or "").strip().lower()
    if not text:
        return None
    best_key, best_score = None, 0
    for key, meta in presets["genres"].items():
        score = 0
        for alias in meta.get("aliases", []):
            a = alias.lower()
            if a and a in text:
                score += len(a)
        for token in re.split(r"[,，/、\s]+", meta.get("keywords_en", "")):
            if token and token.lower() in text:
                score += 1
        if score > best_score:
            best_key, best_score = key, score
    return best_key if best_score > 0 else None


def infer_style(text: str) -> str | None:
    """按最长别名匹配，避免「3D动漫」被「3D」抢先匹配。"""
    presets = load_presets()
    text = (text or "").strip().lower()
    if not text:
        return None
    best_key, best_len = None, 0
    for key, meta in presets["styles"].items():
        for alias in meta.get("aliases", []):
            a = alias.lower()
            if a and a in text and len(a) > best_len:
                best_key, best_len = key, len(a)
    return best_key


def infer_platform(text: str) -> str | None:
    """按平台别名匹配；别名最长的优先（避免 "ins" 抢先匹配 "instagram"）。"""
    presets = load_presets()
    text = (text or "").strip().lower().replace("-", "").replace(" ", "")
    if not text:
        return None
    best_key, best_len = None, 0
    for key, meta in presets["platforms"].items():
        candidates = [meta.get("name", ""), key, *(meta.get("aliases") or [])]
        for candidate in candidates:
            c = str(candidate).lower().replace("-", "").replace(" ", "")
            if c and c in text and len(c) > best_len:
                best_key, best_len = key, len(c)
    return best_key


# ---------------------------------------------------------------- project

def find_project(path: str | None = None) -> Path:
    """定位 project.json：显式路径 > 当前目录 > 逐级向上。"""
    if path:
        p = Path(path)
        if p.is_dir():
            p = p / "project.json"
        if not p.is_file():
            raise SystemExit(f"找不到 project.json: {p}")
        return p
    cwd = Path.cwd()
    for base in [cwd, *cwd.parents]:
        candidate = base / "project.json"
        if candidate.is_file():
            return candidate
    raise SystemExit("未找到 project.json。请指定路径或在项目目录内运行。")


def project_root(project_path: Path) -> Path:
    return Path(project_path).resolve().parent


# ------------------------------------------------------------ 分片布局

EPISODES_DIRNAME = "episodes"


def episodes_dir_of(project_path: Path) -> Path:
    """分片目录：<project.json 所在目录>/episodes。"""
    return Path(project_path).resolve().parent / EPISODES_DIRNAME


def _ep_file_key(p: Path) -> list:
    """文件名自然排序键，保证 E02 排在 E10 前。"""
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", p.stem)]


def load_project(project_path: Path | str) -> dict:
    """读取项目：自动兼容单文件与分片布局。

    分片布局 = project.json 只留 meta/config/characters/scenes，
    分集按集落盘为 episodes/E01.json（含 shots）。读取时按自然序注入
    episodes 数组；project.json 与 episodes/ 同时存有分集属冲突状态，
    拒绝读取以免静默丢数据。
    """
    project_path = Path(project_path)
    project = load_json(project_path)
    ep_dir = episodes_dir_of(project_path)
    if not ep_dir.is_dir():
        return project
    existing = project.get("episodes")
    if existing:
        raise SystemExit(
            f"project.json 内已有 {len(existing)} 个分集，且 {ep_dir.name}/ 目录也存在，"
            f"两处分集数据冲突。请先运行 split_project.py --merge 合并，"
            f"或手工清理其一。")
    project["episodes"] = [load_json(p) for p in sorted(ep_dir.glob("*.json"),
                                                        key=_ep_file_key)]
    return project


def save_project(project: dict, project_path: Path | str) -> None:
    """写回项目：episodes/ 目录存在时按分片布局落盘，否则写单文件。

    分片写入以 project dict 为准：episodes 键从 project.json 移除、
    每集写入 episodes/<id>.json，并清理目录中已不属于当前分集的孤儿文件。
    不修改调用方传入的 dict。
    """
    project_path = Path(project_path)
    ep_dir = episodes_dir_of(project_path)
    if not ep_dir.is_dir():
        dump_json(project, project_path)
        return
    data = dict(project)
    episodes = data.pop("episodes", None) or []
    ids: set[str] = set()
    for ep in episodes:
        eid = str(ep.get("id") or "").strip()
        if not eid:
            raise SystemExit("episodes 存在缺少 id 的分集，无法分片写入")
        if eid in ids:
            raise SystemExit(f"分集 id 重复: {eid}，无法分片写入")
        ids.add(eid)
    for ep in episodes:
        dump_json(ep, ep_dir / f"{safe_dirname(str(ep['id']))}.json")
    for p in ep_dir.glob("*.json"):
        if p.stem not in ids:
            p.unlink()
    dump_json(data, project_path)


def iter_shots(project: dict):
    """遍历 (episode, shot)；对缺失/类型错误的分集与镜头静默跳过。"""
    episodes = project.get("episodes")
    if not isinstance(episodes, list):
        return
    for ep in episodes:
        if not isinstance(ep, dict):
            continue
        shots = ep.get("shots")
        if not isinstance(shots, list):
            continue
        for shot in shots:
            if isinstance(shot, dict):
                yield ep, shot


def episodes_of(project: dict) -> list[dict]:
    """返回合法的分集列表；缺失或类型错误的条目被过滤。"""
    episodes = project.get("episodes")
    if not isinstance(episodes, list):
        return []
    return [e for e in episodes if isinstance(e, dict)]


def shots_of(episode: dict) -> list[dict]:
    """返回某集的合法镜头列表；缺失或类型错误的条目被过滤。"""
    shots = episode.get("shots")
    if not isinstance(shots, list):
        return []
    return [s for s in shots if isinstance(s, dict)]


def characters_by_id(project: dict) -> dict:
    chars = project.get("characters")
    if not isinstance(chars, list):
        return {}
    return {c["id"]: c for c in chars if isinstance(c, dict) and c.get("id")}


def scenes_by_id(project: dict) -> dict:
    scenes = project.get("scenes")
    if not isinstance(scenes, list):
        return {}
    return {s["id"]: s for s in scenes if isinstance(s, dict) and s.get("id")}


def pacing_shot_sec(pacing: str) -> float:
    return {"slow": 4.5, "medium": 3.0, "fast": 2.0}.get(pacing, 3.0)


def limits() -> dict:
    """全局硬约束：单镜时长上下限、提示词字数上限、口播字速、角色/场景上限。"""
    return load_presets()["production"].get(
        "limits",
        {"shot_duration_sec": {"min": 0.5, "max": 30}, "prompt_chars": {"max": 15000}},
    )


def group_by_beat(shots: list[dict]) -> list[tuple[object, list[dict]]]:
    """按 beat 分组：连续相同 beat 为一组；beat 为 None 时每个 shot 自成一组。

    director_md / asset_manifest / validate 共用同一套分组规则，避免三处各写一份。
    """
    groups: list[tuple[object, list[dict]]] = []
    for s in shots:
        b = s.get("beat")
        if groups and b is not None and groups[-1][0] == b:
            groups[-1][1].append(s)
        else:
            groups.append((b, [s]))
    return groups


def char_name(ch: dict, stage_id: str | None = None, fallback: str = "") -> str:
    """角色名（带年龄段标签）；未匹配到年龄段时返回纯名字。

    director_md / asset_manifest 共用，避免重复实现。
    """
    nm = ch.get("name") or fallback
    if stage_id:
        for stg in ch.get("stages") or []:
            if stg.get("id") == stage_id:
                return f"{nm}（{stg.get('label', stage_id)}）"
    return nm


def cjk_chars_per_sec() -> float:
    """口播字速（字/秒），默认 4，可在 production.json 的 limits 中按语种调整。"""
    value = as_float(limits().get("cjk_chars_per_sec"), 4)
    return value if value > 0 else 4.0


def has_cjk(text: str | None) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text or "")


def as_float(value, default: float = 0.0) -> float:
    """安全转 float：缺失/非法值回落 default，避免脚本因脏数据崩溃。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def fmt_sec(value, digits: int = 2) -> str:
    """秒数格式化：3 → "3"，0.5 → "0.5"，1.25 → "1.25"。"""
    v = round(as_float(value), digits)
    return f"{v:g}"


_RESERVED_WIN_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def safe_dirname(name: str) -> str:
    """把剧名转成跨平台可用的目录名（Windows 非法字符 / 保留名 / 首尾点）。"""
    cleaned = "".join(
        "_" if ch in '<>:"/\\|?*' or ord(ch) < 32 else ch
        for ch in (name or "").strip()
    ).strip(" .")
    if not cleaned:
        return "untitled"
    if cleaned.upper() in _RESERVED_WIN_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned[:80]


def resolve_asset(root: Path, rel: str) -> Path | None:
    if not rel:
        return None
    p = Path(rel)
    if not p.is_absolute():
        p = root / p
    return p if p.is_file() else None


# ---------------------------------------------------------------- misc

def srt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def which_ffmpeg() -> str | None:
    for candidate in ("ffmpeg", "ffmpeg.exe"):
        try:
            subprocess.run(
                [candidate, "-version"], capture_output=True, check=True, timeout=15
            )
            return candidate
        except Exception:
            continue
    return None


def die(msg: str, code: int = 1):
    print(f"[错误] {msg}", file=sys.stderr)
    raise SystemExit(code)


def ok(msg: str):
    print(f"[完成] {msg}")
