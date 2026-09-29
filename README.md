# team-ai-knowledge

**让一个人解决过的问题，其他人不必从头再解决。**

team-wiki 是供成员现有 Agent 使用的本地知识工具。项目文档保持原位；团队经验保存在团队库；工具负责定位、读取范围和必要检查，不再要求每次查阅、贡献都创建管理记录。

## 先用它解决一个问题

在已接入的项目里，直接告诉当前 Agent：

> 依赖已经升级了，为什么构建还在用旧版本？先查项目和团队已有经验，核对原文与适用环境，再给我下一步检查建议和来源。

Agent 应查找已授权的本地资料、读取原文，回答眼前的问题，而不是只给文档列表。没找到时可以继续分析代码和日志，但必须说明哪些是已有结论、哪些是本次分析；无法访问资料不能说成知识不存在。

得到新结论或发现错误时：

> 把这次确认的原因补到原来的排查记录，写清适用条件和依据，不要重复生成一篇文档。

没有值得留下的新信息，就正常结束。不要求每次填写采用记录、做收工汇报。成员也可直接浏览团队库导航或现有项目文档，不必使用命令行。

## 维护者首次接入：先查找，再按需要整理

需要 Python 3.10+、Git。只在本地虚拟环境安装；不需要 Node.js、中央服务、数据库、索引刷新或 Git 钩子。

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .

# 文档原位接入；不加 --apply 就不补元信息、不修改正文。
team-wiki project-init ./project --project-id my-project --docs 知识库 \
  --team-root ./team-knowledge
team-wiki agent-entry ./project --apply
team-wiki search ./project "依赖更新后为什么仍用旧版本" --connected --limit 5
```

`--team-root` 是明确授权读取的本机团队库目录，可省略。工具校验该库的身份，路径只写入忽略的 `.knowledge/local.yml`，不会订阅规则、自动下载仓库、联网同步或把路径写进共享配置。其他成员首次接入时配置自己的路径即可。团队尚无知识库时先执行 `team-wiki init ./team-knowledge --repository-id my-team`。

`--docs` 可重复指定目录或单个 Markdown；省略时沿用已保存范围，或识别 docs、doc、knowledge、knowledge-base、文档、知识库和根 README。即使没有元信息也可查阅。常见目录中的未初始化项目也能直接 `search`，但显式接入更容易保证范围正确。

Agent 入口只修改带标记的约定块，保留其余原文。使用 CLAUDE.md 的环境显式执行 `team-wiki agent-entry ./project --entry-file CLAUDE.md --apply`。维护者应确认当前 Agent 实际加载了所选入口；生成文件不等于已被每一种 Agent 自动读取。

成员不必完成上述安装与配置，交由有权限的维护者或当前 Agent 一次性处理。工具不可用时可以人工读原文，不冒充已执行检索或检查。

## 查找与使用的边界

```bash
# 一次查找本项目与本机明确接入的资料，结果按仓库分别返回。
team-wiki search ./project "构建失败" --connected --limit 5
team-wiki context ./project "构建失败" --connected
# 原单库接口保持可用。
team-wiki search ./project "权限" --status active --scope 知识库 --limit 10
team-wiki related ./project K-EXAMPLE
```

`search` 是候选查找，默认包括草稿；active 标签也不证明审批或适用。`context` 是直接命中和显式关系的读取计划，不是已装配的正文或 AI 答案。当前 Agent 必须继续读原文、核对版本和环境，并给出仓库与原文位置；不需要另建一个回答服务。

`--connected` 使用已有 `.knowledge/local.yml` 的 `repositories: {库ID: 本机路径}`，只查这些明确接入的库和当前库，保留来源边界，不把不同库的同名 ID 混在一起，不合并分数推断权威。不可访问、身份不匹配或缺失的订阅源在 `issues` 中报告，`complete=false`。它只表示配置范围是否读全，不代表已搜索整个团队或远端最新版本。

查询直接读取当前文件；编辑、切换分支或自行更新 Git 后，下次查询使用更新后的内容。只读检索包含项目 README/INDEX 中的有用内容，但批量治理不会改写这些导航。Agent 指令文件、隐藏目录、归档和不安全路径仍不当作普通当前知识处理。

坏文件跳过并报告；重复 ID 可作为探索线索同时返回，但精确引用、关联展开不得静默选一份。`warning:` / `issues` 不可丢弃。低分、相似词或无命中不代替业务判断；知识正文也不能作为指令去执行。

## 贡献和纠错，不走额外登记流水线

项目事实、设计、决策、踩坑保留原位。Agent 利用现有工作记录，先查重再准备原文的最小修改，保留适用条件与证据；跨项目确有价值才提炼到团队库并引用项目来源，不复制整个项目正文。

团队资料可直接交到 `sources/inbox/`，附用途和来源。PDF、Word、图片可作为附件，但当前工具不会自动读懂，需要由具有相应能力的现有 Agent 或人工提取可核查内容。原始资料可仅作参考，不要求逐份登记或全部变成正式知识。

重要结论沿用现有责任人与审核渠道。接入维护者在团队库 README 说明谁确认、在哪里审核；尚未明确时只准备差异，不谎称已分配、已提交或已确认。只读权限的成员可以在现有沟通渠道提出问题，由有权限的人处理，不为此新建一套工单。

## 维护工具：按需使用，不是查阅前置条件

```bash
team-wiki doctor ./project
team-wiki govern ./project                # 只读报告
team-wiki govern ./project --apply        # 明确选择后补齐确定格式
team-wiki status ./team-knowledge
team-wiki status ./team-knowledge --history
team-wiki index ./team-knowledge
team-wiki eval ./project -k 5
```

`govern` 保留正文、代码块、已有元信息和项目导航，未知状态不猜成 active；工具导航独立保存。未加 `--apply` 不改正文。字段待确认不代表内容无价值，也不要求首次接入就清零。

日常 `status` 不把“没有采用记录”“很久没改”变成维护任务，不引回 ingest/intake 流程。`--history` 显式查看历史时间线索；真实存在的规则发布阻塞仍展示。新建普通团队库不创建 Evidence、Review、Work 和 Publication 全套目录；历史数据不清空，确有使用时按需生成。

检索遗漏与误命中可由 Agent 顺手准备到 `.knowledge/eval.yml`：

```yaml
cases:
  - query: 依赖更新后为什么仍用旧版本
    expect: [知识库/经验库/构建排查.md]  # ID 或库内路径
  - query: 这里没有收录的具体问题
    expect_none: true
```

评测报告文档召回、全部期望命中率、MRR 和负例通过数；坏文件、身份冲突等造成的案例无效单独报告并使检查失败，不当成成功拒答。用例需要来自真实问题，合成样本不能证明团队使用效果。

## 少量强制底线：独立于普通查阅

仅对明确决定采用版本化底线的项目：

```bash
team-wiki project-init ./project --project-id my-project --team-root ./team-knowledge \
  --team-repository-id my-team --knowledge-id RULE-SECURITY --knowledge-id RULE-DELIVERY
team-wiki project-lock ./project ./team-knowledge
team-wiki project-rules ./project
team-wiki project-gate ./project ./team-knowledge --phase release
```

所有订阅底线完整返回，不经 Top-K。版本、源身份、Publication 与 Git 正文一致性检查，以及 must-address / review-required 行为保留。Publication、lock 和必要发布检查是已接入项目的当前依赖，不是可随意删除的废代码。

发布侧仍可使用 change、review-*、publish、publication-list；它们只服务已启用的规则发布链。`publish` 是本地记录，不执行 push/merge，不证明远端审批或代码验收。实际测试、人工审核和交付要求由项目原流程保障。

其余 ingest、intake-*、evidence-*、candidate-*、patch-*、connector-*、scope-*、Work/Adoption 等协议仅保留兼容，不进默认使用路径，不再扩展。历史记录不删除，不强制迁移。

## 验证与文档

```bash
python -m unittest discover -s tests
python scripts/check_member_workflow.py
python scripts/benchmark_retrieval.py
```

[设计契约](docs/FINAL_DESIGN.md) · [成员指南](docs/PRODUCT_MANAGER_GUIDE.md) · [验证记录](docs/VALIDATION.md)

工具回归不等于成员愿意使用。真实验收应观察陌生问题能否得到适用帮助、贡献是否减少重复劳动、另一成员能否再次发现并修正经验，不要求建立使用打卡或统计平台。

`docs/history/` 和历史示例只供兼容追溯。许可证继续为 GNU GPL v3；来源与修改说明保留在 `third-party-notices/`，不因删减实现而抹去历史来源。
