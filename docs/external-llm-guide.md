# 📝 外部 LLM 生成指南 — 在任意 AI 中生成分镜/角色/场景，导入本管线

> 本指南提供**可直接复制粘贴的提示词**，让你在 ChatGPT、Claude、Gemini、通义千问、文心一言等任意 LLM 中生成符合本管线格式的数据，然后一键导入。

---

## 目录

1. [整体流程](#1-整体流程)
2. [第一步：生成角色配置](#2-第一步生成角色配置)
3. [第二步：生成场景配置](#3-第二步生成场景配置)
4. [第三步：生成分镜表](#4-第三步生成分镜表)
5. [导入方法](#5-导入方法)
6. [格式速查表](#6-格式速查表)
7. [常见问题](#7-常见问题)

---

## 1. 整体流程

```
你的剧情大纲
    │
    ▼
┌──────────────────────────────────┐
│  第一步：在任意 LLM 中生成角色    │  ← 使用提示词 A
│  输出：每个角色一个 YAML 文件     │
└──────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────┐
│  第二步：在任意 LLM 中生成场景    │  ← 使用提示词 B
│  输出：每个场景一个 YAML 文件     │
└──────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────┐
│  第三步：在任意 LLM 中生成分镜    │  ← 使用提示词 C
│  输出：一个 CSV 或 JSON 文件      │
└──────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────┐
│  导入到本管线                     │
│  Web 工作台 → 分镜表 → 导入       │
│  角色/场景 YAML 放入 config/ 目录 │
└──────────────────────────────────┘
```

**建议顺序**：先角色 → 再场景 → 最后分镜（因为分镜需要引用角色 ID 和场景 ID）

---

## 2. 第一步：生成角色配置

### 提示词 A — 角色生成

将以下提示词**完整复制**到任意 LLM 对话中，然后在末尾附上你的角色描述：

```
你是一位专业的短剧角色设计师。我将给你角色描述，请为每个角色生成完整的配置文件。

## 输出格式

每个角色输出一个 YAML 代码块，格式如下（严格遵守，不要遗漏任何字段）：

```yaml
character:
  id: "英文ID（小写字母+下划线，如 linxia、guchen、ghost01）"
  name: "角色真实名字（中文/英文/其他语言，必须唯一）"
  gender: "male 或 female"
  appearance: "详细外貌描述（50-100字），包含年龄、发型、五官、体型、身高等，能指导 AI 绘图"
  personality: "性格特征简述（20-40字），如：外冷内热、善良胆小、沉稳理性"
  outfits:
    default:
      description: "默认服装的详细描述（30-50字）"
      reference_images: []
    casual:
      description: "休闲装描述（30-50字）"
      reference_images: []
    formal:
      description: "正装描述（可选，30-50字）"
      reference_images: []
  voice:
    voice_description: "声音特征描述（20-40字），包含音色、语速、口音等"
```

## 规则

1. `id` 字段：仅允许小写英文字母、数字、下划线 `_`、连字符 `-`，不能有空格或中文
2. `name` 字段：角色的真实显示名，可以是中文，每个角色必须唯一
3. `appearance` 字段：要足够详细，能直接用于 AI 绘图提示词
4. `outfits` 字段：必须包含 `default` 键，可额外添加 `casual`、`formal`、`home` 等
5. `voice` 字段：必须包含 `voice_description`
6. 每个角色用 `---` 分隔
7. 只输出 YAML 代码块，不要额外解释

## 我的角色描述

（在这里粘贴你的角色描述，每个角色一段）
```

### 使用示例

假设你有以下角色描述：

> 林夏：22岁温柔女生，长发，喜欢穿浅色衣服
> 顾辰：25岁帅气男生，短发阳光，运动型

将提示词 A 发送给 LLM 后，你会得到类似这样的输出：

```yaml
character:
  id: "linxia"
  name: "林夏"
  gender: "female"
  appearance: "22岁年轻女性，黑色长发及腰，瓜子脸，大眼睛，皮肤白皙，身高165cm，体型纤细"
  personality: "温柔内敛，善良细心，有点小忧郁"
  outfits:
    default:
      description: "浅粉色针织开衫，白色连衣裙，白色帆布鞋，简约银色项链"
      reference_images: []
    casual:
      description: "白色T恤，浅蓝色牛仔裤，小白鞋，马尾辫"
      reference_images: []
    home:
      description: "米色居家睡衣，棉拖鞋，头发随意扎起"
      reference_images: []
  voice:
    voice_description: "轻柔甜美的年轻女声，语速偏慢，带一点南方口音"
---
character:
  id: "guchen"
  name: "顾辰"
  gender: "male"
  appearance: "25岁年轻男性，黑色短发，剑眉星目，鼻梁高挺，身高180cm，体型匀称有肌肉线条"
  personality: "阳光开朗，做事果断，对林夏很温柔"
  outfits:
    default:
      description: "黑色卫衣，深色休闲裤，运动鞋，双肩包"
      reference_images: []
    formal:
      description: "白色衬衫，黑色西裤，黑色皮鞋，袖口微卷"
      reference_images: []
  voice:
    voice_description: "沉稳有力的年轻男声，声音低沉有磁性，语速适中"
```

**保存方法**：将每个 `character:` 代码块保存为独立 YAML 文件：
- `linxia.yaml`
- `guchen.yaml`

---

## 3. 第二步：生成场景配置

### 提示词 B — 场景生成

```
你是一位专业的短剧场景设计师。我将给你场景描述，请为每个场景生成完整的配置文件。

## 输出格式

每个场景输出一个 YAML 代码块，格式如下（严格遵守，不要遗漏任何字段）：

```yaml
scene:
  id: "英文ID（小写字母+下划线，如 living_room、street_night、cafe）"
  name: "场景中文名"
  description: "详细场景描述（50-100字），包含空间布局、家具摆设、色调、氛围等，能直接用于 AI 绘图"
  lighting: "光照描述（20-40字），包含光源方向、色温、明暗对比等"
```

## 规则

1. `id` 字段：仅允许小写英文字母、数字、下划线 `_`、连字符 `-`，不能有空格或中文
2. `name` 字段：场景的中文显示名
3. `description` 字段：要有画面感，能直接作为 AI 绘图的场景描述
4. `lighting` 字段：要具体到色温（暖/冷）和方向（顶光/侧光/逆光等）
5. 每个场景用 `---` 分隔
6. 只输出 YAML 代码块，不要额外解释

## 我的场景描述

（在这里粘贴你的场景描述）
```

### 输出示例

```yaml
scene:
  id: "living_room"
  name: "客厅"
  description: "现代简约风格客厅，米色布艺沙发靠墙，对面是壁挂电视，落地窗透入柔和光线，木质茶几上放着水杯和手机，墙上挂着风景画，角落有绿植盆栽"
  lighting: "暖色调室内光，自然光从落地窗斜射入，营造温馨氛围"
---
scene:
  id: "street_night"
  name: "夜晚街道"
  description: "城市商业街夜景，两侧霓虹灯招牌闪烁，湿润的柏油路面反射灯光，行人三两走过，远处可见红绿灯和公交站牌"
  lighting: "冷暖混合的霓虹灯光，主色调偏蓝紫，路面有暖黄色反光"
```

**保存方法**：将每个 `scene:` 代码块保存为独立 YAML 文件：
- `living_room.yaml`
- `street_night.yaml`

---

## 4. 第三步：生成分镜表

### 提示词 C — 分镜生成

将以下提示词复制到 LLM，然后附上你的**剧情大纲**。同时提供你已有的**角色 ID 列表**和**场景 ID 列表**。

```
你是一位专业的短剧分镜师。我将给你剧情大纲，请将其拆分为具体的镜头列表。

## 输出格式

输出一个 CSV 格式的表格（逗号分隔），第一行为表头，后续每行一个镜头：

```
episode,shot_id,scene,characters,action,dialogue,camera,shot_type,duration,outfit,emotion,action_en,dialogue_en
1,001,living_room,linxia,坐在沙发上看手机，表情失落,他怎么还不回消息...,缓慢推近,特写,4,home,worried,sitting on sofa looking at phone with a sad expression,Why isn't he replying...
1,002,living_room,linxia,起身走到窗前望向外面,......,跟随平移,中景,3,home,sad,stands up and walks to the window looking outside,...
```

## 字段说明

| 字段 | 格式要求 | 示例 |
|------|---------|------|
| episode | 集数（整数） | 1 |
| shot_id | 三位数，从 001 递增 | 001, 002, 003 |
| scene | 场景 ID（英文小写下划线，必须与场景配置中的 id 一致） | living_room, street_night |
| characters | 角色 ID（英文，多人用 + 连接，必须与角色配置中的 id 一致） | linxia, linxia+guchen |
| action | 中文动作描述，具体到肢体语言 | 坐在沙发上看手机，表情失落 |
| dialogue | 中文台词，无台词用 ...... | 他怎么还不回消息... |
| camera | 运镜方式（固定/缓慢推近/跟随平移/手持晃动/环绕/俯视/仰视） | 缓慢推近 |
| shot_type | 景别（特写/近景/中景/过肩/全身/全景/远景/双人全景） | 特写 |
| duration | 秒数（2-8 之间的整数） | 4 |
| outfit | 服装标签（对应角色 outfits 中的 key，如 default/casual/formal/home） | home |
| emotion | 情绪英文（happy/sad/worried/surprised/angry/romantic/calm/determined/serious/neutral） | worried |
| action_en | action 的英文翻译 | sitting on sofa looking at phone |
| dialogue_en | dialogue 的英文翻译，无台词用 ...... | Why isn't he replying... |

## 规则

1. shot_id 三位数，从 001 递增，不要跳号
2. 每个镜头 duration 2-8 秒，总时长控制在 60-120 秒
3. scene 和 characters 使用英文 ID，action 和 dialogue 用中文
4. dialogue 不要包含引号和逗号（会破坏 CSV），省略号用 ...
5. action_en 和 dialogue_en 必须填写，是对应中文的英文翻译
6. 镜头语言要有节奏感：特写→中景→全景交替，避免连续相同景别
7. 情绪要有起伏，不要全程 neutral
8. characters 字段中的角色 ID 必须与角色配置中的 id 完全一致
9. scene 字段必须与场景配置中的 id 完全一致
10. 如果台词中包含逗号，用双引号包裹整个 dialogue 字段
11. 只输出 CSV，不要额外解释文字

## 我的角色 ID 列表

（列出你的角色 ID 和名字映射，例如：）
- linxia = 林夏
- guchen = 顾辰

## 我的场景 ID 列表

（列出你的场景 ID，例如：）
- living_room = 客厅
- street_night = 夜晚街道

## 我的剧情大纲

（在这里粘贴你的剧情大纲）
```

### 输出示例

```csv
episode,shot_id,scene,characters,action,dialogue,camera,shot_type,duration,outfit,emotion,action_en,dialogue_en
1,001,living_room,linxia,坐在沙发上看手机，表情失落,他怎么还不回消息...,缓慢推近,特写,4,home,worried,sitting on sofa looking at phone sadly,Why isn't he replying...
1,002,living_room,linxia,起身走到窗前望向外面,......,跟随平移,中景,3,home,sad,stands up walks to window looking outside,...
1,003,street_night,guchen,骑自行车快速穿过街道,马上就到了！,固定,全身,4,casual,determined,riding bicycle through the street quickly,I'm almost there!
1,004,living_room,linxia,听到门铃声惊讶地抬头,嗯？,手持晃动,近景,2,home,surprised,looks up in surprise hearing the doorbell,Hmm?
1,005,living_room,linxia+guchen,林夏打开门，两人对视,......,缓慢推近,双人全景,5,default,romantic,door opens they look at each other,...
1,006,living_room,guchen,从背后拿出一束花递过去,生日快乐！,固定,近景,3,formal,happy,takes out a bouquet and presents it,Happy birthday!
1,007,living_room,linxia,接过花，眼眶泛红，感动地笑了,谢谢...我好开心,缓慢推近,特写,4,default,romantic,takes the bouquet eyes tearing up smiling,Thank you... I'm so happy
```

### JSON 格式（备选）

LLM 也可以输出 JSON 数组格式，导入时同样支持：

```json
[
  {
    "episode": "1",
    "shot_id": "001",
    "scene": "living_room",
    "characters": "linxia",
    "action": "坐在沙发上看手机，表情失落",
    "dialogue": "他怎么还不回消息...",
    "camera": "缓慢推近",
    "shot_type": "特写",
    "duration": "4",
    "outfit": "home",
    "emotion": "worried",
    "action_en": "sitting on sofa looking at phone sadly",
    "dialogue_en": "Why isn't he replying..."
  }
]
```

---

## 5. 导入方法

### 5.1 导入角色和场景

将 LLM 生成的 YAML 文件放入对应目录：

```
projects/<你的项目>/config/
├── characters/
│   ├── linxia.yaml      ← 放这里
│   └── guchen.yaml      ← 放这里
└── scenes/
    ├── living_room.yaml  ← 放这里
    └── street_night.yaml ← 放这里
```

**方法一：直接复制文件**
```bash
# 假设你的项目是 default
cp linxia.yaml projects/default/config/characters/
cp living_room.yaml projects/default/config/scenes/
```

**方法二：通过 Web 工作台**
1. 打开 http://localhost:8888
2. 进入「角色管理」→ 点击「+ 新建」
3. 逐个填写字段（从 LLM 输出中复制）
4. 场景同理

### 5.2 导入分镜表

**方法一：Web 工作台导入（推荐）**

1. 打开 http://localhost:8888 → 分镜表
2. 点击右上角「📥 导入」按钮
3. 选择你的 CSV 或 JSON 文件
4. 选择导入模式：
   - **合并**：追加到现有分镜表
   - **覆盖**：替换当前集的分镜
5. 点击确认

**方法二：直接替换 CSV 文件**
```bash
# 备份原文件
cp projects/default/storyboard/episodes.csv projects/default/storyboard/episodes.csv.bak

# 替换（注意：会覆盖所有集的分镜）
cp your_storyboard.csv projects/default/storyboard/episodes.csv
```

### 5.3 导入后验证

导入完成后，在 Web 工作台检查：
1. **角色管理**：头像和字段是否完整
2. **场景管理**：描述和光照是否合理
3. **分镜表**：角色名和场景名是否正确显示（而不是显示英文 ID）
4. **生产管线**：点击某个镜头的 TTS/首帧 测试是否正常

---

## 6. 格式速查表

### 角色 YAML 最小模板

```yaml
character:
  id: "mychar"
  name: "角色名"
  gender: "male"
  appearance: "外貌描述（50-100字）"
  personality: "性格描述（20-40字）"
  outfits:
    default:
      description: "默认服装描述"
      reference_images: []
  voice:
    voice_description: "声音描述（20-40字）"
```

### 场景 YAML 最小模板

```yaml
scene:
  id: "myscene"
  name: "场景名"
  description: "场景描述（50-100字）"
  lighting: "光照描述（20-40字）"
```

### 分镜 CSV 最小模板

```csv
episode,shot_id,scene,characters,action,dialogue,camera,shot_type,duration,outfit,emotion,action_en,dialogue_en
1,001,myscene,mychar,动作描述,台词,固定,中景,4,default,neutral,action in English,dialogue in English
```

### 字段取值范围速查

| 字段 | 可选值 |
|------|--------|
| gender | `male`, `female` |
| camera | `固定`, `缓慢推近`, `跟随平移`, `手持晃动`, `环绕`, `俯视`, `仰视` |
| shot_type | `特写`, `近景`, `中景`, `过肩`, `全身`, `全景`, `远景`, `双人全景` |
| emotion | `happy`, `sad`, `worried`, `surprised`, `angry`, `romantic`, `calm`, `determined`, `serious`, `neutral` |
| duration | 2-8 之间的整数 |
| outfit | 对应角色 outfits 中的 key，默认 `default` |
| language | `zh`（默认）, `en`, `ja`, `ko`, `fr`, `de`, `es` |

---

## 7. 常见问题

### Q: LLM 输出的 YAML 格式不对怎么办？

**方案一**：把错误输出和正确格式示例一起发给 LLM，让它修正：
```
请修正以下 YAML，使其符合格式要求：
（粘贴 LLM 的输出）

正确格式参考：
（粘贴上面的模板）
```

**方案二**：使用在线 YAML 校验工具检查语法：
- https://www.yamllint.com/
- https://codebeautify.org/yaml-validator

### Q: CSV 中的台词包含逗号怎么办？

在 CSV 中，包含逗号的字段要用双引号包裹：
```csv
1,001,living_room,linxia,看着窗外,"你好，世界",固定,中景,4,default,neutral,looking out the window,"Hello, world"
```

### Q: 分镜中的角色 ID 和场景 ID 必须与配置一致吗？

**是的！** 分镜表中的 `characters` 和 `scene` 字段必须与角色/场景配置中的 `id` 完全一致（区分大小写）。如果不一致，生产管线无法找到对应的定妆照和场景参考图。

**建议**：先生成角色和场景，记下它们的 ID，再生成分镜时告诉 LLM 使用这些 ID。

### Q: 可以只生成分镜，不生成角色/场景吗？

可以。分镜表中的 `characters` 和 `scene` 字段可以是任意字符串。但如果你想使用 AI 生成首帧图片时获得角色一致性，就需要配置角色定妆照。

### Q: 一个 YAML 文件里可以放多个角色/场景吗？

**不可以。** 每个文件只能包含一个 `character:` 或 `scene:` 块。多个角色/场景需要分别保存为独立文件。

### Q: 导入分镜时选择「合并」还是「覆盖」？

- **合并**：新镜头追加到现有分镜表后面（适用于分批生成）
- **覆盖**：替换当前集的所有镜头（适用于重新生成）

### Q: LLM 生成的 action_en 和 dialogue_en 质量不好怎么办？

这两个字段主要用于英文字幕。如果质量不好，你可以：
1. 手动修改（在 Web 工作台的分镜表中直接编辑）
2. 留空，后期用 LLM 翻译功能补全
3. 在提示词中强调：「请使用地道的英文翻译，不要直译」

### Q: 如何生成多集短剧？

在提示词 C 中将 `episode` 设置为不同值：
```csv
episode,shot_id,scene,...
1,001,living_room,...
1,002,street,...
2,001,living_room,...   ← 第二集
2,002,cafe,...          ← 第二集
```

导入时，系统会自动按 `episode` 字段分集管理。

### Q: outfit 字段怎么用？

`outfit` 对应角色配置中 `outfits` 的 key。例如角色有 `default`、`casual`、`home` 三套服装，在分镜中可以指定不同镜头穿不同服装：

```csv
1,001,living_room,linxia,早上起床,......,固定,中景,4,home,calm,...  ← 穿居家服
1,002,living_room,linxia,换好衣服出门,......,跟随平移,全身,3,casual,happy,...  ← 穿休闲装
```

服装标签用于 AI 生成首帧图片时选择对应的参考图。如果不指定，默认使用 `default`。
