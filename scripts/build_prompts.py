#!/usr/bin/env python3
"""从 project.json 批量生成图片 / 视频 / 配音 / 导演版提示词。

用法:
    python build_prompts.py [project.json 或目录]
                            [--type image|video|audio|director|assets|table|all]
                            [--force] [--strict-en] [--out DIR]

规则见 references/prompt_recipes.md：
  * 英文为主，中文版用于人工审阅
  * 角色锚点与场景锚点全剧逐字一致
  * 视频提示词只写运动，不重复静态描述（避免改脸）
  * 负面提示词由本脚本按风格 + 卡审规则库（review_rules.json）自动拼装，
    画面/视频禁用元素自动注入负面词
  * 提示词文本按卡审规则扫描：forbidden 级必须改写（退出码 1），
    avoid 级提醒确保该集结尾回正（人读版见 references/review_rules.md）
  * --type director 旧版输出中文素材层分镜（大分镜/小分镜 + 资产槽）；
    最终导演分镜请按 references/director_storyboard_format.md 的 4-15s / 3+N 格式整理
  * --type assets 输出一镜一资产清单（asset_manifest.md/csv）：每镜一条
    资产记录（人物/音色/场景/道具），参考文件列留空待逐条填写
  * --type table 输出 03_storyboard/<集号>.md 分镜表（project.json 的人工编辑视图）
  * 图片/文生视频提示词自动附带画幅 token（meta.aspect_ratio / 平台推导，
    竖屏短剧 = 竖屏 9:16 画幅）；生成工具里也要选同比例，双保险
  * image_prompts.md 顶部输出人物形象参考（定妆照）与场景参考
    （场景定妆照：无人物空场景母版），先确认再批量
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _common as C

SHOT_SIZE_EN = {
    "大远景": "extreme wide shot",
    "远景": "wide shot",
    "全景": "full shot",
    "中全": "medium full shot",
    "中景": "medium shot",
    "近景": "medium close-up",
    "中近景": "medium close-up",
    "半身": "medium shot",
    "全身": "full shot",
    "特写": "close-up",
    "大特写": "extreme close-up",
    "脸部特写": "close-up",
    "过肩": "over-the-shoulder shot",
    "主观视角": "POV shot",
}

CAMERA_EN = {
    "固定": "static camera",
    "固定机位": "static camera",
    "推": "slow push-in",
    "推镜": "slow push-in",
    "拉": "slow pull-back",
    "拉镜": "slow pull-back",
    "摇": "slow pan",
    "摇镜": "slow pan",
    "移": "lateral tracking shot",
    "移镜": "lateral tracking shot",
    "跟": "tracking shot",
    "跟镜": "tracking shot",
    "升": "crane up",
    "降": "crane down",
    "升降": "crane",
    "手持": "handheld camera",
    "环绕": "orbit around the subject",
    "环绕镜头": "orbit around the subject",
    "甩镜": "whip pan",
    "长镜": "long take",
    "斯坦尼康": "steadicam",
    "急推": "fast push-in",
    "急拉": "fast pull-back",
    "变焦推": "zoom in",
    "变焦拉": "zoom out",
    "旋转": "rotate around the subject",
    "升格": "slow motion",
    "延时": "timelapse",
}

COMPOSITION_EN = {
    "三分法": "rule of thirds",
    "三分": "rule of thirds",
    "中心构图": "centered",
    "中心": "centered",
    "中心对称": "symmetrical",
    "对称": "symmetrical",
    "对称压迫": "symmetrical oppressive",
    "框架构图": "frame within frame",
    "框架": "frame within frame",
    "对角线": "diagonal",
    "前景遮挡": "foreground occlusion",
    "负空间": "negative space",
    "大面积留白": "negative space",
    "留白": "negative space",
    "封闭构图": "closed composition",
    "镜像反射": "mirror reflection",
    "过肩": "over-the-shoulder",
    "低角度仰拍": "low angle",
    "仰拍": "low angle",
    "高角度俯拍": "high angle",
    "俯拍": "high angle",
}

TRANSITION_EN = {
    "硬切": "", "无": "", "切": "",
    "叠化": "dissolve", "闪白": "white flash", "跳切": "jump cut",
    "黑屏": "fade to black", "遮挡转场": "wipe", "划像": "wipe",
    "甩镜转场": "whip pan", "匹配剪辑": "match cut",
}

# 景别 → 镜头/景深参数：给图片模型专业摄影信息（焦段决定透视与虚化）
LENS_EN = {
    "extreme wide shot": "wide-angle lens, deep depth of field",
    "wide shot": "wide-angle lens, deep depth of field",
    "full shot": "35mm lens, natural perspective",
    "medium full shot": "35mm lens, natural perspective",
    "medium shot": "50mm lens, natural perspective",
    "medium close-up": "85mm lens, shallow depth of field",
    "close-up": "85mm portrait lens, shallow depth of field",
    "extreme close-up": "100mm macro lens, razor-thin depth of field",
    "over-the-shoulder shot": "50mm lens, natural perspective",
    "POV shot": "",
}

# 常见中文光型 → 专业英文光效术语；映射不到的仍按 CJK 丢弃（由风格
# 后缀的英文光型 token 兜底），映射到的直接进提示词，光感更准
LIGHT_EN = {
    "自然光": "natural light",
    "日光": "daylight",
    "黄金时刻": "golden hour light",
    "黄昏光": "golden hour light",
    "正午顶光": "harsh midday top light",
    "逆光": "backlit, rim light",
    "侧逆光": "backlit, rim light",
    "侧光": "side lighting",
    "轮廓光": "rim light",
    "三点布光": "three-point lighting",
    "伦勃朗光": "Rembrandt lighting",
    "蝴蝶光": "butterfly lighting",
    "底光": "underlighting",
    "顶光": "top-down lighting",
    "低调光": "low-key lighting",
    "高调光": "high-key lighting",
    "冷色调": "cool color tones",
    "暖色调": "warm color tones",
    "霓虹光": "neon glow",
    "雨夜霓虹": "rainy night neon reflections",
    "月光": "moonlight",
    "烛光": "candlelight",
    "台灯光": "practical lamp light",
    "路灯光": "street lamp light",
    "阴天柔光": "overcast soft light",
    "柔光": "soft diffused light",
    "硬光": "hard light, sharp shadows",
    "体积光": "volumetric light",
    "丁达尔光": "volumetric light, god rays",
    "剪影": "silhouette lighting",
    "电影感布光": "cinematic lighting",
    "警灯红蓝": "flashing red and blue lights",
}

QUALITY_EN = ("cinematic still, professional color grading, subtle film grain, "
              "high production value, sharp focus, ultra-detailed")

VIDEO_DISCIPLINE_EN = "single continuous take, no cuts"

# 中文模式（meta.prompt_lang = "zh"，默认）：镜头/景深参数按景别映射；
# 中文画质/纪律 token（风格后缀 prompt_suffix_zh 已含画质词，无需另加）
LENS_ZH = {
    "extreme wide shot": "广角镜头，深景深",
    "wide shot": "广角镜头，深景深",
    "full shot": "35mm 镜头，自然透视",
    "medium full shot": "35mm 镜头，自然透视",
    "medium shot": "50mm 镜头，自然透视",
    "medium close-up": "85mm 镜头，浅景深",
    "close-up": "85mm 人像镜头，浅景深",
    "extreme close-up": "100mm 微距镜头，极浅景深",
    "over-the-shoulder shot": "50mm 镜头，自然透视",
    "POV shot": "",
}
VIDEO_DISCIPLINE_ZH = "单镜头连续拍摄，无剪辑切换"

# 画面文字类生产标记：字幕不得进入生成提示词（硬规则：画面里不生成文字，文字全部后期加）
SCREEN_TEXT_RE = re.compile(r"【\s*字幕[^】]*】")
# 场记行场景 desc（如「1-1 山林-古树下 外 日」）：去掉场次编号前缀，降低提示词噪声
SCENE_SLUG_RE = re.compile(r"^\s*\d+\s*[-－]\s*\d+\s+")


def strip_screen_text(text: str) -> str:
    """移除会诱导模型在画面里写字的字幕标记（字幕一律后期另加）。"""
    return SCREEN_TEXT_RE.sub("", text or "").strip()


def clean_scene_desc(desc: str) -> str:
    """场景 desc 若是场记行（含「N-N」场次号），去掉编号前缀；其余原样返回。"""
    d = (desc or "").strip()
    if SCENE_SLUG_RE.match(d):
        return SCENE_SLUG_RE.sub("", d).strip() or d
    return d


def prompt_lang(project: dict) -> str:
    """提示词语言："zh"（中文为主，默认，剧梦等国内模型）或 "en"（英文）。"""
    return "zh" if str((project.get("meta") or {}).get("prompt_lang") or "zh").strip().lower() \
        .startswith("zh") else "en"


def aspect_ratio_of(project: dict) -> str:
    """画幅比例：meta.aspect_ratio，缺省回落平台预设，再缺省 9:16。"""
    meta = project.get("meta") or {}
    ratio = str(meta.get("aspect_ratio") or "").strip()
    if not ratio:
        try:
            ratio = str(C.platform(meta.get("platform") or "").get("aspect_ratio") or "")
        except SystemExit:
            ratio = ""
    return ratio if ":" in ratio else "9:16"


def framing_token(project: dict, zh: bool) -> str:
    """画幅 token：图片与文生视频提示词的固定 slot。

    成片是竖屏而首帧是横图时，裁切会毁掉构图与安全区；token 与生成
    工具里的画幅选择双保险（工具支持选比例时两者都要设）。
    """
    ratio = aspect_ratio_of(project)
    try:
        w, h = (float(x) for x in ratio.replace("：", ":").split(":", 2)[:2])
    except ValueError:
        w, h = 9.0, 16.0
    if w < h:
        return f"竖屏 {ratio} 画幅" if zh else f"vertical {ratio} portrait framing"
    if w > h:
        return f"横屏 {ratio} 画幅" if zh else f"horizontal {ratio} wide framing"
    return f"正方形 {ratio} 画幅" if zh else f"square {ratio} framing"


def cell(value) -> str:
    """Markdown 表格单元格转义：竖线不破坏表格，换行转 <br>。"""
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", "<br>")


def seconds_phrase(value) -> str:
    """3 → "3 seconds"，0.5 → "0.5 seconds"，1 → "1 second"。"""
    v = C.as_float(value)
    return f"{C.fmt_sec(v)} second" + ("" if abs(v - 1) < 1e-6 else "s")


def join_parts(parts: list[str]) -> str:
    """拼接提示词片段：去空白、去重（避免风格后缀与画质后缀重复）。"""
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        p = p.strip(" ,")
        if not p or p.lower() in seen:
            continue
        seen.add(p.lower())
        out.append(p)
    return ", ".join(out)


def pick(shot: dict, field: str) -> str:
    """优先取英文变体（field_en），否则回落中文原值。"""
    return (shot.get(f"{field}_en") or shot.get(field) or "").strip()


def stage_of(shot: dict, cid: str) -> str | None:
    """读取镜头的年龄段映射；非法类型按未指定处理。"""
    mapping = shot.get("character_stages")
    return mapping.get(cid) if isinstance(mapping, dict) else None


def resolve_char_anchor(ch: dict, stage_id: str | None) -> str:
    """角色锚点：指定年龄段（stages）则用该段锚点，否则用全剧主锚点。"""
    if stage_id:
        for stg in ch.get("stages") or []:
            if stg.get("id") == stage_id and stg.get("image_prompt"):
                return stg["image_prompt"].strip()
    return (ch.get("image_prompt") or ch.get("appearance") or "").strip()


def char_scene_parts(project: dict, shot: dict, chars: dict, scenes: dict,
                     zh: bool) -> list[str]:
    """静态视觉层（无光线/动作）：角色锚点(含服装/年龄段) + 场景锚点 + 景别 + 镜头参数 + 构图。

    图片提示词与文生视频提示词共用，保证两条链路的主体/场景描述逐字同源。
    zh=True 时场景优先用中文 desc、镜头/构图用中文术语；锚点原文照用
    （中文模式下锚点本身应以中文撰写）。
    """
    stage_map = shot.get("character_stages")
    if not isinstance(stage_map, dict):
        stage_map = {}
    char_ids = shot.get("characters") or []
    # 服装映射：shots[].outfits: {"LIN": "B"} 优先；旧字段 shots[].outfit 仅单角色时生效
    outfit_map = shot.get("outfits") if isinstance(shot.get("outfits"), dict) else {}
    legacy_outfit = shot.get("outfit") if len(char_ids) == 1 else ""

    parts: list[str] = []
    for cid in char_ids:
        ch = chars.get(cid)
        if not ch:
            continue
        seg = resolve_char_anchor(ch, stage_map.get(cid))
        outfit_id = outfit_map.get(cid) or legacy_outfit
        if outfit_id:
            for of in ch.get("outfits", []):
                desc = (of.get("desc") or "").strip()
                if of.get("id") == outfit_id and desc:
                    seg = (f"{seg}, wearing {desc}" if not zh
                           else f"{seg}，穿着{desc}")
        parts.append(seg)

    scene = scenes.get(shot.get("scene_id"))
    if scene:
        desc = clean_scene_desc(scene.get("desc") or "")
        if zh:
            parts.append(desc or scene.get("anchor_en") or "")
        else:
            parts.append(scene.get("anchor_en") or desc or "")
    if shot.get("shot_size"):
        size_en = SHOT_SIZE_EN.get(shot["shot_size"], shot["shot_size"])
        if zh:
            parts.append(shot["shot_size"])
            lens = LENS_ZH.get(size_en)
        else:
            parts.append(size_en)
            lens = LENS_EN.get(size_en)
        if lens:
            parts.append(lens)
    if shot.get("composition"):
        raw = shot["composition"]
        if zh:
            parts.append(raw if raw.endswith("构图") else f"{raw}构图")
        else:
            comp = COMPOSITION_EN.get(raw, raw)
            parts.append(f"{comp} composition")
    parts.append(framing_token(project, zh))
    return parts


def resolve_light(shot: dict, scene: dict | None, st: dict, zh: bool) -> str:
    """光型回退链：镜头 → 场景 → 风格。

    zh=True 直接用中文光型原文（剧梦理解中文光效术语，无需翻译）；
    zh=False 先经 LIGHT_EN 专业英译，映射不到才丢弃（由风格后缀兜底）。
    """
    if zh:
        return ((shot.get("lighting") or (scene or {}).get("lighting")
                 or st.get("lighting") or "")).strip()
    light = (shot.get("lighting_en") or (scene or {}).get("lighting_en")
             or shot.get("lighting") or (scene or {}).get("lighting")
             or st.get("lighting") or "")
    light = LIGHT_EN.get(light, light)
    return "" if C.has_cjk(light) else light


def build_image_prompt(project: dict, shot: dict, chars: dict, scenes: dict) -> str:
    """图片提示词。字段顺序全剧固定（统一格式，不得改写）：

    角色锚点(含服装/年龄段) → 场景锚点 → 景别 → 镜头/景深 → 构图 → 画幅 → 动作 → 光线 → 风格后缀 → 画质后缀

    zh 模式（默认）：锚点/动作/光型用中文原值，风格后缀取 prompt_suffix_zh
    （自带画质词）；en 模式额外追加 QUALITY_EN。中英混排在 en 模式由
    --strict-en 拦截（zh 模式允许中英混排，如 85mm/50mm 镜头参数）。
    画幅 token 由 meta.aspect_ratio / 平台自动推导，禁止手改。
    """
    st = C.style(project["meta"]["style"])
    zh = prompt_lang(project) == "zh"
    parts = char_scene_parts(project, shot, chars, scenes, zh)
    if zh:
        parts.append(strip_screen_text(shot.get("action") or shot.get("action_en") or ""))
    else:
        parts.append(strip_screen_text(pick(shot, "action")))
    parts.append(resolve_light(shot, scenes.get(shot.get("scene_id")), st, zh))
    parts.append(st["prompt_suffix_zh" if zh else "prompt_suffix_en"])
    if not zh:
        parts.append(QUALITY_EN)
    return join_parts(parts)


def is_t2v(project: dict) -> bool:
    """视频工作流：meta.video_workflow = "t2v-ref"（文生视频+参考图），
    缺省 "i2v"（图生视频/首帧驱动）。"""
    return str((project.get("meta") or {}).get("video_workflow") or "i2v").strip().lower() \
        in ("t2v", "t2v-ref", "t2v_ref", "t2vref")


def build_video_prompt(project: dict, shot: dict, chars: dict, scenes: dict,
                       bgm_cue: str = "", force: bool = False) -> str:
    """视频提示词。字段顺序全剧固定，按工作流二选一：

    i2v（图生视频，缺省）：运镜 → 纪律 → 动作 → 转场 → 风格后缀 → 时长。
        只描述运动，不重复静态描述（首帧已带，重复会触发改脸）。
    t2v-ref（文生视频+参考图）：主体(锚点+服装) → 场景 → 景别/镜头 → 构图 →
        光线 → 运镜 → 纪律 → 动作 → 转场 → 风格后缀 → 时长。
        无首帧，静态描述必须并入；参考图只负责"人是谁"。
    zh 模式在动作后追加剧梦全要素标签段（缺省字段自动跳过）：
        站位 → 表情 → 台词(含角色名与情绪) → 音效 → BGM(每集提示词首句) → 特效
    纪律 token 防止中途切镜头形象漂移。force=True 时忽略已存的手工覆盖。
    """
    st = C.style(project["meta"]["style"])
    zh = prompt_lang(project) == "zh"
    if not force and (shot.get("video_prompt") or "").strip():
        return shot["video_prompt"].strip()

    parts: list[str] = []
    if is_t2v(project):
        parts.extend(char_scene_parts(project, shot, chars, scenes, zh))
        light = resolve_light(shot, scenes.get(shot.get("scene_id")), st, zh)
        if light:
            parts.append(light)
    if shot.get("camera"):
        # zh 模式运镜直接用中文原值（剧梦理解中文运镜术语），en 模式走词表
        parts.append(shot["camera"] if zh
                     else CAMERA_EN.get(shot["camera"], shot["camera"]))
    parts.append(VIDEO_DISCIPLINE_ZH if zh else VIDEO_DISCIPLINE_EN)
    # 视频动作：zh 用中文原值，en 优先 video_action_en；否则回落 action
    if zh:
        action = ((shot.get("video_action") or "").strip()
                  or (shot.get("action") or "").strip())
    else:
        action = (shot.get("video_action_en") or "").strip() or pick(shot, "action")
    action = strip_screen_text(action)

    if zh:
        # 剧梦全要素段：站位 → 动作 → 表情 → 台词 → 音效 → BGM → 特效
        if (shot.get("blocking") or "").strip():
            parts.append(shot["blocking"].strip())
        if action:
            parts.append(action)
        if (shot.get("expression") or "").strip():
            parts.append(f"表情：{shot['expression'].strip()}")
        dlg = shot.get("dialogue") or {}
        dtext = (dlg.get("text") or "").strip()
        if dtext:
            spk_ch = chars.get((dlg.get("character") or ""))
            speaker = ((spk_ch or {}).get("name") or dlg.get("character") or "").strip()
            emo = (dlg.get("emotion") or "").strip()
            head = f"{speaker}说" if speaker else "台词"
            parts.append(f"{head}：「{dtext}」" + (f"（{emo}）" if emo else ""))
        if (shot.get("sfx") or "").strip() not in ("", "无"):
            parts.append(f"音效：{shot['sfx'].strip()}")
        if bgm_cue:
            parts.append(f"BGM：{bgm_cue}")
        if (shot.get("vfx") or "").strip() not in ("", "无"):
            parts.append(f"特效：{shot['vfx'].strip()}")
    elif action:
        parts.append(action)

    raw_trans = (shot.get("transition_in") or "").strip()
    if zh:
        if raw_trans and raw_trans not in ("无", "切"):
            parts.append(f"结尾{raw_trans}")
    else:
        trans = TRANSITION_EN.get(raw_trans, raw_trans)
        if trans:
            parts.append(f"{trans} at the end")
    suffix = st["prompt_suffix_zh" if zh else "prompt_suffix_en"]
    # 静帧词净化（仅 en）：风格后缀里的 "cinematic still" 是图片用语，视频中改为 footage
    if not zh:
        suffix = re.sub(r"\bstill\b", "footage", suffix)
    parts.append(suffix)
    dur = C.as_float(shot.get("duration_sec"))
    if dur > 0:
        if zh:
            parts.append(f"{dur:g} 秒")
        else:
            parts.append(seconds_phrase(dur))
    return join_parts(parts)


def build_audio_prompt(shot: dict, chars: dict) -> str:
    dlg = shot.get("dialogue") or {}
    narr = shot.get("narration") or ""
    cid = dlg.get("character")
    voice = (chars.get(cid) or {}).get("voice") or {}

    bits: list[str] = []
    if voice.get("timbre"):
        bits.append(f"音色:{voice['timbre']}")
    if voice.get("speed"):
        bits.append(f"语速:{voice['speed']}")
    if voice.get("emotion"):
        bits.append(f"情绪:{voice['emotion']}")
    if dlg.get("text"):
        bits.append(f"对白[{cid or ''}]: {dlg['text']}")
    if narr:
        bits.append(f"旁白: {narr}")
    if shot.get("sfx"):
        bits.append(f"音效: {shot['sfx']}")
    return "；".join(bits) if bits else "（无语音，仅环境声）"


def build_bgm_prompt(project: dict, ep: dict) -> str:
    """每集一条 BGM 提示词（剧梦等音乐模型直接可用，中文）。

    优先 episodes[].bgm_prompt 手工定制；缺省按题材情绪曲线 + 风格
    自动拼装：质感 + 情绪走向 + 节奏 + 时长 + 编排约束。
    """
    if (ep.get("bgm_prompt") or "").strip():
        return ep["bgm_prompt"].strip()
    meta = project.get("meta") or {}
    try:
        g = C.genre(meta.get("genre") or "")
    except SystemExit:
        g = {}
    st = C.style(meta.get("style") or "")
    total = sum(C.as_float(s.get("duration_sec")) for s in C.shots_of(ep))
    pacing = {"fast": "快节奏，鼓点推进，强切点",
              "medium": "中速，张弛交替",
              "slow": "慢板，情绪铺陈"}.get(g.get("pacing") or "", "中速，张弛交替")
    parts = [
        f"短剧配乐，{st.get('name') or meta.get('style') or ''}质感",
        f"情绪走向：{g['emotion_curve']}" if g.get("emotion_curve") else "",
        pacing,
        f"时长约 {C.fmt_sec(total)} 秒" if total else "",
        "纯音乐无人声；反转前 1 秒完成情绪切换；结尾留 0.5-1 秒静音供卡点",
    ]
    return "；".join(p for p in parts if p)


def character_sheet_prompt(project: dict, ch: dict) -> str:
    """人物形象参考图（定妆照）提示词：左半边大头照，右半边三视图（无脸）。

    三视图无脸的原因：小尺寸人脸上的五官必然崩坏，且会与左侧大头照的
    脸冲突；身份信息由大头照承担，三视图只负责体型 / 服装 / 比例。
    锚点缺失时返回空串；en 模式下锚点含中文（未按硬规则英译）也跳过。
    """
    zh = prompt_lang(project) == "zh"
    anchor = (ch.get("image_prompt") or ch.get("appearance") or "").strip()
    if not anchor or (not zh and C.has_cjk(anchor)):
        return ""
    st = C.style(project["meta"]["style"])
    outfit = ""
    for of in ch.get("outfits") or []:
        d = (of.get("desc") or "").strip()
        if d:
            outfit = d
            break
    if zh:
        turnaround = ("右侧为同一角色全身三视图模型稿，正面、侧面、背面三个视图并排站立"
                      + (f"，穿着{outfit}" if outfit else ""))
        parts = [
            "人物角色参考图，浅灰色摄影棚纯色背景，左右分栏构图",
            f"左侧为{anchor}的大头照特写，表情平静，柔光均匀",
            turnaround,
            "三视图人物均不画五官、无面部细节，从头到脚完整可见，双臂微离身体，各视图比例一致",
            st["prompt_suffix_zh"],
        ]
    else:
        turnaround = ("right panel: full-body turnaround model sheet of the same character, "
                      "three views standing side by side (front view, side view, back view)")
        if outfit:
            turnaround += f", wearing {outfit}"
        parts = [
            "character reference sheet on plain light gray studio background, split layout",
            f"left panel: large headshot portrait of {anchor}, neutral expression, even soft lighting",
            turnaround,
            "all turnaround figures are faceless with no facial features, head-to-toe visible, "
            "arms slightly away from body, consistent proportions across views",
            st["prompt_suffix_en"],
            QUALITY_EN,
        ]
    return join_parts(parts)


def scene_sheet_prompt(project: dict, sc: dict) -> str:
    """场景参考图（场景定妆照）提示词：无人物的空场景母版，画幅随平台。

    场景一致性是仅次于换脸的返工源头：每个场景先出这张定妆照并人工
    确认空间/陈设/光型/时段，再批量生成该场景的镜头图；也可直接当
    空镜首帧或作垫图/参考图。光型走 场景 → 风格 回退（场景层，见
    shot_language.md 第四节）。锚点缺失或 en 模式锚点含中文时跳过。
    """
    zh = prompt_lang(project) == "zh"
    if zh:
        anchor = (sc.get("desc") or sc.get("anchor_en") or "").strip()
    else:
        anchor = (sc.get("anchor_en") or "").strip()
    if not anchor or (not zh and C.has_cjk(anchor)):
        return ""
    st = C.style(project["meta"]["style"])
    if zh:
        light = (sc.get("lighting") or st.get("lighting") or "").strip()
        parts = [
            f"空场景参考图，{anchor}",
            "画面中无人物",
            light,
            framing_token(project, True),
            st["prompt_suffix_zh"],
        ]
    else:
        light = (sc.get("lighting_en") or sc.get("lighting") or "").strip()
        light = LIGHT_EN.get(light, light)
        if C.has_cjk(light):
            light = ""
        parts = [
            f"empty scene reference plate, {anchor}",
            "no people in frame",
            light,
            framing_token(project, False),
            st["prompt_suffix_en"],
            QUALITY_EN,
        ]
    return join_parts(parts)


def director_md(project: dict) -> str:
    """生成中文导演版分镜提示词（大分镜/小分镜 + 资产槽 + 台词字段）。

    大分镜 = 同一 beat 的连续镜头组成的一个剧情段（≤30s）；
    小分镜 = 单机位单景别镜头（1-5s）。
    资产槽全部留空，由使用者自行填入人物图 / 音色 / 场景图 / 道具图。
    """
    chars = C.characters_by_id(project)
    scenes = C.scenes_by_id(project)
    st = C.style(project["meta"]["style"])
    style_lighting = st.get("lighting", "")
    rate = C.cjk_chars_per_sec()

    def cjk_len(text: str) -> int:
        return sum(1 for ch in text or "" if "\u4e00" <= ch <= "\u9fff")

    def slot_letter(i: int) -> str:
        return chr(ord("A") + i)

    lines: list[str] = [
        f"# 导演版分镜提示词（{project['meta'].get('title', '')}）",
        "",
        f"项目: {project['meta'].get('title', '')} | "
        f"风格: {project['meta'].get('style', '')} | "
        f"平台: {project['meta'].get('platform', '')}",
        "",
        "格式约定：大分镜 = 一个连续剧情段（≤30 秒）；小分镜 = 单机位单景别镜头（1-5 秒）。",
        "资产槽等号后全部留空，请自行填入人物图 / 音色 / 场景图 / 道具图。",
        "",
    ]

    for ep in C.episodes_of(project):
        eid = ep.get("id", "?")
        shots = C.shots_of(ep)
        if not shots:
            continue
        ep_total = sum(C.as_float(s.get("duration_sec")) for s in shots)
        # beat 分组：与 asset_manifest / validate 共用 _common.group_by_beat
        groups = C.group_by_beat(shots)

        target = ep.get("duration_sec") or ep_total
        showcases = [s["showcase"] for s in shots if s.get("showcase")]
        lines.append(f"## {eid}｜{ep.get('title') or ''}｜目标时长：{target:.0f}s")
        lines.append("")
        dev = abs(ep_total - target) / target if target else 0.0
        lines.append(
            f"- 总时长：{ep_total:.0f}s（偏差 {dev:.0%}）"
            f"｜大分镜 {len(groups)} 个｜小分镜 {len(shots)} 个"
            f"｜炫技 {len(showcases)} 个"
            + (f"（{'、'.join(showcases)}）" if showcases else "")
        )
        if ep.get("hook"):
            lines.append(f"- 钩子：{ep['hook']}")
        if ep.get("cliffhanger"):
            lines.append(f"- 卡点：{ep['cliffhanger']}")
        lines.append("")

        cum = 0.0
        for gi, (beat, gshots) in enumerate(groups, 1):
            g_total = sum(C.as_float(s.get("duration_sec")) for s in gshots)
            cum += g_total
            words = sum(cjk_len((s.get("dialogue") or {}).get("text", ""))
                        + cjk_len(s.get("narration") or "") for s in gshots)
            lines.append(f"### 大分镜{gi:02d}｜{beat or '节拍'}｜建议时长：{g_total:.0f}s"
                         f"（累计至 {cum:.0f}s）")
            lines.append("")
            lines.append(f"（总对话+内心OS：{words}字；按平均{rate:.0f}字/秒计算，"
                         f"所需时间：约{words / rate:.0f}s）")
            lines.append("")
            lines.append("【制作资产槽｜请自行填入对应参考素材】")
            lines.append("")
            seen_chars: list[str] = []
            seen_scenes: list[str] = []
            seen_props: list[str] = []
            for s in gshots:
                for cid in s.get("characters") or []:
                    if cid not in seen_chars:
                        seen_chars.append(cid)
                sid = s.get("scene_id")
                if sid and sid not in seen_scenes:
                    seen_scenes.append(sid)
                for p in s.get("props") or []:
                    if p not in seen_props:
                        seen_props.append(p)
            for i, cid in enumerate(seen_chars):
                name = (chars.get(cid) or {}).get("name", cid)
                lines.append(f"人物{slot_letter(i)}（{name}）=[]")
                lines.append(f"人物{slot_letter(i)}音色=[]")
            for i, sid in enumerate(seen_scenes):
                sc = scenes.get(sid) or {}
                label = sc.get("name", sid)
                if sc.get("time"):
                    label += f"·{sc['time']}"
                lines.append(f"场景{slot_letter(i)}（{label}）=[]")
            for i, p in enumerate(seen_props):
                lines.append(f"道具{slot_letter(i)}（{p}）=[]")
            lines.append("")
            lines.append("【画面提示词】")
            lines.append("")

            t = 0.0
            for si, s in enumerate(gshots, 1):
                dur = C.as_float(s.get("duration_sec"))
                head = f"#### 小分镜{gi:02d}-{si}｜[{t:.0f}–{t + dur:.0f}s]"
                if s.get("showcase"):
                    head += f"｜炫技·{s['showcase']}"
                lines.append(head)
                t += dur

                dlg = s.get("dialogue") or {}
                if dlg.get("text"):
                    cid = dlg.get("character", "")
                    cname = (chars.get(cid) or {}).get("name", cid)
                    head = f"【人物台词】{cname}"
                    if dlg.get("emotion"):
                        head += f"｜情绪：{dlg['emotion']}"
                    if dlg.get("delivery"):
                        head += f"｜表达：{dlg['delivery']}"
                    head += f'："{dlg["text"]}"'
                    lines.append("")
                    lines.append(head)
                narr = s.get("narration") or ""
                if narr:
                    lines.append("")
                    lines.append(f'【旁白】:"{narr}"')

                names = [C.char_name(chars.get(cid) or {}, stage_of(s, cid), cid)
                         for cid in s.get("characters") or []]
                who = "、".join(names) or "（空镜）"
                props = "、".join(s.get("props") or [])
                sc = scenes.get(s.get("scene_id")) or {}
                lines.append("")
                lines.append(f"- 【主体】{who}" + (f"；{props}" if props else ""))
                pos = sc.get("name", s.get("scene_id", ""))
                if s.get("composition"):
                    pos += f"，{s['composition']}"
                if s.get("blocking"):
                    pos += f"；{s['blocking']}"
                lines.append(f"- 【空间位置】{pos}")
                lines.append(f"- 【动作/剧情】{s.get('action', '')}")
                lines.append(f"- 【场景/环境】{sc.get('desc', '')}")
                light = s.get("lighting") or sc.get("lighting") or style_lighting
                lines.append(f"- 【光影氛围】{light}")
                lines.append(f"- 【镜头语言】{s.get('shot_size', '')}"
                             f"{('，' + s['camera']) if s.get('camera') else ''}机位")
                if s.get("sfx"):
                    lines.append(f"- 【音效】{s['sfx']}")
                if s.get("vfx"):
                    lines.append(f"- 【特效】{s['vfx']}")

                # 本镜资产：一镜一条，逐条留空，对应这一条提示词所需的参考素材
                slots: list[str] = []
                speaker = dlg.get("character")
                for ci, cid in enumerate(s.get("characters") or []):
                    nm = C.char_name(chars.get(cid) or {}, stage_of(s, cid), cid)
                    slots.append(f"人物{slot_letter(ci)}（{nm}）=[]")
                    if cid == speaker:
                        slots.append(f"人物{slot_letter(ci)}音色=[]")
                if s.get("scene_id"):
                    sc_label = sc.get("name", s["scene_id"])
                    if sc.get("time"):
                        sc_label += f"·{sc['time']}"
                    slots.append(f"场景A（{sc_label}）=[]")
                for pi, p in enumerate(s.get("props") or []):
                    slots.append(f"道具{slot_letter(pi)}（{p}）=[]")
                if slots:
                    lines.append("")
                    lines.append("【本镜资产】" + "｜".join(slots))
                lines.append("")

            lines.append(f"【风格/画质】{st.get('prompt_suffix_zh', '')}")
            lines.append("【约束】人物身份、服装、空间布局、道具、光源方向和画面轴线"
                         "保持一致；只有指定人物运动；单画面清晰人物不超过2人；"
                         "一个连续、无剪切的镜头。")
            lines.append("")
        lines.append("")
    return "\n".join(lines)


def footer(eid: str, stamp: str) -> str:
    """生成视图的落款：明确它是派生文件，防止与 project.json 脱节后误导。"""
    return (f"\n\n---\n\n> 由 build_prompts.py 生成于 {stamp}（{eid}.md）。"
            f"project.json 为唯一数据源，手工改动会被覆盖；"
            f"改完数据请重跑 `build_prompts.py --type table` 刷新本视图。\n")


def storyboard_tables(project: dict) -> dict[str, str]:
    """生成 03_storyboard/ 下的分镜表 md（每集一份，人工编辑视图）。"""
    chars = C.characters_by_id(project)
    scenes = C.scenes_by_id(project)
    tables: dict[str, str] = {}
    for ep in C.episodes_of(project):
        eid = ep.get("id", "E01")
        shots = C.shots_of(ep)
        if not shots:
            continue
        total = sum(C.as_float(s.get("duration_sec")) for s in shots)
        target = C.as_float(ep.get("duration_sec")) or total
        lines = [
            f"# 分镜表（{eid}｜{ep.get('title', '')}）",
            "",
            "> 每镜必备字段：`scene_id` `characters` `shot_size` `camera` "
            "`composition` `action` `duration_sec`",
            "> 大分镜（`beat`）= 同一连续剧情段的镜头组，总时长 ≤30s；小镜 1-5s。",
            "> 本表是 `project.json` 的人工编辑视图，最终以 `project.json` 为准。",
            "",
            f"总时长：{C.fmt_sec(total)}s ｜ 目标：{C.fmt_sec(target)}s ｜ "
            f"镜头数：{len(shots)}",
            "",
            "| 镜号 | 大分镜 | 场景 | 角色 | 景别 | 运镜 | 构图 | 画面动作 | "
            "对白/旁白 | 道具 | 时长 | 转场 | 标记 |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for s in shots:
            dlg = s.get("dialogue") or {}
            voice_text = ""
            if dlg.get("text"):
                cid = dlg.get("character", "")
                nm = C.char_name(chars.get(cid) or {}, stage_of(s, cid), cid)
                voice_text = f"{nm}：{dlg['text']}"
            elif s.get("narration"):
                voice_text = f"旁白：{s['narration']}"
            names = [C.char_name(chars.get(cid) or {}, stage_of(s, cid), cid)
                     for cid in s.get("characters") or []]
            mark = s.get("showcase") or s.get("notes") or ""
            if s.get("scene_marker"):
                mark = f"{mark} scene_marker" if mark else "scene_marker"
            lines.append(
                f"| {cell(s.get('id', ''))} | {cell(s.get('beat', ''))} | "
                f"{cell(s.get('scene_id', ''))} | "
                f"{cell(' '.join(names) or '（空镜）')} | {cell(s.get('shot_size', ''))} | "
                f"{cell(s.get('camera', ''))} | {cell(s.get('composition', ''))} | "
                f"{cell(s.get('action', ''))} | "
                f"{cell(voice_text)} | {cell('、'.join(s.get('props') or []))} | "
                f"{C.fmt_sec(s.get('duration_sec'))}s | "
                f"{cell(s.get('transition_in', '硬切'))} | {cell(mark)} |"
            )
        tables[eid] = "\n".join(lines) + "\n"
    return tables


def asset_manifest(project: dict) -> tuple[str, list[dict]]:
    """一镜一资产的清单：每镜一条记录（人物/音色/场景/道具）。

    返回 (markdown 表格, csv 行)。参考文件列留空，由使用者逐条填。
    """
    chars = C.characters_by_id(project)
    scenes = C.scenes_by_id(project)
    rows: list[dict] = []
    for ep, shot in C.iter_shots(project):
        names = [C.char_name(chars.get(cid) or {}, stage_of(shot, cid), cid)
                 for cid in shot.get("characters") or []]
        speaker = (shot.get("dialogue") or {}).get("character")
        voices: list[str] = []
        if speaker:
            ch = chars.get(speaker) or {}
            timbre = (ch.get("voice") or {}).get("timbre", "")
            voices.append(f"{ch.get('name', speaker)}" + (f"：{timbre}" if timbre else ""))
        sc = scenes.get(shot.get("scene_id")) or {}
        scene_label = sc.get("name", shot.get("scene_id", ""))
        if sc.get("time"):
            scene_label += f"·{sc['time']}"
        rows.append({
            "shot_id": shot.get("id", ""),
            "episode": ep.get("id", ""),
            "beat": shot.get("beat", ""),
            "shot_no": shot.get("shot_no", ""),
            "duration": shot.get("duration_sec", ""),
            "characters": "、".join(names),
            "voices": "；".join(voices),
            "scene": scene_label,
            "props": "、".join(shot.get("props") or []),
            "ref_files": "",
            "status": "",
        })

    md = [
        "# 资产清单（一镜一资产）",
        "",
        f"项目: {project['meta'].get('title', '')} | 共 {len(rows)} 条"
        f"（一镜一条，覆盖该镜图片/视频/配音所需素材）",
        "",
        "用法：逐行准备人物图 / 音色 / 场景图 / 道具图，把文件路径填进「参考文件」，"
        "填完把「状态」改为 ready。人物图对应 `characters[].image_prompt`（或 stages），"
        "场景图对应 `scenes[].anchor_en`。",
        "",
        "| 镜号 | 集 | 大分镜 | 序 | 时长 | 人物 | 音色 | 场景 | 道具 | 参考文件（自填） | 状态（自填） |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        md.append(
            f"| {cell(r['shot_id'])} | {cell(r['episode'])} | {cell(r['beat'])} | "
            f"{cell(r['shot_no'])} | {C.fmt_sec(r['duration'])}s | "
            f"{cell(r['characters'] or '（空镜）')} | {cell(r['voices'])} | "
            f"{cell(r['scene'])} | {cell(r['props'])} | {cell(r['ref_files'])} | "
            f"{cell(r['status'])} |"
        )
    return "\n".join(md), rows


def main() -> None:
    ap = argparse.ArgumentParser(description="批量生成提示词")
    ap.add_argument("project", nargs="?", help="project.json 或所在目录")
    ap.add_argument("--type", default="all",
                    choices=["image", "video", "audio", "director", "assets", "table", "all"])

    ap.add_argument("--force", action="store_true", help="覆盖已有的 image_prompt / video_prompt / audio_prompt")
    ap.add_argument("--strict-en", action="store_true",
                    help="图片/视频提示词出现中文即报错（保证提示词纯英文）")
    ap.add_argument("--max-chars", type=int, default=None,
                    help=f"单条提示词字数上限（默认 {C.limits()['prompt_chars']['max']}）")
    ap.add_argument("--out", help="输出目录（默认 <项目>/04_prompts）")
    args = ap.parse_args()

    max_chars = args.max_chars or C.limits()["prompt_chars"]["max"]

    path = C.find_project(args.project)
    project = C.load_project(path)
    root = C.project_root(path)
    chars = C.characters_by_id(project)
    scenes = C.scenes_by_id(project)
    meta = project.get("meta") or {}
    if not isinstance(meta, dict) or not meta.get("style"):
        C.die("project.json 缺少 meta.style，无法生成提示词"
              "（请先补全，或运行 validate_project.py 查看缺失字段）")
    style_key = meta["style"]
    episodes = C.episodes_of(project)
    shot_count = sum(len(C.shots_of(e)) for e in episodes)

    want = ({"image", "video", "audio", "director", "assets", "table"} if args.type == "all"
            else {args.type})
    t2v_mode = is_t2v(project)
    zh_mode = prompt_lang(project) == "zh"
    neg_lang = "zh" if zh_mode else "en"
    cjk_shots: set[str] = set()
    rows: list[dict] = []
    md: dict[str, list[str]] = {"image": [], "video": [], "audio": [], "director": []}
    # 每集一条 BGM（剧梦音乐直接生成）；缺省按题材情绪曲线自动拼装
    if "audio" in want:
        bgm_lines = {ep.get("id", "E??"): build_bgm_prompt(project, ep)
                     for ep in episodes if C.shots_of(ep)}
        bgm_done: set[str] = set()
    # 视频提示词里的 BGM 短句：取每集 BGM 提示词的首个分句（质感段）
    bgm_cues = ({ep.get("id", "E??"): build_bgm_prompt(project, ep).split("；")[0]
                 for ep in episodes if C.shots_of(ep)} if "video" in want else {})

    for ep, shot in C.iter_shots(project):
        eid = ep.get("id", "E??")
        sid = shot.get("id", f"{eid}-S?")
        base = {
            "id": sid,
            "episode": eid,
            "shot_no": shot.get("shot_no", ""),
            "duration": shot.get("duration_sec", ""),
            "characters": "+".join(shot.get("characters") or []) or "(空镜)",
            "scene": shot.get("scene_id", ""),
            "shot_size": shot.get("shot_size", ""),
        }

        # 角色专属负面词（characters[].negative_prompt）按出场角色并入负面提示词
        char_neg = ", ".join(
            str((chars.get(c) or {}).get("negative_prompt") or "").strip()
            for c in shot.get("characters") or []
            if str((chars.get(c) or {}).get("negative_prompt") or "").strip()
        )

        if "image" in want:
            prompt = (shot.get("image_prompt") or "").strip()
            if args.force or not prompt:
                prompt = build_image_prompt(project, shot, chars, scenes)
                shot["image_prompt"] = prompt
            if C.has_cjk(prompt):
                cjk_shots.add(sid)
            neg = C.negative_prompt(style_key, lang=neg_lang)
            if char_neg:
                neg = f"{neg}, {char_neg}"
            md["image"].append(
                f"### {sid} | {base['characters']} | {base['shot_size']} | "
                f"{C.fmt_sec(base['duration'])}s\n\n"
                f"- 正面词: `{prompt}`\n"
                f"- 负面词: `{neg}`\n"
            )
            rows.append({**base, "type": "image", "prompt": prompt, "negative": neg})

        if "video" in want:
            vp = (shot.get("video_prompt") or "").strip()
            if args.force or not vp:
                vp = build_video_prompt(project, shot, chars, scenes,
                                        bgm_cue=bgm_cues.get(eid, ""), force=args.force)
                shot["video_prompt"] = vp
            if C.has_cjk(vp):
                cjk_shots.add(sid)
            neg = C.negative_prompt(style_key, for_video=True, lang=neg_lang)
            if char_neg:
                neg = f"{neg}, {char_neg}"
            label = ("提示词（文生+参考图：画面+表演+视听要素，参考图传人物定妆照）"
                     if t2v_mode else "提示词（图生视频：运动+表演+视听要素，不重复首帧静态）")
            md["video"].append(
                f"### {sid} | {base['characters']} | "
                f"{C.fmt_sec(base['duration'])}s\n\n"
                f"- {label}: `{vp}`\n"
                f"- 负面词: `{neg}`\n"
            )
            rows.append({**base, "type": "video", "prompt": vp, "negative": neg})

        if "audio" in want:
            if eid not in bgm_done:
                bgm_done.add(eid)
                md["audio"].append(
                    f"## BGM（{eid}｜每集一条，剧梦音乐直接生成）\n\n"
                    f"- 提示词: `{bgm_lines.get(eid, '')}`\n"
                    f"- 用法: 情绪切换点若与反转镜头对不上，在提示词里调整"
                    f"「情绪走向」措辞后重新生成；BGM 全剧逐集复用时可微调时长\n\n---\n\n"
                )
            ap_text = (shot.get("audio_prompt") or "").strip()
            if args.force or not ap_text:
                ap_text = build_audio_prompt(shot, chars)
                shot["audio_prompt"] = ap_text
            md["audio"].append(f"### {sid}\n\n{ap_text}\n")
            rows.append({**base, "type": "audio", "prompt": ap_text, "negative": ""})

    # 卡审扫描（review_rules.json）：forbidden 阻断，avoid 提醒
    review_errors: list[str] = []
    review_warns: list[str] = []
    wl = C.review_whitelist(project)
    for r in rows:
        for hit in C.scan_review_text(r["prompt"], wl):
            msg = (f"{r['id']} ({r['type']}) 命中卡审 {hit['id']}（{hit['level']}）"
                   f"「{hit['title']}」关键词「{hit['keyword']}」→ {hit['fix']}")
            (review_errors if hit["level"] == "forbidden" else review_warns).append(msg)

    if "director" in want:
        doc = director_md(project)
        md["director"].append(doc)
        for hit in C.scan_review_text(doc, wl):
            msg = (f"导演版提示词 命中卡审 {hit['id']}（{hit['level']}）"
                   f"「{hit['title']}」关键词「{hit['keyword']}」→ {hit['fix']}")
            (review_errors if hit["level"] == "forbidden" else review_warns).append(msg)

    # 回写 project.json（保留已生成素材路径；分片布局写回 episodes/*.json）
    C.save_project(project, path)

    # --out 为相对路径时按项目根解析，避免受当前工作目录影响
    out_dir = Path(args.out) if args.out else root / "04_prompts"
    if not out_dir.is_absolute():
        out_dir = root / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    # 人物形象参考图（定妆照）：左大头照 + 右无脸三视图，剧梦直接生成
    sheets_md: list[str] = []
    scene_sheets_md: list[str] = []
    if "image" in want:
        for cid, ch in chars.items():
            prompt = character_sheet_prompt(project, ch)
            if not prompt:
                continue
            neg = C.negative_prompt(style_key, lang=neg_lang)
            cneg = str(ch.get("negative_prompt") or "").strip()
            if cneg:
                neg = f"{neg}, {cneg}"
            first_outfit = (ch.get("outfits") or [{}])[0]
            sheets_md.append(
                f"### {cid} {ch.get('name') or ''}｜默认服装 {first_outfit.get('id', '-')}\n\n"
                f"- 正面词: `{prompt}`\n"
                f"- 负面词: `{neg}`\n"
            )
        # 场景参考图（场景定妆照）：无人物空场景母版，负面词强制无人
        for sid_key, sc in scenes.items():
            prompt = scene_sheet_prompt(project, sc)
            if not prompt:
                continue
            neg = C.negative_prompt(style_key, lang=neg_lang)
            neg = f"{neg}, " + ("人物，人影，人群" if zh_mode else "people, person, crowd")
            label = sc.get("name", sid_key) + (f"·{sc['time']}" if sc.get("time") else "")
            scene_sheets_md.append(
                f"### {sid_key} {label}\n\n"
                f"- 正面词: `{prompt}`\n"
                f"- 负面词: `{neg}`\n"
                f"- 用法: 先出图人工确认空间/陈设/光型再批量；可当空镜首帧或垫图\n"
            )

    titles = {
        "image": "图片提示词（人物形象参考 + 分镜首帧）",
        "video": ("视频提示词（文生视频+参考图工作流：完整画面描述+运动；参考图传人物定妆照）"
                  if t2v_mode else "视频提示词（图生视频，只写运动）"),
        "audio": "BGM / 配音 / 音效提示词（剧梦工作流：直接复制到剧梦生成）",
        "director": "导演版分镜提示词（中文：大分镜/小分镜 + 资产槽）",
    }
    for kind in ("image", "video", "audio", "director"):
        if kind not in want or not md[kind]:
            continue
        if kind == "director":
            # 导演版文档自带完整表头，不再包一层
            C.write_text(out_dir / f"{kind}_prompts.md", md["director"][0])
            continue
        if kind == "image" and (sheets_md or scene_sheets_md):
            count = (f"分镜 {len(md['image'])} 条"
                     + (f" + 人物形象 {len(sheets_md)} 条" if sheets_md else "")
                     + (f" + 场景参考 {len(scene_sheets_md)} 条" if scene_sheets_md else ""))
            sections: list[str] = []
            if sheets_md:
                sections.append(
                    "## 人物形象参考（定妆照：左大头照 + 右无脸三视图）\n\n"
                    "三视图无脸：小尺寸五官必崩且与大头照冲突，身份由大头照承担，"
                    "三视图只管体型/服装/比例。\n\n" + "\n".join(sheets_md))
            if scene_sheets_md:
                sections.append(
                    "## 场景参考（场景定妆照：无人物空场景母版）\n\n"
                    "场景一致性是仅次于换脸的返工源头：每个场景先出定妆照并人工确认"
                    "空间/陈设/光型，再批量生成该场景镜头图；可直接当空镜首帧或垫图。\n\n"
                    + "\n".join(scene_sheets_md))
            sections.append("## 分镜首帧\n\n" + "\n".join(md["image"]))
            body = "\n---\n\n".join(sections)
        else:
            count = f"共 {len(md[kind])} 条"
            body = "\n".join(md[kind])
        ar_note = (f"> 画幅：生成工具里选择 **{aspect_ratio_of(project)}**"
                   f"（提示词已自动附带画幅 token，双保险）。\n\n")
        header = (
            f"# {titles[kind]}\n\n"
            f"项目: {project['meta'].get('title', '')} | "
            f"风格: {project['meta'].get('style', '')} | "
            f"平台: {project['meta'].get('platform', '')}\n\n"
            f"生成命令: `python build_prompts.py` | {count}\n\n"
            + (ar_note if kind in ("image", "video") else "")
            + "---\n\n"
        )
        C.write_text(out_dir / f"{kind}_prompts.md", header + body)

    # 分镜表（03_storyboard/ 下每集一份人工编辑视图）
    if "table" in want:
        sb_dir = root / "03_storyboard"
        sb_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        for eid, text in storyboard_tables(project).items():
            C.write_text(sb_dir / f"{eid}.md", text + footer(eid, stamp))

    # 一镜一资产清单（每镜一条记录，覆盖该镜全部提示词所需素材）
    if "assets" in want:
        manifest_md, manifest_rows = asset_manifest(project)
        C.write_text(out_dir / "asset_manifest.md", manifest_md)
        with (out_dir / "asset_manifest.csv").open(
                "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=[
                "shot_id", "episode", "beat", "shot_no", "duration",
                "characters", "voices", "scene", "props", "ref_files", "status"])
            w.writeheader()
            w.writerows(manifest_rows)

    # 子类型运行（--type image 等）与既有清单合并，避免互相覆盖；
    # --type all 是全量重建，会清掉已删除镜头的旧记录。
    prompts_json = out_dir / "prompts.json"
    merged_rows = rows
    if args.type != "all" and prompts_json.is_file():
        try:
            old = C.load_json(prompts_json)
        except (OSError, ValueError):
            old = {}
        current_ids = {s.get("id") for _ep, s in C.iter_shots(project)}
        merged = {(r.get("id"), r.get("type")): r
                  for r in old.get("items") or []
                  if r.get("id") in current_ids}
        for r in rows:
            merged[(r["id"], r["type"])] = r
        type_order = {"image": 0, "video": 1, "audio": 2}
        merged_rows = sorted(
            merged.values(),
            key=lambda r: (str(r.get("episode", "")), C.as_float(r.get("shot_no")),
                           type_order.get(r.get("type"), 9)),
        )

    if rows or prompts_json.is_file():
        with (out_dir / "prompts.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=["id", "episode", "shot_no", "type", "characters", "scene",
                            "shot_size", "duration", "prompt", "negative"],
            )
            writer.writeheader()
            writer.writerows(merged_rows)

        C.dump_json(
            {
                "project": project["meta"].get("title", ""),
                "style": style_key,
                "platform": project["meta"].get("platform", ""),
                "count": len(merged_rows),
                "items": merged_rows,
            },
            prompts_json,
        )

    over = [r for r in rows if len(r["prompt"]) > max_chars]

    if review_errors or over:
        print(f"[警告] 提示词已写出但未通过检查: {out_dir}")
    else:
        C.ok(f"提示词已生成: {out_dir}")
    print(f"  共 {len(rows)} 条 "
          f"(image={sum(1 for r in rows if r['type'] == 'image')}, "
          f"video={sum(1 for r in rows if r['type'] == 'video')}, "
          f"audio={sum(1 for r in rows if r['type'] == 'audio')})"
          + (f"；清单累计 {len(merged_rows)} 条" if merged_rows is not rows else "")
          + (", director=1 份" if "director" in want and md["director"] else "")
          + (f", assets={shot_count} 条" if "assets" in want else "")
          + (f", 分镜表={len([e for e in episodes if C.shots_of(e)])} 份"
             if "table" in want else ""))
    if cjk_shots:
        if zh_mode:
            print(f"\n  [提示] {len(cjk_shots)} 条提示词含英文/字母 token"
                  f"（zh 模式允许中英混排，如镜头参数 50mm，无需处理）。")
        elif args.strict_en:
            print()
            print(f"  [错误] {len(cjk_shots)} 条提示词含中文（--strict-en），"
                  f"请补 shots[].action_en 或检查 composition/camera 用词：")
            print(f"  示例: {', '.join(sorted(cjk_shots)[:10])}")
            raise SystemExit(1)
        else:
            print()
            print(f"  [提示] {len(cjk_shots)} 条提示词含中文（en 模式对英文更稳）。"
                  f"建议为这些镜头补充 action_en 字段，或先用模型测试中文效果；"
                  f"要强制纯英文请加 --strict-en。")
            print(f"  示例: {', '.join(sorted(cjk_shots)[:5])}")

    if review_warns:
        print()
        print(f"  [卡审提醒] {len(review_warns)} 条提示词命中 avoid 级规则"
              f"（可保留，但须确保该集结尾回正）：")
        for m in review_warns[:10]:
            print(f"    {m}")
    if review_errors:
        print()
        print(f"  [错误] {len(review_errors)} 条提示词命中 forbidden 级卡审规则，必须改写：")
        for m in review_errors[:10]:
            print(f"    {m}")
        print("  改写原则见 references/review_rules.md（替换指南/三步降级）。")
        raise SystemExit(1)

    if over:
        print()
        print(f"  [错误] {len(over)} 条提示词超过 {max_chars} 字上限：")
        for r in over[:10]:
            print(f"    {r['id']} ({r['type']}): {len(r['prompt'])} 字")
        print("  请精简：删冗余形容词、合并重复描述、只保留必要 token。")
        raise SystemExit(1)
    raise SystemExit(0)


if __name__ == "__main__":
    main()
