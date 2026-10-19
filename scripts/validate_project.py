#!/usr/bin/env python3
"""校验 project.json 的数据质量。

用法:
    python validate_project.py [project.json 或其所在目录] [--strict]

--strict 模式下 WARN 也返回非 0 退出码（用于 CI / 交付前门禁）。
除结构校验外，还按 assets/presets/review_rules.json 执行卡审扫描：
forbidden 级记 ERROR，avoid 级记 WARN（人读版见 references/review_rules.md）。
另有提示词质量 lint（production.json 的 prompt_quality 词库）：空泛词 /
否定句命中记 WARN，改写方向见 cinematic-dictionary.md 第六节。
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _common as C

ERRORS: list[str] = []
WARNS: list[str] = []


def err(msg: str) -> None:
    ERRORS.append(msg)


def warn(msg: str) -> None:
    WARNS.append(msg)


def dialogue_len(text: str) -> int:
    """对白字数：中文按汉字计；纯英文按单词计（≤20 字门禁的统一口径）。"""
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return cjk if cjk else len(text.split())


# 占位文本：形式合规但零信息，混过非空校验会让叙事门禁形同虚设
PLACEHOLDER_TOKENS = ("（本集完）", "(本集完)", "待补充", "待定", "TODO", "TBD", "{{")

# 场记行 desc（如「1-1 山林-古树下 外 日」）：提示词场景段会退化成场记行而非画面描述
SCENE_SLUG_RE = re.compile(r"^\s*\d+\s*[-－]\s*\d+\s+")


def is_placeholder(text: str) -> bool:
    return any(tok in (text or "") for tok in PLACEHOLDER_TOKENS)


def check_meta(project: dict) -> None:
    meta = project.get("meta")
    if not isinstance(meta, dict):
        err("缺少 meta 对象")
        return
    presets = C.load_presets()
    for field in ("title", "genre", "style", "platform", "aspect_ratio", "language"):
        if not meta.get(field):
            err(f"meta.{field} 为空")
    if meta.get("genre") and meta["genre"] not in presets["genres"]:
        err(f"meta.genre 未知: {meta['genre']}")
    if meta.get("style") and meta["style"] not in presets["styles"]:
        err(f"meta.style 未知: {meta['style']}")
    if meta.get("platform") and meta["platform"] not in presets["platforms"]:
        err(f"meta.platform 未知: {meta['platform']}")
    cfg = project.get("config") or {}
    for field in ("episode_count", "episode_duration_sec", "hook_window_sec"):
        value = cfg.get(field)
        if value in (None, ""):
            err(f"config.{field} 为空")
        elif C.as_float(value, -1) <= 0:
            err(f"config.{field} 必须为正数: {value!r}")


def check_references(project: dict) -> tuple[dict, dict]:
    chars = project.get("characters") or []
    scenes = project.get("scenes") or []
    if not isinstance(chars, list):
        err("characters 必须是数组")
        chars = []
    if not isinstance(scenes, list):
        err("scenes 必须是数组")
        scenes = []
    char_ids = [c.get("id") for c in chars]
    scene_ids = [s.get("id") for s in scenes]

    if len(char_ids) != len(set(char_ids)):
        err("characters[].id 存在重复")
    if len(scene_ids) != len(set(scene_ids)):
        err("scenes[].id 存在重复")

    if not chars:
        err("characters 为空：尚无角色定义")
    if not scenes:
        err("scenes 为空：尚无场景锚点定义")
    lim = C.limits()
    max_chars = lim.get("max_characters", 5)
    max_scenes = lim.get("max_scenes", 12)
    if len(chars) > max_chars:
        warn(f"角色数 {len(chars)} > {max_chars}，AI 生成下人物一致性风险显著上升")
    if len(scenes) > max_scenes:
        warn(f"场景数 {len(scenes)} > {max_scenes}，画面一致性与制作成本都会上升")

    for c in chars:
        cid = c.get("id", "?")
        if not c.get("id"):
            err("characters 存在缺少 id 的条目")
        if not c.get("name"):
            err(f"角色 {cid} 缺少 name")
        if not c.get("role"):
            warn(f"角色 {cid} 缺少 role（protagonist/antagonist/supporting/extra）")
        elif c["role"] not in {"protagonist", "antagonist", "supporting", "extra"}:
            warn(f"角色 {cid} 的 role 不在约定枚举内: {c['role']}")
        if not c.get("appearance"):
            err(f"角色 {cid} 缺少 appearance（英文识别锚点）")
        if not c.get("image_prompt"):
            err(f"角色 {cid} 缺少 image_prompt（定妆照提示词）")
        if not c.get("outfits"):
            warn(f"角色 {cid} 未定义服装变体，后续换装易漂移")
        outfit_ids = [o.get("id") for o in c.get("outfits") or []]
        if len(outfit_ids) != len(set(outfit_ids)):
            err(f"角色 {cid} 的 outfits[].id 存在重复")
        for of in c.get("outfits") or []:
            if not of.get("id") or not of.get("desc"):
                warn(f"角色 {cid} 的服装变体缺少 id 或 desc: {of}")
        anchors = c.get("visual_anchors") or []
        if len(anchors) < 3:
            warn(f"角色 {cid} 的 visual_anchors 少于 3 个，识别度不足")
        if c.get("role") == "antagonist" and not c.get("motivation"):
            warn(f"反派 {cid} 缺少 motivation（反派动机）")

    zh = str((project.get("meta") or {}).get("prompt_lang") or "zh").strip().lower().startswith("zh")
    for s in scenes:
        sid = s.get("id", "?")
        if not s.get("id"):
            err("scenes 存在缺少 id 的条目")
        if not s.get("name"):
            err(f"场景 {sid} 缺少 name")
        if zh:
            # zh 模式：中文 desc 是场景锚点主字段（build_prompts 优先取 desc，anchor_en 仅作回退）
            if not (s.get("desc") or s.get("anchor_en")):
                err(f"场景 {sid} 缺少场景锚点（desc 与 anchor_en 至少填一个）")
            elif not s.get("desc"):
                warn(f"场景 {sid} 缺少 desc（中文描述，导演版会用到）")
        else:
            # en 模式：英文 anchor_en 是场景锚点主字段
            if not s.get("anchor_en"):
                err(f"场景 {sid} 缺少 anchor_en（英文场景锚点短语）")
            if not s.get("desc"):
                warn(f"场景 {sid} 缺少 desc（中文描述，导演版会用到）")

    if zh:
        slug_scenes = [str(s.get("id", "?")) for s in scenes
                       if SCENE_SLUG_RE.match(str(s.get("desc") or "").strip())]
        if slug_scenes:
            warn(f"{len(slug_scenes)} 个场景 desc 仍是场记行（如“1-1 … 外日”），"
                 f"建议补成可见画面描述，否则提示词场景段信息不足"
                 f"（例：{'、'.join(slug_scenes[:5])}）")

    return ({c["id"]: c for c in chars if c.get("id")},
            {s["id"]: s for s in scenes if s.get("id")})


def check_shots(project: dict, char_map: dict, scene_map: dict) -> None:
    cfg = project.get("config") or {}
    default_target = C.as_float(cfg.get("episode_duration_sec"))
    episodes = project.get("episodes") or []
    if not episodes:
        err("episodes 为空：尚无任何分集")

    lim = C.limits()
    shot_min = lim["shot_duration_sec"]["min"]
    shot_max = lim["shot_duration_sec"]["max"]

    meta = project.get("meta") or {}
    taboo_words = (C.genre(meta["genre"]).get("taboo", [])
                   if meta.get("genre") in C.load_presets()["genres"] else [])

    shot_episodes: dict[str, str] = {}
    target_warned = False

    for ep_idx, ep in enumerate(episodes):
        eid = ep.get("id", "?")
        # 单集可在 episodes[].duration_sec 覆盖 config 的目标时长
        target = C.as_float(ep.get("duration_sec")) or default_target
        shots = C.shots_of(ep)
        if not shots:
            err(f"{eid} 没有镜头")
            continue
        if not ep.get("hook"):
            err(f"{eid} 缺少 hook（前 3 秒钩子）")
        elif is_placeholder(str(ep["hook"])):
            warn(f"{eid} 的 hook 疑似占位文本，前 3 秒钩子须写具体画面/动作")
        if not ep.get("cliffhanger"):
            err(f"{eid} 缺少 cliffhanger（卡点结尾）")
        elif is_placeholder(str(ep["cliffhanger"])):
            warn(f"{eid} 的 cliffhanger 疑似占位文本，卡点须写具体悬念")

        total = 0.0
        prev_key = None
        same_streak = 0
        for shot in shots:
            sid = shot.get("id", f"{eid}-?")
            if not shot.get("id"):
                err(f"{eid} 存在缺少 id 的镜头")
            else:
                prev_ep = shot_episodes.get(sid)
                if prev_ep is not None and prev_ep != eid:
                    err(f"镜头 id 跨集重复: {sid}（{prev_ep} 与 {eid}）")
                shot_episodes.setdefault(sid, eid)

            raw_dur = shot.get("duration_sec")
            dur = C.as_float(raw_dur, -1)
            if raw_dur in (None, ""):
                err(f"{sid} 缺少 duration_sec")
                dur = 0.0
            elif dur < 0:
                kind = "为负数" if isinstance(raw_dur, (int, float)) else "非数字"
                err(f"{sid} duration_sec {kind}: {raw_dur!r}")
                dur = 0.0
            elif dur > shot_max:
                err(f"{sid} 时长 {C.fmt_sec(dur)}s 超过单镜上限 {shot_max}s")
            elif dur < shot_min:
                err(f"{sid} 时长 {C.fmt_sec(dur)}s 低于单镜下限 {shot_min}s")
            total += max(dur, 0.0)

            char_ids = shot.get("characters")
            if char_ids is None:
                err(f"{sid} 缺少 characters（空镜请写 []）")
            elif not isinstance(char_ids, list):
                err(f"{sid}.characters 必须是数组")
            else:
                if len(char_ids) > 2:
                    warn(f"{sid} 画面人物 {len(char_ids)} 人 > 2，"
                         f"多人一致性风险高（建议全景 + 固定站位）")
                for cid in char_ids:
                    if cid not in char_map:
                        err(f"{sid} 引用了不存在的角色 {cid}")

            # 服装：shots[].outfits 按角色映射；旧字段 outfit 仅单角色时有效
            outfits = shot.get("outfits")
            if outfits is not None and not isinstance(outfits, dict):
                err(f"{sid}.outfits 必须是「角色 id → 服装 id」的对象")
            elif outfits:
                for cid, oid in outfits.items():
                    ch = char_map.get(cid)
                    if not ch:
                        err(f"{sid}.outfits 引用了不存在的角色 {cid}")
                    elif oid not in {o.get("id") for o in ch.get("outfits") or []}:
                        err(f"{sid}.outfits[{cid}] 未知服装 {oid}")
            if shot.get("outfit") and isinstance(char_ids, list) and len(char_ids) > 1:
                warn(f"{sid} 用单值 outfit 指定了 {len(char_ids)} 个角色，"
                     f"建议改用 outfits 映射")

            # 年龄段锚点引用（characters[].stages / shots[].character_stages）
            stages = shot.get("character_stages") or {}
            if not isinstance(stages, dict):
                err(f"{sid}.character_stages 必须是「角色 id → 年龄段」的对象")
                stages = {}
            for cid, stg_id in stages.items():
                ch = char_map.get(cid)
                if not ch:
                    err(f"{sid}.character_stages 引用了不存在的角色 {cid}")
                    continue
                stage_ids = {x.get("id") for x in ch.get("stages") or []}
                if not stage_ids:
                    warn(f"{sid}.character_stages[{cid}] 指定了年龄段 {stg_id}，"
                         f"但角色未定义 stages")
                elif stg_id not in stage_ids:
                    err(f"{sid}.character_stages[{cid}] 未知年龄段 {stg_id}"
                        f"（可选: {sorted(stage_ids)}）")
            if not shot.get("scene_id"):
                err(f"{sid} 缺少 scene_id")
            elif shot["scene_id"] not in scene_map:
                err(f"{sid} 引用了不存在的场景 {shot['scene_id']}")
            if not shot.get("shot_size"):
                err(f"{sid} 缺少 shot_size")
            if not shot.get("camera"):
                err(f"{sid} 缺少 camera（单一主运镜）")
            if not shot.get("composition"):
                err(f"{sid} 缺少 composition（构图）")
            if not shot.get("action"):
                err(f"{sid} 缺少 action（画面动作描述）")
            elif is_placeholder(str(shot["action"])):
                warn(f"{sid} 的 action 疑似占位文本（待补充/本集完等），"
                     f"分镜须写可见画面")

            dlg = shot.get("dialogue") or {}
            if dlg and dlg.get("text"):
                dlen = dialogue_len(dlg["text"])
                if dlen > 20:
                    warn(f"{sid} 对白 {dlen} 字 > 20，短剧需拆短句")
                if dlg.get("character") and dlg["character"] not in char_map:
                    err(f"{sid} 对白角色 {dlg.get('character')} 不存在")

            # 题材禁用词：中文与英文字段都扫（严格模式下英文提示词也是发布内容）
            for text in filter(None, [shot.get("action"), shot.get("action_en"),
                                      shot.get("video_action_en"), shot.get("narration"),
                                      dlg.get("text")]):
                for bad in taboo_words:
                    if bad and bad in text:
                        err(f"{sid} 命中题材禁用词「{bad}」")

            # 生成前的预警：中文动作没配 action_en，strict-en 阶段必然被拦
            if C.has_cjk(shot.get("action")) and not (shot.get("action_en") or "").strip():
                warn(f"{sid} 有中文动作但缺 action_en，"
                     f"build_prompts --strict-en 会被拦截")

            key = (shot.get("scene_id"), tuple(shot.get("characters") or []), shot.get("shot_size"))
            same_streak = same_streak + 1 if key == prev_key else 1
            prev_key = key
            if same_streak > 8:
                warn(f"{sid} 同场景同人物同景别已连续 {same_streak} 镜，节奏拖沓")
                same_streak = 0

        # 镜头 id 唯一性 + shot_no 连续性（防止重编号/复制粘贴造成的错乱）
        ids = [s.get("id") for s in shots]
        dups = {i for i, n in Counter(ids).items() if n > 1}
        if dups:
            err(f"{eid} 镜头 id 重复: {sorted(str(d) for d in dups)}")
        nos = [s.get("shot_no") for s in shots]
        if all(isinstance(n, int) for n in nos):
            for pos, no in enumerate(nos, 1):
                if no != pos:
                    warn(f"{eid} 第 {pos} 个镜头 shot_no={no}，应为 {pos}（序号不连续）")
                    break
        else:
            warn(f"{eid} 存在缺失或非整数的 shot_no，无法校验序号连续性")

        # en 模式下图片锚点里的中文残留（zh 模式锚点本就应为中文，不检查）
        if not str((project.get("meta") or {}).get("prompt_lang") or "zh").startswith("zh"):
            for s in shots:
                if s.get("image_prompt") and C.has_cjk(s["image_prompt"]):
                    warn(f"{s.get('id', '?')} image_prompt 含中文，"
                         f"建议补 action_en/lighting_en 后 build_prompts --force")

        # 长镜头规则（shot_language.md §六）：>10s 每集最多 1 个，且不放第 1 集
        long_shots = [s for s in shots if C.as_float(s.get("duration_sec")) > 10]
        if len(long_shots) > 1:
            warn(f"{eid} 有 {len(long_shots)} 个长镜头（>10s），每集最多 1 个")
        if long_shots and ep_idx == 0:
            warn(f"{eid} 是第 1 集却含长镜头（>10s），第 1 集须快节奏")

        # 换场景必须有视觉标识（review_rules.md §四.1）：scene_id 变化时
        # 新镜头须带 scene_marker: true，否则系统可能误判卡审
        prev_scene = None
        for shot in shots:
            cur_scene = shot.get("scene_id")
            if prev_scene is not None and cur_scene != prev_scene \
                    and not shot.get("scene_marker"):
                warn(f"{shot.get('id', '?')} 换场景（{prev_scene} → {cur_scene}）"
                     f"缺少 scene_marker 标识，会被系统误判卡审")
            prev_scene = cur_scene

        # 大分镜（beat）规则：一个 beat = 一个连续剧情段
        #   * 总时长 ≤30s（硬规则，用户口径「最多每 30s 为一个分镜」）
        #   * 小镜 1-5s（纪律，WARN）
        #   * 不跨场景（连续时空，WARN）
        # beat 分组：与 director_md / asset_manifest 共用 _common.group_by_beat
        beat_groups = C.group_by_beat(shots)
        for b, gshots in beat_groups:
            label = b if b is not None else "（未分组）"
            g_total = sum(C.as_float(s.get("duration_sec")) for s in gshots)
            if g_total > 30:
                err(f"{eid} 大分镜「{label}」总时长 {C.fmt_sec(g_total)}s > 30s，"
                    f"必须拆成下一条大分镜")
            for s in gshots:
                if C.as_float(s.get("duration_sec")) > 5:
                    warn(f"{s.get('id', '?')} 时长 "
                         f"{C.fmt_sec(s.get('duration_sec'))}s > 5s，"
                         f"小分镜纪律为 1-5s（大分镜「{label}」内）")
            g_scenes = {s.get("scene_id") for s in gshots}
            if len(g_scenes) > 1:
                warn(f"{eid} 大分镜「{label}」跨越多个场景 {sorted(g_scenes)}，"
                     f"通常应按场景拆分（闪回/快闪也建议单独成 beat）")

            # 口播匹配：对白+旁白字数 ÷ 字速，超出画面时长 10% 即提醒
            words = sum(dialogue_len((s.get("dialogue") or {}).get("text", ""))
                        + dialogue_len(s.get("narration") or "") for s in gshots)
            if g_total > 0 and words / C.cjk_chars_per_sec() > g_total * 1.1:
                warn(f"{eid} 大分镜「{label}」口播约 "
                     f"{words / C.cjk_chars_per_sec():.0f}s > 画面 {g_total:.0f}s，"
                     f"VO 会压到后续镜头（扩画面或跨镜分布）")

        # 3+N 视觉名场面法则（narrative.md §四）：每集 3 个炫技段，
        # 不足 3 个没有足够记忆点，超过 3 个会稀释名场面浓度
        showcases = [s for s in shots if s.get("showcase")]
        if len(showcases) < 3:
            warn(f"{eid} 只有 {len(showcases)} 个炫技镜头（showcase），"
                 "3+N 要求每集 3 个视觉名场面")
        elif len(showcases) > 3:
            warn(f"{eid} 有 {len(showcases)} 个炫技镜头，超过 3 个会稀释名场面浓度")

        if total <= 0:
            err(f"{eid} 镜头总时长为 0")
            continue
        if target <= 0:
            if not target_warned:
                warn("config.episode_duration_sec 非正数，已跳过时长偏差校验")
                target_warned = True
        else:
            dev = abs(total - target) / target
            if dev > 0.2:
                err(f"{eid} 镜头总时长 {C.fmt_sec(total)}s 与目标 "
                    f"{C.fmt_sec(target)}s 偏差 {dev:.0%}（>20%），"
                    f"须继续拆镜补足或调整目标时长")

        # 第一个镜头必须是动作开场（不能是空镜 + 旁白）
        first = shots[0]
        if not (first.get("characters") or []):
            warn(f"{eid} 首个镜头画面无人，前 3 秒完播率风险高"
                 f"（建议人物入画，或把人物动作压进前 3 秒）")

    # 全剧一致性：集 id 唯一、集序号连续
    ep_ids = [e.get("id") for e in episodes]
    dup_eps = {i for i, n in Counter(ep_ids).items() if n > 1}
    if dup_eps:
        err(f"episodes[].id 重复: {sorted(str(d) for d in dup_eps)}")
    expected = 1
    for ep in episodes:
        eid = ep.get("id", "?")
        try:
            no = int(str(eid).lstrip("Ee"))
        except ValueError:
            warn(f"集编号无法解析: {eid}")
            continue
        if no != expected:
            warn(f"集编号不连续：期望 E{expected:02d}，实际 {eid}")
        expected += 1

    planned = int(C.as_float(cfg.get("episode_count"), 0))
    if len(episodes) > 1 and len(episodes) < planned:
        warn(f"实际 {len(episodes)} 集 < 计划 {planned} 集")


def check_review(project: dict) -> None:
    """卡审规则扫描（assets/presets/review_rules.json）。

    forbidden 级命中记 ERROR（必须改写）；avoid 级命中记 WARN（出现时
    该集结尾须回正）。扫描范围：标题、角色锚点、场景锚点、每集
    hook/cliffhanger、镜头动作/旁白/对白。
    """
    whitelist = C.review_whitelist(project)

    def scan(label: str, text: str | None) -> None:
        for hit in C.scan_review_text(text or "", whitelist):
            msg = (f"{label} 命中卡审 {hit['id']}（{hit['level']}）"
                   f"「{hit['title']}」关键词「{hit['keyword']}」→ {hit['fix']}")
            if hit["level"] == "forbidden":
                err(msg)
            else:
                warn(msg)

    meta = project.get("meta") or {}
    scan(f"标题「{meta.get('title', '')}」", meta.get("title"))

    for c in project.get("characters") or []:
        cid = c.get("id", "?")
        for field in ("appearance", "desc", "image_prompt"):
            scan(f"角色 {cid}.{field}", c.get(field))
        for of in c.get("outfits") or []:
            scan(f"角色 {cid}.outfits[{of.get('id', '?')}]", of.get("desc"))

    for s in project.get("scenes") or []:
        sid = s.get("id", "?")
        for field in ("desc", "anchor_en"):
            scan(f"场景 {sid}.{field}", s.get(field))

    for ep in project.get("episodes") or []:
        eid = ep.get("id", "?")
        for field in ("title", "logline", "hook", "cliffhanger"):
            scan(f"{eid}.{field}", ep.get(field))
        for shot in C.shots_of(ep):
            sid = shot.get("id", f"{eid}-?")
            for field in ("action", "action_en", "video_action_en", "narration"):
                scan(f"{sid}.{field}", shot.get(field))
            for prop in shot.get("props") or []:
                scan(f"{sid}.props", prop)
            dlg = shot.get("dialogue") or {}
            scan(f"{sid}.dialogue", dlg.get("text"))


def check_prompt_quality(project: dict) -> None:
    """提示词质量 lint（词库见 production.json 的 prompt_quality，命中记 WARN）。

    只扫会流入提示词的人工字段：镜头 action/action_en/video_action_en/
    lighting、场景 desc/lighting、角色锚点（含年龄段）与服装描述。
    不扫脚本自动拼装的风格后缀（其后缀本身含"质感"等合法 token）。
    空泛词按 cinematic-dictionary.md 第六节改写；否定句改正向约束
    （prompt_recipes.md 原则 6：视频模型对否定句执行不稳定）。
    """
    pq = C.load_presets()["production"].get("prompt_quality") or {}
    vague_zh = [w for w in pq.get("vague_words_zh") or [] if w]
    vague_en = [w.strip() for w in pq.get("vague_words_en") or [] if w.strip()]
    neg_zh = [w for w in pq.get("negation_words_zh") or [] if w]
    neg_en = [w.strip() for w in pq.get("negation_words_en") or [] if w.strip()]

    def hit_ascii(text_lower: str, word: str) -> bool:
        return re.search(r"(?<![a-z])" + re.escape(word.lower()) + r"(?![a-z])",
                         text_lower) is not None

    def scan(label: str, text) -> None:
        text = str(text or "")
        if not text:
            return
        low = text.lower()
        for w in vague_zh:
            if w in text:
                warn(f"{label} 含空泛词「{w}」，模型无法转译成画面，"
                     f"按 cinematic-dictionary.md 第六节改写为具体景别/光源/构图")
        for w in vague_en:
            if hit_ascii(low, w):
                warn(f"{label} 含空泛词「{w}」，改写为可见的画面描述")
        for w in neg_zh:
            if w in text:
                warn(f"{label} 含否定表述「{w}」，主提示词写正向约束，"
                     f"否定项走负面词通道（脚本已自动拼装）")
        for w in neg_en:
            if hit_ascii(low, w):
                warn(f"{label} 含否定表述「{w}」，改写为正向约束（should-do）")

    for c in project.get("characters") or []:
        cid = c.get("id", "?")
        scan(f"角色 {cid}.image_prompt", c.get("image_prompt"))
        for stg in c.get("stages") or []:
            scan(f"角色 {cid}.stages[{stg.get('id', '?')}]",
                 stg.get("image_prompt"))
        for of in c.get("outfits") or []:
            scan(f"角色 {cid}.outfits[{of.get('id', '?')}].desc", of.get("desc"))
    for s in project.get("scenes") or []:
        sid = s.get("id", "?")
        scan(f"场景 {sid}.desc", s.get("desc"))
        scan(f"场景 {sid}.lighting", s.get("lighting"))
    for ep in project.get("episodes") or []:
        eid = ep.get("id", "?")
        for shot in C.shots_of(ep):
            sid = shot.get("id", f"{eid}-?")
            for field in ("action", "action_en", "video_action_en", "lighting"):
                scan(f"{sid}.{field}", shot.get(field))


def check_assets(project: dict, root: Path) -> None:
    missing = 0
    total = 0
    for _ep, shot in C.iter_shots(project):
        for kind, rel in (shot.get("assets") or {}).items():
            if not rel:
                continue
            total += 1
            if not C.resolve_asset(root, rel):
                missing += 1
    if missing:
        warn(f"有 {missing}/{total} 个素材文件在磁盘上不存在（生成阶段可忽略）")


def main() -> None:
    ap = argparse.ArgumentParser(description="校验 project.json")
    ap.add_argument("project", nargs="?", help="project.json 路径或其所在目录")
    ap.add_argument("--strict", action="store_true", help="WARN 也视为失败")
    args = ap.parse_args()

    path = C.find_project(args.project)
    project = C.load_project(path)
    if not isinstance(project, dict):
        C.die("project.json 顶层必须是 JSON 对象")
    if project.get("meta") is not None and not isinstance(project["meta"], dict):
        C.die("project.json 的 meta 必须是对象")
    for key in ("characters", "scenes", "episodes"):
        if project.get(key) is not None and not isinstance(project[key], list):
            C.die(f"project.json 的 {key} 必须是数组")
    root = C.project_root(path)

    print(f"校验目标: {path}")
    check_meta(project)
    char_map, scene_map = check_references(project)
    genre_key = (project.get("meta") or {}).get("genre")
    if not isinstance(project.get("meta"), dict):
        project["meta"] = {}
    if genre_key in C.load_presets()["genres"]:
        check_shots(project, char_map, scene_map)
    check_review(project)
    check_prompt_quality(project)
    check_assets(project, root)

    print("-" * 60)
    print(f"结果: {len(ERRORS)} ERROR / {len(WARNS)} WARN")
    if ERRORS:
        print(f"错误 {len(ERRORS)} 项:")
        for e in ERRORS:
            print(f"  [ERROR] {e}")
    if WARNS:
        print(f"警告 {len(WARNS)} 项:")
        for w in WARNS:
            print(f"  [WARN ] {w}")
    if not ERRORS and not WARNS:
        print("校验通过，无错误无警告。")

    if ERRORS or (args.strict and WARNS):
        raise SystemExit(1)
    raise SystemExit(0)


if __name__ == "__main__":
    main()
