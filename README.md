# team-ai-knowledge

团队级 AI 知识库的设计与 V0.1 试验实现。

## 三种角色，三条路径

| 角色 | 你要做什么 | 入口 |
|---|---|---|
| **产品经理 / 知识读者** | 看知识、交资料、提建议 | 浏览器打开仓库 → [`docs/PRODUCT_MANAGER_GUIDE.md`](docs/PRODUCT_MANAGER_GUIDE.md) |
| **工程师 / 知识使用者** | 在项目里消费团队知识 | 下方"工程师高频 2 命令" |
| **知识管理员 / 工具维护者** | 登记资料、审 CHG、发布、治理 | [`docs/FINAL_DESIGN.md`](docs/FINAL_DESIGN.md) |

## 工程师高频 2 命令（V0.8 起）

在一个**已接入团队知识库的项目**里，一次任务只需要这 2 条命令：

```bash
# 1. 开始：start 门禁 → 固定知识版本快照 → 直接返回锁定正文
team-wiki project-work . <team-root> --phase start \
  --goal "实现订单导入" --read K-A
# → 返回 work_id 和 K-A 的锁定正文（从 Git 历史精确读取，不读当前工作树）

# 2. 收尾：记录采用与结果 → release 门禁 → 回报团队知识库
team-wiki project-work . <team-root> --phase finish \
  --work-id <work-id> \
  --adopt K-A --used-for "实现导入校验" \
  --observe "K-A:supported-in-scope:批量场景验证通过"
```

> 门禁没有因此放松：`must-address` 仍在开始时阻断，`review-required` 仍在交付前阻断，
> 任务中途 lock 变化仍会拒绝收尾。需要分步执行时用原来的 5 条命令：
> `project-prepare / project-context / project-adopt / project-observe / project-finalize`。

其他命令（`init / ingest / publish / doctor / connector / review / batch / patch-*` 等）属于**知识管理员路径**，普通工程师不需要掌握。

## 知识管理员常用路径

修改一条知识的最短路径（V0.8 起）：

```bash
# 1. 资料登记 + 切分成可引用的证据片段
team-wiki ingest . ./notes.md --title "示例资料"
team-wiki intake-source . <source-id>

# 2. 一次调用决定保留哪些片段（不必逐块声明）
team-wiki intake-decide . <intake-id> --keep-evidence <evidence-id>

# 3. 直接规划知识修改（无需先理解 Candidate）
team-wiki patch-plan-direct . \
  --knowledge <knowledge-id> \
  --comparison narrows \
  --statement "修改后的结论" \
  --evidence <evidence-id> \
  --summary "变更摘要"

# 4. 读取上下文 → 写完整 Markdown → 安全应用
team-wiki patch-context . <plan-id>
team-wiki patch-apply . <plan-id> ./revision.md

# 5. 人工审核 → 提交 → 正式发布
git commit -am "..."
team-wiki publish . <change-id> <knowledge-id> --requirement review-required
```

需要逐块精细控制时仍可用 `intake-apply`；需要显式审阅 Candidate 时仍可用 `candidate-create` / `patch-plan`。

## 内容

- `docs/FINAL_DESIGN.md`：最终统一设计与建设指引
- `docs/PRODUCT_MANAGER_GUIDE.md`：产品经理 Web-only 使用指南
- `docs/V0.8_SCOPE.md`：使用减负落地范围（当前版本）
- `src/team_wiki/`：knowledge-kit V0.1 的确定性实现
- `examples/team-knowledge/`：可运行示例
- `tests/`：首版行为测试
- `upstream.lock.yml`：project-wiki / llm_wiki 评估基线

## V0.1 能力

- 初始化 team-knowledge 工作区；
- 将资料登记为稳定 source package；
- 生成 `sources/wiki/changes` 索引；
- 校验知识 ID、基础目录和来源资料包；
- 检查目录增长与 inbox 积压；
- 简单关键词搜索；
- 创建知识变更记录；
- 记录一次工作快照。

## 快速开始（知识管理员）

> 工程师日常使用请直接看上方"高频 2 命令"；本节仅面向第一次搭建知识库或做知识治理的管理员。

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .

team-wiki init ./demo --repository-id demo-team
team-wiki doctor ./demo
team-wiki ingest ./demo ./notes.md --title "示例资料"
team-wiki index ./demo
team-wiki search ./demo "订单 导入"
team-wiki prepare ./demo --goal "验证一项知识工作"
```

> V0.2 已增加 project-wiki source-scope 适配、llm_wiki 关系/字符预算适配，以及 Work → Evidence → Observation → Change 最小闭环。完整自动编译、Review 重开、LanceDB、MCP 与 CI 门禁仍未实现。


## V0.2 分支

当前实现位于 `feature/v0.2-knowledge-loop`，详见 `docs/V0.2_SCOPE.md`。合并前需确认 GPLv3 适配代码的整体分发许可证策略。


## License

从 V0.2 起，本仓库以 GNU GPL v3 发布。原因是 V0.2 开始包含基于 `nashsu/llm_wiki` GPLv3 源码适配的模块。

- project-wiki 来源部分继续保留其 MIT 声明；
- llm_wiki 适配模块保留 GPLv3 来源和修改说明；
- 详细第三方声明见 `third-party-notices/`。

这是一项工程分发策略，不替代组织自身的法律审查。


## V0.3

当前 V0.3 分支继续补齐知识闭环：

- Review 稳定身份与新证据重开；
- 来源修订影响追踪；
- Text/Markdown intake 分块与 review-progress；
- 确定性 GitHub Actions 回归。

详见 `docs/V0.3_SCOPE.md`。


## V0.4

V0.4 引入 Evidence Layer：

- 稳定 source identity 与 source revision 分离；
- 来源逻辑路径与本地资料包路径分离；
- processing.yml 记录 parser / version / effective config；
- Evidence Chunk 保存 source revision、heading path、字符定位和 index state；
- 人工纠正不覆盖 parser output；
- Evidence 可以绑定 candidate / knowledge / change / review；
- 来源更新影响分析同时使用 frontmatter source 引用和 evidence binding；
- source-status 区分 acquisition / processing / evidence / indexing / knowledge-change。

WeKnora 作为来源/证据处理的设计参考，不作为第三个必须运行的平台。详见 `docs/V0.4_SCOPE.md`。


## V0.5

V0.5 打通两条链路：

- **Evidence → Candidate → Knowledge Patch Plan → stale-safe apply**；
- **Local Git Connector → checkpoint → incremental add/modify/rename/delete**。

关键边界：

- Candidate/Comparison 由当前 Agent 或领域责任人明确，不由确定性脚本猜业务语义；
- Patch Plan 同时锁定目标 Knowledge base hash 和 Evidence current hash；
- `patch-apply` 只修改贡献工作区并把 CHG 推进到 proposed，不等于发布；
- Git Connector 只在整批事件成功后推进 checkpoint；
- rename 保持 source_id；
- rename 移出 scope 与真正 delete 分开处理；
- 没有知识依赖的来源更新不自动制造 CHG/Review。

详见 `docs/V0.5_SCOPE.md`。


## V0.6

V0.6 把多来源证据、显式依赖、正式发布和后续采用串成一条完整链：

- Candidate Batch：多份来源/候选显式归并为 merged Candidate；
- dependency-impact：仅沿 depends_on 传播强影响；
- Patch Apply 自动建立 dependency Review；
- publish：要求 Review 已处理且真实 Git commit 中的正文 hash 匹配；
- prepare/adopt 自动绑定最新 Publication；
- finalize 生成共享 Adoption Record；
- adoption-status 查看最新发布版本被哪些 consumer 真正采用。

详见 `docs/V0.6_SCOPE.md`。


## V0.7

V0.7 将团队知识 Publication 正式接入业务项目消费流程：

- 项目显式声明 `knowledge_ids`；
- `.knowledge/knowledge.lock.yml` 固定精确 Publication；
- `notice / review-required / must-address` 转化为 start/release 门禁；
- review-required 支持有理由 defer；
- must-address 必须升级 lock，不能 defer；
- Work 开始固定 lock SHA 和完整快照；
- `project-context` 从 Git 历史 commit 精确读取锁定正文；
- 任务中途 lock 改变时 finalize 拒绝，避免静默混用版本；
- Project finalize 将实际 Publication adoption 回报 team-knowledge。

详见 `docs/V0.7_SCOPE.md`。


## V0.8

V0.8 不增加业务对象，只削减使用路径：

- `intake-decide`：一次调用决定整份 intake，逐块声明从 O(块数) 降到 O(1)；
- 移除恒为假的 `indexing` 状态维度（LanceDB 未实现，字段永远为 `not-indexed`）；
- `patch-plan-direct`：Candidate 降级为实现细节，内部记录与门禁完全不变；
- `project-work`：项目侧 5 步收敛为 2 步，所有门禁照常执行；
- Candidate Batch 标记为实验性，移出主推荐路径；
- 修复 macOS 临时目录下 `patch-apply` 的路径崩溃。

以 3 万字文档（7 块）修改一条知识为例，命令调用数从 17 降到 10；
项目侧一次任务从 5 条降到 2 条。全部原命令与数据格式保留。
详见 `docs/V0.8_SCOPE.md`。
