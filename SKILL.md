---
name: ai-short-drama
description: AI 短剧端到端制作技能。覆盖题材自动配置、分集大纲、剧本、角色人设、分镜表、图片/视频/配音提示词、素材批量生成与 ffmpeg 成片合成。当用户要求创作、改编或制作 AI 短剧、竖屏微短剧、连载爽剧、网剧、品牌短剧，或需要剧本、分镜表、生成提示词、成片时使用本技能。
---

# AI 短剧制作

把一句需求或一份现成剧本变成可发布的竖屏短剧。核心原则：**一个数据源（`project.json`）、一套预设参数库（`assets/presets/`，含 33 题材 / 26 风格 / 平台参数 / 卡审规则 / 提示词质量词库）、八个可复用脚本（另附 `selftest.py` 自检）、十三份方法论文档**。

---

## 一、快速开始

### 路径 A：一句话需求（自动配置）

按 `references/genres.md` 的流程自动推断题材、风格、平台，然后初始化项目：

```bash
python <skill>/scripts/init_drama.py --title "荆棘王冠" --brief "重生复仇题材，写实电影感，发抖音" --out .
```

脚本会：
- 从 `assets/presets/genres.json`（33 个题材）匹配题材
- 从 `assets/presets/styles.json`（26 种视觉风格）裁定风格
- 从 `assets/presets/production.json` 匹配平台与竖屏安全区
- 推导集数、单集时长、镜头时长、反转节奏
- 生成完整项目目录与 `project.json`
- 渲染 `01_script/outline.md`、`01_script/E01.md`、角色卡/分镜模板（占位符已替换）

**必须**把推断结果（题材/风格/平台/集数/时长）明确告知用户，允许一句"换成 X"覆盖。绝不静默决定题材方向。

### 路径 B：现成剧本 / 小说（先拆书，再分镜）

用户直接扔剧本、小说或片段进来时，按 `references/script_analysis.md` 做**分析理解**（主线/支线/时间线、人物关系、金手指与爽点、情绪曲线），把分析结论与用户指定片段交给路径 A 的需求确认流程；**等用户说"生成那一片段的分镜"再逐镜拆解**。本阶段不续写、不改写、不生成正文。

分析确认后，如需先把文本落成结构骨架，可运行 `import_script.py`（集/场/镜/对白/动作初拆）；它只做结构解析，不替代拆书分析，角色与场景会生成待补全占位。

```bash
python <skill>/scripts/init_drama.py --title "剧名" --out .
python <skill>/scripts/import_script.py 剧本.docx --project "剧名"
# 也支持 .txt / .md / .fountain；自动初始化：
# python <skill>/scripts/import_script.py 剧本.docx --out . --title "剧名"
```

> 台词默认不拆、不改；长对白导入时加 `--max-shot-sec 15`，否则单镜时长可能不够。需要旧版“≤20 字拆句”时显式加 `--split-dialogue`。

---

## 二、工作流程（十步）

| # | 步骤 | 动作 | 参考 |
|---|---|---|---|
| 1 | 输入分析 | 一句话需求走自动配置；现成剧本走拆书分析。推断结果复述给用户 | `references/genres.md` / `references/script_analysis.md` |
| 2 | 初始化 | `init_drama.py`；现成剧本可加 `import_script.py` 做结构初拆 | 本文件 |
| 3 | 角色与场景 | 写角色卡（3 个视觉锚点 + 定妆提示词）、场景锚点 | `references/prompt_recipes.md` §6 |
| 4 | 大纲 | 分集表：每集钩子/任务/爽点/卡点 | `references/narrative.md` |
| 5 | 剧本 | 逐集剧本，过叙事自检 | `references/narrative.md` §8 |
| 6 | 分镜 | 逐镜写入 `project.json`；按 `beat` 分大分镜组 | `references/shot_language.md` |
| 7 | 校验 | `validate_project.py` | 本文件 §四 |
| 8 | 提示词 | `build_prompts.py` | `references/prompt_recipes.md` |
| 9 | 生成与审片 | 定妆照确认 → 批量首帧 → `enhance.py --upscale` 放大首帧 → 图生视频 → 尾帧衔接 → 路径写回 `assets` → `preview.py` | `references/production.md` §3-4、`references/model_adapters.md` |
| 10 | 合成 | `assemble.py` | `references/production.md` |

---

## 三、数据源：`project.json`

**所有分镜数据只存在 `project.json`。** 不要在别处保存分镜。字段定义、最小可运行示例与校验规则见 `references/schema.md`。

关键约束：
- `characters[].image_prompt`（识别锚点，zh 模式中文 / en 模式英文）全剧逐字一致，改脸的唯一元凶就是它被改写
- `scenes[].anchor_en`（en 模式）/ `scenes[].desc`（zh 模式）同理
- 换装用 `shots[].outfits`（`{"LIN":"B"}` 的角色→服装 id 映射）；旧字段 `shots[].outfit` 只在单角色镜头生效
- `episodes[].shots[].assets` 存素材相对路径，重跑脚本自动跳过已生成内容
- 每个镜头必须有：`scene_id`、`characters`、`shot_size`、`camera`、`composition`、`action`、`duration_sec`
- **导演分镜段**：连续小镜按 **4-15 秒**重组为导演分镜段，标注“本段时长 / 本集累计时长”；每个分镜段台词**逐字不改**。项目里的 1-5 秒小镜只作为素材层。导演分镜必须遵循 3+N（每集 3 个炫技段 + N 个正常叙事段），完整标准见 `references/director_storyboard_format.md`

---

## 四、脚本

均在 `<skill>/scripts/`，需要 Python 3.10+（仅标准库）与 ffmpeg 6+（需 libx264/aac）。Windows 可 `winget install Python.Python.3.12`、`winget install Gyan.FFmpeg`（或从 gyan.dev 下载便携版并把 `bin` 加入 PATH）；macOS 可 `brew install python ffmpeg`。装好后运行 `python scripts/selftest.py` 自检。

| 脚本 | 用途 | 常用参数 |
|---|---|---|
| `init_drama.py` | 初始化项目与目录；模板占位符自动渲染；可用 `--assets` 导入角色/场景 JSON | `--title --brief --genre --style --platform --episodes --duration --assets --out [--force]` |
| `import_script.py` | 把现成剧本/小说初拆为 `project.json` 骨架（集/场/镜/对白，角色/场景为占位）；支持 `.docx` / `.txt` / `.md` / `.fountain` | `<剧本> [--project 项目] [--out 父目录] [--title] [--episode E01] [--alias 别名=正名] [--format] [--force] [--dry-run]` |
| `validate_project.py` | 校验数据结构与叙事质量 + 提示词质量 lint（空泛词/否定句 WARN） | `[路径] [--strict]` |
| `build_prompts.py` | 批量生成图片/视频/配音提示词 + 一镜一资产清单 + 分镜表；图片/文生视频提示词自动带画幅 token；含人物定妆照与场景定妆照提示词；`--type director` 为旧版素材层分镜，最终导演分镜按 `references/director_storyboard_format.md` 整理 | `[路径] [--type image\|video\|audio\|director\|assets\|table\|all] [--force] [--strict-en] [--out]` |
| `enhance.py` | 素材增强：图片批量放大（首帧先放大再驱动视频）+ 视频尾帧提取（下一镜首帧） | `--upscale [--factor 2]` / `<视频> --last-frame [--out]` |
| `preview.py` | 生成单文件 HTML 分镜墙（支持图片/视频预览） | `[路径] [--out]` |
| `assemble.py` | ffmpeg 合成每集成片；字幕始终输出 `.srt` | `[--episode E01\|--all] [--no-subtitles] [--dry-run] [--keep-work]` |
| `split_project.py` | project.json 单文件 ↔ 分片布局互转（分片 = 每集一个 `episodes/E01.json`）；长剧（50+ 集）单文件数 MB 时拆分，所有脚本用法不变 | `[路径] [--merge]` |
| `selftest.py` | **开发自检**：合成数据跑通全链路（2 集正常链路 + 13 项异常用例 + 分片布局互转），改完技能即跑（不参与制作流程） | `[--keep]` |

补充：`init_drama.py --force` 只覆盖 `project.json`，已有剧本/模板/素材不会被清掉；`build_prompts.py` 的 `--type` 子集运行会与已有 `prompts.json` 合并（不清空其他类型），`--type all` 才是全量重建。

`<skill>` = skill 安装目录。`validate_project.py` 有 ERROR 时**必须**修完再进入生成阶段；`--strict` 下 WARN 也阻断。`validate_project.py` 与 `build_prompts.py` 均按 `assets/presets/review_rules.json` 强制执行卡审规则：forbidden 级必须改写，avoid 级出现时该集结尾须回正。

---

## 五、何时读哪个 reference

按需加载，不要一次全读：

| 情况 | 读 |
|---|---|
| 推断题材/风格/参数 | `references/genres.md` |
| **现成剧本/小说分析（拆书）** | `references/script_analysis.md` |
| 写剧本、钩子、卡点、对白 | `references/narrative.md` |
| 写分镜、选景别运镜 | `references/shot_language.md` |
| 对话戏覆盖、轴线、站位 | `references/dialogue-coverage.md` |
| 戏剧概念/表演/光影转译为可见画面 | `references/cinematic-dictionary.md` |
| 写提示词、做角色一致性 | `references/prompt_recipes.md` |
| 提示词贴到具体生成工具的适配（语言/工作流/参数） | `references/model_adapters.md` |
| 生成顺序、QC、合成、平台参数 | `references/production.md` |
| 内容红线、版权、广告法 | `references/compliance.md` |
| 平台卡审规则（forbidden/avoid 两级 + 替换指南） | `references/review_rules.md` |
| 整理导演版分镜（4-15 秒分镜段、资产槽、时间轴、3 个炫技段） | `references/director_storyboard_format.md` |
| 字段定义、示例 | `references/schema.md` |

`assets/presets/` 由脚本直接读取，不需要人工阅读；需要查看可用题材/风格清单时读对应 JSON 的 key 与 `name`。

---

## 六、硬约束

| 项 | 上限 | 执行者 |
|---|---|---|
| 单镜时长 | 0.5-30 秒（超 30s 必须拆镜） | `validate_project.py` 报错 |
| 大分镜时长（beat 分组） | ≤30 秒（一个连续剧情段） | `validate_project.py` 报错 |
| 单条提示词 | ≤15000 字 | `build_prompts.py` 报错并列出条目 |

## 七、质量门禁（不可跳过）

**剧本门禁**：每集前 3 秒有动作钩子；结尾是未完成动作/新信息；每 20 秒有信息增量；无连续 3 句纯对话；对白单句 ≤20 字；未命中题材 `taboo`。

**分镜门禁**：每镜必备字段齐全；运镜只有一个；镜头总时长与目标偏差 ≤20%；同场景同景别未连续超过 8 镜；每个大分镜（beat）总时长 ≤30s；小镜 1-5s；换场景带 `scene_marker`；对话戏先建地理后特写（见 `dialogue-coverage.md`）；每集 3 个炫技分镜段（`showcase`，3+N）。

**素材门禁**：先出定妆照（人物 + 场景）并确认"脸对/景对"，再批量；每集一次生成 6-8 张，抽检通过再继续；首帧先 `enhance.py --upscale` 放大再驱动视频；视频一次一镜，失败立即重抽。

**成片门禁**：无超过 2 秒空洞镜头；字幕无错别字无越界；结尾帧是卡点；时长符合平台区间。

---

## 八、硬规则

1. **一致性优先于单张好看。** 全剧只用一个 `prompt_suffix`；角色锚点短语禁止改写；换装只改服装描述。
2. **视频提示词只写运动。** 图生视频时重复静态描述（脸/服装/场景）会导致改脸。
3. **画面里不生成文字。** 所有文字后期加，否则必出乱码。
4. **单镜头 ≤2 人。** 多人用全景 + 固定站位。
5. **说话镜头避免近景正面。** 用侧脸/背影/中远景，或"说完再切"。
6. **风格漂移是最大的返工来源。** 批量前先抽 2-3 张测试图确认风格与人物。
7. **红线必须改写，不是模糊。** 见 `references/compliance.md` 的三步降级。
8. **不编造平台规则。** 具体平台最新审核标准以官方为准，交付前提醒用户人工复核。
9. **卡审规则由脚本强制执行。** forbidden 级（`review_rules.json`）出现即报错，必须改写；avoid 级出现时该集结尾必须回正。
10. **单集分镜拆满，单镜 ≤30 秒。** 分镜总时长与该集目标时长偏差必须 ≤20%（超出 `validate_project.py` 直接报错）；超 30s 的镜头直接报错。
11. **提示词格式全剧统一。** 图片提示词字段顺序固定为：角色锚点(含服装) → 场景锚点 → 景别 → 构图 → 画幅 → 动作 → 光线 → 风格后缀 → 画质后缀；视频提示词固定为：运镜 → 动作 → 转场 → 风格后缀 → 时长。由 `build_prompts.py` 机械拼装保证，固定 token（锚点/画幅/风格后缀/画质后缀）禁止手改。生成工具里的画幅选项与提示词画幅 token 双保险。
12. **换场景必须有标识。** `scene_id` 变化时新镜头带 `scene_marker: true`，否则系统误判卡审（`validate_project.py` WARN）。
13. **台词零修改。** 分镜 `dialogue.text` 必须与剧本逐字一致，语气词、标点一个都不能改；剧本阶段的改写自由在进入分镜时对台词终止。导演分镜里被小镜拆开的台词要合并回原文，不得补字、改标点。
14. **3+N 视觉名场面。** 每集必须规划 **3 个炫技分镜段**（`shots[].showcase` 标注技术类型），其余为 N 个正常叙事段；炫技位布置在情绪爆发、反转、道具揭晓、卡点节点。不足 3 个时标记“炫技位·待定”，不得静默省略。类型库见 `cinematic-dictionary.md` 第九节，规划方法见 `narrative.md` 第四节。
15. **导演分镜 4-15 秒。** 连续小镜按 4-15 秒重组为导演分镜段，标注本段时长与整集累计时长；单段超过 15 秒必须拆分。镜头术语统一：全景 WS / 中景 MS / 近景 MCU / 特写 CU / 大特写 ECU / 过肩 OTS。
16. **提示词以中文为主（`meta.prompt_lang`，默认 `"zh"`）。** zh 模式：锚点/动作/光型用中文原值，风格后缀取 `prompt_suffix_zh`，镜头/景深/构图用中文术语，允许中英混排（如 `50mm 镜头`）；锚点字段照样全剧逐字一致。`"en"` 模式（海外模型用）：锚点用英文，景别/运镜/构图/转场走内置英译表，动作必须补 `action_en`、视频运动补 `video_action_en`、光线补 `lighting_en`，`build_prompts.py --strict-en` 拦截中文残留。中文只留在导演版文档里（en 模式下亦然）。工具适配差异见 `references/model_adapters.md`。
17. **跨年龄角色用 `stages`。** 同一人物幼年/少年/成年各有独立英文锚点，分镜用 `character_stages` 指定；禁止同一张脸硬套不同年龄段。
18. **质量 lint 是提示词的守门员。** `validate_project.py` 按 `production.json` 的 `prompt_quality` 词库扫描人工字段：空泛词（电影感/高级感/masterpiece 等）必须改写成可见画面描述；否定句（不要/不要过亮）改写为正向约束。高提示词质量 = 高出图质量的前置条件。

---

## 九、交付物

一次完整交付包含：`project.json`、分集大纲与剧本（`01_script/`）、角色卡（`02_characters/`）、分镜表（`03_storyboard/E01.md`…，由 `build_prompts.py --type table` 生成，是 `project.json` 的人工编辑视图）、提示词清单（`04_prompts/`，含 `image/video/audio/director_prompts.md` 与 `prompts.json`/`prompts.csv`；`image_prompts.md` 顶部含**人物形象参考**（定妆照）与**场景参考**（场景定妆照：无人物空场景母版）；导演版为 4-15 秒分镜段 + 累计时间 + 景别/机位/运镜 + 人物资产/人物音色/场景资产/道具资产槽 + 站位/轴线 + 动作/表情/情绪 + 焦段/景深/光影 + 原样台词 + 音效/BGM + 视觉特效 + 每集 3 个炫技段；完整格式见 `references/director_storyboard_format.md`）、**一镜一资产清单**（`04_prompts/asset_manifest.md` 与 `.csv`，每镜一条资产记录：人物/音色/场景/道具 + 参考文件空位）、素材目录（`05_assets/`，首帧放大件带 `-2x` 后缀）、成片（`06_output/episodes/E01.mp4`…）、分镜墙（`07_preview/storyboard.html`）。

**只出文字时**（用户不生成图/视频/音频）：交付 `project.json` + 剧本 + 分镜表 + `director_prompts.md`（+ 按需的 image/video 提示词），跳过素材生成与合成两步。
