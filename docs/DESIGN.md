# osu-mapwright · 项目逻辑文档

> **状态**：设计阶段（v0.1）
> **目标模式**：osu! standard（`Mode: 0`）
> **最后更新**：2026-11-19

---

## 0. 一句话

**输入一首歌，输出一张能直接进 osu! 游玩、并且能在官方编辑器里继续编辑的 standard 谱面（或谱面集）。**

不是"AI 取代 mapper"，而是"把 mapper 最耗时的机械劳动自动化，把创作判断留给人"。

---

## 1. 目标与非目标

### 1.1 目标

| 优先级 | 目标 | 验收方式 |
|---|---|---|
| P0 | 输出的 `.osu` 能被 osu! 加载、被编辑器打开 | 双击能玩 |
| P0 | 通过官方 AiMod 检查，无 Error | `Ctrl+Shift+A` 零报错 |
| P0 | 物件全部吸附、不出屏、spinner 长度达标 | AiMod + 自检 |
| P1 | 节奏"听起来是这首歌"（重音对齐、段落起伏） | 人耳试听/试打 |
| P1 | 间距与流向可打（不出现人类达不到的跳） | 约束求解 + 试打 |
| P2 | 支持目标难度（给定 SR 自动逼近） | `rosu-pp` 计算 |
| P2 | 一次产出多难度（满足 spread 要求） | 按 drain time 校验 |
| P3 | 生成结果"像人写的"（pattern 可辨识） | 模式级生成 |

### 1.2 非目标（明确不做）

- ❌ 一键产出 **ranked** 谱面。上架是社交流程（5 hype + 2 BN 提名 + 7 天 qualified），工具无法替代。
- ❌ 替代 modding。工具只负责**消灭机械问题**，风格问题仍需要人。
- ❌ 端到端"音频 → 坐标"的黑盒大模型。理由见 §3.4。
- ❌ 其他模式（taiko / catch / mania）的生成。第一版只做 standard。

### 1.3 成功标准（可测）

> **一个 mapper 接手这份 draft 后，把它改成可提交状态所花的时间，比从零开始少 60% 以上。**

副指标：

- AiMod 零 Error、Warning ≤ 3 条且都是有意为之；
- 物件的"时间-距离"关系不出现明显违和；
- 生成的 combo 分组和乐句边界对齐率 > 80%。

---

## 2. 已确认的事实基础

> 以下均来自官方文档，是整套设计的硬约束。

### 2.1 文件格式

- 一个谱面集 = 一个文件夹；**一个 `.osu` = 一个难度**；故事板在 `.osb`。
- 纯文本，第一行 `osu file format v14`（写 v14，兼容 stable；lazer 的 v128 老客户端读不了）。
- 8 个 section：`[General]` `[Editor]` `[Metadata]` `[Difficulty]` `[Events]` `[TimingPoints]` `[Colours]` `[HitObjects]`。
- **真正决定可玩性的只有 `[TimingPoints]` 和 `[HitObjects]`**，其余是元数据/外观。
- `[HitObjects]` 一行一个物件：`x,y,time,type,hitSound,objectParams,hitSample`。
- `type` 是位域：`1`=圆圈 `2`=滑条 `4`=新 combo `8`=spinner `16/32/64`=跳色 `128`=mania hold。
- `hitSound` 是位域：`1`=normal `2`=whistle `4`=finish `8`=clap。
- 文件里**没有** combo 长度、没有吸附信息、没有动画。全部运行时推导。

### 2.2 时间系统

- 坐标系 **512 × 384**（4:3），中心 `(256, 192)`。
- **红线**（`uninherited=1`）：`beatLength` = 每拍毫秒数，`BPM = 60000 / beatLength`。每条红线**重置小节线计数**，并把网格原点重置到自己的 `time`。
- **绿线**（`uninherited=0`）：`beatLength` = `-100 / SV`，只改 SV / 音量 / 样本组 / kiai。**不改 BPM，不切网格。**
- 第一条必须是红线。
- 同一毫秒可同时有红线和绿线，红线先应用。
- `[Difficulty]` 的 `SliderMultiplier` 是全局基准；绿线 SV 是局部倍率。

### 2.3 派生公式（生成时必须用）

| 量 | 公式 |
|---|---|
| 判定圈半径 | `r = 54.4 − 4.48 × CS` |
| AR 提前量 | AR<5: `1200 + 600×(5−AR)/5`；AR≥5: `1200 − 750×(AR−5)/5` |
| OD 判定窗（300） | `80 − 6 × OD` ms |
| 滑条速度 | `px/ms = SliderMultiplier × 100 × SV / beatLength` |
| **滑条时长（单程）** | `length / (SliderMultiplier × 100 × SV) × beatLength` |
| 距离吸附参考 | `距离 = (Δt / beatLength) × (100 × SM × SV) × DistanceSpacing` |

> ⚠️ **滑条必须"时长优先"**：先决定这个滑条要持续多久，再反算 `length`。反过来做必然出现"节奏对了但滑条飞太快"。

### 2.4 审核门槛（ranking criteria 摘要）

**Spread（按 drain time）**：

| drain time | 最低难度不得难于 |
|---|---|
| < 2:30 | Normal |
| 2:30 – 3:15 | Hard |
| 3:15 – 4:00 | Insane |

- break 时间可折算，最高难度最多算 30 秒 break。
- 低于 30 秒 drain time 的地图基本无法上架。

**难度参数区间**：

| 难度 | AR | OD | HP | CS |
|---|---|---|---|---|
| Easy | ≤ 5 | 1–3 | 1–3 | ≤ 4 |
| Normal | 4–6 | 3–5 | 3–5 | ≤ 5 |
| Hard | 6–8 | 5–7 | 4–6 | ≤ 6 |
| Insane | 7–9.3 | 7–9 | 5–8 | ≤ 7 |
| Expert | ≥ 8 | ≥ 8 | ≥ 5 | ≤ 7 |

**硬规则（违反直接不能上架）**：

- 物件不得在任何 4:3 下出屏；
- spinner 必须长到 Auto 能拿 1000 分；
- 每个可点击物件至少有一个可听 hitsound；
- 至少两种自定义 combo 颜色。

**指导（guideline，可偏离但需理由）**：

- 所有 circle 和 slider head 必须吸附到音乐中**明确的声音**上；
- sliderend 按拍结构吸附（直线拍 1/4、1/8、1/16；swing 拍 1/6、1/12）；
- 距离吸附 0.8–1.2（Easy）/ 0.8–1.3（Normal）；
- combo 长度要反映乐句，不能过短过长；
- Hard 及以上避免 > 5 notes 的 stream（Hard）；
- spinner 后到下一物件的间隔：Easy 4 拍、Normal 2 拍、Hard 1 拍。

---

## 3. 核心设计原则

### 3.1 两阶段：先节奏，后几何

```
节奏（哪些时刻、什么类型）  →  几何（放哪、怎么走）
```

两个阶段分开实现、分开评估、分开调试。不端到端一把梭。

### 3.2 红线是"测量"，绿线是"编译产物"

| | 红线 | 绿线 |
|---|---|---|
| 本质 | 客观事实（BPM/offset） | 主观决策（SV/音量/kiai） |
| 来源 | 音频分析 | 设计意图 |
| 流水线位置 | **最前** | **最后** |
| 数量 | 通常 1–3 条 | 0–50 条 |

**红线数量由"音乐是否真的变速"决定，不由段落数决定。** 新手最常见的错误是每段加一条红线，结果小节线全乱。

### 3.3 硬约束不可"平均"

神经网络输出的是条件期望；把一百个三角跳取平均，得到的不是三角，是一团模糊区域。因此：

- **几何必须由约束求解器兜底**（边界、可达速度、重叠）；
- **模式必须整块实例化**（见 §3.4）。

### 3.4 模式级生成，而非坐标回归

不学"上下文 → (x, y)"，而学：

```
上下文 → 模式类型 + 参数      （学习）
模式 + 参数 → 精确坐标        （几何，确定性）
```

理由：

1. 坐标回归会产出**平均地图**，丢失所有有辨识度的 pattern；
2. 模式是**刚体**，撞边界时整体平移/缩放即可，形状不坏；
3. 可控性强（调类别权重 = 调风格），数据效率高一个数量级。

### 3.5 可验证优先

三层验证，从上到下难度递增：

| 层 | 内容 | 能否自动验证 |
|---|---|---|
| 格式层 | 能被加载、能打开 | ✔ 能 |
| 规范层 | 吸附、出屏、spinner、间距、combo 长度、hitsound | ✔ 能（AiMod 已覆盖大半） |
| 手感层 | 打不打得到、好不好玩 | ✘ 只能模拟 + 真人试打 |

**前两层做到 100%，第三层做概率优化。**

---

## 4. 架构与数据流

```
                 ┌─────────────┐
  音频文件 ──────▶│ M0 音频分析 │──── BPM/beat/downbeat/onset/段落 ──┐
                 └─────────────┘                                    │
                                                                    ▼
                 ┌─────────────┐        ┌──────────────┐      ┌──────────┐
                 │ M1 时间系统 │◀───────│ M2 结构分析  │─────▶│ M3 设计  │
                 │  (红线)     │        │ (段落/能量)  │      │  决策    │
                 └──────┬──────┘        └──────────────┘      └────┬─────┘
                        │ 网格                                      │ 密度/SV/SR
                        ▼                                           ▼
                 ┌─────────────┐        ┌──────────────┐      ┌──────────┐
                 │ M4 节奏生成 │───────▶│ M5 分组      │─────▶│ M6 几何  │
                 │  (选点)     │        │ (combo/类型) │      │ (pattern)│
                 └─────────────┘        └──────────────┘      └────┬─────┘
                                                                   │
                        ┌──────────────┐      ┌──────────┐         │
                        │ M8 校验闭环  │◀─────│ M7 落地  │◀────────┘
                        │ (AiMod/SR)   │      │ (序列化) │
                        └──────┬───────┘      └──────────┘
                               │ 不达标则回到 M3 / M4 / M6
                               ▼
                          .osu 文件
```

**数据流是单向的，唯一回流是 M8 → M3/M4/M6 的调参闭环。**

---

## 5. 模块规格

### 5.1 M0 音频分析

| 输出 | 方法 | 备注 |
|---|---|---|
| BPM + beat 相位 | Beat This! / All-in-One / librosa（降级） | 拍点检测 |
| downbeat（小节首拍） | All-in-One / 自相关 + 重音模板 | 决定重音，必须准 |
| onset 显著性 | SuperFlux / 谱通量 + 频带加权 | 每帧一个分数 |
| 段落切分 | 自相似矩阵 + 能量曲线 | intro/verse/chorus/bridge/outro |
| 鼓组/人声分离（可选） | demucs | **唯一的重活**，第一版可跳过 |

**产出**：`AudioAnalysis` 对象（见 §6）。

### 5.2 M1 时间系统

**职责**：把音频分析结果变成一组红线，并提供"时间 ↔ 拍"的换算。

```
输入：BPM 估计、offset 估计、downbeat 相位
输出：list[RedLine]，以及 confidence / residual 报告
```

**规则**：

1. offset 精度要求 ±5ms 以内（人耳敏感），**必须可 1ms 微调**；
2. 恒定 BPM → **1 条红线**；
3. 仅当真的变速 / 明显 drift / 变拍号时才加红线；
4. 输出 `downbeat_phase`（0–3）：相位错了不破坏可玩性，但重音全错位；
5. 输出诊断：`平均残差(ms)`、`drift(ms/分钟)`，供人判断是否手动干预。

**网格**（M4 使用）：

```
第 k 格 = red.time + beat_length × k / divisor
```

### 5.3 M2 结构分析

**职责**：把曲子切成段落，给每段打上"角色"和"能量"。

```
Section(start, end, role, energy, density_target, sv_target, kiai)
```

**角色 → 密度**的映射是设计决策（M3），M2 只负责测量能量和边界。

**关键对齐问题**：段落边界和红线边界常常不重合（chorus 可能起在红线后 0.5 拍）。规则：

- 段落边界**吸附到最近的拍**，不吸附到红线；
- 密度曲线在段落边界做**线性过渡**（约 1–2 拍），避免突兀跳变。

### 5.4 M3 设计决策

**职责**：把"测量结果 + 用户参数"变成"生成参数"。

| 输入 | 说明 |
|---|---|
| `target_sr` | 目标星级（如 4.2） |
| `difficulty_tier` | Easy/Normal/Hard/Insane/Expert |
| `density_bias` | 密度倾向 |
| `slider_ratio` | 滑条占比 |
| `jump_bias` | 跳跃倾向 |
| `seed` | 随机种子（可复现） |

**输出**：每个段落的 `density`（目标 NPS）、`sv` 意图、`kiai`、`difficulty settings`。

**难度参数选择**：直接查 §2.4 的区间表，按 tier 取中位值。

**目标 SR 闭环**（v2 再做）：生成 → 算 SR → 二分调整 `density` 或 `jump_bias` → 逼近目标。

### 5.5 M4 节奏生成

**核心**：在网格上选择子集。

```
候选 = [(t, 格位, 分度) for t in grid_ticks]
score(t) = onset_salience(t) × accent_weight(格位) × density_gate(段落)
选出 score 最高的子集，满足 NPS 上限
```

**约束**：

| 约束 | 值 |
|---|---|
| 各段落硬 NPS 上限 | 见下表 |
| 密度由段落能量驱动 | verse 低、chorus 高 |
| 长音/低能量段 | 允许留空，或转 slider/spinner |
| 每小节至少 1 个重音位物件 | 保证"踩得上点" |

**NPS 参考上限**（1/4 分度下，`NPS = 4 × BPM / 60`）：

| BPM | 1/4 的 NPS | 评价 |
|---|---|---|
| 120 | 8.0 | 可接受 |
| 150 | 10.0 | 偏密 |
| 180 | 12.0 | 接近极限 |
| 200 | 13.3 | 不可打 |
| 220 | 14.7 | 不可打 |

> **绝对上限建议 12 NPS**，超过必须降分度或留空。

**分度选择**：按段落决定（主歌 1/4、swing 段 1/6），**不是全局常量**。

### 5.6 M5 分组

**职责**：给物件打 `+4`（新 combo），并决定物件类型。

**combo 规则**：

1. 长度控制在 **4–12**（AiMod 在 15–18 才警告，但人类习惯更短）；
2. 在**乐句边界**处断 combo（通常 2 或 4 小节）；
3. 密集段落（1/4 流）可每 4 个断一次；
4. spinner 必须带新 combo（AiMod 会检查）。

**物件类型规则（v1）**：

| 条件 | 类型 |
|---|---|
| 短促重音、单点 | circle |
| 持续音、长音、人声拖腔 | slider |
| 段落留白、长音收尾 | spinner |
| 密度过高时 | 把部分 circle 合并为 slider 降低点击密度 |

**滑条占比**：建议 20%–35%（偏离太多会显得单调或过于拖沓）。

### 5.7 M6 几何

**职责**：给每个物件定坐标、给滑条定路径和长度。

#### 坐标约束

- 边界：`[r, 512−r] × [r, 384−r]`；
- 相邻物件的**可达速度**上限（`px/ms`），随难度提高；
- 时间相近的物件不能视觉重叠（参考 AR 提前量）；
- 优先让轨迹**连续、转角平滑**（降低 jerk）。

#### 间距模型

```
目标距离 = (Δt / beat_length) × (100 × SM × SV) × spacing_factor
```

`spacing_factor` 由难度和段落强度决定，建议落在 0.8–1.3（对齐距离吸附的建议区间）。

#### 模式词汇表（v1）

见 §7。**生成顺序**：先选模式 → 再实例化坐标 → 最后整体做边界投影。

#### 滑条

- **时长优先**：`length = 时长(ms) × (SM × 100 × SV) / beatLength`；
- 曲线默认 `B`（贝塞尔），简单段落用 `L`（直线）；
- 控制点数量 ≤ 4，避免"absurdly large amount of points"警告；
- 反向滑条（`slides ≥ 2`）只用于长音，长度要保证反向可读。

#### 边界处理（模式是刚体）

```
if 模式越界:
    整体平移最小位移量
    if 仍越界: 整体等比缩放 (0.9, 0.95, ...)
形状保持不变
```

### 5.8 M7 落地（序列化）

**职责**：把内部数据模型写成 `.osu`。

**输出清单**：

1. `[General]`：`AudioFilename`（必须与真实文件一致）、`Mode: 0`、`StackLeniency: 0.7`；
2. `[Metadata]`：`Title/TitleUnicode/Artist/ArtistUnicode/Creator/Version`，`Version` 在集内唯一；
3. `[Difficulty]`：HP/CS/OD/AR/SM/TickRate；
4. `[Events]`：背景、break（break 计入 drain time 计算）；
5. `[TimingPoints]`：红线在前、绿线在后，**按时间升序**；
6. `[Colours]`：至少 2 种 combo 色；
7. `[HitObjects]`：按时间升序，时间整数。

**由 M3/M6 的意图编译出绿线**：

```
sections.sv 变化 → 绿线 (-100/SV)
sections.volume 变化 → 绿线 volume
sections.kiai 变化 → 绿线 effects |= 1 / &= ~1
```

**编码**：UTF-8、无 BOM、小数点用 `.`（.NET 需 `InvariantCulture`）。

### 5.9 M8 校验闭环

**三层检查**：

#### 第一层：格式（自检）
- 能被解析器读回；
- 时间升序、无重复时间；
- 第一条是红线；
- 所有 `curvePoints` 在合法范围。

#### 第二层：规范（对标 AiMod）
官方 AiMod（`Ctrl+Shift+A`）已覆盖：

| 检查项 | AiMod | 是否自实现 |
|---|---|---|
| 物件未吸附 / 滑条尾未吸附 | ✔ | 需要（生成时就该保证） |
| 物件 / 滑条尾出屏 | ✔ | 需要（边界投影） |
| spinner 太短 | ✔ | 需要 |
| 两物件 < 10ms / 同时刻 | ✔ | 需要 |
| 无 hitsound | ✔ | 需要 |
| 间距太近 / 太远 | ✔（需勾选） | 需要 |
| combo 太长 | ✔ | 需要 |
| drain time < 30s | ✔ | 需要 |
| 元数据跨难度不一致 | ✔ | 多难度时用 |
| 复杂 patterning / timing 质量 | ✘ | **AI 也做不好，留给人** |

> **策略**：不重写 AiMod，而是**生成时就不产生这些问题**；自实现一份等价检查用于批量跑（AiMod 只能手动在 GUI 里开）。

#### 第三层：手感
- `rosu-pp` 算 SR / Aim / Speed；
- 光标可达性模拟（最大速度/加速度约束）；
- 目标 SR 二分。

**闭环**：不达标 → 调 M3 的 `density` / `jump_bias` → 重跑 M4/M6。

---

## 6. 数据模型（草案）

```python
@dataclass
class RedLine:
    time: int              # ms
    beat_length: float     # ms/beat
    meter: int = 4
    # 派生：bpm = 60000 / beat_length

@dataclass
class GreenLine:
    time: int
    sv: float = 1.0        # 文件里存 -100/sv
    volume: int = 100
    sample_set: int = 0
    kiai: bool = False

@dataclass
class Section:
    start: int
    end: int
    role: str              # intro/verse/chorus/bridge/outro
    energy: float          # 0..1
    density: float         # 目标 NPS
    sv: float              # 意图，非文件字段
    kiai: bool = False

@dataclass
class HitObject:
    time: int
    x: int
    y: int
    kind: Literal["circle", "slider", "spinner"]
    new_combo: bool = False
    hitsound: int = 0
    slides: int = 1
    length: float = 0.0
    curve_type: str = "B"
    curve_points: list[tuple[int, int]] = field(default_factory=list)
    end_time: int = 0      # spinner

@dataclass
class Pattern:
    kind: str              # stream/triangle/zigzag/jump/square/slider_run
    objects: list[HitObject]
    anchor: tuple[int, int]
    rotation: float
```

> **注意**：`Section.sv` 和文件里的绿线是两种东西，中间隔着一个编译器（§5.8）。这样改"副歌用 1.2x"只需改一个字段。

---

## 7. 模式词汇表（v1）

| 模式 | Δt | 距离 | 转角 | 音频特征 |
|---|---|---|---|---|
| **stream（串）** | 全等（1/4） | 近似相等、偏小 | 小（±10–30°），同向累积 | 连续密集 onset |
| **jump（跳）** | 全等（1/2、1/1） | 大 | 不定，常成对 | 强重音、鼓点 |
| **triangle（三角）** | 全等 | 三边近似相等 | **±120°**，连续两次同向 | 三连音、重音组 |
| **zigzag（折返）** | 全等 | 相等 | **交替** ±θ（大） | 强弱交替 |
| **square（方框）** | 全等 | 相等 | 连续 ±90° | 四拍循环 |
| **slider_run** | 混合 | 沿路径 | 平滑 | 长音、人声 |

**判定用的尺度无关特征**：

```
归一化 Δt      = Δt / beat_length
归一化距离     = distance / (Δt × 参考速度)
转角序列       = angle(v[i], v[i+1])
转角符号一致性 = sign consistency
```

> 三角的"闭合"是**跨三个点的全局约束**，局部转移模型无法保证，所以必须整块实例化。

---

## 8. 学习层

### 8.1 目标

**不是**学坐标，而是学：

```
上下文 → 模式类型 + 参数（边长、朝向、间距比例）
```

### 8.2 路径（无需先训大模型）

1. **切片**：从数据集中取每 3–6 个连续物件；
2. **特征**：尺度无关特征（§7）；
3. **聚类**：KMeans / DBSCAN → 自然浮现三角/串/折返等团；
4. **命名**：人工看一眼样例，给簇起名（这是"从数据里发现社区词汇表"）；
5. **分类器**：输入音频上下文（段落能量、密度、拍位、前一个模式），输出模式类别。

### 8.3 数据源

- `data.ppy.sh` 的月度 `.osu` 全量 dump（`*_osu_files.tar.bz2`）；
- 使用前阅读同目录 `LICENCE.txt`。

### 8.4 注意事项

- **按难度分层统计**：同样的三角，2★ 边长 60px，7★ 边长 200px；
- **时代偏差**：数据集集中在 2015–2020 风格；
- **模式与 combo 耦合**：一个 pattern 通常 = 一个 combo，需联合决策；
- **旋律型 pattern** 需要额外输入 pitch 轮廓，v1 不做。

---

## 9. 输出规范与坑

1. **必须写 v14**（v128 老客户端读不了）；
2. **UTF-8 无 BOM，小数点用 `.`**；
3. `AudioFilename` 必须与真实文件名完全一致；
4. `Version`（难度名）在集内唯一；
5. `[TimingPoints]` 必须按时间升序，第一条必须红线；
6. 1/3 网格会产生非整数毫秒，**取整**（误差 < 1ms，无感）；
7. 未吸附不报错但会被 AiMod 警告 → 生成时保证吸附；
8. `StackLeniency` 用 0.7；密集段落注意自动堆叠可能毁掉可读性；
9. break 会算进 drain time，影响 spread 要求。

---

## 10. 目录结构（建议）

```
osu-mapwright/
├── docs/
│   └── DESIGN.md              # 本文档
├── mapwright/
│   ├── __init__.py
│   ├── audio/                 # M0
│   │   ├── tempo.py
│   │   ├── onset.py
│   │   └── structure.py
│   ├── timing/                # M1
│   │   ├── redline.py
│   │   └── grid.py
│   ├── design/                # M3
│   │   └── profile.py
│   ├── rhythm/                # M4
│   │   └── generator.py
│   ├── grouping/              # M5
│   │   └── combo.py
│   ├── geometry/              # M6
│   │   ├── spacing.py
│   │   ├── patterns.py
│   │   └── solver.py
│   ├── osu/                   # M7
│   │   ├── model.py
│   │   ├── writer.py
│   │   └── reader.py
│   └── validate/              # M8
│       ├── automod.py
│       └── difficulty.py
├── tests/
├── pyproject.toml
└── README.md
```

---

## 11. 里程碑

> 里程碑编号（S1–S9）与模块编号（M0–M8）是两套体系：里程碑表示"先做什么"，模块表示"代码长什么样"。

| 里程碑 | 内容 | 对应模块 | 产出 |
|---|---|---|---|
| **S1** | `.osu` 读写 + 数据模型 + 最小可玩文件 | M7 | 能被 osu! 打开 |
| **S2** | 音频分析（BPM/beat/downbeat）+ 红线生成 | M0, M1 | 时间轴对准 |
| **S3** | 段落切分 + 密度曲线 | M2, M3 | 有起伏 |
| **S4** | 节奏生成（圆点，格点选点） | M4 | 节奏像这首歌 |
| **S5** | 几何 + 间距模型 + 滑条 | M6 | 开始像谱面 |
| **S6** | 校验闭环（AiMod 等价 + SR） | M8 | 能自动调参 |
| **S7** | 多难度 spread | M3, M7 | 具备上架资格的形状 |
| **S8** | 模式词汇表 + 实例化 | M6 | 有辨识度的 pattern |
| **S9** | 学习层（聚类 → 分类器） | §8 | 风格化 |

> **关键：S1–S3 是纯工程，不依赖任何 ML，应当最先完成并稳定。**

---

## 12. 风险与开放问题

| 风险 | 影响 | 缓解 |
|---|---|---|
| offset 估计误差 | 全盘皆输 | 1ms 微调 + 残差报告 |
| 过密段落 | 不可打 | 硬 NPS 上限 |
| 滑条速度不自洽 | 飞出屏幕 | 时长优先反算长度 |
| pattern 平均化 | 无辨识度 | 模式实例化，不回归坐标 |
| 数据集版权 | 不能分发 | 只用于训练，产物不含原曲 |
| AiMod 规则滞后 | 误判 | 以现行 RC 为准，AiMod 只做交叉验证 |

**开放问题**：

1. 段落边界与红线边界不重合时的过渡策略（§5.3 已给初步规则，需实测）；
2. 目标 SR 的收敛速度与稳定性（二分可能震荡）；
3. 多难度之间如何保持"同一套 pattern 语言"的连贯性；
4. 旋律型 pattern（跟随 pitch）是否值得做。

---

## 13. 参考资料

- [.osu 文件格式](https://osu.ppy.sh/wiki/en/Client/File_formats/osu_%28file_format%29)
- [Beatmapping](https://osu.ppy.sh/wiki/en/Beatmapping)
- [Timing tab](https://osu.ppy.sh/wiki/en/Client/Beatmap_editor/Timing)
- [osu! ranking criteria](https://osu.ppy.sh/wiki/en/Ranking_criteria/osu!)
- [Beatmap ranking procedure](https://osu.ppy.sh/wiki/en/Beatmap_ranking_procedure)
- [AiMod](https://osu.ppy.sh/wiki/en/Client/Beatmap_editor/AiMod)
- [data.ppy.sh](https://data.ppy.sh/)（谱面数据 dump）
- Dance Dance Convolution（DDR 谱面生成，两阶段思路参考）
