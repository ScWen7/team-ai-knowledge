# 团队级 AI 知识库：最终统一设计与建设指引

**状态：V2.1 设计基线 / V0.1 实施起点**

> 知识指导工作，工作产生证据，证据推动知识变化，变化经过审核进入下一次工作。

本方案基于三个来源融合而成：

1. `project-wiki`：项目知识工作流、来源处理、渐进式读取、确定性脚本和项目事实维护；
2. `llm_wiki`：Purpose、增量编译、关系检索、上下文预算、Review、缺口发现、主动补证据、生命周期处理；
3. 团队实践文章：团队知识独立 Git 仓库、项目/团队知识分域、渐进式消费、工作流服务知识沉淀。

这不是把两套系统桥接起来，而是把它们统一到同一套 **知识、证据、工作、知识变更** 契约中。

---

## 1. 建设目标

### 1.1 AI 开发标准化

让不同成员、不同 Agent 在同一项目中取得相同发布体系下的适用规则，并在交付时提供真实执行的检查、测试或人工审核证据。

### 1.2 部门知识沉淀

让团队约定、技术知识、业务知识和项目知识具有来源、范围、责任、版本和证据，不再依赖某个人、某次聊天。

### 1.3 运行约束

- 不建设中央知识服务器；
- 不要求中央向量数据库；
- 使用团队已有 Git 托管平台；
- 由成员当前使用的 Agent 执行知识读取、分析和编译；
- `knowledge-kit` 只提供确定性工具、工作流协议和 Agent 适配；
- LanceDB 仅作为后续可选的本地派生检索层。

---

## 2. 两个仓库的定义

### 2.1 team-knowledge

团队真正使用的知识仓库。

普通成员只需认识三个入口：

- `sources/`：交资料；
- `wiki/`：看正式知识；
- `changes/`：看知识修改和待确认问题。

### 2.2 knowledge-kit

工具维护者使用的源码工程，包含：

- Skill / Agent 工作流协议；
- Schema；
- 资料登记、索引、检查、迁移程序；
- 检索、关系、预算与生命周期适配模块；
- 安装、升级、doctor 和测试。

普通成员不在 `knowledge-kit` 中保存业务文档。

---

## 3. team-knowledge 的最终目录

顶层入口保持简单，内部结构允许随知识增长。

```text
team-knowledge/
├── README.md
├── sources/                         # 原始资料与允许共享的证据
│   ├── INDEX.md
│   ├── inbox/                       # 默认投递区
│   ├── YYYY/MM/SRC-xxxx-主题/       # 稳定来源资料包
│   │   ├── source.yml
│   │   ├── 原始文件
│   │   └── attachments/
│   └── evidence/                    # 可共享的持久验证证据
├── wiki/                            # 正式结构化知识
│   ├── INDEX.md
│   ├── PURPOSE.md
│   ├── OVERVIEW.md
│   ├── team-conventions/
│   ├── technical/
│   ├── business/
│   └── projects/
├── changes/                         # 知识变更与待确认问题
│   ├── INDEX.md
│   ├── views/
│   │   ├── open.md
│   │   ├── blocked.md
│   │   └── recently-published.md
│   ├── YYYY/MM/CHG-xxxx.md
│   └── reviews/YYYY/MM/REV-xxxx.md
├── .knowledge/
│   ├── config.yml
│   ├── records/
│   ├── runs/                        # 本地，不提交
│   └── cache/                       # 本地，不提交
├── .agents/skills/team-wiki/
└── AGENTS.md
```

### 3.1 sources 的扩容规则

`sources/` 按 **首次登记时间 + 稳定来源资料包** 组织，不镜像最终知识分类。

- 成员只需要把资料放进 `sources/inbox/`；
- 工具登记后生成稳定 `source_id`；
- 资料归位后尽量不再搬动；
- 一份来源可支持多条正式知识；
- 已有外部权威文档时可只保存稳定引用和必要元信息。

### 3.2 wiki 的扩容规则

正式知识按 **领域 → 主题 → 条目** 生长，例如：

```text
wiki/business/orders/import/contact-phone-rule.md
wiki/technical/backend/api-design/idempotency.md
wiki/team-conventions/engineering/interface-compatibility.md
```

知识类型通过元信息表达，不再额外建立 `rules/ guides/ analysis/` 三套平行树。

一个知识只有一个主要归属，通过稳定 ID 和关系出现在多个导航视图中。

### 3.3 changes 的扩容规则

变更和 Review 按首次创建时间固定保存：

```text
changes/YYYY/MM/CHG-xxxx.md
changes/reviews/YYYY/MM/REV-xxxx.md
```

状态不通过移动文件表达。`open.md`、`blocked.md` 等只是可重建导航视图。

### 3.4 索引原则

物理目录可以深，但读取路径必须短：

1. 根 `INDEX.md`：知识地图；
2. 领域 `INDEX.md`：子主题和条目摘要；
3. 正文：完整知识；
4. 需要核查时读取来源；
5. 机器注册表负责 `knowledge_id → path/version/scope`。

根索引不能随着规模增长退化为“全库文件清单”。

---

## 4. 四种核心记录

### 4.1 Knowledge（K）

团队当前确认或明确保留的认识：结论、条件、例外、责任、状态、证据。

### 4.2 Evidence（E）

来源、代码、测试、批准决定、实际观察及其版本。证据用于支持、限制或挑战知识。

### 4.3 Work（W）

一次实际工作的目标、工具/知识版本、真正采用的知识、结果和未决项。

### 4.4 Change（CHG）

为什么要改知识、准备改什么、依据、影响、Review、审核与采用要求。

核心关系：

```text
W 使用 K@v3
  ↓
产生 E
  ↓
CHG 比较旧知识与新证据
  ↓
发布 K@v4
  ↓
下一次 W 使用 v4 并留下新结果
```

Review、PR、日志、摄取进度都围绕这四类对象工作，不再各自形成第二套业务状态。

---

## 5. 完整知识闭环

```text
正式知识
  ↓
任务准备：固定版本、选择规则、读取参考知识
  ↓
实际使用：找到 / 读取 / 采用 / 验证分开记录
  ↓
形成观察：支持 / 边界 / 冲突 / 未知
  ↓
知识变更：比较已有知识与新证据
  ↓
必要时补证据、形成 Review
  ↓
增量修改知识、Overview、验证要求
  ↓
领域审核与正式发布
  ↓
后续工作采用新版本并继续验证
```

新资料导入、项目扫描、来源变化、主动研究都进入同一闭环。

---

## 6. project-wiki 的最终保留范围

保留并融合：

- `init / scan / update / sync / maintain` 工作语义；
- 任务前读取、任务后知识更新；
- 项目事实与业务意图分离；
- 根索引、分区索引、稳定 ID；
- 来源范围、去重、解析、分块进度；
- Schema、初始化、模板、校验和迁移；
- 结构检查后再做语义维护。

调整：

- 团队仓库不强制完整项目管理结构；
- 中文团队可使用中文模板；
- 目录模型适配 `sources/wiki/changes`；
- 项目已有知识结构优先映射，不全量搬迁。

---

## 7. llm_wiki 的最终保留范围

不能只吸收“编译”。必须保留：

- Purpose / Overview；
- 两阶段摄取和增量整合；
- 来源身份、缓存、队列、恢复；
- 关系相关性与关系扩展；
- 关键词 + 可选向量 + 图扩展；
- 上下文预算；
- 来源核查模式；
- Async Review；
- graph-insights 缺口线索；
- Purpose/Overview 驱动的补证据；
- Analysis/跨来源综合；
- 来源更新、删除、关系和索引联动；
- 多格式资料解析。

可裁剪：

- 独立聊天产品；
- 桌面窗口；
- 图谱动画；
- 媒体播放；
- 另一套回答 Agent；
- 需要常驻桌面应用的写库通道。

---

## 8. 知识结构与状态

目录负责“在哪里看”，元数据负责“是什么、适用哪里、当前状态”。

必须分开：

- `scope`：团队/项目/领域/版本/环境；
- `type`：rule / concept / decision / guide / pitfall / process / analysis；
- `status`：draft / active / superseded / deprecated；
- `confidence`：confirmed / inferred / unknown。

不使用“引用越多越可信”的自动成熟度规则。

知识身份为：

```text
repository_id + knowledge_id
```

路径、标题变化不改变知识身份。

---

## 9. 入库与预编译

资料进入后执行：

```text
来源登记与授权
  → 解析 / 去重 / 覆盖记录
  → 读取 Purpose、Overview、相关知识
  → 识别新增、补充、重复、矛盾、失效
  → 形成 CHG 和必要 Review
  → 贡献分支增量修改
  → 结构检查 + 语义审核
  → 发布
```

输出不是“一份资料一篇摘要”，而是“应该修改哪些已有知识、哪些内容不能改、哪些证据还缺”。

已审核正文是下一轮编译基础，不能每次从原料全库重生成。

---

## 10. 知识消费

### 10.1 三条读取路径

- 强制规则：完整选择，不做 Top-K；
- 参考知识：按范围和相关性读取；
- 动态事实：回到代码、发布或业务系统查询。

### 10.2 参考检索

```text
范围与版本
 → 目录 / ID / 别名 / 关键词
 → 可选向量候选
 → 关系扩展
 → 去重与预算
 → 读取正文和必要证据
 → 输出结论、引用、条件和未知项
```

关系相关性不等于可信度。共同来源、共同邻居和类型亲和只用于召回和调查。

### 10.3 上下文预算

只控制工具返回的知识内容，不假装掌握整个 Agent 会话剩余上下文。

规则不能因预算被静默丢弃。参考资料可以分步加载并明确未读部分。

---

## 11. Review 与主动补知识

Review 用于持久保存：

- contradiction；
- duplicate；
- missing-page；
- confirm；
- suggestion。

同一问题和相同证据可以去重，新证据/新版本允许重开。

主动补知识流程：

```text
Purpose / 查询失败 / Review / 关系线索
 → 明确调查问题和价值
 → 关联原 CHG
 → 内部知识、代码、测试、负责人确认
 → 必要时授权外部研究
 → 返回原 CHG
 → 发布或有依据地不修改
```

不能研究完成后留下原 Review 永远未处理。

---

## 12. 发布与生命周期

发布必须能解释：

- 正文变化；
- 证据变化；
- 依赖处理；
- 验证要求；
- 下游采用影响。

正式有效性统一依据：

```text
可信发布渠道 + 准确版本 + 有效状态 + 适用范围 + 当前证据条件
```

发布、采用、验证是三个不同完成事实。

来源更新、撤回、条目替代、删除都要影响正文、依赖、索引和 Review；删除了链接不代表剩余结论已经重新验证。

---

## 13. knowledge-kit 的接入方式

`knowledge-kit` 是版本化运行包，不是第二知识库。

工程结构：

```text
knowledge-kit/
├── SKILL.md
├── schema/
├── references/
├── assets/
├── scripts/
├── packages/knowledge-core/
├── adapters/
├── tests/
├── docs/
├── third-party-notices/
└── upstream.lock.yml
```

运行包安装到：

- `team-knowledge/.agents/skills/team-wiki/`；
- 每个接入项目的 Agent Skill 位置。

不同 Agent 只做薄适配，知识协议和实现只有一份。

工具需要提供这些确定性能力：

- `prepare`：环境、版本和工作快照；
- `search/read/related/context`：读取与上下文装配；
- `rules`：规则选择；
- `observe`：记录采用和结果；
- `change/review`：变更和未决问题；
- `index`：生成导航视图；
- `doctor`：结构、版本、积压和接入健康检查；
- `finalize`：校验收尾，不自动发布。

---

## 14. 目录增长治理是 knowledge-kit 的正式职责

工具必须负责：

- 来源登记和稳定资料包；
- 归属建议；
- 分层索引生成；
- 稳定 ID 定位；
- 超大目录/索引/积压检测；
- 安全目录迁移；
- 深层目录检索兼容。

首版维护信号：

- 根索引约 50—100 行后考虑下沉；
- 分区索引约 100—200 行后考虑拆主题/分页；
- 叶目录约 40—60 篇且出现自然子主题时考虑拆分；
- inbox / Review 积压成为明确 doctor 告警。

数量只是治理信号，不是硬限制。

状态变化不搬文件，版本变化不默认维护 `v1/v2/v3` 三棵正文树。

---

## 15. 工具版本和健康更新

必须区分：

- 工具版本；
- 知识格式版本；
- 知识内容版本。

工具升级流程：

```text
真实问题 / 上游修复
 → 可复现案例
 → 修复与回归
 → 候选版本
 → 试点知识库与项目
 → 稳定版本
 → 仓库升级变更
```

运行中的任务固定工具与知识版本，不热替换。

工具缺陷如果污染了历史知识，必须根据工具/协议版本定位可能受影响的 CHG/知识并复核，不能只升级程序。

---

## 16. LanceDB 的位置

LanceDB 只作为本地派生检索层：

- 正文仍在 Git；
- 每人本地索引；
- 向量模型需要单独配置；
- 真实中文和团队任务验证有收益后再启用；
- 索引可以重建，正式知识不能当缓存重写。

---

## 17. 建设顺序

### M0：基线与统一契约

固定两个上游提交，运行允许的测试，定义 K/E/W/CHG、路径和最小实现；至少验证一个可复用模块。

### M1：最小完整闭环

一个知识域、两次真实工作：

```text
旧知识 → 第一次采用 → 新证据 → CHG → 审核发布 → 第二次采用
```

### M2：首版团队闭环

两人、两项目、两种 Agent，加入：

- 基础关系；
- 上下文预算；
- Review；
- 主动补证据；
- 来源生命周期；
- 目录增长治理；
- 安装、doctor、升级和回退。

### M3：规模和效率

真实评测集、增量缓存、必要的向量与高级关系算法。

### M4：可选体验

只读门户、图谱 UI、多格式增强和授权外部研究；仍使用同一知识契约和发布体系。

---

## 18. V0.1 的实施目标

V0.1 不假装完整知识闭环已经完成，只落地第一条确定性纵向切片：

- 初始化团队知识目录；
- 稳定来源登记；
- 可扩展索引；
- 知识 ID 检查；
- 简单关键词检索；
- 工作快照；
- 变更记录；
- doctor 增长与结构检查。

后续 V0.2 优先接入 `project-wiki` 的范围/解析/校验能力和 `llm_wiki` 的关系/预算纯计算模块，再完成 W/E/CHG 采用—验证闭环。

---

## 19. 最终验收

首版不能只证明“生成了 Markdown”或“两个工具互相调用”。必须回答：

1. 某次工作实际采用了哪条知识、哪个版本？
2. 某份新证据支持、限制或挑战了哪些结论？
3. 某次知识修订处理了哪些依赖、Overview 和验证要求？
4. 某个 Review 为什么解决，新证据出现后怎样继续？
5. 后续任务是否真正采用了适用新版本？
6. 目录增长后，人和 Agent 是否仍可从短入口定位知识？
7. 工具升级后，是否能定位它可能污染过的历史知识？

建议试点累计 50—100 个真实问题/任务，并保留安全、故障、迁移负例。

---

## 20. 固定上游评估基线

```yaml
project_wiki:
  repository: giodra96/project-wiki
  ref: 09f24a20e7790e1a0215d28644333eb6ad1bb543
  upstream_schema: "1.6.0"
llm_wiki:
  repository: nashsu/llm_wiki
  ref: e8082119649e6a8e1cf85eaf289adcabfdf39d4e
```

上游能力需要按模块记录“直接复用 / 适配复用 / 保留机制 / 暂缓 / 裁剪”。不能一边说复用，一边无理由全部重写；也不能为了复用几个模块先重构完整桌面应用。

许可和间接依赖必须在实际代码复用前再次核查。


---

## 21. WeKnora 对来源与证据层的补强

V2.1 的 K / E / W / CHG 闭环保持不变，但 Evidence（E）进一步具体化为：

```text
来源连接 / 人工投递
  → 稳定 source identity
  → source revision
  → versioned processing
  → structured evidence chunks
  → correction / evidence binding
  → candidate or existing knowledge diff
  → CHG / Review
  → 正式知识修订与发布
```

### 21.1 来源身份与来源修订分离

来源身份描述“上游是哪一份材料”；修订描述“这次取得的内容版本”。

有上游稳定 ID 时，`source_id` 由 `connector + upstream_id` 生成；内容哈希只描述修订。手工投递且没有稳定上游 ID 时，允许内容哈希作为去重 fallback。

本地存储路径、来源逻辑路径和正式知识归属相互独立，不通过复制原件实现多视图。

### 21.2 处理配置必须可追溯

每次解析记录：

- source revision；
- parser + parser version；
- effective processing config；
- coverage / warnings；
- processing state；
- 产物位置。

解析器或配置变化可以触发受影响阶段重跑，不要求重新获取未变化的原件，也不能静默覆盖已审核的知识正文。

### 21.3 Evidence Chunk 不是知识条目

证据片段保存：

- evidence_id；
- source / source revision；
- processing_id；
- heading/path/position 等真实 locator；
- content sha；
- index state。

小片段用于查找和引用，正式知识仍表达团队整理后的结论、适用条件和例外。

### 21.4 原始解析与人工纠正分离

parser output 保持不可变。OCR、文本抽取等错误的人工纠正以独立 correction record 保存，记录修改前后哈希、理由、核对者和证据修订。

读取 Evidence 默认可以返回当前纠正后的可用文本，但 raw parser output 始终可追溯。重新解析产生新的 evidence_id，不自动把旧纠正套到新产物。

### 21.5 候选知识先绑定证据，再编译语言

知识编译不只在最后附“参考文档”，而应先建立：

```text
candidate / knowledge
  ↕ supports / limits / contradicts / relevant
evidence chunk
```

然后再与现有 K 比较，生成 CHG。引用存在只证明定位合法，不证明其语义支持结论；正式发布仍需要 Agent/责任方做语义核查。

### 21.6 处理阶段分别可见

来源处理至少区分：

```text
acquired → processed → evidence ready → indexed → compiled → published
```

当前实现阶段可以缺失，但不能把前一阶段成功冒充后一阶段成功。索引失败不必阻断基于原文 Evidence 的知识编译；向量可查询也不代表知识已经发布。

### 21.7 WeKnora 的采用边界

我们吸收其来源同步、处理配置、Chunk 结构、证据接地、批量归并和状态治理思路，但不把 WeKnora 作为第三个必须运行的平台。

普通成员入口继续只有：

- `sources/`；
- `wiki/`；
- `changes/`。

内部仍由 knowledge-kit、project-wiki 已适配能力和 llm_wiki 已适配能力共同服务同一 K/E/W/CHG 契约。


---

## 22. Evidence 到正式知识的安全修改与持续 Git 来源

V0.5 将 Evidence Layer 继续向两端延伸：向上连接 Candidate/Patch Plan，向下连接本地 Git 项目的持续来源同步。

### 22.1 Candidate 是变更过程中的临时语义对象

Candidate 用于表达“当前 Agent/责任人认为这些 Evidence 可能意味着什么”。它不是正式 Knowledge，也不改变 K/E/W/CHG 四个核心业务对象。

Candidate 必须绑定具体 Evidence，随后显式声明与已有 Knowledge 的关系：

```text
new / adds / narrows / contradicts / duplicates
```

程序不根据相似度、引用次数或 LLM 输出自行决定该关系。

### 22.2 Patch Plan 将语义判断转换为可验证写入

Patch Plan 保存：

- Candidate；
- comparison；
- target knowledge ID/path；
- target base content hash；
- Evidence IDs/current hashes/source revisions；
- CHG；
- 必要 Review；
- Agent 给出的变更摘要。

当前 Agent 使用 `patch-context` 读取原知识与具体 Evidence，生成完整 Markdown 修订稿。

确定性 `patch-apply` 在写入前重新检查：

1. 目标 Knowledge 未发生并发变化；
2. Evidence 未发生纠正/版本变化；
3. Markdown ID 与目标一致；
4. 新 Knowledge ID 尚不存在。

任一前提变化都使旧 Plan stale，必须重新比较。

应用完成只表示贡献分支中的正文已按 Plan 修改，CHG 进入 proposed；是否正式发布仍由 Git 审核/发布规则决定。

### 22.3 本地 Git Connector 是首个持续来源实现

Git Connector 的共享状态只保存：

- connector ID；
- repository identity；
- include scope；
- logical root；
- checkpoint；
- tracked/retired source mapping。

本地绝对 checkout 路径不提交到团队知识仓库，每次同步由成员/Agent 在已有授权下提供。

首次同步从指定 Git commit 建立 Source；后续同步使用 commit checkpoint 计算增量：

```text
add / modify / rename / delete / scope-remove
```

rename 通过 tracked mapping 保持原 source_id；modify 产生新 source revision；delete 保留历史证据并标记 deleted-upstream；rename 移出监控范围只标记 out-of-scope，不伪装成上游删除。

### 22.4 Checkpoint 代表完整批次完成

每次同步建立 SYNC 记录，保存 from/to commit、事件、已处理事件、错误与计数。

只有全部事件完成才推进 connector checkpoint。失败时 checkpoint 保持旧值，下一次重新从旧 checkpoint 计算；Source 操作必须保持幂等，避免重试制造重复来源或重复修订。

### 22.5 V0.5 后的完整链

```text
Git / manual source
  → Source identity + revision
  → Processing + Evidence chunks
  → Candidate + Evidence bindings
  → explicit comparison
  → Knowledge Patch Plan
  → CHG / Review
  → Agent-produced Markdown
  → deterministic stale-safe apply
  → Git review / publish
  → later Work adoption
```

下一阶段重点不再是增加对象，而是处理多来源聚合、Overview/Analysis 依赖影响、发布记录和后续采用验证。


---

## 23. 多来源归并、依赖影响与发布采用闭环

V0.6 将 V0.5 的单一 Candidate/Patch Plan 扩展成完整的团队复用链：

```text
多来源 Evidence
  → 多 Candidate
  → Batch + merged Candidate
  → Patch Plan
  → Wiki 修改
  → 显式依赖影响
  → Review
  → Git 发布
  → Publication
  → 后续 Work adoption
  → Adoption Record
```

### 23.1 Batch 是工作产物，不是新的正式知识层

Candidate Batch 只用于把同一 proposed knowledge 的多个 Candidate 放到一起处理。它不会自动决定结论，merged statement 仍由当前 Agent/领域责任人明确。

程序负责：

- 候选兼容性；
- Evidence 去重；
- Evidence relation 保留；
- relation 冲突提示；
- merged Candidate 建立。

最终仍然进入既有 Patch Plan / CHG，不形成第二套发布流程。

### 23.2 强影响只沿显式 depends_on 传播

知识关系分两类：

- related / graph relevance：帮助检索和调查；
- depends_on：表示上游知识变化后需要复核。

V0.6 的 impact 只认 `depends_on` 和 `references.relation=depends_on`。

因此，修改 K-A 时：

```text
K-B depends_on K-A
Overview depends_on K-B
```

会形成：

```text
K-A changed
 → K-B direct review
 → Overview transitive review
```

但普通 related 页面不会被自动列入强制复核。

### 23.3 Patch Apply 后立即产生依赖 Review

Patch Plan 应用完成后：

1. 计算显式 dependency impact；
2. 如存在 dependents，创建/复用 dependency Review；
3. 将 Review 关联原 CHG；
4. 保存 impact 到 Patch Plan 与 CHG；
5. Publication 必须等待 Review 被 resolved/dismissed。

这保证“正文已经改了”不会绕过依赖知识的复核。

### 23.4 Publication 必须绑定真实 Git commit

知识的 active/status 字段不能宣布自己已发布。

正式 Publication 需要核验：

```text
CHG proposed/ready
 + no unresolved Reviews
 + real Git commit
 + commit 中目标 Markdown hash == 当前正文 hash
```

然后才产生 PUB 记录。

Publication 记录 adoption requirement，但不自动 push/merge Git，也不替代仓库保护规则。

### 23.5 Work adoption 绑定已发布版本

Work adopted 某条知识时，只有当前正文和最新 Publication 的 content hash 一致，才记录：

- publication_id；
- published_ref；
- adoption_requirement；
- publication_match=true。

若成员处在包含未发布知识修改的工作树中：

```text
latest Publication hash != current file hash
```

则该使用不会被计为对正式发布版本的 adoption。

### 23.6 Adoption Record 是共享的复用证据

Work 本身可以继续是本地运行记录，但其中“某个 consumer 实际采用哪个 Publication，以及结果如何”具有团队复用价值。

因此 finalize 将这部分提炼为共享 Adoption Record：

```text
consumer
 + publication
 + used_for
 + outcome
 + evidence
```

这样可以回答：

- 新知识发布后哪些项目实际采用过；
- 哪些采用只是使用，哪些有 supported/boundary/contradicted 结果；
- 一个发布是否已经跨项目得到复用验证。

发布次数不再被误当成复用次数。

### 23.7 当前闭环

至 V0.6，完整链路为：

```text
Source
 → Revision
 → Processing
 → Evidence
 → Candidate
 → Batch
 → Patch Plan
 → CHG / Review
 → Wiki modification
 → Dependency Review
 → Git commit
 → Publication
 → Work adoption
 → Outcome
 → Adoption Record
 → new Evidence / next CHG
```

下一阶段重点从“把链路接起来”转向“提高多人、多项目下的治理质量”：依赖 Review 修订、项目 adoption requirement 门禁、知识锁版本以及冲突批次处理。


---

## 24. 项目侧知识消费治理

V0.7 将团队知识从“已经发布、可被项目采用”进一步推进为“项目按精确版本消费，并受更新要求约束”。

### 24.1 项目显式声明消费边界

项目 Profile 必须声明：

```yaml
knowledge_sources:
  - repository_id: team-knowledge
    knowledge_ids:
      - K-A
      - K-B
```

首版不允许 Agent 在任务开始时自行省略明确声明的知识。自动 scope/rule selection 后续只能在该显式边界内扩展。

### 24.2 Knowledge Lock 是项目知识基线

项目提交：

```
.knowledge/knowledge.lock.yml
```

每条锁定项指向一个精确 Publication：

```text
knowledge_id
 + publication_id
 + published_ref
 + content_sha256
 + adoption_requirement
```

因此项目的知识基础可以随代码一起审查、比较和回滚。

本地 team-knowledge checkout 路径仍属于本机配置，不进入共享 lock。

### 24.3 更新要求成为真实门禁

Publication 的 adoption requirement 在项目侧解释为：

| Requirement | Task start | Release |
|---|---|---|
| notice | 允许，warning | 允许，warning |
| review-required | 允许，warning | 必须 accept 或有理由 defer |
| must-address | 阻断 | 阻断，必须升级 |

Defer 只对具体的旧 Publication → 新 Publication 生效，不自动覆盖后续版本。

### 24.4 生效时间与最新版本分开

项目同时认识：

- latest effective Publication；
- scheduled future Publication。

如果 v2 已生效、v3 未来生效，项目必须先处理 v2，不能因为 v3 更新而把 v2 隐藏。

初次 lock 只选择已经生效的 Publication，不提前消费未来规则。

### 24.5 Task Snapshot 禁止中途静默切换

Project Work 开始时固定：

- knowledge.lock SHA；
- lock 完整内容；
- project git 状态；
- kit version。

任务读取知识时，不读取 team-knowledge 当前工作树，而是从锁定 Publication 的 Git commit 精确读取正文并重新验证 hash。

如果 task start 后项目升级 lock：

```text
work.lock_sha != current knowledge.lock sha
```

则旧 Work 不能 finalize，需要重新 prepare。这样一个 Work 不会同时使用两个团队知识版本。

### 24.6 Start Gate 与 Release Gate 分离

Start Gate 解决“现在是否允许开始工作”。

Release Gate 解决“这次交付是否已经处理了必须处理的团队知识更新”。

这允许 review-required 在开发早期先提示、在最终交付前强制完成决策；must-address 则从任务开始就阻断。

### 24.7 项目采用结果回到团队知识库

Project Work 本身继续留在项目本地。

但 finalize 会将真正采用的 Publication 提炼为团队 Adoption Record：

```text
project consumer
 + publication
 + used_for
 + outcome
 + evidence
```

因此团队可以看到一条知识：

- 发布到哪里；
- 哪些项目仍锁旧版本；
- 哪些项目明确 defer；
- 哪些项目已经采用；
- 采用后的结果是 supported、boundary 还是 contradicted。

### 24.8 V0.7 后的闭环

```text
Team Knowledge
  → Publication
  → Project knowledge.lock
  → Project start gate
  → exact historical context
  → Project Work
  → adopt / observe
  → new Publication
  → notice / review-required / must-address
  → accept / defer / block
  → release gate
  → finalize
  → Team Adoption Record
  → new Evidence / next CHG
```

下一阶段重点是把这些确定性门禁接到项目 CI/required check，并增加适用规则选择、approved exception 和项目侧反馈自动回流。
