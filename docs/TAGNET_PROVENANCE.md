# TAGNet-CS2 实验来源与分发范围

本项目的 CT 实验参考并在本地导入 [weyoung-open-lab/TAGNet-CS2](https://github.com/weyoung-open-lab/TAGNet-CS2)，固定上游 commit 为 `1a7ac7cf817ba5ba476e94b3bee36046f4fef56c`。模型结构、原版数值复现与训练控制均在报告中区分；本项目新增的共同特征、线性控制和检索诊断不代表上游发布结论。

保留上游 [MIT 版权及许可文本](licenses/TAGNet-CS2-LICENSE.txt)。原始上游 checkout、发布权重、运行环境、完整特征导出及本地赛事 Demo 位于忽略目录，不随本次提交分发。赛事录像和地图资产的权利不由软件许可自动授予。

仓库新增的 `datasets/models/ct_linear_v1.json` 是使用源域共同观测重新拟合的 88 系数线性控制，不是上游神经网络权重。其来源文件哈希、特征版本、训练/验证规模及选择方法保存在模型文件和模型卡中。

`datasets/evaluation/ct_structural_review_v3.json` 保存真实观测的结构摘要和待审核候选，所有相关性判断为空，不能作为人工标注、战术金标或已通过的检索质量证据。模拟测试数据只用于代码契约检查，并在测试文件中标注。

最新实验及限制见 [CT 扩展实验 v3](CT_EXPANSION_V3.md)。
