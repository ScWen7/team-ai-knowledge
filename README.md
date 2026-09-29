# team-ai-knowledge

team-wiki 是面向团队知识库和项目知识库的本地工具。当前版本 V0.9：项目存量文档治理、直接读取文件的中文检索，以及显式团队底线的版本读取和检查。

同时服务四个目标：AI 开发标准化；事实经验持久沉淀；非技术成员低成本维护；内容增长后的准确性与性能。设计契约见 [现行设计](docs/FINAL_DESIGN.md)，验证记录见 [VALIDATION](docs/VALIDATION.md)。

## 知识放在哪里

- 团队库：团队业务认知、共同规范、共享经验、协作流程和项目入口。
- 项目库：项目设计、决策、实现约束、踩坑和迭代证据，沿用原目录。
- 工具仓库：本仓库，只维护工具、设计、示例与测试。

项目经验经提炼和审核后进入团队域，保留项目来源引用。无需复制项目正文或统一项目目录。

## 成员入口

不安装工具的成员可用已有 Git Web 浏览文档、提交资料、提出文档修改，或直接让当前 Agent 协助。负责人沿用现有审核渠道；不会自动分配负责人、创建 CHG 或发布知识。具体动作见 [成员指南](docs/PRODUCT_MANAGER_GUIDE.md)。

普通查阅无需创建 Work，也无需填采用记录。`search` 是探索检索，结果包含草稿等状态；确认结论前需核对正文、来源和适用范围。只想看 active 条目时显式加 `--status active`；active 元信息本身不证明审批完成。

## 安装

需要 Python 3.10+ 与 Git，无需 Node.js 或中央服务。

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
team-wiki --help
```

只在本地虚拟环境安装。部署或启用远端工作流属于独立操作。

## 接入已有项目文档

先只读查看治理差异，再应用可确定的格式补全：

```bash
team-wiki govern ./project --docs 知识库
team-wiki project-init ./project --project-id my-project --docs 知识库 --apply
team-wiki doctor ./project
```

`--docs` 可以重复指定目录或单个 Markdown；不提供时优先使用已保存范围，再识别常见文档目录。`govern` 默认完全只读。`project-init` 写入工具配置和忽略项，未加 `--apply` 时只预览正文治理。

治理保留现有元信息、正文、代码块和项目导航，仅补齐确定的身份/标题和待确认标记。未知类型、有效性、责任或来源列入报告，不自动确认。重复执行不生成新 ID 或无意义差异。

工具导航位于 `.knowledge/documents.md`，原有 INDEX 不被覆盖。归档、指令入口、隐藏目录和越界链接不纳入批量正文修改。报告中的语义问题需要负责人判断，格式通过不等于知识正确。

## 查找知识

```bash
team-wiki search ./project "依赖更新后为什么仍用旧版本"
team-wiki search ./project "权限" --status active --scope 知识库 --limit 10
team-wiki context ./project "构建失败"
team-wiki related ./project K-EXAMPLE
```

查询直接读取已配置范围内的当前 Markdown 和 frontmatter。成员 `git pull`、切换版本或直接编辑后，下一次查询就使用更新后的文件，无需执行 SQL、刷新索引或安装 Git 钩子。检索不创建数据库、不维护跨查询缓存；旧检索数据库即使存在也不会被读取、改写或删除。

`--scope` 精确匹配显式 scope、库 ID 或仓库相对目录范围，不推断业务适用性。`index` 在团队库生成 Markdown 导航；在项目库只检查文档，项目导航通过 `govern` 维护。

`related` 仅返回当前文件中的显式引用及反向引用。一次 `context` 调用内部复用刚读取的文档，调用结束即释放。`context` 返回检索计划，尚未装配或裁切正文；`budget` 兼容入口仅给字符预算建议，结果标明 `applied=false`。这些入口不替代共同底线读取。

单个文件损坏（YAML 错误、读取期间被改写）时，`search` 跳过该文件并在 stderr 输出 `warning:`；重复 ID 的文档仍可检索但会被报告。这些提示表示知识库有问题需要负责人处理，不表示查询失败。

## Agent 入口与检索评测

```bash
team-wiki agent-entry ./project           # 预览
team-wiki agent-entry ./project --apply   # 写入 AGENTS.md 中带标记的约定块，其余内容不动
team-wiki eval ./project -k 5             # 读取 .knowledge/eval.yml，输出 recall@k、MRR、负例通过数
```

约定块要求 Agent 开工前读取底线并先搜索、收工时判断是否沉淀、检索遗漏时追加评测用例。评测用例格式：

```yaml
cases:
  - query: 依赖更新后为什么仍用旧版本
    expect: [知识库/经验库/踩坑记录/base-SNAPSHOT不刷新.md]   # ID 或仓库相对路径
  - query: 区块链共识算法
    expect_none: true
```

## 接入团队共同底线

团队底线由项目明确订阅，完整读取，不经 Top-K。以下命令仅用于已决定接入版本化底线的项目：

```bash
team-wiki project-init ./project --project-id my-project \
  --team-repository-id my-team --knowledge-id RULE-SECURITY --knowledge-id RULE-DELIVERY
team-wiki project-lock ./project ./team-knowledge
team-wiki project-rules ./project ./team-knowledge
team-wiki project-gate ./project ./team-knowledge --phase release
```

`project-rules` 无需 Work，返回所有订阅底线的锁定正文并检查源身份、Publication 与 Git 内容一致性。`must-address` 和 `review-required` 的已有 start/release 行为保留。实际测试、人工审核、交付证据仍按项目规则执行。

如明确需要工作快照与采用追溯，可继续使用 `project-work` 或分步命令。它们不是普通知识查阅的前置条件，也不会代替项目设计和踩坑文档。

## 创建团队库与贡献

```bash
team-wiki init ./team-knowledge --repository-id my-team
team-wiki doctor ./team-knowledge
```

成员提交资料或指出问题后，Agent/维护者定位已有知识，准备带原因、来源和影响的 Markdown 差异，由负责人按既有 Git 审核流程确认。

## 命令分层

`team-wiki --help` 只列出日常与规则发布链命令：

- **日常**：`search`、`related`、`context`、`govern`、`project-init`、`agent-entry`、`eval`、`doctor`、`status`、`index`、`init`。
- **团队底线**：`project-rules`、`project-lock`、`project-status`、`project-update`、`project-gate`；团队库发布侧使用 `change`、`publish`、`publication-list`、`review-*`。
- **已冻结的旧协议**：`ingest`、`intake-*`、`evidence-*`、`candidate-*`、`patch-*`、`connector-*`、`scope-*`、`dependency-impact`、`adoption-status`、`prepare`/`adopt`/`observe`/`finalize`、`project-prepare`/`project-context`/`project-adopt`/`project-observe`/`project-finalize`/`project-work`、`budget`。不出现在帮助中，调用时输出 `notice:`，行为保持兼容，不再新增功能。试点后按实际使用决定删除；历史记录不清空、不强制迁移。

`publish` 生成本地 Publication 记录并校验提交内容和未决 Review，不执行 push/merge，不证明远端审批。原始资料自动解析限 UTF-8 文本和 Markdown，PDF/Word 需先转换并保留原始来源。`status` 的无采用记录和久未更新仅为可观测线索，不判定知识无人使用或失效。

## 验证与当前边界

```bash
python -m unittest discover -s tests
python scripts/benchmark_retrieval.py
```

工程验证与规模结果记在 [验证记录](docs/VALIDATION.md)。合成语料不代表真实团队语义命中率；多人、非技术成员贡献和跨项目复用仍需真实试点验证。不存在“中文检索 100%”的通用承诺。

## 历史与许可证

`docs/history/` 保存 V0.1—V0.9 范围文档与上游复用评估，仅供追溯；现行行为以本 README 和 `FINAL_DESIGN.md` 为准。

仓库继续使用 GNU GPL v3。移除 Node.js 执行层不会抹去历史代码来源，第三方来源与修改说明保留在 `third-party-notices/`，评估基线保留在 `upstream.lock.yml`。
