#!/usr/bin/env python3
"""生成 HTML 分镜墙，用于人工审阅剧本与生成进度。

用法:
    python preview.py [project.json 或目录] [--out 07_preview/storyboard.html]

输出为单文件 HTML（无外部依赖），浏览器直接打开。
"""

from __future__ import annotations

import argparse
import copy
import html as html_lib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _common as C


def main() -> None:
    ap = argparse.ArgumentParser(description="生成 HTML 分镜墙")
    ap.add_argument("project", nargs="?", help="project.json 或所在目录")
    ap.add_argument("--out", help="输出 HTML 路径（默认 <项目>/07_preview/storyboard.html）")
    args = ap.parse_args()

    path = C.find_project(args.project)
    project = C.load_project(path)
    root = C.project_root(path)
    presets = C.load_presets()

    # 深拷贝：预览层需要把素材路径改成相对路径，不能污染 project 数据
    data = copy.deepcopy(project)
    data["episodes"] = C.episodes_of(data)
    for ep in data["episodes"]:
        ep["shots"] = C.shots_of(ep)
    if not isinstance(data.get("config"), dict):
        data["config"] = {}
    chars = data.get("characters")
    data["characters"] = [c for c in chars if isinstance(c, dict)] if isinstance(chars, list) else []
    meta = data.get("meta")
    if not isinstance(meta, dict):
        meta = {}
        data["meta"] = meta
    data["_genreName"] = presets["genres"].get(meta.get("genre"), {}).get("name", "")
    data["_styleName"] = presets["styles"].get(meta.get("style"), {}).get("name", "")
    data["_platformName"] = presets["platforms"].get(meta.get("platform"), {}).get("name", "")

    out = Path(args.out) if args.out else root / "07_preview" / "storyboard.html"
    if not out.is_absolute():
        out = root / out
    preview_dir = out.resolve().parent
    preview_dir.mkdir(parents=True, exist_ok=True)

    # 素材路径转为相对预览目录的路径
    for _ep, shot in C.iter_shots(data):
        assets = shot.get("assets")
        if not isinstance(assets, dict):
            continue
        for kind in ("image", "video", "audio"):
            rel = assets.get(kind)
            if not rel:
                continue
            p = Path(rel)
            if not p.is_absolute():
                p = root / p
            try:
                assets[kind] = Path(os.path.relpath(p, preview_dir)).as_posix()
            except ValueError:
                # Windows 跨盘符无法相对化，退化为绝对路径
                assets[kind] = p.as_posix()

    tpl = C.read_text(C.TEMPLATES_DIR / "storyboard_preview.html")
    title = html_lib.escape(str(meta.get("title") or "未命名"))
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = tpl.replace("__DATA__", payload, 1).replace("__TITLE__", title, 1)

    C.write_text(out, html)

    episodes = C.episodes_of(data)
    shots = sum(len(C.shots_of(e)) for e in episodes)
    C.ok(f"分镜墙已生成: {out}")
    print(f"  {len(episodes)} 集 / {shots} 个镜头")
    print("  用浏览器打开该文件即可审阅（无需启动服务）")


if __name__ == "__main__":
    main()
