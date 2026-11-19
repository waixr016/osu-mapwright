# osu-mapwright

把一首歌变成一张 **osu! standard** 谱面：能直接进游戏打，也能在官方编辑器里继续改。

> **当前状态**：设计阶段。只有文档，没有代码。
> 完整设计见 **[docs/DESIGN.md](docs/DESIGN.md)**。

## 这是什么

一个自动谱面生成工具。目标不是"取代 mapper"，而是把 mapper 最耗时的机械劳动自动化，把创作判断留给人。

拿到的产物应该是：**一张节奏对得上歌、间距打得动、通过官方 AiMod 检查的 draft**，而不是一张需要推倒重来的生成物。

## 设计要点

- **两阶段**：先定节奏（哪些时刻、什么类型），再定几何（放哪、怎么走）。
- **红线是测量，绿线是编译产物**：时间轴来自音频分析，滑块速度/音量来自设计决策，两者在流水线里一头一尾。
- **模式级生成**：学"三角跳/串"这类 pattern 的类型和参数，而不是回归坐标——后者只会产出"平均地图"。
- **可验证优先**：格式层与规范层做到 100%，手感层做概率优化。

## 路线

| 里程碑 | 内容 |
|---|---|
| S1 | `.osu` 读写 + 数据模型 |
| S2 | 音频分析 + 红线 |
| S3 | 段落切分 + 密度曲线 |
| S4 | 节奏生成 |
| S5 | 几何 + 滑条 |
| S6 | 校验闭环 |
| S7 | 多难度 |

详见 [docs/DESIGN.md](docs/DESIGN.md) §11。

## 快速开始

```bash
python examples/make_minimal.py build   # 生成一张可玩的最小谱面
```

把生成的 `.osu` 连同任意 `song.mp3`、`bg.jpg` 放进 osu! 的 `Songs` 目录，按 `F5` 刷新生效。

读写 API：

```python
from mapwright.osu import parse, serialize, save

beatmap = parse(open("song.osu", encoding="utf-8").read())
beatmap.metadata.version = "Hard"
save(beatmap, "out/Song (mapper) [Hard].osu")
```

跑测试：

```bash
python -m unittest discover -s tests -t . -v
```

## 许可

MIT
