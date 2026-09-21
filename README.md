# team-ai-knowledge

团队级 AI 知识库的设计与 V0.1 试验实现。

## 内容

- `docs/FINAL_DESIGN.md`：最终统一设计与建设指引；
- `src/team_wiki/`：knowledge-kit V0.1 的确定性实现；
- `examples/team-knowledge/`：可运行示例；
- `tests/`：首版行为测试；
- `upstream.lock.yml`：project-wiki / llm_wiki 评估基线。

## V0.1 能力

- 初始化 team-knowledge 工作区；
- 将资料登记为稳定 source package；
- 生成 `sources/wiki/changes` 索引；
- 校验知识 ID、基础目录和来源资料包；
- 检查目录增长与 inbox 积压；
- 简单关键词搜索；
- 创建知识变更记录；
- 记录一次工作快照。

## 快速开始

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
