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

`.github/workflows/ci.yml` 配置 Ubuntu 24.04、Python 3.11.15、Node 22.23.0，执行受约束安装、依赖检查、离线测试、npm ci 和前端构建。尚未推送并触发 GitHub Actions，因此当前验证是本机全新虚拟环境和独立前端目录复现，不宣称远端 Linux 工作流已经运行。
