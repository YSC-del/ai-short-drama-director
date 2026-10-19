#!/usr/bin/env python3
"""把素材合成成集。

用法:
    python assemble.py [project.json 或目录] [--episode E01 | --all]
                       [--no-subtitles] [--dry-run] [--keep-work]

流程（每集）:
    1. 每镜归一化为平台分辨率 / fps / 精确时长的视频片段（无声）
    2. 每镜生成对应时长的音频片段（有配音则用，否则静音；超长截断、过短补齐）
    3. 分别拼接，混音，烧录字幕（可选），输出 06_output/episodes/E01.mp4
    4. 同步生成 E01.srt

需要 ffmpeg。未安装时脚本会给出提示；加 --dry-run 可只打印命令。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _common as C


def concat_path(path: Path) -> str:
    """ffmpeg concat 列表（demuxer）里的路径：正斜杠 + 转义单引号。"""
    return str(path).replace("\\", "/").replace("'", "\\'")


def filter_path(path: Path) -> str:
    """ffmpeg 滤镜参数里的路径：Windows 盘符冒号与单引号都要转义。"""
    return str(path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def run(cmd: list[str], dry: bool) -> None:
    print("  $ " + " ".join(cmd))
    if dry:
        return
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=1800)
    except subprocess.CalledProcessError as exc:
        C.die(f"命令执行失败: {' '.join(cmd)}\n{exc.stderr[-2000:] if exc.stderr else ''}")


def platform_video_conf(project: dict, prod: dict) -> tuple[str, int, str]:
    """返回 (分辨率 WxH, fps, 归一化滤镜)。分辨率/fps 取项目平台配置。"""
    meta = project.get("meta")
    if not isinstance(meta, dict):
        meta = {}
    pm = C.platform(meta.get("platform") or "douyin")
    res = str(pm.get("resolution") or "1080x1920").lower().replace("×", "x")
    parts = res.split("x")
    width, height = (parts[0], parts[1]) if len(parts) == 2 else ("1080", "1920")
    if not (width.isdigit() and height.isdigit()):
        width, height = "1080", "1920"
    fps = int(C.as_float(pm.get("fps"), 30))
    if fps <= 0:
        fps = 30
    scale_pad = (prod.get("ffmpeg", {}).get("scale_pad")
                 or "scale={width}:{height}:force_original_aspect_ratio=decrease,"
                    "pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0x101014")
    vf = scale_pad.format(width=width, height=height)
    return f"{width}x{height}", fps, vf


def loudness_filter(project: dict) -> list[str]:
    """按平台 audio_loudness 做单遍响度归一化（如 -14 LUFS）；解析失败则跳过。"""
    meta = project.get("meta")
    if not isinstance(meta, dict):
        meta = {}
    pm = C.platform(meta.get("platform") or "douyin")
    raw = str(pm.get("audio_loudness") or "")
    target = C.as_float(raw.split("LUFS")[0].strip(), 0)
    if target >= 0:
        return []
    return ["-af", f"loudnorm=I={target:g}:TP=-1.5:LRA=11"]


def audio_is_silent(ffmpeg: str, path: Path, threshold_db: float = -60.0) -> bool:
    """检测整集音频是否近似静音；静音时 loudnorm 会输出 NaN，必须跳过。"""
    if not path.is_file():
        return False
    cmd = [ffmpeg, "-hide_banner", "-nostats", "-i", str(path),
           "-af", "volumedetect", "-f", "null", "-"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
    except OSError:
        return False
    m = re.search(r"max_volume:\s*(-?inf|-?\d+(?:\.\d+)?)\s*dB",
                  proc.stderr or "", re.I)
    if not m:
        return False
    value = m.group(1).lower()
    if value.endswith("inf"):
        return value.startswith("-")
    try:
        return float(value) < threshold_db
    except ValueError:
        return False


def resolve_assets(root: Path, shot: dict) -> dict:
    """把 shots[].assets 解析为磁盘上的绝对路径；缺失文件按空处理。"""
    out: dict[str, str] = {}
    for kind in ("video", "image", "audio"):
        rel = (shot.get("assets") or {}).get(kind) or ""
        if not rel:
            out[kind] = ""
            continue
        p = Path(rel)
        if not p.is_absolute():
            p = root / p
        out[kind] = str(p) if p.is_file() else ""
    return out


def clip_cmd(ffmpeg: str, shot: dict, assets: dict, out: Path,
             video_conf: tuple[str, int, str], dry: bool) -> None:
    dur = C.as_float(shot.get("duration_sec"), 3) or 3
    res, fps, vf = video_conf
    out.parent.mkdir(parents=True, exist_ok=True)

    if assets.get("video"):
        cmd = [ffmpeg, "-y", "-i", assets["video"], "-t", f"{dur}",
               "-vf", f"{vf},fps={fps}", "-an", "-c:v", "libx264",
               "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
               str(out)]
    elif assets.get("image"):
        cmd = [ffmpeg, "-y", "-loop", "1", "-t", f"{dur}", "-i", assets["image"],
               "-vf", f"{vf},fps={fps}", "-an", "-c:v", "libx264",
               "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
               str(out)]
    else:
        # 无素材：生成黑场占位，保证流程不断
        w, h = res.split("x")
        cmd = [ffmpeg, "-y", "-f", "lavfi", "-i",
               f"color=c=0x101014:s={w}x{h}:r={fps}:d={dur}",
               "-vf", f"fps={fps}", "-an", "-c:v", "libx264",
               "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
               str(out)]
    run(cmd, dry)


def audio_cmd(ffmpeg: str, shot: dict, assets: dict, out: Path, dry: bool) -> None:
    dur = C.as_float(shot.get("duration_sec"), 3) or 3
    out.parent.mkdir(parents=True, exist_ok=True)
    if assets.get("audio"):
        # apad 补齐过短音频；-t 截断过长音频，保证与视频逐镜等长
        cmd = [ffmpeg, "-y", "-i", assets["audio"], "-af", f"apad=whole_dur={dur}",
               "-t", f"{dur}", "-ar", "48000", "-ac", "2",
               "-c:a", "pcm_s16le", str(out)]
    else:
        cmd = [ffmpeg, "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
               "-t", f"{dur}", "-ar", "48000", "-ac", "2",
               "-c:a", "pcm_s16le", str(out)]
    run(cmd, dry)


def concat(ffmpeg: str, list_file: Path, out: Path, copy: bool, dry: bool) -> None:
    cmd = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file)]
    if copy:
        cmd += ["-c", "copy"]
    cmd += [str(out)]
    run(cmd, dry)


def write_srt(path: Path, shots: list[dict]) -> None:
    lines: list[str] = []
    t = 0.0
    for i, shot in enumerate(shots, 1):
        dur = C.as_float(shot.get("duration_sec"))
        dlg = shot.get("dialogue") or {}
        narr = shot.get("narration") or ""
        parts: list[str] = []
        if dlg.get("text"):
            parts.append(str(dlg["text"]).strip())
        if narr and narr.strip() not in parts:
            parts.append(narr.strip())
        if parts:
            text = "\n".join(parts)
            lines.append(f"{i}\n{C.srt_time(t)} --> {C.srt_time(t + dur)}\n{text}\n")
        t += dur
    C.write_text(path, "\n".join(lines) if lines else "")


def process_episode(ffmpeg: str | None, project: dict, ep: dict, root: Path,
                    dry: bool, subtitles: bool, keep_work: bool) -> None:
    prod = C.load_presets()["production"]
    video_conf = platform_video_conf(project, prod)
    eid = ep.get("id", "E??")
    shots = C.shots_of(ep)
    if not shots:
        C.die(f"{eid} 没有镜头")

    work = root / "06_output" / "work" / eid
    work.mkdir(parents=True, exist_ok=True)
    final_dir = root / "06_output" / "episodes"
    final_dir.mkdir(parents=True, exist_ok=True)
    final = final_dir / f"{eid}.mp4"
    srt = final_dir / f"{eid}.srt"

    # 字幕先落盘：即使没有 ffmpeg 也能拿到可用的 SRT
    write_srt(srt, shots)

    # dry-run 时即使没有 ffmpeg 也用占位名打印命令，便于人工检查
    bin_name = ffmpeg or "ffmpeg"
    print_cmds = ffmpeg is not None or dry

    print(f"\n--- {eid}（{len(shots)} 镜）---")
    vlist = work / "video_list.txt"
    alist = work / "audio_list.txt"
    vlines, alines = [], []
    placeholders: list[tuple[str, float]] = []

    for shot in shots:
        sid = shot.get("id", "?")
        assets = resolve_assets(root, shot)
        vout = work / f"{sid}.mp4"
        aout = work / f"{sid}.wav"
        kind = ("视频" if assets["video"]
                else "图片" if assets["image"] else "占位")
        print(f"  [{sid}] {shot.get('shot_size', '')} {shot.get('camera', '')} "
              f"{C.fmt_sec(shot.get('duration_sec'))}s 素材={kind}")
        if kind == "占位":
            placeholders.append((sid, C.as_float(shot.get("duration_sec"))))
        if print_cmds:
            clip_cmd(bin_name, shot, assets, vout, video_conf, dry)
            audio_cmd(bin_name, shot, assets, aout, dry)
        vlines.append(f"file '{concat_path(vout)}'")
        alines.append(f"file '{concat_path(aout)}'")

    # 黑场占位统计：缺素材会被静默合成黑场，必须显式暴露而不是混进"完成"
    if placeholders:
        black_sec = sum(d for _, d in placeholders)
        sample = ", ".join(sid for sid, _ in placeholders[:5])
        more = f" 等 {len(placeholders)} 镜" if len(placeholders) > 5 else ""
        print(f"  [警告] {eid} 有 {len(placeholders)} 镜无任何素材，"
              f"将以黑场占位（共 {C.fmt_sec(black_sec)}s）：{sample}{more}；"
              f"成片门禁要求无超过 2s 空洞镜头，请补齐素材后重新合成")

    C.write_text(vlist, "\n".join(vlines))
    C.write_text(alist, "\n".join(alines))

    raw_video = work / f"{eid}_raw.mp4"
    raw_audio = work / f"{eid}_raw.wav"
    if print_cmds:
        concat(bin_name, vlist, raw_video, copy=True, dry=dry)
        concat(bin_name, alist, raw_audio, copy=True, dry=dry)

    if print_cmds:
        loud = loudness_filter(project)
        if loud and audio_is_silent(bin_name, raw_audio):
            loud = []
            print("  [提示] 本集音频接近静音，跳过响度归一化")
        if subtitles:
            style = (prod.get("ffmpeg", {}).get("subtitle_style") or "").strip("'")
            vf = f"subtitles='{filter_path(srt)}'"
            if style:
                vf += f":force_style='{style}'"
            run([bin_name, "-y", "-i", str(raw_video), "-i", str(raw_audio),
                 "-vf", vf, "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                 "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                 "-ar", "48000", "-ac", "2",
                 *loud, "-movflags", "+faststart", "-shortest", str(final)], dry)
        else:
            run([bin_name, "-y", "-i", str(raw_video), "-i", str(raw_audio),
                 "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                 "-ar", "48000", "-ac", "2",
                 *loud, "-movflags", "+faststart", "-shortest", str(final)], dry)

    total = sum(C.as_float(s.get("duration_sec")) for s in shots)
    if dry:
        C.ok(f"{eid} 命令已打印（dry-run），预计 {C.fmt_sec(total)}s")
    elif ffmpeg:
        size = f"（{final.stat().st_size / 1024 / 1024:.1f} MB）" if final.is_file() else ""
        C.ok(f"{eid} 合成完成: {final}{size}（{C.fmt_sec(total)}s）")
    else:
        # 没有 ffmpeg 又不 dry-run：如实报告未合成，避免调用方误判成功
        C.ok(f"{eid} 未合成：未检测到 ffmpeg（已生成字幕 {srt}，安装 ffmpeg 后重试）")

    if not keep_work and not dry:
        import shutil
        shutil.rmtree(work, ignore_errors=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="合成每集成片")
    ap.add_argument("project", nargs="?", help="project.json 或所在目录")
    ap.add_argument("--episode", help="只合成某一集，如 E01")
    ap.add_argument("--all", action="store_true", help="合成所有集")
    ap.add_argument("--no-subtitles", action="store_true", help="不烧录字幕（仍输出 .srt）")
    ap.add_argument("--keep-work", action="store_true", help="保留中间文件")
    ap.add_argument("--dry-run", action="store_true", help="只打印 ffmpeg 命令")
    args = ap.parse_args()

    path = C.find_project(args.project)
    project = C.load_project(path)
    root = C.project_root(path)
    episodes = C.episodes_of(project)
    if not episodes:
        C.die("project.json 中没有分集")

    if args.episode:
        episodes = [e for e in episodes if e.get("id") == args.episode]
        if not episodes:
            C.die(f"找不到集 {args.episode}")
    elif not args.all:
        episodes = episodes[:1]
        print(f"未指定 --all，默认只合成第一集 {episodes[0].get('id')}")

    ffmpeg = C.which_ffmpeg()
    if not ffmpeg:
        print("[警告] 未检测到 ffmpeg，将只生成字幕与命令清单。")
        print("       安装后重试即可；或加 --dry-run 查看将要执行的命令。")

    for ep in episodes:
        process_episode(ffmpeg, project, ep, root, args.dry_run,
                        not args.no_subtitles, args.keep_work)

    if ffmpeg and not args.dry_run:
        print()
        print(f"成片目录: {root / '06_output' / 'episodes'}")
    elif not ffmpeg and not args.dry_run:
        # 未产出任何成片，明确失败，避免被上游当作成功
        raise SystemExit(1)


if __name__ == "__main__":
    main()
