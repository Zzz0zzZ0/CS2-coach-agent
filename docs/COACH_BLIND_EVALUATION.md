# Coach 优先级盲评与模型增益协议 v1

本实验比较生产 Coach 的规则选择与 `qwen3.8-flash` 白名单工具选择。双方读取同一份冻结指标，并使用同一个确定性报告模板；模型只能选择 / 排序四个允许的训练优先级，不能自由编写事实或报告。这是优先级选择实验，不是检索消融，也不是第七项确定性画像总结的模型化。

## 冻结与范围

- 在模型调用前冻结 `coach_blind_v1/inputs.json`、`manifest.json` 和实现哈希。
- 固定选择历史图谱中 ID 升序前四场比赛，各取地图名排序第一张；再加入此前独立比赛试跑的 2396950 两图。共 6 图、5 个比赛组。
- 这些比赛都已用于开发或工程验收，不称为新盲测 / OOD。既有第 3、4 项相关性与泛化评测缺口保持原状。
- 历史样本从图谱的原始事件重建指标；两张试跑地图复用既有解析报告。评审包给出双方相同的指标和 `[C#]` 当前回合事实。
- 原图谱只读，不写入知识库；评审身份、评分、方法映射与运行目录默认保留在本地 `data/evaluation/`。

## 调用边界

`prepare` 和 `score` 离线运行。只有显式 `run` 调用现有模型客户端，要求配置模型与固定模型一致；不打印密钥，不切换模型。

首轮最多 6 次调用，每次最多输出 512 token、超时 45 秒，沿用客户端零重试。按提示 UTF-8 字节、工具 schema 字节和额外余量预留，整批预留上限 30,000 token。这是保守的本地调用估算，不是提供商计费或账户免费额度余额。报告分别记录预留量与提供商实际 usage；没有账户总额度账本，不将本轮用量伪称为账户剩余额度。

每次网络调用前写 attempt 文件。请求失败、限额拒绝、非法工具输出或 usage 缺失时停止，不把规则降级伪装成模型答案。运行目录不得覆盖；中断后的不确定请求不得自动重试。原始结果保存本地，阶段汇总进入 Git。

## 盲评方法

- 每个案例分别随机安排 A / B，方法映射在 review 目录外。只把 review 目录交给评审者，不能附方法映射、原始结果或调用日志。
- 相同内容也保留，不因两种选择相同而删掉案例。相同内容应给相同评分。
- 至少两位独立评审者，分别填写 reviewer 文件，确认未看方法映射、未共同商议分数，提供日期、每个案例的分数、偏好和理由。
- 1–5 分评估证据一致性、优先级适切性、可执行性：1 明显不合适；3 部分有用但需修改；5 证据充分且明确有用。主要指标是优先级适切性。
- 模型分减规则分，先在每场比赛内对地图和评审者取均值，再对比赛取均值。偏好票数另报，不代替主要指标。不因一个系列赛有更多地图而增加其主要指标权重。
- 评分绑定 packet 和方法映射文件哈希。空白或未完整确认的评分只输出 pending 和 null；错包、重复评审、重复 / 缺失案例、越界分数会拒绝。
- 独立性和盲法依赖真实人员声明，机器不能证明。首轮样本小，只作描述性结果，不输出显著性、因果或泛化结论。

## 运行方式

在仓库根目录执行；已有目录和产物不得覆盖，应选择新的版本名。

```bash
.venv/bin/python -m pytest -q
.venv/bin/python scripts/evaluate_coach_blind.py prepare \
  --output datasets/evaluation/coach_blind_v1
.venv/bin/python scripts/evaluate_coach_blind.py run \
  --frozen datasets/evaluation/coach_blind_v1 \
  --output data/evaluation/coach_blind_v1_run
.venv/bin/python scripts/evaluate_coach_blind.py score \
  --packet data/evaluation/coach_blind_v1_run/review/packet.json \
  --key data/evaluation/coach_blind_v1_run/method_key.json \
  --reviews data/evaluation/coach_blind_v1_run/review/reviewer_1.json \
            data/evaluation/coach_blind_v1_run/review/reviewer_2.json \
  --output data/evaluation/coach_blind_v1_run/score_pending.json
```

## 当前验收

125 项离线测试通过，包含调用前预算限制、失败立即停止、输入变更拒绝、匿名包与身份映射分离、空白评分拒绝出分，以及按比赛而非按地图加权的手算用例。模型运行结果和真实人工评分在执行后分别记录；冻结工具通过不等于模型有增益。
