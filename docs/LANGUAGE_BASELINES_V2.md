# 双语 dense 与词法分词对照

在 `738388d` 冻结参数、代码、模型文件及既有问题 / 标签后，完成 24 个开发语义问题、48 个中英文表述、2 组问法处理、8 个检索方法，共 768 条结果。独立算术与范围核算 768/768 通过，原 BM25 / MiniLM / RRF 的 144 条排序全部复现。

## 结果

正例按 12 个语义组配对平均，k=5；12 个无答案语义组单独计算。原始问法：

| 方法 | 英文 nDCG | 中文 nDCG | 配对 nDCG | 配对 Recall |
| --- | ---: | ---: | ---: | ---: |
| unicode61 BM25 | 0.1330 | 0.1654 | 0.1492 | 0.2569 |
| 预训练子词 BM25 | 0.2049 | 0.1272 | 0.1660 | 0.2083 |
| MiniLM dense | 0.1827 | 0.1124 | 0.1476 | 0.2188 |
| Jina 中英 dense | 0.1922 | 0.4374 | 0.3148 | 0.3819 |
| unicode61 + Jina RRF | — | — | 0.2277 | 0.3299 |
| 子词 + Jina RRF | — | — | 0.2653 | 0.3021 |

沿用先前固定词表后，Jina 配对 nDCG 为 0.3252、Recall 为 0.3958；MiniLM 为 0.1646 / 0.2708。两种 BM25 排序没有因词表变化而改善。其他消融及每题失败保存在原始结果中。

所有文本方法的无答案误召回仍为 100%：这些基线尚未校准拒答，不能把 top-k 文本相似当作关系成立的证明。新模型的提升也没有消除主体、同一敌人和 tick 时序错误。预训练子词 BM25 提升英文但降低中文，不能据此宣称“中文词法问题已解决”。本轮没有将 Jina 替换为生产默认 embedding。

## 公平性与复现

- 所有方法读取相同 1,019 回合的源事实文本和相同显式范围 / 实体，k=5；BM25 IDF 使用全语料。自然语言范围解析单列为生产关系查询任务。
- 原 MiniLM 的真实 tokenizer 上限为 128，完整分块后等权平均；新 Jina 为 512，同样完整分块并 L2 归一化。模型和实际容量均不同，只能归因于整套基线设置。
- 保持原量化 MiniLM 的完整 1,019 文档批次以复现已有排序；Jina 仅编码所有查询范围的并集 88 回合。分别用时约 117.1 秒 / 31.4 秒，编码文档数量不同，**不能据此宣称新模型建库更快**。检索耗时单独保留；不作一次运行的生产性能结论。
- Jina 模型从[官方仓库固定 revision](https://huggingface.co/jinaai/jina-embeddings-v2-base-zh/tree/c1ff9086a89a1123d7b5eff58055a665db4fb4b9)取得，约 641 MB ONNX，Apache-2.0。使用现有 FastEmbed 0.8.0 与 ONNX Runtime，无新依赖、不执行下载的 Python 代码。模型定位参考[官方模型卡](https://huggingface.co/jinaai/jina-embeddings-v2-base-zh)。
- 不读取金标准关系槽位来排名；标签仅在得到排序后评分。RRF 使用完整候选排序，固定常数 60，没有逐题调参。远程模型调用 0。

在冻结提交 `738388d` 的环境执行：

```bash
PYTHON_DOTENV_DISABLED=1 HF_HUB_OFFLINE=1 .venv/bin/python -m scripts.evaluate_language_baselines \
  --protocol datasets/evaluation/language_baselines_v2_protocol.json \
  --output data/evaluation/language_baselines_v2_reproduction.json
```

本机模型路径写入协议便于复现；其他机器需按 manifest 获取同一制品并记录新的路径映射，不能绕过哈希检查。输出须为新文件。协议、模型 manifest、结果与审计分别见 `datasets/evaluation/language_baselines_v2_*.json`。

## Review gate

- Verdict：通过（开发实验与工程复现范围）。
- Findings：子词中文下降、融合落后于 Jina dense、全部文本负例误召回已保留。
- Verified：768 条指标 / 范围核算及 144 条原排序复现；冻结制品哈希一致。
- Risks：AI 源标注，12 个正例组且共享历史语料；模型与分块容量不同；未做独立质量盲评或统计效力论证。
- Next actions：冻结隔离比赛的事实标签并做检索试点，保留失败；不能靠继续调这 24 题代替泛化验证。
