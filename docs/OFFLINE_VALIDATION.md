# 离线测试与环境复现

## 本地复现

参考环境：Python 3.11.15、Node 22.23.0。先安装依赖，测试执行阶段不需要模型、Redis、Milvus或下载 embedding。

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt -c requirements-lock.txt
.venv/bin/python -m pip check
make test
npm --prefix frontend ci
make frontend-build
```

`requirements-lock.txt` 约束本次验证的直接与传递依赖，包括 FastEmbed 0.8.0；因此 pooling 行为不会因该依赖无意升级而改变。它不是带制品哈希的供应链锁。后续研究评测还需记录实际 ONNX/embedding 文件哈希。

前端保留原有 package-lock.json，`npm ci` 使用锁定依赖，不重写用户的 lockfile。

## 测试边界

`conftest.py` 禁用 `.env` 加载并清空测试密钥，关闭辅助模型调用与自动入库。自动测试拦截 Python socket 连接，意外联网会失败；测试使用临时 SQLite 和明确的检索/模型 fixture。

根目录测试覆盖接口调度、完整 `AnalysisPipeline` 至 Verifier、解析器和画像逻辑。`scripts/test_webhook.py` 是会提交真实任务的手动探测脚本，已从 pytest 自动发现范围排除；它不能作为无成本单元测试运行。

`make eval-rag`、`make eval-v1` 等真实数据评测仍需要本地 Milvus/图谱；它们独立于离线 CI，不应在缺少语料或服务时伪装成成功。

## CI

`.github/workflows/ci.yml` 已启用，配置 Ubuntu 24.04、Python 3.11.15、Node 22.23.0，执行受约束安装、依赖检查、离线测试、npm ci 和前端构建。

2026-09-06 首次远端运行通过：96 项测试通过、1 条上游弃用警告（3.16 秒），pip check 无冲突，前端生产构建成功。[GitHub Actions 运行记录](https://github.com/Zzz0zzZ0/CS2-coach-agent/actions/runs/34031162026)；验证提交为 `1f7c77ca6d5fe5a11d24906c81918ee2545277fb`。

此前 OAuth 凭据缺少 workflow scope，配置曾以示例文件保存；补充授权后已迁入正式工作流路径并成功执行。后续 push、pull request 和手动触发都会执行同一套离线验收。
