# 📝 外部 LLM 生成指南

> 在 ChatGPT / Claude / Gemini / 通义 / 文心 / DeepSeek 等任意 LLM 中生成角色、场景、分镜数据，导入本管线。

---

## 流程

```
1. 生成角色 YAML  ──→  放入 config/characters/
2. 生成场景 YAML  ──→  放入 config/scenes/
3. 生成分镜 CSV   ──→  放入 storyboard/episodes.csv
4. 运行校验       ──→  python scripts/validate_import.py <目录>
```

**建议顺序**：角色 → 场景 → 分镜（分镜需要引用角色/场景 ID）

---

## 1. 生成角色

复制以下提示词发送给 LLM，末尾附上角色描述：

```
为每个角色生成一个 YAML 代码块，格式如下：

```yaml
character:
  id: "英文ID（小写字母+下划线）"
  name: "角色名字"
  gender: "male 或 female"
  appearance: "外貌描述 50-100 字，含年龄/发型/五官/体型"
  outfits:
    default:
      description: "默认服装描述"
      reference_images: []
  voice:
    voice_description: "声音特征 20-40 字"
```

规则：
- id 仅允许 a-z 0-9 _ -
- outfits 必须含 default 键
- 每个角色一个代码块，用 --- 分隔
- 只输出 YAML，不要解释

我的角色描述：
（粘贴你的角色描述）
```

保存：每个 `character:` 块存为 `config/characters/<id>.yaml`

---

## 2. 生成场景

```
为每个场景生成一个 YAML 代码块：

```yaml
scene:
  id: "英文ID（小写字母+下划线）"
  name: "场景中文名"
  description: "场景描述 50-100 字，含空间布局/色调/氛围"
  lighting: "光照描述 20-40 字，含色温/方向"
```

规则：
- id 仅允许 a-z 0-9 _ -
- 每个场景一个代码块，用 --- 分隔
- 只输出 YAML，不要解释

我的场景描述：
（粘贴你的场景描述）
```

保存：每个 `scene:` 块存为 `config/scenes/<id>.yaml`

---

## 3. 生成分镜

提供角色 ID 列表、场景 ID 列表和剧情大纲：

```
将剧情大纲拆分为镜头列表，输出 CSV 格式：

episode,shot_id,scene,characters,action,dialogue,camera,shot_type,duration,outfit,emotion,action_en,dialogue_en
1,001,场景ID,角色ID,中文动作,中文台词,运镜,景别,秒数,服装,情绪,英文动作,英文台词

字段说明：
- shot_id: 三位数，001 起递增
- scene: 场景 ID（与场景配置 id 一致）
- characters: 角色 ID（多人用 + 连接，如 linxia+guchen）
- camera: 固定/缓慢推近/跟随平移/手持晃动/环绕/俯视/仰视
- shot_type: 特写/近景/中景/过肩/全身/全景/远景/双人全景
- duration: 2-8 秒
- outfit: 角色 outfits 中的 key（默认 default）
- emotion: happy/sad/worried/surprised/angry/romantic/calm/determined/serious/neutral/smug/fearful/action
- action_en / dialogue_en: 对应中文的英文翻译
- 无台词用 ......

规则：
- shot_id 从 001 递增，不跳号
- 总时长 60-120 秒
- 台词不要含英文双引号和逗号（会破坏 CSV），用中文引号或省略号
- 只输出 CSV，不要解释

我的角色 ID：（列出）
我的场景 ID：（列出）
我的剧情大纲：（粘贴）
```

---

## 4. 校验

导入前运行校验脚本：

```bash
python scripts/validate_import.py projects/<项目名>/config/characters/ projects/<项目名>/config/scenes/ projects/<项目名>/storyboard/episodes.csv
```

- ✅ 全部通过 → 可以使用
- ⚠ 有警告 → 通常不影响运行（emotion/shot_type 不在预设值时会自动回退）
- ❌ 有错误 → 必须修正（缺少必填字段、ID 格式错误等）

---

## 5. 导入

**方法一**：直接放文件
```bash
cp 角色.yaml projects/<项目名>/config/characters/
cp 场景.yaml projects/<项目名>/config/scenes/
cp 分镜.csv projects/<项目名>/storyboard/episodes.csv
```

**方法二**：Web 工作台
- 角色管理 → 新建
- 场景管理 → 新建
- 分镜表 → 导入（支持 CSV 和 JSON）

---

## 字段速查

| 字段 | 可选值 |
|------|--------|
| gender | `male`, `female` |
| camera | `固定`, `缓慢推近`, `跟随平移`, `手持晃动`, `环绕`, `俯视`, `仰视` |
| shot_type | `特写`, `近景`, `中景`, `过肩`, `全身`, `全景`, `远景`, `双人全景` |
| emotion | `happy`, `sad`, `worried`, `surprised`, `angry`, `romantic`, `calm`, `determined`, `serious`, `neutral`, `smug`, `fearful`, `action` |
| duration | 2-8 整数 |
| language | `zh`(默认), `en`, `ja`, `ko` |

---

## 常见问题

**Q: CSV 台词包含逗号？**
用双引号包裹：`1,001,scene,char,动作,"你好，世界",固定,中景,4,default,neutral,...`

**Q: 角色/场景 ID 不一致？**
分镜中的 `scene` 和 `characters` 必须与配置中的 `id` 完全一致（区分大小写）。

**Q: 一个 YAML 放多个角色？**
不可以。每个文件一个 `character:` 或 `scene:`。

**Q: LLM 生成了校验警告的 emotion？**
运行时会自动回退到 `neutral`，不影响生产。如需精确控制，手动修改为预设值。
