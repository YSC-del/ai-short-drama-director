#!/usr/bin/env python3
"""素材增强：图片批量放大（lanczos + 轻锐化）与视频尾帧提取。

用法:
    python enhance.py [路径] --upscale [--factor 2]
        路径 = 图片文件 / 图片目录 / 项目路径（缺省取项目的 05_assets/images）。
        放大结果写为同目录 <名>-<N>x.png，绝不覆盖原图；已放大的文件自动跳过。
    python enhance.py <视频文件> --last-frame [--out PNG]
        提取视频最后一帧（默认写同目录 <名>-tail.png）。

为什么放大（高质量成片的关键一环）：
  * 图生视频模型会压缩输入，低分辨率首帧 = 成片必然糊；首帧放大到
    2K+ 再驱动 i2v，成片清晰度显著提升（见 references/production.md 素材增强节）。
  * 尾帧必须由视频最后一帧导出（不要重新生成），用作下一镜首帧才不跳变
    （见 references/prompt_recipes.md 第五节首尾帧工作流）。

需要 ffmpeg 6+（与 assemble.py 相同依赖）。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _common as C

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
DONE_PAT = re.compile(r"-\d+(\.\d+)?x$")


def run_ffmpeg(args: list[str]) -> None:
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if r.returncode != 0:
        raise SystemExit(f"[错误] ffmpeg 失败:\n{r.stderr[-800:]}")


def upscale_one(ff: str, src: Path, factor: float) -> Path | None:
    """放大单张图：lanczos + 轻锐化，输出 <名>-<N>x.png。已存在则跳过。"""
    dst = src.with_name(f"{src.stem}-{factor:g}x.png")
    if dst.is_file():
        print(f"  [跳过] 已存在 {dst.name}")
        return None
    vf = (f"scale=trunc(iw*{factor:g}/2)*2:trunc(ih*{factor:g}/2)*2:"
          f"flags=lanczos+accurate_rnd,unsharp=5:5:0.4:5:5:0.0")
    run_ffmpeg([ff, "-y", "-i", str(src), "-vf", vf, "-frames:v", "1", str(dst)])
    return dst


def collect_images(path: Path) -> list[Path]:
    """收集待放大图片：文件 → 单张；目录 → 全部图片；项目 → 05_assets/images。"""
    if path.is_file():
        return [path]
    if (path / "project.json").is_file() or path.name == "05_assets":
        target = path / "05_assets" / "images" if path.name != "05_assets" else path / "images"
        if target.is_dir():
            path = target
    if not path.is_dir():
        raise SystemExit(f"路径不是文件或目录: {path}")
    return sorted(p for p in path.rglob("*")
                  if p.suffix.lower() in IMAGE_EXTS and not DONE_PAT.search(p.stem))


def main() -> None:
    ap = argparse.ArgumentParser(description="素材增强：图片放大 / 视频尾帧提取")
    ap.add_argument("path", nargs="?",
                    help="图片文件/目录/项目路径（--upscale），或视频文件（--last-frame）")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--upscale", action="store_true",
                      help="批量放大图片（lanczos + 轻锐化，输出 <名>-<N>x.png）")
    mode.add_argument("--last-frame", action="store_true",
                      help="提取视频最后一帧（首尾帧工作流的下一镜首帧）")
    ap.add_argument("--factor", type=float, default=2.0,
                    help="放大倍数（默认 2）")
    ap.add_argument("--out", help="尾帧输出路径（默认同目录 <名>-tail.png）")
    args = ap.parse_args()

    ff = C.which_ffmpeg()
    if not ff:
        C.die("未找到 ffmpeg。安装方式见 SKILL.md 第四节（winget install Gyan.FFmpeg）")

    if args.last_frame:
        if not args.path:
            C.die("--last-frame 需要指定视频文件")
        src = Path(args.path)
        if not src.is_file():
            C.die(f"视频文件不存在: {src}")
        if src.suffix.lower() not in VIDEO_EXTS:
            print(f"  [提示] 非常见视频扩展名 {src.suffix}，仍按视频处理")
        out = Path(args.out) if args.out else src.with_name(f"{src.stem}-tail.png")
        out.parent.mkdir(parents=True, exist_ok=True)
        # -sseof 从文件末尾seek，取最后一帧；-update 1 保证只输出一张
        run_ffmpeg([ff, "-y", "-sseof", "-0.15", "-i", str(src),
                    "-update", "1", "-frames:v", "1", str(out)])
        C.ok(f"尾帧已提取: {out}")
        print("  用法: 作为下一镜图生视频的首帧（prompt_recipes.md 第五节），保持 seed 与风格后缀一致")
        raise SystemExit(0)

    # --upscale
    if args.path:
        path = Path(args.path)
        if not path.exists():
            C.die(f"路径不存在: {args.path}")
    else:
        # 缺省 = 当前项目的 05_assets/images
        path = C.project_root(C.find_project(None)) / "05_assets" / "images"
        if not path.is_dir():
            C.die(f"项目缺少 {path}（先生成首帧图，或指定图片文件/目录）")

    images = collect_images(path)
    if not images:
        C.die(f"未找到待放大的图片（png/jpg/jpeg/webp）: {path}")

    if args.factor <= 1.0:
        C.die("--factor 必须大于 1（放大用）")

    done = 0
    for src in images:
        try:
            dst = upscale_one(ff, src, args.factor)
        except SystemExit as e:
            print(f"  [失败] {src.name}: {e}")
            continue
        if dst:
            done += 1
            print(f"  [放大] {src.name} → {dst.name}（×{args.factor:g}）")
    C.ok(f"图片放大完成: {done}/{len(images)} 张（原图保留，放大件带 -{args.factor:g}x 后缀）")
    print("  用法: 图生视频首帧请选放大件（-Nx 后缀），成片清晰度显著更高")
    raise SystemExit(0 if done else 1)


if __name__ == "__main__":
    main()
