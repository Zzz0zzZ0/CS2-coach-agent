# 关系表达与跨回合统计 v2

开发契约与 32 条合成表达在 `48a3003` 先冻结。新增主动 / 被动语态、中英文简短表达、完整扫描计数和主体所在队伍的条件回合胜率。该集合由实现者编写，属于开发集，不是独立语言泛化测试。

示例（页面选择 Mirage，或在文本中提供 `Match 2396609, map Mirage.`）：

- `Cedar was killed by Alpha after the bomb was planted`
- `Count rounds where Alpha got the opening kill against Cedar`
- `Round win rate when Alpha traded Bravo within 320 ticks`
- `回合胜率：下包后 Alpha 击杀 Cedar`

Alpha / Bravo / Cedar 是合成测试身份；实际查询须用范围内选手名称。被动表达会交换语法主语与事件主体。`first killed by` 在本受限语法内解释为回合首杀，不支持其他 first 修饰含义；补枪指为具名队友击杀同一敌人。秒数、阵营附加条件、否定、合取或析取条件无法完整解析时返回 unsupported。仍不是通用自然语言理解。

## 数字契约

- 统计先扫描限定范围，再按 k 展示事件证据；匹配回合去重，不以事件数或返回的 top-k 作分母。
- `co_present_rounds` 是完整名单中两名选手共同参赛的回合数；名单不全的回合进入 unknown。所有匹配引用保存在 `matched_source_ids`，胜负引用在 `outcome_source_ids`。
- `exact_matched_rounds` 与 `match_rate` 只在关系范围完整时提供；缺失事实时保留已证实数量，完整数字为 null。
- 根据主体该回合名单阵营与 winner 判断胜负；未知胜负 / 阵营不进入 `known_outcome_rounds`。`observed_win_rate` 使用已知样本，零分母返回 null；未知范围或结果明确标注不完整。
- 胜率为观测描述，不是个体贡献、因果增益或胜率预测。API、页面消息与 agent 上下文共用数字表述；事件卡片仅为证据样本。

## 验收协议

257 项离线测试已通过；其中新增测试覆盖 32 个冻结表达，以及 top-k 截断、重复证明、零匹配、缺失名单 / tick / 胜负 / 阵营、API 与混合调用层一致性。原不支持用例中的被动语态已迁入支持测试。

`relation_engine_v2_protocol.json` 固定实现与输入；旧 v1 协议 / 结果保留。已通过 48/48 条既有关系回归与 96/96 条计数 / 胜率衍生核算。旧检索三模式开发集均为 50/50；旧 holdout 为 28/30、30/30、30/30，与 v1 相同。浏览器验证 Nuke 21 回合的 donk 补枪样本为 1/1 胜，TeSeS 下包后击杀 tN1R 为零匹配且胜率未知，引用跳转有效。常驻服务状态单独核对，不能由离线通过推断已加载。

## Review gate

- Verdict：通过（开发 / 工程回归范围）。
- Findings：无已复现的阻断问题。
- Verified：257 项离线测试、48 条原关系、96 条聚合核算、旧检索与页面消息 / 来源跳转；生产图谱未变。
- Risks：表达仍受限，AI 标签与源解析共享事实；不作独立泛化或质量增益声明。
- Next actions：完善公平基线，随后做隔离比赛检索评测；服务加载状态另行验收。

常驻服务验收：在 Celery active / reserved / scheduled 与 Redis 队列均为 0 后正常重启 API 和 worker，新 `/api/graph/search` 已实测提供 match_id 与跨回合统计，预算端点返回 200，worker 响应且无任务。原 Vite 仍监听 IPv6 localhost:5173。见 `relation_engine_v2_live_service_audit.json`；此次检查未提交分析任务或触发模型调用。
