#!/usr/bin/env python3
"""skill 自检：用合成数据跑通全链路，验证不依赖具体剧本。

用法:
    python selftest.py            # 全量自检（临时目录，跑完自动清理）
    python selftest.py --keep     # 保留临时目录便于排查

覆盖：
  A. 正常链路：2 集 × 若干镜，init(--assets) → validate → build(--strict-en)
     → preview → assemble(dry-run)，含多集累计、资产清单行数、导演版结构断言
  B. 剧本导入：表格 / 中文剧本 / 小说 / Word 四种输入，集场镜对白映射、
     换场标记、默认跳过已有镜头、角色场景占位校验
  C. 异常用例：重复镜号（集内/跨集）、beat 超 30s、缺 duration、非数字时长、
     shot_no 不连续、中文动作缺 action_en、时长为 0（防除零崩溃）、零目标时长
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
PY = sys.executable

FAILURES: list[str] = []
CJK = re.compile(r"[\u4e00-\u9fff]")


def run(args: list[str], expect_fail: bool = False,
        label: str = "") -> subprocess.CompletedProcess:
    label = label or " ".join(str(a) for a in args[:2])
    # 子进程统一 UTF-8 输出，避免 Windows 下父子进程编码不一致
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    r = subprocess.run([PY] + [str(a) for a in args], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=env)
    if expect_fail and r.returncode == 0:
        FAILURES.append(f"{label}: 预期失败但返回 0")
    if not expect_fail and r.returncode != 0:
        FAILURES.append(f"{label}: 返回 {r.returncode}\n"
                        f"{r.stdout[-400:]}\n{r.stderr[-200:]}")
    return r


ASSETS = {
    "characters": [
        {
            "id": "LIN", "name": "林晚", "role": "protagonist", "age": "28",
            "gender": "女",
            "appearance": "black long straight hair, amber eyes, fair skin, sharp jawline",
            "outfits": [{"id": "A", "desc": "beige trench coat over white shirt"}],
            "motivation": "拿回被夺走的一切",
            "visual_anchors": ["黑色长直发", "琥珀色眼眸", "左手银戒"],
            "voice": {"timbre": "清冷御姐", "speed": 1.05, "emotion": "克制"},
            "image_prompt": "a young woman with black long straight hair, amber eyes, "
                            "fair skin, sharp jawline",
            "negative_prompt": "child face, teenage look",
            "seed": 20261016,
            "stages": [
                {"id": "child", "label": "幼年",
                 "image_prompt": "a five-year-old Chinese girl, round face, double ponytails"},
            ],
        },
        {
            "id": "ZHAO", "name": "赵衡", "role": "antagonist", "age": "32",
            "gender": "男",
            "appearance": "short black hair, thin framed glasses, narrow eyes, tall build",
            "outfits": [{"id": "A", "desc": "navy three-piece suit"}],
            "motivation": "保住公司控制权",
            "visual_anchors": ["银丝眼镜", "海军蓝三件套", "左手腕表"],
            "voice": {"timbre": "低沉男声", "speed": 1.0, "emotion": "冷漠"},
            "image_prompt": "a tall man with short black hair, thin framed glasses, "
                            "narrow eyes",
            "seed": 20261017,
        },
    ],
    "scenes": [
        {
            "id": "S1", "name": "老宅客厅", "time": "夜",
            "desc": "昏暗的老宅客厅，红木家具，泛黄全家福",
            "anchor_en": "dimly lit living room of an old Chinese family house, "
                         "mahogany furniture, night",
            "lighting": "煤油灯暖黄光，低照度",
            "lighting_en": "warm kerosene lamp light, low key",
        },
        {
            "id": "S2", "name": "雨夜街道", "time": "夜",
            "desc": "空荡街道，大雨，湿地面反射霓虹",
            "anchor_en": "empty city street in heavy rain at night, wet asphalt "
                         "reflecting neon",
            "lighting": "冷蓝夜雨光，霓虹反光",
            "lighting_en": "cold blue rainy night light, neon reflections",
        },
    ],
}


def shot(sid: str, no: int, beat: str, scene: str, chars: list[str], dur: int,
         action: str, action_en: str, motion: str, **extra) -> dict:
    s = {
        "id": sid, "shot_no": no, "beat": beat, "scene_id": scene,
        "characters": chars, "shot_size": "中景", "camera": "手持",
        "composition": "三分法", "action": action, "action_en": action_en,
        "video_action_en": motion, "duration_sec": dur, "transition_in": "硬切",
        "status": "pending", "assets": {"image": "", "video": "", "audio": ""},
    }
    s.update(extra)
    return s


SHOTS_E01 = [
    shot("E01-S01", 1, "摔协议", "S1", ["LIN", "ZHAO"], 3,
         "赵衡把离婚协议摔在桌上，林晚站着没动",
         "the man slams the divorce papers onto the table, the woman stands still",
         "the papers hit the table and slide, she does not flinch",
         dialogue={"character": "ZHAO", "text": "签了，你净身出户。",
                   "emotion": "冷漠", "delivery": "语速平缓，尾音下沉"},
         outfits={"LIN": "A"},
         props=["离婚协议"], showcase="震颤式手持", sfx="纸张拍桌"),
    shot("E01-S02", 2, "摔协议", "S1", ["LIN"], 3,
         "林晚嘴角慢慢上扬，眼神由灰暗转为冷厉",
         "the corner of her mouth rises slowly, her eyes turn cold",
         "her gaze lifts gradually to the lens",
         character_stages={"LIN": "child"},
         narration="三年后我才知道，这一晚是我求来的。"),
    shot("E01-S03", 3, "雨夜", "S2", [], 3,
         "大雨砸在空荡街面，无人经过",
         "heavy rain hammers the empty street, no one passes",
         "rain streaks across the frame, ripples spreading on wet asphalt",
         scene_marker=True, transition_in="叠化"),
]

SHOTS_E02 = [
    shot("E02-S01", 1, "回娘家", "S1", ["LIN"], 4,
         "林晚抱着襁褓推门进屋，衣角还在滴水",
         "she pushes the door open with the swaddle in her arms, her coat still dripping",
         "she steps in slowly, water dripping from her coat",
         dialogue={"character": "LIN", "text": "妈，我回来了。",
                   "emotion": "哽咽", "delivery": "声音发紧"}),
    shot("E02-S02", 2, "回娘家", "S1", ["LIN", "ZHAO"], 3,
         "苏建业站在门口没敢进，双手在衣襟上蹭了又蹭",
         "he stops at the doorway, wiping his hands on his jacket again and again",
         "he shifts his weight, hands wiping his jacket",
         props=["襁褓"], showcase="低角度冲击"),
]


def check(label: str, cond: bool, detail: str = "") -> None:
    if not cond:
        FAILURES.append(f"{label}: {detail}")


def main() -> None:
    ap = argparse.ArgumentParser(description="skill 自检")
    ap.add_argument("--keep", action="store_true", help="保留临时目录")
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="drama_selftest_"))
    assets_path = tmp / "assets.json"
    assets_path.write_text(json.dumps(ASSETS, ensure_ascii=False, indent=2),
                           encoding="utf-8")

    # ---------- A. 正常链路（2 集）----------
    run([SCRIPTS / "init_drama.py", "--title", "SelfTest", "--genre", "revenge",
         "--style", "cinematic-realism", "--platform", "douyin",
         "--episodes", "2", "--duration", "90", "--assets", assets_path,
         "--out", tmp], label="init --assets")

    proj_dir = tmp / "SelfTest"
    proj_path = proj_dir / "project.json"
    if not proj_path.is_file():
        FAILURES.append("init 未生成 project.json")
        _finish(tmp, args.keep)
        return

    project = json.loads(proj_path.read_text(encoding="utf-8"))
    # A 节沿用英文模式断言（zh 默认模式在 F 节单独验证）
    project["meta"]["prompt_lang"] = "en"
    proj_path.write_text(json.dumps(project, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    project["episodes"][0].update({
        "title": "自检第一集", "hook": "协议摔在桌上，她没哭反而笑了",
        "cliffhanger": "她抬头看向镜头", "duration_sec": 10,
        "shots": SHOTS_E01})
    project["episodes"].append({
        "id": "E02", "title": "自检第二集", "logline": "回娘家",
        "hook": "她抱着襁褓推门", "cliffhanger": "他站在门口没敢进",
        "duration_sec": 4.5,
        "shots": SHOTS_E02})
    # 非整数时长：验证视频提示词输出 "0.5 seconds" 而不是 "0 seconds"
    project["episodes"][1]["shots"][1]["duration_sec"] = 0.5
    proj_path.write_text(json.dumps(project, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    n_shots = sum(len(e["shots"]) for e in project["episodes"])

    # 模板渲染与目录映射（占位符不得残留）
    outline = (proj_dir / "01_script" / "outline.md").read_text(encoding="utf-8")
    script = (proj_dir / "01_script" / "E01.md").read_text(encoding="utf-8")
    check("outline 已渲染", "{{" not in outline and "SelfTest" in outline, outline[:80])
    check("E01 剧本已渲染", "{{" not in script, script[:80])
    check("角色卡在 02_characters",
          (proj_dir / "02_characters" / "character_card.md").is_file())
    check("init 不再产出占位分镜模板",
          not (proj_dir / "03_storyboard" / "storyboard.md").exists())

    r = run([SCRIPTS / "validate_project.py", proj_dir], label="validate(2集)")
    check("validate 无 ERROR", "[ERROR]" not in r.stdout, r.stdout)
    check("validate 无 action_en 缺失告警", "缺 action_en" not in r.stdout, r.stdout)

    r = run([SCRIPTS / "build_prompts.py", proj_dir, "--type", "all",
             "--strict-en"], label="build all --strict-en")
    check("build 无报错", "[错误]" not in r.stdout, r.stdout)

    out_dir = proj_dir / "04_prompts"
    for name in ("image_prompts.md", "video_prompts.md", "audio_prompts.md",
                 "director_prompts.md", "prompts.csv", "prompts.json",
                 "asset_manifest.md", "asset_manifest.csv"):
        check(f"产物 {name}", (out_dir / name).is_file())
    for eid in ("E01", "E02"):
        check(f"分镜表 {eid}.md", (proj_dir / "03_storyboard" / f"{eid}.md").is_file())

    # 资产清单行数 == 全部镜头数（两集合计）
    if (out_dir / "asset_manifest.csv").is_file():
        with (out_dir / "asset_manifest.csv").open(encoding="utf-8-sig") as fh:
            rows = list(fh)
        check("资产清单行数 == 镜头数", len(rows) - 1 == n_shots,
              f"{len(rows) - 1} vs {n_shots}")

    project = json.loads(proj_path.read_text(encoding="utf-8"))
    s1 = project["episodes"][0]["shots"][0]
    img, vid = s1["image_prompt"], s1["video_prompt"]
    check("image_prompt 纯英文", not CJK.search(img), img)
    check("构图已英译", "rule of thirds" in img, img)
    check("景别联动镜头参数", "50mm lens" in img, img)
    check("画质后缀专业级", "professional color grading" in img, img)

    # 人物形象参考（定妆照）：左大头照 + 右无脸三视图
    img_doc = (out_dir / "image_prompts.md").read_text(encoding="utf-8")
    check("定妆照分区存在", "## 人物形象参考" in img_doc and "## 分镜首帧" in img_doc,
          img_doc[:200])
    check("定妆照复合布局", "split layout" in img_doc and "turnaround" in img_doc, img_doc[:200])
    check("三视图无脸", "faceless with no facial features" in img_doc, img_doc[:200])
    check("video 用 video_action_en", "the papers hit the table" in vid, vid)
    check("视频单镜头纪律", "single continuous take" in vid, vid)
    check("服装按角色映射", "beige trench coat" in img and "navy three-piece" not in img, img)

    s2 = project["episodes"][0]["shots"][1]
    check("年龄段锚点生效", "five-year-old" in s2["image_prompt"], s2["image_prompt"])

    e2s2 = project["episodes"][1]["shots"][1]
    check("0.5s 视频时长格式", "0.5 seconds" in e2s2["video_prompt"],
          e2s2["video_prompt"])

    # 角色专属负面词并入
    items = json.loads((out_dir / "prompts.json").read_text(encoding="utf-8"))["items"]
    neg = next(i["negative"] for i in items
               if i["type"] == "image" and i["id"] == "E01-S01")
    check("角色负面词并入", "child face" in neg, neg)

    # 导演版：两集都要有集头总览与累计
    doc = (out_dir / "director_prompts.md").read_text(encoding="utf-8")
    for token in ("## E01｜", "## E02｜", "- 总时长：", "累计至", "【本镜资产】", "【约束】"):
        check(f"导演版含 {token}", token in doc)

    # 音频输出：每集一条 BGM（剧梦工作流），情绪曲线自动拼装
    audio_doc = (out_dir / "audio_prompts.md").read_text(encoding="utf-8")
    check("音频含 BGM 标题", "## BGM（E01" in audio_doc and "## BGM（E02" in audio_doc,
          audio_doc[:200])
    check("BGM 含情绪走向", "情绪走向" in audio_doc, audio_doc[:200])
    check("E02 累计独立于 E01", doc.count("累计至") >= 2)

    # 子类型运行（--type table）不应清空 image/video/audio 清单
    run([SCRIPTS / "build_prompts.py", proj_dir, "--type", "table"],
        label="build table 增量")
    with (out_dir / "prompts.csv").open(encoding="utf-8-sig") as fh:
        rows_after = list(fh)
    check("--type table 保留 prompts.csv", len(rows_after) - 1 == n_shots * 3,
          f"{len(rows_after) - 1} vs {n_shots * 3}")

    run([SCRIPTS / "build_prompts.py", proj_dir, "--type", "image"],
        label="build image 增量")
    with (out_dir / "prompts.csv").open(encoding="utf-8-sig") as fh:
        rows_after = list(fh)
    check("--type image 保留其他类型", len(rows_after) - 1 == n_shots * 3,
          f"{len(rows_after) - 1} vs {n_shots * 3}")

    # 预览墙：有视频素材时渲染 <video>
    project = json.loads(proj_path.read_text(encoding="utf-8"))
    project["episodes"][0]["shots"][0]["assets"]["video"] = \
        "05_assets/videos/E01/E01-S01.mp4"
    proj_path.write_text(json.dumps(project, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    run([SCRIPTS / "preview.py", proj_dir], label="preview")
    preview_html = (proj_dir / "07_preview" / "storyboard.html").read_text(encoding="utf-8")
    check("storyboard.html", (proj_dir / "07_preview" / "storyboard.html").is_file())
    check("预览墙支持视频", "<video" in preview_html)
    r = run([SCRIPTS / "assemble.py", proj_dir, "--all", "--dry-run"],
            label="assemble --all dry-run")
    check("assemble dry-run 打印命令", "$ ffmpeg" in r.stdout)

    # ---------- C. 剧本导入 ----------
    import_root = tmp / "import_out"
    table_script = tmp / "import_table.md"
    table_script.write_text(
        "# 第一集 测试\n\n场景1：客厅 夜\n\n"
        "| 镜号 | 景别 | 运镜 | 构图 | 画面动作 | 对白/旁白 | 时长 |\n"
        "|---|---|---|---|---|---|---|\n"
        "| 1 | 中景 | 固定 | 中心 | 赵衡把协议摔在桌上，林晚站着没动 | 赵衡：签了。 | 3 |\n"
        "| 2 | 特写 | 推镜 | 中心 | 林晚嘴角上扬 | 林晚：我会签的。 | 2.5 |\n\n"
        "场景2：街道 夜\n\n"
        "| 镜号 | 景别 | 运镜 | 构图 | 画面动作 | 对白/旁白 | 时长 |\n"
        "|---|---|---|---|---|---|---|\n"
        "| 3 | 全景 | 固定 | 中心 | 林晚走进雨里 |  | 4 |\n\n"
        "# 第二集 回门\n\n场景1：客厅 夜\n\n"
        "| 镜号 | 景别 | 运镜 | 构图 | 画面动作 | 对白/旁白 | 时长 |\n"
        "|---|---|---|---|---|---|---|\n"
        "| 1 | 中景 | 跟拍 | 中心 | 林晚推门进屋 | 林晚：妈，我回来了。 | 4 |\n",
        encoding="utf-8")

    r = run([SCRIPTS / "import_script.py", table_script, "--out", import_root,
             "--title", "ImportTest", "--genre", "revenge",
             "--style", "cinematic-realism", "--platform", "douyin",
             "--episodes", "2", "--duration", "90"], label="import table")
    check("import 不崩溃", "Traceback" not in r.stderr, r.stderr)
    import_proj = import_root / "ImportTest"
    import_json = import_proj / "project.json"
    check("import 生成 project.json", import_json.is_file())
    imp = json.loads(import_json.read_text(encoding="utf-8")) if import_json.is_file() else {}
    imp_eps = imp.get("episodes") or []
    check("import 集数", [e.get("id") for e in imp_eps] == ["E01", "E02"],
          str([e.get("id") for e in imp_eps]))
    check("import E01 镜头数", len(imp_eps[0].get("shots") or []) == 3 if imp_eps else False)
    check("import E02 镜头数", len(imp_eps[1].get("shots") or []) == 1 if len(imp_eps) > 1 else False)
    check("import 角色数", len(imp.get("characters") or []) == 2,
          str(imp.get("characters")))
    check("import 场景数", len(imp.get("scenes") or []) == 2,
          str(imp.get("scenes")))
    if imp_eps:
        s1 = imp_eps[0]["shots"][0]
        check("import 对白映射", s1.get("dialogue", {}).get("text") == "签了。", str(s1))
        check("import 说话人映射", bool(s1.get("dialogue", {}).get("character")), str(s1))
        check("import 动作人物入镜", len(s1.get("characters") or []) >= 2, str(s1.get("characters")))
        check("import 换场标记", imp_eps[0]["shots"][2].get("scene_marker") is True,
              str(imp_eps[0]["shots"][2]))
    check("import 源备份", (import_proj / "01_script" / "source.md").is_file())
    check("import 报告", (import_proj / "01_script" / "import_report.md").is_file())
    check("import 剧本视图", (import_proj / "01_script" / "E01.md").is_file())
    check("import meta", (imp.get("meta") or {}).get("_import", {}).get("format") == "table",
          str((imp.get("meta") or {}).get("_import")))

    r = run([SCRIPTS / "validate_project.py", import_proj], expect_fail=True,
            label="import validate(占位)")
    check("import 占位被 validate 指出", "缺少 appearance" in r.stdout, r.stdout)
    check("import validate 不崩溃", "Traceback" not in r.stderr, r.stderr)

    r = run([SCRIPTS / "import_script.py", table_script, "--project", import_proj],
            label="import 默认跳过已有")
    check("import 默认跳过", "跳过已有镜头" in r.stdout, r.stdout)

    screen_script = tmp / "import_screen.txt"
    screen_script.write_text(
        "第一集\n场景1：办公室 日\n林晚：我回来了。\n赵衡（冷笑）：坐吧。\n",
        encoding="utf-8")
    r = run([SCRIPTS / "import_script.py", screen_script, "--project", import_proj,
             "--episode", "E05"], label="import screenplay E05")
    check("import 剧本格式", "格式=screenplay" in r.stdout, r.stdout)
    imp = json.loads(import_json.read_text(encoding="utf-8"))
    e05 = next((e for e in imp["episodes"] if e["id"] == "E05"), None)
    check("import E05", bool(e05), str([e.get("id") for e in imp["episodes"]]))
    if e05:
        check("import E05 镜头数", len(e05["shots"]) == 2, str(e05["shots"]))
        check("import 情绪解析", e05["shots"][1].get("dialogue", {}).get("emotion") == "冷笑",
              str(e05["shots"][1]))
    check("import 集数自动扩展", imp.get("config", {}).get("episode_count") == 5,
          str(imp.get("config")))

    novel_script = tmp / "import_novel.txt"
    novel_script.write_text(
        "第一章\n雨下了一整夜。\n林晚站在门口，没有敲门。\n她想起三年前的那个晚上。\n",
        encoding="utf-8")
    r = run([SCRIPTS / "import_script.py", novel_script, "--project", import_proj,
             "--episode", "E06"], label="import novel E06")
    check("import 小说格式", "格式=novel" in r.stdout, r.stdout)
    imp = json.loads(import_json.read_text(encoding="utf-8"))
    e06 = next((e for e in imp["episodes"] if e["id"] == "E06"), None)
    check("import E06", bool(e06), str([e.get("id") for e in imp["episodes"]]))
    if e06:
        check("import 小说切镜", len(e06["shots"]) == 3, str(e06["shots"]))
    novel_scene = next((s for s in imp["scenes"] if s["name"] == "未命名场景"), None)
    check("import 小说场景占位", bool(novel_scene), str(imp["scenes"]))

    docx_script = tmp / "import.docx"
    wns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

    def wp(text: str) -> str:
        return f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"

    def wtc(text: str) -> str:
        return f"<w:tc>{wp(text)}</w:tc>"

    header = ["镜号", "景别", "运镜", "构图", "画面动作", "对白/旁白", "时长"]
    row = ["1", "中景", "固定", "中心", "林晚推门而入", "林晚：我回来了。", "3"]
    table = "<w:tbl>" + "".join(
        "<w:tr>" + "".join(wtc(c) for c in cells) + "</w:tr>"
        for cells in (header, row)) + "</w:tbl>"
    docx_xml = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f"<w:document {wns}><w:body>{wp('第一集')}{table}</w:body></w:document>")
    with zipfile.ZipFile(docx_script, "w") as zf:
        zf.writestr("word/document.xml", docx_xml)

    r = run([SCRIPTS / "import_script.py", docx_script, "--project", import_proj,
             "--episode", "E07"], label="import docx E07")
    check("import Word 编码", "编码=docx" in r.stdout, r.stdout)
    imp = json.loads(import_json.read_text(encoding="utf-8"))
    e07 = next((e for e in imp["episodes"] if e["id"] == "E07"), None)
    check("import E07", bool(e07), str([e.get("id") for e in imp["episodes"]]))
    if e07:
        check("import Word 表格切镜", len(e07["shots"]) == 1, str(e07["shots"]))
        check("import Word 对白", e07["shots"][0].get("dialogue", {}).get("text") == "我回来了。",
              str(e07["shots"][0]))
    check("import Word 源备份", (import_proj / "01_script" / "source.docx").is_file())

    # ---------- B. 异常用例 ----------
    def variant(tag: str, mutate) -> Path:
        p2 = json.loads(json.dumps(project))
        mutate(p2)
        path = tmp / f"case_{tag}.json"
        path.write_text(json.dumps(p2, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def dup_id(p2):
        p2["episodes"][0]["shots"][1]["id"] = "E01-S01"

    def beat_long(p2):
        for s in p2["episodes"][0]["shots"]:
            if s["beat"] == "摔协议":
                s["duration_sec"] = 16

    def no_duration(p2):
        p2["episodes"][0]["shots"][0].pop("duration_sec")

    def bad_no(p2):
        p2["episodes"][0]["shots"][2]["shot_no"] = 9

    def no_en(p2):
        p2["episodes"][0]["shots"][0].pop("action_en")

    def zero_time(p2):
        for e in p2["episodes"]:
            e["duration_sec"] = 0
            for s in e["shots"]:
                s["duration_sec"] = 0

    def dup_cross(p2):
        p2["episodes"][1]["shots"][0]["id"] = "E01-S01"

    def bad_duration(p2):
        p2["episodes"][0]["shots"][0]["duration_sec"] = "abc"

    def zero_target(p2):
        p2["config"]["episode_duration_sec"] = 0

    def dev_over(p2):
        # 镜头总时长 ~10s，目标拉回 90s → 偏差 >20% 必须报 ERROR
        p2["episodes"][0]["duration_sec"] = 90

    # 以下三例应为 ERROR（退出码非 0）
    r = run([SCRIPTS / "validate_project.py", variant("dup", dup_id)],
            expect_fail=True, label="重复镜号")
    check("重复镜号 → ERROR", "镜头 id 重复" in r.stdout, r.stdout)

    r = run([SCRIPTS / "validate_project.py", variant("beat", beat_long)],
            expect_fail=True, label="beat 超 30s")
    check("beat>30s → ERROR", "> 30s" in r.stdout, r.stdout)

    r = run([SCRIPTS / "validate_project.py", variant("nodur", no_duration)],
            expect_fail=True, label="缺 duration")
    check("缺 duration → ERROR", "缺少 duration_sec" in r.stdout, r.stdout)

    r = run([SCRIPTS / "validate_project.py", variant("badno", bad_no)],
            label="shot_no 不连续")
    check("shot_no 不连续 → WARN", "序号不连续" in r.stdout, r.stdout)

    r = run([SCRIPTS / "validate_project.py", variant("noen", no_en)],
            label="缺 action_en")
    check("缺 action_en → WARN", "缺 action_en" in r.stdout, r.stdout)

    # 时长全 0：validate 会报错，但 build 不得崩溃（曾发生除零崩溃）
    zero_path = variant("zero", zero_time)
    run([SCRIPTS / "validate_project.py", zero_path], expect_fail=True,
        label="时长全 0 → validate 失败（预期）")
    r = run([SCRIPTS / "build_prompts.py", zero_path, "--type", "all"],
            label="时长全 0 → build 不崩溃")
    check("零时长 build 不崩溃", "Traceback" not in r.stderr, r.stderr)

    # 跨集重复镜号 / 非数字时长 / 零目标时长：必须报错且不崩溃
    r = run([SCRIPTS / "validate_project.py", variant("cross", dup_cross)],
            expect_fail=True, label="跨集重复镜号")
    check("跨集镜号 → ERROR", "跨集重复" in r.stdout, r.stdout)

    r = run([SCRIPTS / "validate_project.py", variant("baddur", bad_duration)],
            expect_fail=True, label="非数字时长")
    check("非数字时长 → ERROR", "非数字" in r.stdout, r.stdout)
    check("非数字时长不崩溃", "Traceback" not in r.stderr, r.stderr)

    r = run([SCRIPTS / "validate_project.py", variant("ztarget", zero_target)],
            expect_fail=True, label="零目标时长")
    check("零目标时长 → ERROR", "必须为正数" in r.stdout, r.stdout)
    check("零目标时长不崩溃", "Traceback" not in r.stderr, r.stderr)

    r = run([SCRIPTS / "validate_project.py", variant("devover", dev_over)],
            expect_fail=True, label="时长偏差 >20%")
    check("时长偏差 >20% → ERROR", "偏差" in r.stdout and "[ERROR]" in r.stdout, r.stdout)

    def placeholder_ep(p2):
        p2["episodes"][0]["cliffhanger"] = "（本集完）"
        p2["episodes"][0]["shots"][1]["action"] = "待补充画面动作"

    r = run([SCRIPTS / "validate_project.py", variant("ph", placeholder_ep)],
            label="占位文本")
    check("占位文本 → WARN", "疑似占位文本" in r.stdout, r.stdout)
    check("占位文本不崩溃", "Traceback" not in r.stderr, r.stderr)

    def review_hit(p2):
        p2["meta"]["review_whitelist"] = []
        p2["episodes"][0]["shots"][1]["action"] = "操场上升国旗"

    r = run([SCRIPTS / "validate_project.py", variant("rvhit", review_hit)],
            expect_fail=True, label="卡审子串误伤")
    check("卡审命中（无豁免）", "命中卡审" in r.stdout, r.stdout)

    def review_wl(p2):
        review_hit(p2)
        p2["meta"]["review_whitelist"] = ["升国旗"]

    r = run([SCRIPTS / "validate_project.py", variant("rvwl", review_wl)],
            label="卡审豁免")
    check("卡审豁免生效", "命中卡审" not in r.stdout and "[ERROR]" not in r.stdout,
          r.stdout)

    # ---------- D. 分片布局互转 ----------
    r = run([SCRIPTS / "split_project.py", proj_dir], label="split")
    check("拆分生成 episodes/E01.json", (proj_dir / "episodes" / "E01.json").is_file())
    check("拆分生成 episodes/E02.json", (proj_dir / "episodes" / "E02.json").is_file())
    if (proj_dir / "episodes" / "E01.json").is_file():
        e1 = json.loads((proj_dir / "episodes" / "E01.json").read_text(encoding="utf-8"))
        check("分片内容完整", e1.get("id") == "E01" and len(e1.get("shots") or []) == 3,
              str(e1.get("id")))
    check("拆分后 project.json 无 episodes",
          "episodes" not in json.loads(proj_path.read_text(encoding="utf-8")))

    r = run([SCRIPTS / "validate_project.py", proj_dir], label="validate(分片)")
    check("分片 validate 无 ERROR", "[ERROR]" not in r.stdout, r.stdout)
    r = run([SCRIPTS / "build_prompts.py", proj_dir, "--type", "table"],
            label="build table(分片)")
    check("分片 build 不崩溃", "Traceback" not in r.stderr, r.stderr)
    check("分片 build 回写分集文件",
          (proj_dir / "episodes" / "E01.json").is_file())
    r = run([SCRIPTS / "preview.py", proj_dir], label="preview(分片)")
    check("分片 preview 不崩溃", "Traceback" not in r.stderr, r.stderr)
    r = run([SCRIPTS / "assemble.py", proj_dir, "--all", "--dry-run"],
            label="assemble(分片)")
    check("分片 assemble dry-run", "$ ffmpeg" in r.stdout)

    r = run([SCRIPTS / "split_project.py", proj_dir, "--merge"], label="merge")
    merged = json.loads(proj_path.read_text(encoding="utf-8"))
    check("合并恢复 episodes",
          [e.get("id") for e in merged.get("episodes") or []] == ["E01", "E02"],
          str([e.get("id") for e in merged.get("episodes") or []]))
    check("合并后 episodes 目录已删除", not (proj_dir / "episodes").exists())
    r = run([SCRIPTS / "validate_project.py", proj_dir], label="validate(合并后)")
    check("合并后 validate 无 ERROR", "[ERROR]" not in r.stdout, r.stdout)

    # ---------- E. 文生视频+参考图模式（meta.video_workflow = t2v-ref） ----------
    project = json.loads(proj_path.read_text(encoding="utf-8"))
    project["meta"]["video_workflow"] = "t2v-ref"
    for e in project["episodes"]:
        for s in e["shots"]:
            s.pop("video_prompt", None)
    proj_path.write_text(json.dumps(project, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    r = run([SCRIPTS / "build_prompts.py", proj_dir, "--type", "video"],
            label="t2v build")
    check("t2v build 不崩溃", "Traceback" not in r.stderr, r.stderr)
    project = json.loads(proj_path.read_text(encoding="utf-8"))
    vid = project["episodes"][0]["shots"][0]["video_prompt"]
    check("t2v 含主体+服装静态层", "beige trench coat" in vid, vid)
    check("t2v 保留运动描述", "the papers hit the table" in vid, vid)
    check("t2v 保留纪律 token", "single continuous take" in vid, vid)
    check("t2v 不含静帧词", "cinematic still" not in vid and "cinematic footage" in vid, vid)

    # ---------- F. 中文模式（meta.prompt_lang = zh，默认，剧梦工作流） ----------
    project["meta"]["prompt_lang"] = "zh"
    s1zh = project["episodes"][0]["shots"][0]
    s1zh["expression"] = "眼眶泛红，嘴角带笑"
    s1zh["sfx"] = "纸张拍桌"
    s1zh["vfx"] = "无"
    for e in project["episodes"]:
        for s in e["shots"]:
            s.pop("image_prompt", None)
            s.pop("video_prompt", None)
    proj_path.write_text(json.dumps(project, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    run([SCRIPTS / "build_prompts.py", proj_dir, "--type", "image"],
        label="zh build image")
    run([SCRIPTS / "build_prompts.py", proj_dir, "--type", "video"],
        label="zh build video")
    project = json.loads(proj_path.read_text(encoding="utf-8"))
    img_zh = project["episodes"][0]["shots"][0]["image_prompt"]
    vid_zh = project["episodes"][0]["shots"][0]["video_prompt"]
    check("zh 图片含中文景别+镜头参数", "中景" in img_zh and "mm 镜头" in img_zh, img_zh)
    check("zh 图片含中文风格后缀", "写实电影剧照" in img_zh, img_zh)
    check("zh 视频纪律 token", "单镜头连续拍摄" in vid_zh, vid_zh)
    check("zh t2v 静态层含服装", "beige trench coat" in vid_zh, vid_zh)
    check("zh 视频台词段", "：「签了，你净身出户。」" in vid_zh, vid_zh)
    check("zh 视频表情段", "表情：眼眶泛红，嘴角带笑" in vid_zh, vid_zh)
    check("zh 视频音效段", "音效：纸张拍桌" in vid_zh, vid_zh)
    check("zh 视频 BGM 段", "BGM：" in vid_zh, vid_zh)
    check("zh 视频无值段跳过", "特效：" not in vid_zh, vid_zh)
    img_doc = (proj_dir / "04_prompts" / "image_prompts.md").read_text(encoding="utf-8")
    check("zh 定妆照中文模板", "无面部细节" in img_doc and "三视图" in img_doc,
          img_doc[:200])
    check("zh 负面词为中文", "低画质" in img_doc, img_doc[:200])

    _finish(tmp, args.keep)


def _finish(tmp: Path, keep: bool) -> None:
    if FAILURES:
        print(f"\n自检失败 {len(FAILURES)} 项:")
        for f in FAILURES:
            print("  -", f)
        print(f"\n临时目录: {tmp}")
        raise SystemExit(1)
    print("自检通过：2 集正常链路（init --assets → validate → build --strict-en → "
          "preview → assemble）+ 剧本导入（表格/剧本/小说/Word）+ 13 项异常用例 "
          "+ 分片布局互转（split → validate/build/preview/assemble → merge）")
    if keep:
        print(f"临时目录保留: {tmp}")
    else:
        shutil.rmtree(tmp, ignore_errors=True)
    raise SystemExit(0)


if __name__ == "__main__":
    main()
