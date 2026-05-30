# TODO — 待开发功能 & 已知缺陷

> 更新：2026-05-30

## ~~1. `build_prompt()` 后端感知 — Flux/Cosmos 自然语言 prompt~~ ✅ 已完成

**方案**: B（改 `build_prompt()` 拼接逻辑，不改翻译层）

**改动文件**:
- `engines/prompt.py` — `build_prompt()` 新增 `image_backend` 参数，Flux/Cosmos 输出自然语言段落
- `engines/workflow_builder.py` — 传入当前 `image_backend`
- `tests/test_all.py` — 覆盖 SD1.5 tag 风格 + Flux/Cosmos 自然语言风格

**实现**:
- SD1.5/SDXL（CLIP）: 保持逗号 tag 风格
- Flux/Cosmos（T5-XXL）: 自然语言段落风格，将各维度组装为连贯描述

**Flux/Cosmos prompt 示例**:
```
A cinematic style in urban atmosphere. Set in modern living room.
Young woman sitting on sofa, with a worried expression.
extreme close-up shot, slow zoom in, dolly in.
```
