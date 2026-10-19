# project.json 数据模型

`project.json` 是**唯一数据源**：`init_drama.py` 生成它，Agent 填充它，`build_prompts.py` / `validate_project.py` / `preview.py` / `assemble.py` 全部读取它。不要在其他文件里保存分镜数据。

## 分片布局（长剧推荐）

50+ 集的单文件 project.json 会膨胀到数 MB。用 `split_project.py` 把分集拆出：

- `project.json`：只保留 `meta` / `config` / `characters` / `scenes`
- `episodes/E01.json`…：每集一个文件（完整分集对象，含 `shots`），读取时按自然序注入 `episodes`

所有脚本经 `load_project` / `save_project` 自动识别两种布局，**命令完全不变**；`split_project.py <路径> --merge` 合并回单文件。`project.json` 与 `episodes/` 同时存有分集属冲突状态，脚本会拒绝读取（须二选一清理）。

> 用 `import_script.py` 初拆剧本时，会生成 `characters[]` / `scenes[]` 占位（`appearance`、`image_prompt`、`anchor_en` 为空）并写入 `meta._import` 元数据；这些占位必须补全后才能通过 `validate_project.py`。

---

## 顶层结构

```jsonc
{
  "meta":    { ... },   // 项目元信息
  "config":  { ... },   // 从题材预设推导的制作参数
  "characters": [ ... ],// 角色卡
  "scenes":  [ ... ],   // 场景锚点
  "episodes": [ ... ]   // 分集 → 分镜
}
```

---

## meta

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `title` | string | 是 | 剧名 |
| `genre` | string | 是 | `genres.json` 的 key |
| `subgenre` | string | 否 | 子类型 |
| `style` | string | 是 | `styles.json` 的 key |
| `platform` | string | 是 | `production.json` 的 key |
| `aspect_ratio` | string | 是 | 默认 `9:16` |
| `language` | string | 是 | 默认 `zh-CN` |
| `logline` | string | 否 | 一句话故事 |
| `created_at` | string | 否 | ISO 日期 |
| `video_workflow` | string | 否 | 视频工作流：`"i2v"`（图生视频/首帧驱动，视频词只写运动）或 `"t2v-ref"`（文生视频+参考图，init 默认，视频词含主体/场景完整描述） |
| `prompt_lang` | string | 否 | 提示词语言：`"zh"`（中文为主，init 默认，剧梦等国内模型）或 `"en"`（英文，海外模型；--strict-en 仅 en 模式生效） |
| `review_whitelist` | string[] | 否 | 卡审豁免短语：关键词命中区间完全落在短语内则不报（如剧名「杀疯了」豁免后「杀」不再单独命中）；与 presets 的 `review_rules.text_whitelist` 合并生效 |
| `_import` | object | 否 | 剧本导入元数据（source/format/imported_at/warnings），脚本忽略 |

## config

| 字段 | 类型 | 说明 |
|---|---|---|
| `episode_count` | int | 总集数 |
| `episode_duration_sec` | int | 单集目标时长 |
| `shot_duration_sec` | float | 默认镜头时长（由 pacing 推导） |
| `hook_window_sec` | int | 前几秒必须出钩子，默认 3 |
| `reversal_every` | int | 每几集一次大反转 |
| `voice_locale` | string | 配音语言 |
| `subtitle_burned` | bool | 是否烧录字幕 |

---

## characters[]

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 是 | 大写字母代号，如 `LIN`，分镜用此引用 |
| `name` | 是 | 角色名 |
| `role` | 是 | protagonist / antagonist / supporting / extra |
| `age` / `gender` | 否 | 用于提示词 |
| `appearance` | 是 | 识别锚点（发色、发型、五官、体型） |
| `outfits` | 否（强烈建议） | 服装变体数组 `[{"id":"A","desc":"..."}]`；缺省时换装易漂移（WARN） |
| `personality` | 否 | 性格 |
| `motivation` | 否 | 动机（反派必填） |
| `visual_anchors` | 是 | 3 个可视觉化识别点，全剧不得改 |
| `voice` | 否 | `{"timbre":"","speed":1.0,"emotion":""}` |
| `image_prompt` | 是 | 定妆照英文提示词（主锚点） |
| `stages` | 否 | 跨年龄段的独立锚点 `[{"id":"child","label":"幼年5岁","image_prompt":"..."}]`；同一人物不同年龄段各用各的锚点，防止跨年龄换脸 |
| `negative_prompt` | 否 | 该角色专属负面词 |
| `seed` | 否 | 固定 seed |
| `ref_image` | 否 | 定妆照路径 |

---

## scenes[]

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 是 | 如 `S1` |
| `name` | 是 | 场景名 |
| `time` | 否 | 日/夜/黄昏 |
| `desc` | 是（zh 模式） | 中文描述；zh 模式下为场景锚点主字段，`build_prompts.py` 优先生效 |
| `anchor_en` | 是（en 模式） | 英文场景锚点短语，全剧逐字一致；en 模式必填，zh 模式仅作回退 |
| `lighting` | 否 | 场景默认光型（中文，给导演版用；夜外/特殊光效场景必填） |
| `lighting_en` | 否 | 场景光型的英文版（给图片/视频提示词用；缺省时英文提示词跳过光型，由风格后缀兜底） |
| `ref_image` | 否 | 场景参考图 |

---

## episodes[]

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 是 | `E01` |
| `title` | 否 | 集标题 |
| `logline` | 否 | 本集一句话 |
| `hook` | 是 | 前 3 秒的钩子描述 |
| `cliffhanger` | 是 | 结尾卡点 |
| `duration_sec` | 否 | 目标时长 |
| `bgm_prompt` | 否 | 本集 BGM 提示词（剧梦等音乐模型直接用）；缺省由 build_prompts.py 按题材情绪曲线+风格自动拼装 |
| `shots` | 是 | 镜头数组 |

### episodes[].shots[]

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 是 | `E01-S01` |
| `shot_no` | 是 | 集内序号，从 1 开始 |
| `beat` | 否 | 所属大分镜分组（同一连续剧情段的 shot 填同一个值，如 `"摔协议"`）。缺省时每个 shot 自成一个大分镜 |
| `scene_id` | 是 | 引用 `scenes[].id` |
| `characters` | 是 | 角色 id 数组，空数组表示空镜 |
| `character_stages` | 否 | 本镜使用的年龄段 `{"YHE":"child"}`；未指定的角色用主锚点 |
| `shot_size` | 是 | 景别，见 `shot_language.md` |
| `camera` | 是 | 运镜，**只能一个主运镜** |
| `composition` | 是 | 构图 |
| `lighting` | 否 | 本镜光型（中文，导演版用；缺省回落 `scenes[].lighting`，再回落风格） |
| `lighting_en` | 否 | 本镜光型的英文版（英文提示词优先用它；无则跳过光型） |
| `action_en` | 否 | 动作的英文版（英文图片提示词优先用它；`--strict-en` 下必填） |
| `video_action_en` | 否 | 视频专用英文运动描述（只写运动，不写静态画面；视频提示词优先用它） |
| `blocking` | 否 | 本镜站位/视线关系（如「A 画面左，B 画面右，隔着办公桌」）；对话戏必填；zh 视频提示词直接拼入 |
| `expression` | 否 | 本镜人物表情/微表情（如「眼眶泛红，嘴角带笑」）；zh 视频提示词以「表情：」段拼入 |
| `action` | 是 | 画面动作描述 |
| `dialogue` | 否 | `{"character":"LIN","text":"...","emotion":"克制","delivery":"声线稳定，句尾放轻"}`，无对白省略 |
| `narration` | 否 | 旁白文本 |
| `props` | 否 | 本镜出现的剧情道具名数组（如 `["离婚协议","钢笔"]`），用于导演版资产槽 |
| `showcase` | 否 | 炫技镜头技术类型（如 `"FPV穿越"`、`"子弹时间"`、`"希区考克变焦"`），标注即视为视觉名场面；每集 3 个，见 `narrative.md` 3+N 法则 |
| `vfx` | 否 | 视觉特效描述（UI、魔法效果、文字特效、色调转换等），多数镜头留空 |
| `sfx` | 否 | 音效 |
| `duration_sec` | 是 | 时长，**0.5-30 秒**（超 30 秒必须拆镜） |
| `transition_in` | 否 | 入场转场，默认 `硬切` |
| `scene_marker` | 否 | 换场景标识。`scene_id` 变化时设 `true`，否则系统误判卡审 |
| `notes` | 否 | 标记 `foreshadow` / `callback` / `payoff` |
| `outfits` | 否 | 按角色指定服装变体 `{"LIN":"B","ZHAO":"A"}`；多角色换装用这个 |
| `outfit` | 否 | 单角色镜头的服装变体 id（多角色时会被忽略并 WARN，建议改用 `outfits`） |
| `image_prompt` | 否 | 留空则脚本自动生成 |
| `video_prompt` | 否 | 图生视频运动描述 |
| `audio_prompt` | 否 | 配音参数 |
| `status` | 否 | pending / image_done / video_done / done |
| `assets` | 否 | `{"image":"","video":"","audio":""}` |

---

## 最小可运行示例

> 下面的示例可直接通过 `validate_project.py` 与 `build_prompts.py --strict-en`（动作已补英文）。

```json
{
  "meta": {
    "title": "荆棘王冠",
    "genre": "revenge",
    "style": "cinematic-realism",
    "platform": "douyin",
    "aspect_ratio": "9:16",
    "language": "zh-CN",
    "logline": "被丈夫与闺蜜联手陷害的全职太太，三年后以合作方身份归来。",
    "created_at": "2026-10-16"
  },
  "config": {
    "episode_count": 1,
    "episode_duration_sec": 90,
    "shot_duration_sec": 2,
    "hook_window_sec": 3,
    "reversal_every": 3,
    "voice_locale": "zh-CN",
    "subtitle_burned": true
  },
  "characters": [
    {
      "id": "LIN",
      "name": "林晚",
      "role": "protagonist",
      "age": "28",
      "gender": "女",
      "appearance": "black long straight hair, amber eyes, fair skin, sharp jawline",
      "outfits": [{"id": "A", "desc": "beige trench coat over white shirt, black trousers"}],
      "motivation": "拿回被夺走的一切",
      "visual_anchors": ["黑色长直发", "琥珀色眼眸", "左手银戒"],
      "voice": {"timbre": "清冷御姐", "speed": 1.05, "emotion": "克制"},
      "image_prompt": "a young woman with black long straight hair, amber eyes, fair skin, sharp jawline",
      "seed": 20261016
    },
    {
      "id": "ZHAO",
      "name": "赵衡",
      "role": "antagonist",
      "age": "32",
      "gender": "男",
      "appearance": "short black hair, thin framed glasses, narrow eyes, tall build",
      "outfits": [{"id": "A", "desc": "navy three-piece suit, silver tie clip"}],
      "motivation": "保住公司控制权",
      "visual_anchors": ["银丝眼镜", "海军蓝三件套", "左手腕表"],
      "voice": {"timbre": "低沉男声", "speed": 1.0, "emotion": "冷漠"},
      "image_prompt": "a tall man with short black hair, thin framed glasses, narrow eyes",
      "seed": 20261017
    }
  ],
  "scenes": [
    {
      "id": "S1",
      "name": "林家老宅客厅",
      "time": "夜",
      "desc": "昏暗的老宅客厅，红木家具，泛黄墙上的全家福，头顶一只白炽灯泡",
      "anchor_en": "dimly lit living room of an old Chinese family house, mahogany furniture, yellowed family photos on the wall, single hanging incandescent bulb, night"
    }
  ],
  "episodes": [
    {
      "id": "E01",
      "title": "离婚协议",
      "logline": "林晚被逼签下离婚协议，却发现丈夫口袋里藏着另一份文件。",
      "hook": "赵衡把离婚协议摔在林晚脸上，她没哭，反而笑了",
      "cliffhanger": "林晚从丈夫西装里抽出一份股权转让书，抬头看向镜头",
      "duration_sec": 90,
      "shots": [
        {
          "id": "E01-S01",
          "shot_no": 1,
          "beat": "摔协议",
          "scene_id": "S1",
          "characters": ["LIN", "ZHAO"],
          "shot_size": "中景",
          "camera": "手持",
          "composition": "三分法",
          "action": "赵衡把离婚协议摔在桌上，林晚站着没动，指尖按住纸张",
          "action_en": "the man slams the divorce papers onto the table, the woman stands still, her fingertips pressing the paper",
          "video_action_en": "the papers hit the table and slide, she does not flinch",
          "dialogue": {"character": "ZHAO", "text": "签了，你净身出户。", "emotion": "冷漠", "delivery": "语速平缓，尾音下沉"},
          "props": ["离婚协议"],
          "sfx": "纸张拍桌",
          "duration_sec": 3,
          "transition_in": "硬切",
          "notes": "foreshadow",
          "status": "pending",
          "assets": {"image": "", "video": "", "audio": ""}
        },
        {
          "id": "E01-S02",
          "shot_no": 2,
          "beat": "摔协议",
          "scene_id": "S1",
          "characters": ["LIN"],
          "shot_size": "特写",
          "camera": "推",
          "composition": "中心构图",
          "action": "林晚嘴角慢慢上扬，眼神由灰暗转为冷厉",
          "action_en": "the corner of her mouth rises slowly, her eyes turn cold",
          "video_action_en": "her gaze lifts gradually to the lens",
          "narration": "三年后我才知道，这一晚是我求来的。",
          "duration_sec": 4,
          "transition_in": "硬切",
          "notes": "foreshadow",
          "status": "pending",
          "assets": {"image": "", "video": "", "audio": ""}
        }
      ]
    }
  ]
}
```

---

## 校验规则（validate_project.py 实现）

1. `meta.genre` / `meta.style` / `meta.platform` 必须是预设库合法 key
2. 角色 `id` 唯一；分镜引用的角色必须存在
3. 分镜引用的 `scene_id` 必须存在
4. 每集镜头时长总和与目标（优先 `episodes[].duration_sec`，否则 `config.episode_duration_sec`）偏差 ≤20%（超出报 ERROR，须拆镜补足或调整目标）
4a. 每个镜头 `duration_sec` 在 0.5-30 秒之间
4b. 长镜头（>10s）每集最多 1 个，且不在第 1 集（WARN）
4c. 换场景（`scene_id` 变化）时新镜头须带 `scene_marker: true`（WARN）
4d. 大分镜（`beat` 分组）总时长 ≤30 秒（ERROR）；beat 内单镜 >5 秒（WARN，小镜纪律 1-5s）；beat 跨场景（WARN，通常应拆分）
4e. 每集必须 3 个 `showcase` 炫技镜头（3+N 法则，WARN）；超过 3 个也 WARN（名场面过密会稀释）
4f. 大分镜口播检查：beat 内「对白+旁白」字数 ÷ 4 > beat 时长 → WARN（VO 会压到后续镜头，需扩画面或跨镜分布）
4g. `character_stages` 引用校验：角色不存在 → ERROR；年龄段不存在 → ERROR；角色未定义 stages → WARN
4h. 中英混排：`build_prompts.py --strict-en` 下图片/视频提示词含中文 → ERROR（补 `action_en`）；`validate_project.py` 对已存的 `image_prompt` 含中文记 WARN
4i. 镜头 `id` 集内或跨集重复 → ERROR；`shot_no` 缺失/非整数或不连续 → WARN
4j. 阈值可配置：角色数 > `limits.max_characters`、场景数 > `limits.max_scenes` → WARN；口播按 `limits.cjk_chars_per_sec` 核算
4k. `duration_sec` 非数字 → ERROR；`config.episode_duration_sec` 非正数 → ERROR（不再触发除零崩溃）
4l. `shots[].outfits` 必须是角色→服装 id 映射，引用的角色/服装必须存在 → 否则 ERROR；单值 `outfit` 用于多角色镜头 → WARN
4m. 单镜 `characters` 超过 2 人 → WARN（多人用全景 + 固定站位）
5. 每集必须有 `hook` 与 `cliffhanger`
6. `image_prompt` 可留空，由 `build_prompts.py` 补全；`scene_id`/`shot_size`/`camera`/`composition`/`action`/`duration_sec` 缺失 → ERROR
7. 单句对白 >20 字 → 警告（中文计汉字，英文计单词）
8. 同一场景连续 >8 镜 → 警告
9. `assets` 指向的文件不存在 → 警告（生成阶段可忽略）
10. 出现题材 `taboo` 关键词 → 报错
11. 命中卡审规则（`review_rules.json`）：forbidden → 报错，avoid → 警告
