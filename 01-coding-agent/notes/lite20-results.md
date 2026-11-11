# lite20 结果（2026-11-11）

- 配置卡：`configs/lite20-nonnative.yaml`
- 模型：Qwen3.8-27B-Q4_K_M，llama-server 16K / parallel=1 / q8 KV
- agent：OpenHands 1.16，**非原生工具调用**（prompt-mocked）
- 数据集：SWE-bench Lite，revision `b0dde109…`

## 进度：10 / 20

后 10 个新实例的官方镜像拉取被网络卡死（sphinx 的大层在 1panel/1ms 两个源
30+ 分钟无进展），因此当前只有前 10 个（pilot 那批重跑）完成。

| 实例 | 结果 | 分类 |
|---|---|---|
| astropy__astropy-12907 | resolved | RESOLVED |
| django__django-10914 | resolved | RESOLVED |
| matplotlib__matplotlib-18869 | resolved | RESOLVED |
| pylint-dev__pylint-5859 | resolved | RESOLVED |
| pytest-dev__pytest-11143 | resolved | RESOLVED |
| scikit-learn__scikit-learn-10297 | resolved | RESOLVED |
| mwaskom__seaborn-2848 | unresolved | PATCH_ERROR 5d |
| pallets__flask-4045 | unresolved | PATCH_ERROR 5d |
| psf__requests-1963 | unresolved | PATCH_ERROR 5e |
| pydata__xarray-3364 | unresolved | PATCH_ERROR 5e |

**解决率：6/10 = 60%**（与非原生模式前的 pilot 相同；空补丁已清零）

## 本轮发现并修复的两个工程问题

1. **补丁提取漏掉 agent 的提交**：OpenHands 会自己 `git commit`，旧逻辑对当前 HEAD
   取 diff → 空补丁（scikit-learn 两次 0B）。修复：统一对运行前的 `base_ref`
   取 `git diff --cached <base_ref>`，sklearn 补丁恢复（977B）并 resolved。
2. **启动时拉取 GitHub 扩展**：`load_public_skills=True` 在断网时 fetch 失败 4 次后
   直接结束，产出空补丁。已在本地关闭并写入排查文档。

## 失败分析

- 5d（seaborn/flask）：补丁只修复部分 F2P，说明模型对问题范围理解不足
- 5e（requests/xarray）：引入了 P2P 回归，说明缺少"改动后全量回归"的验证习惯
- 下一步：提示词强化"提交前跑相关测试 + 检查相邻模块"，或加一步自动回归检查
