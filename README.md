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

> V0.1 没有实现 LLM 编译、关系评分、Review 语义判断、LanceDB 或 MCP。它只用于验证统一目录与确定性纵向切片。
