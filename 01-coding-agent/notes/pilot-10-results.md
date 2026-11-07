# pilot-10 结果（2026-11-07）

- 数据集：SWE-bench Lite，revision `b0dde1093fe4`（分层采样 10 实例）
- agent：OpenHands 1.16（本地 runtime）
- 模型：Qwen3.8-27B-Q4_K_M，llama-server，16K ctx，`parallel=1`，q8 KV
- harness：swebench 5.0.2
- **解决率：6/10 = 60%**

| 实例 | 耗时 | patch | 结果 | 分类 |
|---|---:|---:|---|---|
| astropy__astropy-12907 | 1975s | 504B | resolved | RESOLVED |
| django__django-10914 | 360s | 625B | resolved | RESOLVED |
| matplotlib__matplotlib-18869 | 992s | 1827B | resolved | RESOLVED |
| pylint-dev__pylint-5859 | 1036s | 650B | resolved | RESOLVED |
| pytest-dev__pytest-11143 | 346s | 557B | resolved | RESOLVED |
| scikit-learn__scikit-learn-10297 | 817s | 1551B | resolved | RESOLVED |
| pallets__flask-4045 | 797s | 630B | unresolved | PATCH_ERROR / 5d_partial_f2p |
| psf__requests-1963 | 1093s | 361B | unresolved | PATCH_ERROR / 5b_never_tested |
| mwaskom__seaborn-2848 | 2607s | 0B | unresolved | FORMAT_ERROR / tool_call_json |
| pydata__xarray-3364 | 691s | 0B | unresolved | FORMAT_ERROR / tool_call_json |

## 失败分析

1. **FORMAT_ERROR（2 例）**：27B 在生成 bash 工具调用时输出非法 JSON（引号未闭合），
   llama-server 的 tool parser 直接拒绝，agent 重试耗尽后空手结束。
   - 可缓解方向：服务端更宽松的 parser / 客户端在工具参数上用 JSON repair；
   - 这两个实例耗时（2607s、691s）说明重试浪费大量时间。
2. **PATCH_ERROR 5d（flask）**：补丁可应用，但只修好部分 FAIL_TO_PASS。
3. **PATCH_ERROR 5b（requests）**：整个轨迹没有可靠运行过测试就提交。
4. 上下文 16K 是硬约束：复杂实例（seaborn）更容易触发长输出/解析失败。

## 对比

| 路线 | astropy-12907 |
|---|---|
| OpenHands 框架 | resolved（1975s） |
| 自研 sweagent | LIMIT_ERROR（40 步、空补丁、5 次压缩） |

结论：在本机 27B + 16K 条件下，成熟框架的工具编排和上下文管理明显更稳。
