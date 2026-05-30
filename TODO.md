# TODO — 待开发功能 & 已知缺陷

> 更新：2026-05-30

## 1. `build_prompt()` 后端感知 — Flux/Cosmos 自然语言 prompt

**方案**: B（改 `build_prompt()` 拼接逻辑，不改翻译层）

**问题**: 当前 `build_prompt()` 对所有后端使用相同的逗号分隔 tag 风格拼接：
```
cinematic style, urban atmosphere, {scene}, {character}, {action_en}, sad expression, medium shot, static camera
```
这种风格适合 SD1.5/SDXL（CLIP 编码器），但 Flux/Cosmos 使用 T5-XXL 编码器，能理解更丰富的自然语言描述。当前翻译后的 `action_en` 是简洁短句，浪费了 T5 的表达能力。

**改动范围**: `engines/prompt.py` — `build_prompt()` 函数

**实现思路**:
- 读取 `config.models.image_backend` 判断当前后端
- SD1.5/SDXL: 保持现有逗号 tag 风格
- Flux/Cosmos: 改用自然语言段落风格，将各元素组装为连贯描述

**Flux/Cosmos prompt 示例**:
```
A cinematic shot of a young woman in a modern living room.
She sits alone on the sofa, looking down at her phone with a melancholic expression.
The mood is sad. Medium shot, static camera.
```

**注意**:
- `action_en` 保持纯翻译不变（CSV/字幕仍可用）
- 不需要重跑 `prepare`，只影响 `produce` 阶段
- 需要确认各后端的 workflow 模板中 CLIP/T5 节点的 prompt 输入方式是否一致
