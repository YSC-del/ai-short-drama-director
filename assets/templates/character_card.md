# 角色卡

> 每个角色 3 个**可视觉化**识别锚点（发型/发色、标志服装、标志道具）。
> 这三个锚点在所有分镜与提示词里必须逐字一致，否则 AI 生成会换脸。

## {{CHAR_ID}}｜{{NAME}}

- 定位：主角 / 反派 / 配角 / 群演
- 年龄 / 性别：
- 英文识别锚点（image_prompt，全剧固定）：
  ```
  例: a young woman with black long straight hair, amber eyes, fair skin, sharp jawline
  ```
- 中文识别锚点（人工审阅用）：1. 2. 3.
- 服装变体：
  - A：
  - B：
- 性格：
- 动机（反派必填）：
- 弧光转变（必须有一次可视化事件：换装/受伤/拿到道具）：
- 配音：音色 / 语速 / 默认情绪
- 定妆照：`05_assets/refs/{{CHAR_ID}}.png`

## 检查

- [ ] 英文锚点已写入 `project.json` 的 `characters[].image_prompt`
- [ ] 服装变体已写入 `characters[].outfits`
- [ ] `visual_anchors` 有 3 项
- [ ] 已生成定妆照并通过"脸对"检查
