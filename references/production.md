# 制作 SOP 与质量控制

从"用户一句话"到"可发布成片"的完整流程。每一步都有入口判据与出口判据。

---

## 一、十步流程

| # | 步骤 | 动作 | 出口判据 |
|---|---|---|---|
| 1 | 需求确认 | 提取题材/风格/平台/集数，向用户复述确认 | 用户确认配置 |
| 2 | 初始化 | `python scripts/init_drama.py`；现成剧本可再跑 `import_script.py` 做结构初拆 | 生成 `project.json` 与目录 |
| 3 | 世界观与人物 | 写角色卡（识别锚点 + 定妆提示词） | 每个角色有 3 个视觉锚点 |
| 4 | 大纲 | 分集大纲，标出钩子/爽点/卡点/伏笔 | 每集有 hook 与 card |
| 5 | 剧本 | 逐集剧本，含对白 | 过 `references/narrative.md` 第八节自检 |
| 6 | 分镜 | 逐镜拆解，写满每镜必备字段 | 过 `scripts/validate_project.py` |
| 7 | 提示词 | `python scripts/build_prompts.py` | 生成 image/video/audio/director 四份清单 |
| 8 | 素材生成 | 批量生成图片 → 首帧放大（`enhance.py --upscale`）→ 图生视频 → 配音 | 每镜素材齐备，抽检通过 |
| 9 | 审片 | HTML 分镜墙 + 成片审看 | 无一致性事故、无静默镜头 |
| 10 | 合成 | `python scripts/assemble.py` | 每集导出 `E01.mp4` … |

---

## 二、项目目录约定

```
<项目名>/
├── project.json              # 唯一数据源（所有脚本读写它）
├── README.md
├── 01_script/                # 大纲、分集剧本；导入剧本时含 source.* 与 import_report.md
├── 02_characters/            # 角色卡、定妆照
├── 03_storyboard/            # 分镜表 md
├── 04_prompts/               # build_prompts.py 输出
│   ├── image_prompts.md
│   ├── video_prompts.md
│   ├── audio_prompts.md
│   ├── director_prompts.md   # 中文导演版（大分镜/小分镜 + 资产槽 + 每镜资产）
│   ├── asset_manifest.md     # 一镜一资产清单（每镜一条记录）
│   ├── asset_manifest.csv
│   ├── prompts.json
│   └── prompts.csv
├── 05_assets/
│   ├── images/E01/E01-S01.png
│   ├── videos/E01/E01-S01.mp4
│   ├── audio/E01/E01-S01.wav
│   ├── shots/common/         # 可跨集复用的反应镜头 / 空镜
│   └── refs/                 # 角色定妆照
├── 06_output/
│   ├── episodes/E01.mp4
│   └── final/
└── 07_preview/storyboard.html
```

命名规范：`E{集号}-S{镜号}`，如 `E01-S07`。补拍素材加 `-v2` 后缀，不覆盖原文件。

---

## 三、生成顺序（重要）

1. **先生成角色定妆照**，人工确认"这个人对"再往下走。
2. **再生成场景定妆照（空场景母版）**，确认空间/陈设/光型一致（`image_prompts.md` 的「场景参考」区）。
3. **然后按集生成镜头图**，每集生成后立即抽检，不要一次生成 20 集。
4. **首帧放大**（`scripts/enhance.py --upscale`，见第四节）。
5. **图生视频**：用放大后的首帧，一次一镜，失败立即重抽（不要批量后才发现全崩）。
6. **配音**：与视频并行，不影响。

**批量纪律**：每集最多一次生成 6-8 张，抽检后再继续。一次生成 50 张若风格或人物漂移，返工成本极高。

---

## 四、素材增强（scripts/enhance.py）

图片与视频之间的两步增益，直接影响成片清晰度与镜头衔接：

1. **首帧放大后再图生视频**：视频模型会压缩输入，低分辨率首帧成片必糊。
   ```bash
   python scripts/enhance.py <项目路径> --upscale            # 05_assets/images 全部放大 ×2
   python scripts/enhance.py <图片目录> --upscale --factor 2  # 指定目录
   ```
   输出 `<名>-2x.png`（lanczos + 轻锐化），原图保留、已放大自动跳过；i2v 一律选放大件当首帧。
2. **尾帧提取（首尾帧工作流）**：下一镜首帧必须用上一镜视频的最后一帧导出，不要重新生成（重新生成必跳变）。
   ```bash
   python scripts/enhance.py <视频文件> --last-frame          # 输出 <名>-tail.png
   ```
3. 需要更高质量时用第三方超分（Real-ESRGAN / Topaz 类）处理首帧，本脚本只保证零依赖基线（ffmpeg lanczos）。

---

## 五、质量控制门禁

### 图片 QC（每张 10 秒）
- [ ] 人物脸与定妆照一致
- [ ] 手部正常（无多余指、无扭曲）
- [ ] 服装与预设变体一致
- [ ] 场景与场景锚点一致
- [ ] 构图符合景别要求
- [ ] 画面内无乱码文字

### 视频 QC（每镜 15 秒）
- [ ] 首帧与图片一致（无突变）
- [ ] 运动方向正确
- [ ] 无人脸形变、无人影闪烁
- [ ] 时长达标（≥设定时长，可裁不可拉）
- [ ] 有画面信息，不是静止卡帧

### 音频 QC
- [ ] 音色与角色设定一致
- [ ] 无明显机械感
- [ ] 音量与 BGM 平衡（人声 -3dB 于 BGM）

### 成片 QC（每集）
- [ ] 无超过 2 秒的空洞镜头
- [ ] 字幕无错别字、无越界
- [ ] 转场不卡
- [ ] 结尾帧是卡点
- [ ] 时长符合平台要求

---

## 六、常见问题修复

| 症状 | 原因 | 修复 |
|---|---|---|
| 角色每张都不一样 | 锚点短语被改动/seed 未固定 | 恢复锚点；换方案 B 参考图 |
| 视频里脸变了 | 图生视频提示词重复了静态描述 | 只写运动，删掉脸/服装/场景描述 |
| 动作幅度过大 | 运动描述过多 | 改为单一微小动作 |
| 画面文字乱码 | 在画面里生成文字 | 改为后期字幕 |
| 嘴型对不上 | 近景说话 | 换中远景/侧脸，或改用"说完再切" |
| 镜头之间跳变 | 重新生成尾帧 | 用上一镜尾帧做下一镜首帧（`enhance.py <视频> --last-frame`） |
| 成片发糊不清 | 低分辨率首帧直接驱动视频 | 首帧先 `enhance.py --upscale` 放大，再用放大件驱动 i2v |
| 成片节奏拖沓 | 镜头时长过长 | 按 `shot_language.md` 第六节的时长×情绪表压缩 |
| 音画不同步 | 音频与视频时长不等 | `assemble.py` 按 `duration_sec` 自动对齐（静音补齐/截取） |
| 字幕遮挡主体 | 安全区未留 | 主体上移，字幕放下 25% |

---

## 七、成本与效率

- **场景复用**：全剧 ≤12 个场景，每个场景只需 1 次空镜 + N 个角色镜头。
- **镜头复用**：反应镜头、空镜可跨集复用，放入 `05_assets/shots/common/`。
- **配音复用**：旁白与固定台词可用同一音色批量生成。
- **并行**：图片按集并行，视频串行（视频接口慢且失败率高）。
- **缓存**：`project.json` 里已生成的 `assets` 路径不要清空，重跑脚本时自动跳过。

---

## 八、平台输出参数

见 `assets/presets/production.json` 的 `platforms` 与 `ffmpeg`。`assemble.py` 按项目 `platform` 自动取分辨率与 fps（默认竖屏 1080×1920 / 30fps / H.264 / CRF 18 / AAC 192k），字幕样式在 `ffmpeg.subtitle_style`，画面归一化模板在 `ffmpeg.scale_pad`。

**全局硬约束**（见 `production.json` 的 `limits`）：
- 单镜时长 **0.5-30 秒**。超过 30 秒必须拆镜；`assemble.py` 按 `duration_sec` 逐镜切片，长镜头用图片序列时注意图片需高清。
- 单条提示词 **≤15000 字**。`build_prompts.py` 超限即报错并列出条目。

**发布前统一处理**：
1. 时长裁剪到平台区间
2. 响度归一化到平台目标 LUFS（`assemble.py` 按 `platforms[].audio_loudness` 自动执行；整集静音时自动跳过，避免 `loudnorm` 产生 NaN）
3. 字幕烧录（平台上传后不可改则必须烧）
4. 导出封面帧（选卡点那一帧）

---

## 九、平台合规硬约束

见 `references/compliance.md`。任何一步不得绕过。
