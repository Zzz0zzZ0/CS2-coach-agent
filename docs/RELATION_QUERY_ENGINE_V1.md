# 受限自然语言关系查询 v1

上一轮发现关系题的有效证据频繁漏出 top-5，无答案题又持续返回泛化回合。本次增加一个读取源事件的受限查询路径：明确解析动作主体、对手与关系条件，扫描限定范围，验证后再截取结果。没有给已有 BM25 / dense / RRF 分数加权或按题目 ID 打补丁。

## 行为与接口

`GraphRAGClient.retrieve_relations` 返回有状态的 `RetrievalResult`；已有 `retrieve` 保留证据列表接口，但关系题不再进入普通图评分。`GET /api/graph/search` 增加可选 `match_id`，返回 `relation`、用户提示 `message` 与事件证据。前端显示核查 / 匹配回合数和状态，可点击来源展开回合。

支持三类：指定选手对指定对手的首杀、指定定向击杀发生在下包之后、在指定 tick 窗口内为指定队友补枪。补枪要求三个身份不同、队友队伍一致、击杀同一敌人，且 `0 < 延迟 <= 窗口`。下包之后严格使用 tick 大于关系，同 tick 不算。窗口为 1–6400 ticks；不猜测秒数对应的 tick rate。

示例（选手是否参赛、事件是否存在仍由实际数据决定）：

```text
Match 2396949, map Nuke. Find rounds where NiKo kills donk after a bomb plant.
比赛 2396949，地图 Nuke。查找 NiKo 击杀 donk 并取得本回合首杀的回合。
Match 2396949, map Nuke. NiKo trades teammate m0NESY within 320 ticks
```

要求显式比赛或地图范围，可以写进上述前缀或由 API 元数据提供；两者冲突时不扩大范围。名称按限定范围的完整参赛名单、大小写不敏感解析为 Steam ID；未知 / 重名身份不猜测。当前不支持额外阵营、武器、否定、反向下包时序、秒数或多关系并列条件，这些已识别的关系请求返回 `unsupported`。完整句式匹配避免静默丢掉尾部限制。

| 状态 | 含义 |
| --- | --- |
| `found` | 返回具体事件及 tick 证明关系成立；`complete=false` 时匹配数只是已确认部分 |
| `not_found` | 非空、名单完整的限定候选范围全部核查，关系相关字段完整，未发现满足条件的事件 |
| `unknown` | 图谱不可用、范围为空、身份不确定、名单 / 事件信息缺失、源读取失败或范围超过 5000 回合 |
| `unsupported` | 不能完整理解该句式或过滤条件，未宣称关系不存在 |

`not_found` 只针对现有解析记录，不是独立重读 Demo 后对真实比赛的绝对证明。范围缺失和源字段缺失不能作为无答案标签。

混合检索调用层优先走同一个关系引擎，不再并入未经关系验证的向量回合；重试保留原问题，不把 Critique 文本加入受限语法，也清除旧泛化证据。纯向量客户端遇到已识别的关系请求返回 `unknown`，不会调用重写模型。其他普通战术 / 画像查询沿用原检索路径。

## 验证协议

先以独立合成比赛、Alpha / Bravo / Cedar / Delta 四个虚构选手验证，再冻结 [生产回归协议](../datasets/evaluation/relation_engine_v1_protocol.json)。原 [24 题与标签](../datasets/evaluation/relation_v1_queries.json) 保持不变，随后只运行一次完整回归。

```bash
PYTHON_DOTENV_DISABLED=1 HF_HUB_OFFLINE=1 .venv/bin/python -m scripts.evaluate_relation_queries \
  --protocol datasets/evaluation/relation_engine_v1_protocol.json \
  --output data/evaluation/new-reproduction/relation-report.json
```

回归引擎只接收自然语言及普通范围元数据，不接收标签中的 actor / target / family / window。结果产生后才核对解析槽、完整候选范围、所有匹配回合、事件证据、指标、API 和混合调用层一致性。Graph 公共列表、状态接口与 API 的 k=5，混合调用层维持 k=4；此题组每个正例最多 4 个相关回合，因此可核对完整集合，不掩盖数量截断。

## Verdict

通过本轮工程验收。实现与协议先在 `3147950` 冻结并推送，再运行已观察的关系题；48/48 个表述、624/624 项核对通过。218 项离线测试及前端构建通过，冻结提交 [CI](https://github.com/Zzz0zzZ0/CS2-coach-agent/actions/runs/34074910972) 通过。完整 [关系回归结果](../datasets/evaluation/relation_engine_v1_report.json) 保留所有查询、解析结果、事件证明与检查项。

## 实际结果

| 检查 | 结果 |
| --- | --- |
| 自然语言关系回归 | 24 题意 / 48 中英文表述，全部通过 |
| 正例 nDCG@5 / Recall@5 | 1.0000 / 1.0000（12 个题意，语言先按题平均） |
| 无答案误召回 / 正例误拒答 | 0 / 0（各 12 个题意） |
| 角色、窗口、范围、事件证明与入口一致性 | 624/624 项通过 |
| 既有画像 / 战术结构契约 | 50/50 |
| 既有检索开发集 Vector / Graph / Hybrid | 50/50、50/50、50/50 |
| 既有已观察 holdout Vector / Graph / Hybrid | 28/30、30/30、30/30，原有两个 Vector 失败保留 |

关系路径只从自然语言读取条件；SQL oracle 的结构槽没有传给生产实现。Graph 与 Hybrid 在这里共享一个确定性关系引擎，入口一致性不算两种独立方法的成功，也不说明 RRF 算法改善。上述满分只证明已观察题组与受限句式下的工程行为，不能推断新表达或新比赛性能。

[普通路径回归摘要](../datasets/evaluation/relation_engine_v1_legacy/summary.json)、[开发集完整结果](../datasets/evaluation/relation_engine_v1_legacy/development.json) 与 [旧 holdout 完整结果](../datasets/evaluation/relation_engine_v1_legacy/holdout.json) 均保留，模型文件哈希与此前冻结本地模型相同。图谱 SHA 未变化，所有验证远程模型调用均为 0。

复现普通路径回归：

```bash
PYTHON_DOTENV_DISABLED=1 HF_HUB_OFFLINE=1 LLM_AUXILIARY_CALLS_ENABLED=false \
  .venv/bin/python -m scripts.check_relation_legacy_regression \
  --model-dir /absolute/path/to/frozen/local/model \
  --output-dir data/evaluation/new-legacy-reproduction
```

此命令只接受本地 Milvus 和匹配哈希的 FastEmbed 模型；模型发现不访问远端，查询采用原生产 embedding 适配器。关系查询单次状态接口的本机中位耗时约 3.67 ms，仅针对本轮 17–30 候选回合范围，不含前端 / API 往返，不能作为大库吞吐结论。

## Findings

已补齐单纯 top-k 排序无法表达的主体和时序核验。没有高置信度阻断项。纯向量关系请求明确返回“信息不足”，因此不能把它的空列表当成正确识别了无答案；有答案时应使用源事件关系路径。复核时修正了地图元数据合并、前端来源参数及缺失范围 / 非法 k 的边界，防止冲突范围扩大或把没有返回位置误当成关系不存在。

## Verified

新增 46 项测试覆盖双语角色、作用域冲突、未知身份、严格时序、0 / 1 / 320 / 321 ticks、错误队伍、跨回合、不支持的限制、源信息缺失、部分证据、无图谱、API 状态、混合入口和重试旧证据清理。使用合成数据，没有从 frozen qrels 生成实现结果。无新增依赖、模型调用或生产数据写入。

另在临时 `127.0.0.1:18101` 新进程与构建后的前端完成 [浏览器验收](../datasets/evaluation/relation_engine_v1_ui_audit.json)：donk 为 zont1x 的补枪命中第 1 回合，按钮打开实际 Nuke 回合时间线，显示 tick 11243 / 11385；TeSeS 对 tN1R 的下包后击杀问题显示核查 21 回合、匹配 0，并清除旧结果；5 seconds 限制显示不支持与不完整提示。浏览器控制台无错误。临时预览页面与服务已关闭，原服务未动。

## Risks

仅支持三类关系的受限句式，识别边界以已测试语法为准，不能宣传为任意中文问答。来源缺失检查不等于独立验证 Demo 解析完整性。候选扫描上限 5000 回合，范围过大返回未知；当前小库采用现有 SQLite 索引，不引入额外索引服务。既有 24 题已经观察过，即使全通过也不构成独立泛化或图算法优势证据。

原 8001 / 5173 常驻服务及 Worker 不重启。本次验证使用新进程；常驻后端下一次正常重启后才加载新代码。前端开发服务可热更新，但旧后端暂时不会返回新增状态。

## Next actions

优先建立新的独立表达开发集：主动 / 被动、角色交换、阵营条件、不同时间单位、复合限制和不支持句式，明确识别率与误拒答。实现前冻结问题，不在这 48 个已通过表述上继续调分。随后扩展跨回合画像的统计分子 / 分母任务，并对同一输入下的事件表示、词法 / dense 基线另做冻结实验。常驻后端的代码加载留到下一次正常服务重启，不把隔离预览验收当成已上线。
