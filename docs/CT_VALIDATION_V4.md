# CT 实验继续阶段：全量离线回归通过

日期：2026-10-23。CT 实验代码、报告、模型、上游许可已推送到仓库；后续处理了此前阻塞全量测试的环境及跨系统问题。

后续新增输入清单/队伍别名检查后，[最新实验](CT_EVENT_AND_RETRIEVAL_V6.md) 的全量回归为 412 项通过。本文保留首次全部通过时的 406 项记录。

## 结果

在本机隔离的补充依赖环境运行全部测试，**406 通过、0 失败、0 收集错误**，保留 3 项第三方弃用警告。该结果取代“当前仍被依赖阻塞”的描述；[v3 回归记录](../datasets/evaluation/ct_regression_v3_report.json) 继续保留历史失败，不改写旧记录。

完整运行证据、版本及源码哈希见 [v4 验证报告](../datasets/evaluation/ct_validation_v4_report.json)。运行的是离线测试，不证明真实 Milvus 服务、外部嵌入模型或付费 LLM 调用已验收。

## 修复

1. **Milvus 导入**：使用项目已声明的 `langchain-milvus` 集成，替换已安装新版 `langchain-community` 不再提供的旧导入。构造参数和上层调用保持现有契约；相关 API、任务、检索与跟进测试均实际运行。[官方集成文档](https://reference.langchain.com/python/langchain-milvus/vectorstores/milvus/Milvus)。
2. **补充依赖**：在忽略目录创建继承基础环境的隔离虚拟环境，补齐 `fastembed==0.8.0`、`tokenizers==0.23.2`，保留 NumPy 2.3.5。没有安装或下载嵌入模型权重，没有修改 GPU 环境或系统级依赖。
3. **旧冻结表达式文件**：工作目录的 CRLF 与已记录的 LF 校验不一致。恢复仓库已有的原始 LF 字节，并用 Git 属性固定该文件的换行方式；原案例内容、清单哈希和测试要求不变。
4. **Windows 密钥保护**：原 POSIX `0600` 检查不能验证 Windows 的真实访问控制。现在对新建的空临时文件先移除继承权限、只给当前用户 SID 授权，再写入密钥并原子替换；POSIX 分支继续使用 `0600`。[Python 权限说明](https://docs.python.org/3/library/os.html#os.chmod)、[Windows icacls 文档](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/icacls)。

Windows 测试读取实际落盘的 DACL，确认禁止继承且只有当前用户的一条允许规则；另测身份解析失败、超时、权限设置失败及旧密钥保留。所有测试只使用示例密钥。权限设置失败时，在写入密钥之前退出并清理临时文件。

为避免 Git 在跨系统检出时改变旧实验所校验的原始字节，对冻结 CT 输入逐一指定保留策略。旧报告和权重哈希仍一致。首次属性配置曾波及三个旧脚本，后续修复提交已将它们恢复为实验前的相同内容，并将策略收窄为实际实验文件。

## 运行与边界

```powershell
# 在已有项目开发依赖的基础解释器上补齐本机缺失项。
uv venv --system-site-packages --python python output/tagnet/.venv-regression
uv pip install --python output/tagnet/.venv-regression/Scripts/python.exe fastembed==0.8.0 tokenizers==0.23.2 numpy==2.3.5
$env:PYTHONUTF8='1'
output/tagnet/.venv-regression/Scripts/python.exe -m pytest -q
```

这里是继承基础环境的补充依赖验证，不是全新环境的完整锁文件复现。Windows 的 ACL 路径实际执行；本轮没有在 Linux/macOS 上运行 POSIX 分支。真实后端连通性、独立战术相关性和教练质量仍需分别验收。

CT 模型及预测结果没有因这些修复而调整。现阶段继续以 [扩展实验 v3](CT_EXPANSION_V3.md) 的线性预测和共同状态检索作为控制，T 方训练和生产 Coach 接入尚未启动。
