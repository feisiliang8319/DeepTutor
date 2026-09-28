# 可重复的教学资料注入

本目录是经限定来源、逐题加工的内容配方和原创讲义。它与 `application/source_supply.py` 一起工作，不要求家长整理 JSON，也不自动把抓取结果判定为合格考卷。

## 当前内容

- `cemc-b-2025-26.recipe.json`：CEMC 2025–2026 Problem of the Week B 的20道中文改编候选题，来自20个不同原题；每题有知识点、参考答案、讲解、原页码、原文版本和人工可复核的加工记录。
- 来源原本面向五至六年级。本包关联现有四年级数学课程中的进阶知识节点，表示拓展素材，**不表示覆盖该年级、完成教学或获得晋级资格**。难度3/4为待校准初值。
- `lessons/`：三篇 AI 辅助原创 Chat 讲义，讲系统枚举、约束与边界、单位与模型。例子与候选试题分开。
- 官方合集解析出30个不同题目；只对其中20个完成本轮加工。余下10个没有注入，尤其不能把尚未校对的图形题转为缺图题。

## 运行与注入

在已安装 DeepTutor 及 PDF 解析依赖的源码环境运行：

```sh
python -m deeptutor.education.application.source_supply \
  --recipe deeptutor/education/content_sources/cemc-b-2025-26.recipe.json \
  --output /private/tmp/deeptutor-source-intake
```

该命令获取指定官方 PDF、校验固定 SHA256、保留不可变原件和页级提取记录，生成现有内容工作台支持的候选题包。打印 `package_path` 和 `source_receipt`，**该步不写生产**。原文件版本或页内文字发生变化时停止，不能沿用旧答案继续导入。

经授权的操作方使用现有管理员 API 客户端调用：

```python
from deeptutor.education.application.source_supply import ingest

ingest(authenticated_admin_client, package)              # 预检，无写入
ingest(authenticated_admin_client, package, apply=True)  # 写入候选题
```

也可在管理端“知识库 → 资料导入”载入生成的题包并预检、导入。服务端负责角色鉴权、知识点校验、整批事务、冲突拒绝和重复导入回执。模块不读取凭据、不直写数据库、不审批题目、不修改学生年级。若网络在提交后中断，先查询回执或按相同包重试；稳定包身份防止重复新增。不得更改题目 ID 来绕过冲突。

原创讲义通过现有 `/api/v1/knowledge/{name}/upload` 接口进入已经授权的主库。上传前备份资料与注册表，上传后等索引完成，并用普通自然语言问题核对新文件来源。索引未完成时继续读取任务进度，不再次上传同名文件。题包中的测试答案不作为整包讲义上传 RAG。

## 增加后续资料

1. 操作方从已经确认的来源选择新资料，先确认用途、许可、学科和年级范围。当前连接器仅支持 CEMC 官方文档路径；其他来源需要相应边界与解析适配，不能直接放宽成任意 URL 抓取。
2. 保存原始文件和版本。对新标题、变更文件、缺图、公式排版和疑似重复问题进行复核；现有版本停止规则不会自动认可新版权或新答案。
3. 补充配方中的中文题干、知识点、答案、讲解及页码，运行独立数学核验和导入预检。仅换数字不能冒充新的原题来源。
4. 题目进入待审区；教材进入资料库，保留用途和来源。发布、正式考试分类与课程覆盖验收各自独立，不能用题量替代它们。
5. 留下导入回执、备份路径、旧资料完整性校验和检索证据。后续重复运行同一配方保持幂等。

这是操作方触发的可复用流程，尚未配置定时抓取、无人值守审核、全学科内容覆盖或商业版权许可。家长资料继续走家庭权限流程，不会进入公共资料采集器。

## 内容许可

CEMC 改编内容与程序代码的许可证不同。`cemc-b-2025-26.recipe.json` 中的改编题及其生成包按 **CC BY-NC 4.0** 保留署名、原始链接、改编说明和非商业使用限制；不能因为处于代码仓库就将它视为代码许可证下的内容。原始版权归 University of Waterloo / Centre for Education in Mathematics and Computing；DeepTutor 的改编不代表 CEMC 背书。

- 原始资料：<https://cemc.uwaterloo.ca/sites/default/files/documents/2026/POTWB-25-combined-linked.pdf>
- 官方归档：<https://cemc.uwaterloo.ca/resources/potw-archive>
- 官方许可：<https://cemc.uwaterloo.ca/copyright>
- 许可证全文：<https://creativecommons.org/licenses/by-nc/4.0/>

本目录 `lessons/` 是 DeepTutor 新编例子与讲义，不是 CEMC 原题译本。源文件与题包留在服务器私有资料回执中，提交源码不附整本原始 PDF 或运行凭据。
