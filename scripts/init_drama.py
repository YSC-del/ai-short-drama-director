#!/usr/bin/env python3
"""初始化一个 AI 短剧项目。

用法:
    python init_drama.py --title "剧名" --brief "题材 风格 平台 的自由描述" [--out DIR]
    python init_drama.py --title "剧名" --genre revenge --style cinematic-realism --platform douyin --episodes 20 --duration 90 [--out DIR]

未显式指定 genre/style/platform 时，从 --brief 自动推断（见 references/genres.md）。
--force 允许写入已存在的非空目录（覆盖 project.json 与模板，不动素材）。
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _common as C

DIRS = [
    "01_script",
    "02_characters/refs",
    "03_storyboard",
    "04_prompts",
    "05_assets/images",
    "05_assets/videos",
    "05_assets/audio",
    "05_assets/refs",
    "05_assets/shots/common",
    "06_output/episodes",
    "06_output/final",
    "07_preview",
]

# 模板 → (项目内子目录, 目标文件名)
# 03_storyboard 不再放占位模板：分镜表由 build_prompts.py --type table
# 按集生成（03_storyboard/E01.md），避免 init 模板与真实数据脱节误导。
TEMPLATE_TARGETS = {
    "outline.md": ("01_script", "outline.md"),
    "episode_script.md": ("01_script", "E01.md"),
    "character_card.md": ("02_characters", "character_card.md"),
    "README.md": ("", "README.md"),
}


def build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="初始化 AI 短剧项目")
    ap.add_argument("--title", required=True, help="剧名")
    ap.add_argument("--brief", default="", help="需求自由描述，用于自动推断题材/风格/平台")
    ap.add_argument("--genre", help="题材 key（不填则自动推断，兜底取 production.json 的 default_genre）")
    ap.add_argument("--style", help="视觉风格 key")
    ap.add_argument("--platform", help="目标平台 key")
    ap.add_argument("--episodes", type=int, help="总集数")
    ap.add_argument("--duration", type=int, help="单集时长（秒）")
    ap.add_argument("--assets", help="角色/场景资产 JSON（可选，导入 characters/scenes）")
    ap.add_argument("--out", default=".", help="输出目录（默认当前目录）")
    ap.add_argument("--force", action="store_true",
                    help="输出目录非空时仍继续（覆盖 project.json；已有的剧本/模板/素材保留）")
    return ap


def load_assets(path: str) -> tuple[list[dict], list[dict]]:
    """读取资产 JSON：{"characters": [...], "scenes": [...]}，做最小结构校验。"""
    p = Path(path)
    if not p.is_file():
        C.die(f"找不到资产文件: {p}")
    data = C.load_json(p)
    if not isinstance(data, dict):
        C.die(f"资产文件顶层必须是对象: {p}")
    chars = data.get("characters") or []
    scenes = data.get("scenes") or []
    for tag, items, need in (("characters", chars, ("id", "name")),
                             ("scenes", scenes, ("id", "name", "anchor_en"))):
        if not isinstance(items, list):
            C.die(f"资产 {tag} 必须是数组: {p}")
        for item in items:
            if not isinstance(item, dict):
                C.die(f"资产 {tag} 条目必须是对象: {item}")
            missing = [k for k in need if not item.get(k)]
            if missing:
                C.die(f"资产 {tag} 条目缺字段 {missing}: {item}")
    for tag, items in (("characters", chars), ("scenes", scenes)):
        ids = [i["id"] for i in items]
        dups = {i for i in ids if ids.count(i) > 1}
        if dups:
            C.die(f"资产 {tag} 的 id 重复: {sorted(dups)}")
    return chars, scenes


def auto_config(brief: str, args: argparse.Namespace,
                notes: list[str]) -> tuple[str, str, str]:
    """返回 (genre, style, platform)，并把推断过程写入 notes。

    显式传入的 key 会立即校验，避免后续 KeyError / 静默回退。
    """
    presets = C.load_presets()
    inferred_genre = C.infer_genre(brief)
    g = args.genre or inferred_genre or presets["default_genre"]
    gm = C.genre(g)
    if args.genre:
        notes.append(f"题材（手动指定）：{gm['name']}")
    elif inferred_genre:
        notes.append(f"识别题材：{gm['name']}")
    else:
        notes.append(f"未能从描述中识别题材，使用默认「{gm['name']}」")

    inferred_style = C.infer_style(brief)
    s = args.style or inferred_style or gm["default_style"]
    sm = C.style(s)
    if args.style:
        notes.append(f"风格（手动指定）：{sm['name']}")
    elif inferred_style:
        notes.append(f"识别风格：{sm['name']}")
    else:
        notes.append(f"风格采用题材默认：{sm['name']}")

    inferred_platform = C.infer_platform(brief)
    p = args.platform or inferred_platform or "douyin"
    pm = C.platform(p)
    if args.platform:
        notes.append(f"目标平台（手动指定）：{pm['name']}")
    elif inferred_platform:
        notes.append(f"识别平台：{pm['name']}")
    else:
        notes.append(f"未识别平台，使用默认「{pm['name']}」")

    return g, s, p


def make_project(title: str, g: str, s: str, p: str, episodes: int | None,
                 duration: int | None, notes: list[str]) -> dict:
    gm = C.genre(g)
    pm = C.platform(p)
    shot_sec = C.pacing_shot_sec(gm["pacing"])

    if episodes is not None and episodes <= 0:
        C.die(f"--episodes 必须为正整数: {episodes}")
    if duration is not None and duration <= 0:
        C.die(f"--duration 必须为正整数: {duration}")

    requested = duration or gm["episode_sec"]
    lo, hi = pm["episode_sec"]
    final_dur = max(lo, min(requested, hi))
    if final_dur != requested:
        notes.append(f"单集时长 {requested}s 超出平台区间 {lo}-{hi}s，"
                     f"已调整为 {final_dur}s")

    cfg = {
        "episode_count": max(1, episodes or gm["episodes"]),
        "episode_duration_sec": final_dur,
        "shot_duration_sec": shot_sec,
        "hook_window_sec": 3,
        "reversal_every": gm["reversal_every"],
        "voice_locale": "zh-CN",
        "subtitle_burned": True,
    }

    return {
        "meta": {
            "title": title,
            "genre": g,
            "subgenre": gm["subgenres"][0] if gm.get("subgenres") else "",
            "style": s,
            "platform": p,
            "aspect_ratio": pm["aspect_ratio"],
            "language": "zh-CN",
            "prompt_lang": "zh",
            "video_workflow": "t2v-ref",
            "logline": "",
            "created_at": date.today().isoformat(),
        },
        "config": cfg,
        "characters": [],
        "scenes": [],
        "episodes": [],
    }


def render_template(text: str, values: dict[str, object]) -> str:
    """替换 {{KEY}} 占位符；未提供的占位符保持原样（如角色卡按角色复制）。"""
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


def main() -> None:
    args = build_argparser().parse_args()
    title = (args.title or "").strip()
    if not title:
        C.die("剧名不能为空")

    notes: list[str] = []
    g, s, p = auto_config(args.brief, args, notes)
    project = make_project(title, g, s, p, args.episodes, args.duration, notes)
    cfg = project["config"]

    # 可选：从资产 JSON 导入角色与场景（换剧本时复用，不必手写 project.json）
    if args.assets:
        chars, scenes = load_assets(args.assets)
        project["characters"] = chars
        project["scenes"] = scenes
        notes.append(f"已导入资产：{len(chars)} 个角色 / {len(scenes)} 个场景")

    dir_name = C.safe_dirname(title)
    if dir_name != title:
        notes.append(f"剧名含路径非法字符或超长，项目目录使用「{dir_name}」")

    out_dir = Path(args.out).resolve() / dir_name
    if out_dir.exists() and any(out_dir.iterdir()):
        if not args.force:
            C.die(f"目录已存在且非空: {out_dir}（如需重新初始化 project.json，加 --force）")
        notes.append("目标目录已存在：已覆盖 project.json；已有的剧本/模板/素材未改动")

    for d in DIRS:
        (out_dir / d).mkdir(parents=True, exist_ok=True)

    # 生成第一集空壳，其余集由 Agent 按需补
    project["episodes"].append({
        "id": "E01",
        "title": "",
        "logline": "",
        "hook": "",
        "cliffhanger": "",
        "duration_sec": cfg["episode_duration_sec"],
        "shots": [],
    })
    if (out_dir / "episodes").is_dir():
        C.die("目标项目已是分片布局（存在 episodes/ 目录）。"
              "请先运行 split_project.py --merge 合并，或删除该目录后重试。")
    C.dump_json(project, out_dir / "project.json")

    # 模板渲染：占位符全部替换，避免交付物里残留 {{TITLE}}
    values = {
        "TITLE": title,
        "GENRE": C.genre(g)["name"],
        "STYLE": C.style(s)["name"],
        "PLATFORM": C.platform(p)["name"],
        "EPISODES": cfg["episode_count"],
        "DURATION": cfg["episode_duration_sec"],
        "SHOT_SEC": C.fmt_sec(cfg["shot_duration_sec"]),
        "REVERSAL": cfg["reversal_every"],
        "RATE": C.fmt_sec(C.cjk_chars_per_sec()),
        "WORDS": int(cfg["episode_duration_sec"] * C.cjk_chars_per_sec()),
        "EP_ID": "E01",
        "EP_TITLE": "（待定）",
    }
    for name, (sub_dir, target_name) in TEMPLATE_TARGETS.items():
        src = C.TEMPLATES_DIR / name
        if not src.is_file():
            continue
        target = out_dir / sub_dir / target_name
        if target.is_file() and target.stat().st_size > 0:
            # --force 重跑时保护已写好的剧本/角色卡，不让模板覆盖
            continue
        C.write_text(target, render_template(C.read_text(src), values))

    gm = C.genre(g)
    print("=" * 60)
    print(f"项目已创建: {out_dir}")
    print("=" * 60)
    print(f"剧名    : {title}")
    print(f"题材    : {gm['name']}  ({g})")
    print(f"风格    : {C.style(s)['name']}  ({s})")
    print(f"平台    : {C.platform(p)['name']}  ({p})")
    print(f"集数    : {cfg['episode_count']}")
    print(f"单集时长: {cfg['episode_duration_sec']}s")
    print(f"镜头时长: {C.fmt_sec(cfg['shot_duration_sec'])}s (pacing={gm['pacing']})")
    print(f"大反转集: 第 1, {cfg['reversal_every']}, "
          f"{2 * cfg['reversal_every']} ... 集")
    for n in notes:
        print(f"  * {n}")
    print()
    print("下一步：")
    print(f"  1. cd {out_dir}")
    print("  2. 写 01_script/outline.md 与 02_characters/character_card.md")
    if not args.assets:
        print("  3. 把角色/场景写入 project.json 或下次用 --assets 导入")
    else:
        print("  3. 检查资产锚点（validate 会做引用与卡审扫描）")
    print("  4. python <skill>/scripts/validate_project.py 校验")
    print("  5. python <skill>/scripts/build_prompts.py --type all --strict-en 生成提示词")
    print("  6. python <skill>/scripts/preview.py 生成分镜墙审阅")
    print("  7. python <skill>/scripts/assemble.py --episode E01 合成成片")


if __name__ == "__main__":
    main()
