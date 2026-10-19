#!/usr/bin/env python3
"""project.json 单文件 ↔ 分片布局互转。

分片布局: project.json 只留 meta/config/characters/scenes，
分集数据按集落盘为 episodes/E01.json（读取时按自然序注入 episodes）。
长剧（50+ 集）单文件会膨胀到数 MB，拆分后所有脚本用法不变。

用法:
    python split_project.py <项目路径>            # 单文件 → 分片
    python split_project.py <项目路径> --merge    # 分片 → 单文件
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import _common as C


def main() -> None:
    ap = argparse.ArgumentParser(description="project.json 单文件/分片布局互转")
    ap.add_argument("project", nargs="?", default=None,
                    help="project.json 或其所在目录（默认从当前目录逐级向上查找）")
    ap.add_argument("--merge", action="store_true",
                    help="分片合并回单文件（默认把单文件拆分为分片）")
    args = ap.parse_args()

    path = C.find_project(args.project)
    ep_dir = C.episodes_dir_of(path)

    if args.merge:
        if not ep_dir.is_dir():
            C.die(f"未找到分片目录 {ep_dir}，项目已是单文件布局")
        project = C.load_project(path)
        merged = project.get("episodes") or []
        if not merged:
            C.die("分片目录为空，没有任何分集可合并")
        # 先写临时文件再原子替换，失败时保留原分片目录
        tmp = path.with_name(path.name + ".tmp")
        C.dump_json(project, tmp)
        os.replace(tmp, path)
        shutil.rmtree(ep_dir)
        C.ok(f"已合并 {len(merged)} 个分集 → {path}")
        return

    if ep_dir.is_dir():
        C.die(f"分片目录已存在: {ep_dir}（如需合并回单文件加 --merge）")
    project = C.load_json(path)
    episodes = project.get("episodes") or []
    if not episodes:
        C.die("project.json 没有分集数据，无需拆分")

    # 先整表校验 id，再落盘，避免写一半才发现坏数据
    seen: set[str] = set()
    for ep in episodes:
        eid = str(ep.get("id") or "").strip()
        if not eid:
            C.die("episodes 存在缺少 id 的分集，已中止（未写入任何分片）")
        if eid in seen:
            C.die(f"分集 id 重复: {eid}，已中止（未写入任何分片）")
        seen.add(eid)

    ep_dir.mkdir(parents=True, exist_ok=True)
    for ep in episodes:
        C.dump_json(ep, ep_dir / f"{C.safe_dirname(str(ep['id']))}.json")
    data = dict(project)
    data.pop("episodes", None)
    tmp = path.with_name(path.name + ".tmp")
    C.dump_json(data, tmp)
    os.replace(tmp, path)
    C.ok(f"已拆分 {len(episodes)} 个分集 → {ep_dir}")


if __name__ == "__main__":
    main()
