# 产品经理使用指南（无需安装 CLI）

本指南面向**不安装 team-wiki CLI**、只通过 Git 托管平台 Web 界面使用团队知识库的成员。如果你要执行知识登记、变更、发布等操作，请改用 CLI 路径。

## 我能做什么 / 不能做什么

| 我想... | 可以 | 做法 |
|---|---|---|
| 看正式知识 | ✅ | 浏览 `wiki/` 目录 |
| 交资料 | ✅ | 上传到 `sources/inbox/` |
| 看最近变更 | ✅ | 看 `changes/views/recently-published.md` |
| 提修改建议 | ✅ | 在对应知识文件点 "Edit"，提 PR |
| 把资料登记成稳定 source | ❌ | 需要工程师或 Agent 执行 `team-wiki ingest` |
| 发布知识 | ❌ | 需要走 CHG → Review → publish 流程 |
| 锁定项目知识版本 | ❌ | 工程师的项目侧操作 |

## 三种日常使用方式

### 1. 我要看知识

直接在 GitHub / GitLab Web 界面浏览：

```
wiki/
├── team-conventions/   团队约定
├── technical/          技术知识
├── business/           业务知识
└── projects/           项目入口
```

每个目录下的 `INDEX.md` 是该领域的导航，点进去就能看。

### 2. 我要交资料

**步骤**：
1. 进入 `sources/inbox/` 目录
2. 点右上角 "Add file" → "Upload files"
3. 把文件拖进去（PDF / Word / Markdown / 图片都可以）
4. 写一句简短的提交说明，例如 "2026-09 订单导入业务规则 v3"
5. Commit 到 main（或新建分支提 PR）

**接下来会发生什么**：
- 仓库配置的 GitHub Actions 会自动检测 inbox 新文件
- 自动创建一个"待登记"提醒，分配给值日工程师
- 工程师会执行 `team-wiki ingest` 把它登记成稳定 source package，并按需进入知识变更流程

**你不需要做**：
- 不需要自己移动到 `sources/YYYY/MM/` 子目录（工具会做）
- 不需要填写 source.yml（工具会生成）

### 3. 我要看最近变更

打开：

```
changes/views/recently-published.md
```

这是只读视图，由工具自动维护。也可以看：

- `changes/views/open.md`：进行中的知识变更
- `changes/views/blocked.md`：被阻塞的变更
- `changes/INDEX.md`：所有变更的入口

### 4. 我要提修改建议

如果你发现某条知识**有误 / 过时 / 不清楚**：

1. 打开对应的 `wiki/**/*.md` 文件
2. 点右上角铅笔图标（Edit this file）
3. 修改内容
4. 底部选 "Create a new branch for this commit and start a pull request"
5. PR 标题前缀加 `[知识建议]`，正文说明：
   - 为什么改
   - 依据是什么（最好附链接或文档）
6. 提交 PR，系统会自动提醒该知识的 owner 审核

**注意**：
- 这种"直接编辑 wiki"不会立即生效——会触发一个 CHG（知识变更）流程
- 领域责任人审核后才会进入正式发布

## 我收到"知识更新"通知时该怎么办

当团队知识发布新版本时，你可能收到：
- 邮件 / 飞书通知（如果配置了）
- 在相关 PR 中被 @
- 在周会/日报里听到

**你只需要**：
- 如果这条知识跟你的工作有关 → 抽时间看一下新版本
- 如果无关 → 忽略

**你不需要**：执行任何命令、更新任何文件。

## 常见问题

**Q：我想搜索知识怎么办？**
A：用 GitHub / GitLab 自带的搜索框（仓库内搜索），或在本地 Agent（如 Claude Code）中打开这个仓库然后问它。

**Q：我能直接改 `wiki/` 下的文件让变更立即生效吗？**
A：不能。所有 wiki 修改都要走 CHG 流程。如果你直接编辑，GitHub Actions 会自动创建一个 CHG 并通知 owner 审核，不会立即覆盖现有知识。

**Q：我提交的资料会被保密吗？**
A：资料保存在团队 Git 仓库内，访问权限 = 仓库权限。不要上传涉及个人敏感信息、客户机密数据的资料。

**Q：我看到 `changes/` 目录下有我看不懂的术语怎么办？**
A：忽略即可。那是工程师和 Agent 的工作区。你只需要关注 `changes/views/` 下的三个视图文件。

## 我需要安装什么吗

**不需要。** 只需要：
- 一个 GitHub / GitLab 账号
- 能访问本仓库的权限

所有 CLI 操作由工程师或本地 Agent 完成。
