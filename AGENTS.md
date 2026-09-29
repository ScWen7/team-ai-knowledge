# team-ai-knowledge

本仓库维护 team-wiki 工具、设计和可运行示例。团队域与项目域的知识归属及四项目标见 `docs/FINAL_DESIGN.md`；当前实现边界见 `README.md`。

- 项目文档治理保留原有目录、正文、规则权威和已有元信息。未知的责任、有效性或证据不能由格式修复推断为已确认。
- `/Users/scwen/ReportExcel/reportHub-doc` 是独立维护的项目知识库。没有针对该仓库的明确授权时，只用作只读样本；验证写入使用本仓库 `.tmp/` 中的样本。
- 团队底线的完整读取与检查不能被 Top-K、上下文预算或采用统计替代。Git 提交内容校验不等于人工审批、远端发布或真实业务验收。
- 本地验证：`.venv/bin/python -m unittest discover -s tests`。CLI 入口为 `.venv/bin/team-wiki`；项目依赖通过虚拟环境安装，不安装全局依赖。
- 检索直接读取当前工作区文件，不维护数据库、持久检索缓存或 Git 更新钩子。文档和 Git 是事实来源。测试与性能样本放 `.tmp/<task>/` 或测试进程的临时目录，不修改外部项目。
