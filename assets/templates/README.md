# AI 短剧项目

由 `ai-short-drama` skill 生成。

## 目录

```
project.json            唯一数据源（所有脚本读写它）
episodes/               分片布局（split_project.py 拆分后；每集一个 E01.json，可选）
01_script/              大纲、分集剧本
02_characters/          角色卡、定妆照
03_storyboard/          分镜表（人工编辑视图）
04_prompts/             build_prompts.py 输出
05_assets/              图片 / 视频 / 音频 / 参考图
06_output/episodes/     成片
06_output/final/        最终交付
07_preview/             分镜墙 HTML
```

## 常用命令

```bash
# 现成剧本初拆（可选；角色/场景会生成待补全占位）
python <skill>/scripts/import_script.py 剧本.docx --project .

# 校验数据结构
python <skill>/scripts/validate_project.py

# 长剧拆分：分集拆为 episodes/*.json（--merge 合并回单文件）
python <skill>/scripts/split_project.py .
python <skill>/scripts/split_project.py . --merge

# 生成提示词清单（纯英文校验 + 资产清单 + 分镜表）
python <skill>/scripts/build_prompts.py --type all --strict-en

# 只生成中文导演版分镜提示词（大分镜/小分镜 + 资产槽 + 台词字段）
python <skill>/scripts/build_prompts.py --type director

# 只刷新分镜表 / 资产清单（不会清空已有提示词）
python <skill>/scripts/build_prompts.py --type table
python <skill>/scripts/build_prompts.py --type assets

# 生成分镜墙
python <skill>/scripts/preview.py

# 合成某一集（需要 ffmpeg）
python <skill>/scripts/assemble.py --episode E01

# 只查看将要执行的命令
python <skill>/scripts/assemble.py --episode E01 --dry-run
```

`<skill>` 指向本 skill 所在目录（本仓库即 `ai-short-drama/` 的安装路径）。

## 制作顺序

0. 现成剧本：`import_script.py` 初拆为 `project.json` 骨架（可选）
1. `01_script/outline.md` 分集大纲
2. `02_characters/character_card.md` 角色卡 + 定妆照
3. 把 `characters` / `scenes` 写进 `project.json`
4. 逐集写分镜进 `project.json`
5. `validate_project.py` 校验
6. `build_prompts.py` 出提示词
7. 批量生成素材，把路径写回 `shots[].assets`
8. `preview.py` 审片
9. `assemble.py` 合成
