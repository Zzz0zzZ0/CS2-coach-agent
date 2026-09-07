# 求职与港硕申请材料使用说明

当前可讲清楚的主线是：**把不可靠的自然语言分析问题，拆成可核验的数据、检索、统计和生成边界，并用实验决定实现方向。** 工程工作与开发评测已经有证据；模型让选手变强、专家认为建议更好、未见比赛泛化等结论尚无充分证据。

## 英文简历表述草稿

- Built an evidence-grounded CS2 analysis prototype using FastAPI, Celery/Redis, SQLite, Milvus and React, covering 20 historical series, 49 maps and 56 player profiles with roster-based participation denominators and round-level source traceability.
- Designed frozen bilingual retrieval experiments comparing lexical, dense and fusion configurations; audited 768 historical-development results and 960 isolated-series pilot results, preserving negative and regression cases rather than assuming model or RRF improvements.
- Implemented bounded source-event relation verification and complete-scope aggregates; validated 60 bilingual pilot expressions and 780 integration checks, with a separate 224-query player-profile equivalence audit showing a local median latency reduction from 335 ms to 104 ms.

这些是项目贡献草稿，不自动代表个人独立完成全部实现。面试时如实说明使用了 AI 辅助开发与审核，并能解释核心取舍、复现结果、失败定位及自己负责的部分。若版面有限，第三条不必同时放两个互不相同的测试数字。

## 港硕申请中的研究动机草稿

> Building this prototype showed me that the main difficulty in applied language-model systems is often the boundary between a plausible answer and an answer supported by the available evidence. I investigated this boundary through roster-aware statistics, source-event verification and frozen retrieval experiments. A bilingual dense setup improved one development sample but did not show a stable advantage across two isolated series, while rank fusion also failed to improve consistently. These findings strengthened my interest in information retrieval, uncertainty-aware systems and reproducible evaluation. I would like to study how such systems can choose between text retrieval, structured queries and abstention, and how their usefulness should be evaluated with independent users.

这是通用研究动机，不包含未经提供的课程、导师、学校匹配或个人学术经历。正式申请时应结合真实背景与具体项目要求调整，不能直接扩写成已发表研究或独立验证成果。

## 面试建议展示顺序

1. 先展示错误风险：名单缺失、无事件参赛回合、赛前刀局污染、仅同现但不满足关系的检索结果。
2. 展示一个可下钻的关系与一个真正无答案查询，说明 found / not_found / unknown / unsupported 的区别。
3. 展示完整分母统计：页面只取少量证据，计数与胜率仍来自完整范围；未知结果不当失败或零值。
4. 展示 benchmark 图，主动指出两场比赛优劣方向不同、文本拒答缺口以及 RRF 退化。
5. 最后讲可复现流程、失败保留、预算边界与下一步独立评测。

## 不应使用的表述

“GraphRAG 泛化达到 100%”“RRF 优于所有基线”“AI 教练提高了选手胜率”“专家评审已通过”“56 个完整生涯画像”均超出证据。可以说“受限源事件查询契约通过”“当前已收录样本画像”“AI 辅助开发评测”。

时间趋势与稳定风格标签暂不作为展示能力：历史清单没有逐场日期，窗口也只有 20 场且组成不均。先取得可靠日期、更多可比样本和明确的时间 / 角色条件，再设计时间隔离验证；不把 match_id 或文件时间伪装成比赛日期。
