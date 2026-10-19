# 提示词配方

本文件定义图像 / 视频 / 配音 / 导演版提示词的拼装公式。`scripts/build_prompts.py` 实现了其中可确定的部分；创作性部分（动作、情绪）由 Agent 填写。

---

## 一、通用原则

1. **语言跟随 `meta.prompt_lang`（默认 `"zh"` 中文为主，剧梦等国内工作流）**。zh 模式锚点/动作/光型用中文原值，风格后缀取 `prompt_suffix_zh`，允许中英混排（`50mm 镜头`）；`"en"` 模式用于海外模型，要求纯英文，`--strict-en` 拦截中文残留。模型适配差异见 `references/model_adapters.md`。
2. **单条提示词上限 15000 字（字符）**，默认 150-400 词。需要极精细控制（多人物站位、复杂场景、指定构图与材质）时可写到 1000-3000 词；超长提示词必须分层组织，不要堆形容词。
3. **固定 token 前置**：角色锚点(含服装) → 场景锚点 → 景别 → 镜头/景深 → 构图 → 画幅 → 动作 → 光线 → 风格后缀 → 画质后缀。画幅 token（竖屏 9:16 画幅）由脚本按 `meta.aspect_ratio`/平台自动拼入，与生成工具里的画幅选择构成双保险。
4. **一致性优先**：同一角色、同一场景，其"锚点短语"必须逐字一致，只改变化的部分。
5. **负面提示词必须带**：`production.json` 与 `styles.json` 的 negative 字段已由脚本拼好，不要手写。
6. **正向约束优先**：视频模型对否定句执行不稳定。主提示词写"应该保持什么"（如"摄影机固定在三脚架上，全程保持完全相同的位置、方向和构图"），不要反复写"不要什么"；否定项统一走负面提示词通道。正向约束词库见 `references/cinematic-dictionary.md` 第七节；`validate_project.py` 会对人工字段里的空泛词与否定句记 WARN（词库在 `production.json` 的 `prompt_quality`）。
7. **抽象概念必须转译**：压迫感、电影感、高级感这类词 AI 不会自动翻译成画面——按 `cinematic-dictionary.md` 的表格转成位置、动作、光线结果、起止状态，或直接弃用（空泛词改写表）。validate 的质量 lint 会直接点名这些词。
8. **跨年龄角色用 `stages`**：同一人物幼年 / 少年 / 成年各有独立英文锚点（`characters[].stages`），分镜用 `shots[].character_stages` 指定；禁止用同一张脸硬套不同年龄段，那是换脸级事故。

### 长提示词分层写法（>500 词时使用）

```
[层1 画风]      one style token block
[层2 场景]      location, time, weather, architecture, props
[层3 角色]      per character: anchor + outfit + posture + position in frame
[层4 构图运镜]  shot size, camera move, lens, composition, depth of field
[层5 光线色彩]  light source, direction, ratio, color grading
[层6 情绪氛围]  mood, tension, narrative beat
[层7 画质]      quality tokens
```

**长度不是质量。** 超过 3000 词仍说不清的，问题在描述结构不在字数。`build_prompts.py` 会在超过 15000 字时报错并列出超长条目。

---

## 二、图像提示词公式（角色镜头）

```
[角色锚点, 服装变体] , [场景锚点] , [景别] , [镜头/景深] , [构图] , [画幅] , [动作] , [光线] , [风格后缀] , [画质后缀]
```

**本顺序即 `build_prompts.py` 的拼装顺序，全剧逐镜一致**：固定 slot 一个不能少、不能换序。光线缺省时自动取 `styles.json` 的 `lighting`（光型必须与风格一致，见 `shot_language.md` 第四节）。景别自动联动镜头参数（`LENS_EN`：大远景/远景配广角深景深，中近景/特写配 85mm 浅景深，大特写配 100mm 微距）；中文光型自动经 `LIGHT_EN` 译为专业光效术语（逆光→backlit rim light、丁达尔→volumetric god rays 等），未收录的光型由风格后缀兜底。

**角色锚点**（全剧固定，逐字一致）：
```
{a young woman|an elderly man} , {black long straight hair|gray buzz cut} , {amber eyes|deep-set eyes} , {fair skin, sharp jawline}
```
写一次，之后所有镜头复制粘贴，只改后面的部分。

**服装变体**用固定编号，例：
```
outfit A: beige trench coat over white shirt, black trousers
outfit B: dark navy qipao, jade hairpin
```

**场景锚点**（同一场景固定）：
```
S1: dimly lit living room of an old Chinese family house, mahogany furniture, yellowed wall photos, single hanging bulb, night
```

**场景定妆照**（build_prompts.py 自动生成，每场景一张）：无人物的空场景母版，先出图人工确认空间/陈设/光型/时段，再批量生成该场景的镜头图；可直接当空镜首帧或垫图。负面词自动附加"无人"约束。

**示例**（完整可抄，字段顺序即标准输出）：
```
a young woman with black long straight hair, amber eyes, fair skin, sharp jawline, wearing beige trench coat over white shirt, dimly lit living room of an old Chinese family house, mahogany furniture, yellowed wall photos, single hanging bulb, night, medium close-up, three-quarter angle, she grips a divorce contract in her right hand, jaw clenched, eyes downcast, dramatic chiaroscuro lighting, photorealistic cinematic still, 35mm anamorphic lens, shallow depth of field, real skin texture, subtle film grain, ultra detailed, 8k
```

---

## 三、视频提示词公式（两种工作流，`meta.video_workflow` 二选一）

### 模式 A：图生视频 / 首帧驱动（`"i2v"`，默认）

```
[运镜] , [单镜头纪律] , [动作] , [转场] , [风格后缀] , [时长]
```

只描述运动，不重复静态描述（首帧已带，重复会触发模型改脸）。

### 模式 B：文生视频 + 参考图（`"t2v-ref"`，剧梦等"文生+参考图"工作流用这个）

```
[主体锚点+服装] , [场景锚点] , [景别/镜头] , [构图] , [光线] , [运镜] , [单镜头纪律] , [站位] , [动作] , [表情：] , [台词：] , [音效：] , [BGM：] , [特效：] , [转场] , [风格后缀] , [时长]
```

**无首帧，静态描述必须并入**：主体/场景/景别/光线由提示词完整交代，参考图只负责"人是谁"（上传人物定妆照）。静态层与图片提示词**同源同字**（同一 `char_scene_parts`），保证视频与首帧图形象一致。主体/场景描述会拉长提示词——这是模式 B 的必要成本，不要为了"精简"删掉锚点，删了必换脸。

**zh 模式全要素标签段**（剧梦视频支持台词口型/音效/BGM，字段留空自动跳过）：`站位`（`blocking` 原文）→ `表情：`（`expression`）→ `台词：{角色名}说：「{原文}」（{情绪}）`（`dialogue`，逐字不改）→ `音效：`（`sfx`）→ `BGM：`（每集 BGM 提示词首句质感段）→ `特效：`（`vfx`）。标签段固定在动作之后、转场之前。

**本顺序即 `build_prompts.py` 的拼装顺序，全剧逐镜一致**：固定 slot 一个不能少、不能换序。手工覆盖 `shots[].video_prompt` 时同样遵循本顺序。运镜词表见 `CAMERA_EN`（含急推/急拉/变焦/升格/延时等）；脚本在运镜后自动追加 `single continuous take, no cuts`（单镜头纪律），防止视频模型中途切镜头导致人物形象漂移。

**关键规则**：

- 模式 A 下**不重复首帧已有的静态描述**（脸、服装、场景），只写"发生什么变化"。
- 模式 B 下静态层照写（见上），但**动作仍只描述一个主运动**。两个以上运动会互相打架。
- 动作必须可执行：`her hand trembles slightly as she signs` ✓；`she is conflicted and emotional` ✗（情绪不是动作）。
- 模式 A 的运动描述控制在 80 词内；模式 B 静态层 + 运动合计尽量 ≤150 词。

**示例**（脚本标准输出，模式 A）：
```
static camera, single continuous take, no cuts, her eyes lift slowly from the contract to meet the lens, hard cut at the end, photorealistic cinematic footage, 35mm anamorphic lens, shallow depth of field, real skin texture, subtle film grain, ultra detailed, 8k, 3 seconds
```

需要更细控制时，可在动作后追加细微变化（呼吸、环境动势、光线闪烁），但仍保持"运镜 → 动作 → （变化）→ 转场 → 风格后缀 → 时长"的顺序骨架：
```
static camera, her eyes lift slowly from the contract to meet the lens, breath visible in cold air, the hanging bulb sways slightly, single cold key light flickers, hard cut at the end, photorealistic cinematic footage, 3 seconds
```

---

## 四、中文导演版分镜提示词（新标准）

> **自本版本起，导演分镜以 `references/director_storyboard_format.md` 为准：**
> - 分镜段 4-15 秒，标注本段时长 / 累计时长
> - 台词零修改，项目小镜拆开的台词合并回原文
> - 每集 3 个炫技段 + N 个正常叙事段
> - 景别用 全景 WS / 中景 MS / 近景 MCU / 特写 CU / 大特写 ECU / 过肩 OTS
> - 每段含人物资产、人物音色、场景资产、道具资产空槽；动作/表情/情绪/站位/运镜/焦段/光影/台词/音效/BGM 独立字段
>
> 本节以下“大分镜/小分镜 + 资产槽”为旧版素材层说明，保留用于项目内部拆镜与资产准备，不再作为最终导演分镜输出格式。

面向即梦 / Seedance 等中文视频工作流与人工审阅。旧版字段顺序如下，仅作内部参考。

### 1. 两级结构

- **大分镜** = 同一 `beat` 的连续镜头，一个连续剧情段，**≤30 秒**（硬规则，`validate_project.py` 报错）
- **小分镜** = 单机位单景别镜头，**1-5 秒**（纪律，超 5s 记 WARN）
- 15s 大分镜通常拆 3-4 个小分镜；16-24s 拆 4-6 个；25-30s 拆 5-7 个
- 跳时或换景通常拆成下一条大分镜；换场景镜头带 `scene_marker: true`

### 2. 大分镜头部

- （）标注：总对话+内心OS 字数与所需时间（按 **`production.json` 的 `limits.cjk_chars_per_sec`，默认 4 字/秒**）
- 集头总览：总时长/偏差、大分镜与小分镜数量、炫技清单、钩子与卡点
- 标题带「建议时长」与整集「累计至 XXs」；小分镜标题带 `[起–止s]` 时间区间
- 炫技镜头在小分镜标题追加「炫技·技术类型」（来自 `shots[].showcase`）
- 资产槽：人物 A/B…、人物音色、场景 A/B…、道具 A/B…，等号后一律留空 `[]`，由使用者自填人物图 / 音色 / 场景图 / 道具图

### 3. 小分镜六要素（顺序固定）

```
【主体】【空间位置】【动作/剧情】【场景/环境】【光影氛围】【镜头语言】
```

**画面细节四要素**（每个要素至少要落实一项，靠调用 `cinematic-dictionary.md` 的词汇落地）：
- 光影方向：光从哪来、亮部与阴影分别落在什么上（光型走三级回退：镜 → 场景 → 风格，见 `shot_language.md` 第四节）
- 材质纹理：皮肤汗水、金属反光、潮湿地面、织物褶皱等可见表面
- 动态轨迹：推拉摇移的起止、主体运动的路径与速度
- 环境细节：天气、使用痕迹、空气介质（雨/雾/灰尘/烟）

有台词的小分镜，在标题后加**独立字段**，不混入视觉条目：

```
【人物台词】角色名｜情绪：克制｜表达：声线稳定，句尾放轻："台词原文。"
```

**台词零修改（硬规则）**：「台词原文」必须与剧本逐字一致，语气词、标点一个都不能改。剧本阶段你可以随意改写对白；进入分镜后，台词只能原样搬运。

（情绪与表达取自 `shots[].dialogue.emotion` / `.delivery`，缺省则只留角色名和原文）

有 `sfx` / `vfx` 的小分镜，在六要素后各加一行 `- 【音效】…` / `- 【特效】…`（不进视觉要素，视觉纯度边界见下一小节）。

**每个小分镜都要有独立的【本镜资产】**（一镜一资产）：按本镜实际出场，逐条列出人物（含年龄段）、说话人的音色、场景、道具，等号后留空 `[]`。大分镜头部的资产槽只做汇总，逐条准备参考素材以【本镜资产】为准。批量清单见 `04_prompts/asset_manifest.md`（`.csv` 同内容），每镜一行（覆盖该镜图片/视频/配音所需素材），参考文件列自填。

```
【本镜资产】人物A（苏建业）=[]｜人物A音色=[]｜场景A（青雾岭山脚老松树·夜）=[]｜道具A（襁褓）=[]
```

每条大分镜结尾固定输出：

```
【风格/画质】<风格后缀中文>
【约束】人物身份、服装、空间布局、道具、光源方向和画面轴线保持一致；只有指定人物运动；单画面清晰人物不超过2人；一个连续、无剪切的镜头。
```

### 4. 视觉纯度边界（画面提示词只写摄像机可见内容）

**可以写入**：时间/天气/地点/可见环境；人物外貌、服装、站位、朝向、遮挡关系；动作起点、路径、速度、力度、结束状态；眉眼、嘴角、下颌、手指、肩颈、呼吸等可见表演；景别、机位、构图、运镜、焦点、景深；光源方向、色温、明暗、阴影、反射、雾、雨、灰尘；材质、色彩、画幅、清晰度；"画面中无字幕、无文字、无水印、无额外人物"等可见的缺失状态。

**不得写入**：台词原文、旁白、内心 OS、声音、语气、音色、环境音、音效、配乐（只进【人物台词】与资产槽）；字数统计、口播时长估算、剧情总结、情绪解释、戏剧功能说明；"请生成""确保生成正确"等操作指令；摄像机看不到的心理活动、动机、因果解释；文件链接与教学说明。

### 5. 中文格式与英文提示词的对应

| 导演版字段 | `project.json` 字段 | 英文提示词 slot |
|---|---|---|
| 【主体】 | `characters` + `props` | 角色锚点(含服装) |
| 【空间位置】 | `scene_id` + `composition` | 场景锚点 → 构图 |
| 【动作/剧情】 | `action` | 动作 |
| 【场景/环境】 | `scenes[].desc` | 场景锚点 |
| 【光影氛围】 | `lighting`（缺省取风格光型） | 光线 |
| 【镜头语言】 | `shot_size` + `camera` | 景别 → 镜头/景深 |
| 【风格/画质】 | `meta.style` | 风格后缀 → 画质后缀 |
| 标题「炫技·类型」 | `showcase` | 写进 `camera` / `action` 的运动描述 |
| 【音效】/【特效】 | `sfx` / `vfx` | 不进英文提示词，音频与特效另行生成 |
| 【约束】 | 固定约束块 | 负面词通道 + 正向约束 |

两套格式消费的是**同一批字段**：改 `action`，英文图片提示词与中文导演版同步变。

---

## 五、首尾帧工作流（推荐）

1. 生成首帧图（用第二节公式）→ 人工挑选
2. 用同一张图 + 第三节公式生成 3-5 秒视频
3. 需要长镜头时：用尾帧再生成下一段（保持 seed 与风格后缀一致）

尾帧必须由视频的最后一帧导出，不要重新生成（否则跳变）。

---

## 六、角色一致性策略（三选一）

| 方案 | 做法 | 适用 | 风险 |
|---|---|---|---|
| A. 固定 seed + 锚点 | 同一 seed、同一锚点短语、同一负面词 | 无参考图能力时 | 中等，需抽检 |
| B. 角色参考图（首选） | 用 1-3 张定妆照做 image prompt / reference | 支持参考图的模型 | 低 |
| C. 训练角色 LoRA / 角色 ID | 用 20-40 张同一角色图训练 | 长剧、重要角色 | 最低但成本高 |

**规则**：一旦选定方案，全剧不得切换。换装必须用"换服装描述，不改锚点"的方式。

**定妆照（复合参考图，默认方案）**：一张图承载全部身份信息——**左半边大头照 + 右半边三视图（无脸）**（正/侧/背并排，头到脚完整，双臂微离身体）。三视图无脸的原因：小尺寸人脸上的五官必然崩坏，且会与左侧大头照的脸冲突；身份由大头照承担，三视图只负责体型/服装/比例。`build_prompts.py` 在 `image_prompts.md` 顶部的「人物形象参考」区按角色自动生成（`character_sheet_prompt()`，锚点缺失或含中文时跳过）。需要更强身份锁定时再补拍 3/4 侧面特写与动态姿势全身各 1 张；同一光位同一背景，确保只有脸和服装在变。

---

## 七、配音 / 音效 / BGM 提示词

### 配音（TTS）
```
[音色] + [语速] + [情绪] + [停顿] + [重音标记]
```
- 例：`清冷女声，语速 1.05，克制压抑，句间停顿 0.3s，"我签"二字加重`
- 每个角色的音色在 `project.json` 的 `characters[].voice` 里定义，全剧不得更换
- 情绪词只用：平静 / 克制 / 愤怒 / 哽咽 / 冷漠 / 颤抖 / 强势 / 疲惫 / 欣喜 / 沙哑
- 配音语速建议 1.0-1.15；中老年向题材降到 0.9
- 单镜台词的**情绪与表达方式**写在 `shots[].dialogue.emotion` / `.delivery`，导演版输出为独立的【人物台词】字段，不进画面提示词

### 音效（SFX）
按镜头写，每条 ≤8 字：`钥匙落地`、`玻璃碎裂`、`心跳声渐强`、`雨声`、`手机震动`。
音效必须与动作同帧，宁缺毋滥。

### BGM
- 每集 1 条主 BGM，最多 2 段情绪切换；`build_prompts.py` 在 `audio_prompts.md` 里按集输出 BGM 提示词（剧梦等音乐模型直接可用）——优先取 `episodes[].bgm_prompt` 手工定制，缺省按题材情绪曲线 + 风格自动拼装（质感 + 情绪走向 + 节奏 + 时长 + 编排约束）
- 情绪切换点放在反转前 1 秒，不要切在动作中间
- 反转成功时抽掉 BGM（静音 0.5-1s）是性价比极高的手法

---

## 八、常见崩坏与规避写法

| 崩坏 | 规避写法 |
|---|---|
| 手部畸形 | 画面里不出现手，或只拍到手背/握拳；避免手指张开特写 |
| 多人物混淆 | 单镜头 ≤2 人；多人用全景 + 固定站位，不切近景 |
| 文字乱码 | 不在画面里生成文字；所有文字后期加 |
| 换镜头变脸 | 锚点短语逐字一致 + 固定 seed；换装不改脸 |
| 口型不同步 | 优先"侧脸/背影/中远景"说话；近景说话用"说完再切" |
| 连续镜头跳变 | 用上一镜尾帧做下一镜首帧 |
| 动作夸张失真 | 运动描述改为"微小动作"（tremble / clench / glance） |
| 风格漂移 | 风格后缀全剧复制粘贴，禁止改写 |
| 情绪不会演 | 情绪词一律转可见微动作（面部/手部/姿态/视线/呼吸五维），对照表见 `cinematic-dictionary.md` 第三节 |
| 空泛词无效 | "电影感/高级感/戏剧性"等删除，改写成具体景别、光源、运镜与结束构图，见 `cinematic-dictionary.md` 第六节 |

---

## 九、负面提示词（脚本自动拼装）

- 基础负面：`production.json` 与 `styles.json` 中的 `negative_extra_*`
- 视频额外负面：morphing face / temporal inconsistency / identity swap / jitter
- 场景额外负面（如食品题材）：`disgusting, mold, rotten`

不要在负面词里写"text"以外的长句，负面词越长，主提示词越弱。
