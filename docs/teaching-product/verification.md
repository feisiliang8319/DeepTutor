# 教学收敛开发验证记录

2026-09-27；当前交付是独立工作树中的首版实现及隔离预览。没有生产迁移、部署、远端推送或合并，也没有宣称完整教学质量验收。

## 已实现并核对

- 单管理员；管理员只创建/配置家长；家长只能创建/配置自己的学生。学生在管理端仅留记录。授权链在 API 和数据库中约束，不依赖隐藏菜单。
- 每家长最多 5 个学生，停用仍占名额。SQLite 插入/转移约束及事务覆盖并发创建；迁移超过名额会拒绝，不截断数据。
- 合成预览接口创建到第 5 个学生，第 6 个返回 HTTP 409，回读无失败账户残留。家长页面显示 5 / 5，创建按钮禁用。
- 学生入口只有 Chat / Quiz。英文、简体、繁体可切换；昵称、雾蓝主题、大字号、关闭动效保存后刷新保持。语言单项更新不会覆盖其他外观设置。
- Quiz 提交两份合成答案后只展示正确性与参考答案；讲解、原始作答和批改依据自动进入同一学生 Chat。新学生实际提交的英文讲解已复验。
- 人工复核后追加新的讲解，不覆盖旧作答/旧消息；投递失败可单独重试，不重复批改。该恢复路径由后端回归验证。
- 家长为新学生选择课程，保存后重新打开保持。390 × 844 与桌面视口检查了学生阅读、折叠侧栏及输入控件。
- 管理端模型配置归类为教学模型、检索模型、研究搜索服务；实际教学模型子页可进入。未改写真实服务配置。

## 用户批准后的真实服务隔离验证

只在隔离运行目录复用现有主力模型和嵌入服务，输入为自编材料和合成题目。凭据留在主机的受限配置文件，不进入源代码或验证输出。

- 实际模型为现有配置的 `gpt-5.6-luna`，嵌入为本机 `bge-m3-mlx-8bit`。三个请求的持久化快照均记录服务器选定 `openai-direct / gpt-5.6-luna` 和所属家庭的 `family-materials`，均保存 sources 事件。
- 家长通过实际页面上传 `family-synthetic-study.md` 并完成索引。修复了异步处理中清空 FileList 导致上传 422 的问题；上传错误现在显示可读信息。
- 家长将资料只开放给 `preview_student`。API 回读该学生可见；同家庭未选中的 `child_five`、另一家庭学生和家长均不可见。
- Chat 自动检索材料，回答 72 个单位正方形的六种整数边长方案、最小周长 34 和不遗漏的证明，并引用合成来源标记 `OTTER-FAMILY-726`。界面可展开来源文件与摘录，无需学生选择模型或知识库。
- 学生要求直接在 Chat 出三道 Quiz 并评分时，实际回答指向 Quiz，没有生成测试题。
- 实际上传合成 Markdown 作业后，Chat 读出漏掉的 `8×9`，将错误的最小周长 36 纠正为 34，并说明完整性证明，没有变成 Quiz。
- 管理员通过实际页面将合成家庭资料加入共享目录。API 验证晋升本身不向其他家庭开放；给另一家长明确授权后其学生可见，撤回授权后不可见，撤出共享目录也立即不可见。原家长指定的学生范围始终保留。
- 上述共享测试结束后，资料已恢复家庭私有，另一家庭授权恢复原状。没有删除资料或账号。

## 自动验证

最近相关后端回归：**517 passed，3 warnings，15.06 秒**。

覆盖命令（在隔离 source 目录，以项目已有 Python 环境运行）：

```sh
DEEPTUTOR_HOME=/private/tmp/deeptutor-teaching-01a0e337/test-runtime PYTHONPATH=. python -m pytest tests/multi_user deeptutor/education/tests tests/services/session/test_turn_runtime.py tests/services/session/test_turn_runtime_subscribe.py tests/services/session/test_turn_runtime_title.py tests/services/session/test_sqlite_store.py tests/api/test_unified_ws_turn_runtime.py -q --disable-warnings
```

TypeScript `tsc --noEmit` 退出 0；三端账户导航 Node 测试 **5 项通过**；`git diff --check` 无错误。断言证据预筛未发现不支持项，但它不替代代码审查或构成发布批准。

测试运行目录与浏览器预览运行目录分开。此前共用目录导致旧模式测试继承新身份配置，已修正测试运行方式，未削弱权限断言。

预览同步改为逐文件比较并原子替换。此前直接解包引发开发服务器短暂读不到文件及缓存错误；旧缓存已移出源码目录保留，重启后同一路径浏览器及类型检查恢复。

## 剩余工作与证据边界

- Chat 困难对后续 Quiz 选题/难度的个性化反馈仍需完整实现与教学验收；现有共享状态不能等同于自适应出卷完成。
- 真实多模型升级、外部 Research 搜索和图片/OCR 作业尚未作本轮端到端验证；当前真实调用只覆盖一个主力模型、文本资料检索和 Markdown 作业。
- 长期记忆迭代和纠正机制、旧管理页面的全部繁体文案与手机适配仍需收尾；当前新增三端页面使用三种语言。
- 尚无本轮独立代码审查、完整生产构建、CI 或正式发布验收。
- 生产身份映射、旧家庭资料归属、迁移 dry-run、停写备份及恢复演练未进行。需要明确实际账户归属和独立生产切换授权。
- 生产用户、资料、权限和服务没有被本轮迁移。首版预览不应直接替换生产。

## 预览与材料位置

源代码：`/Users/h2h/.codex/worktrees/teaching-product/DeepTutor`，分支 `codex/teaching-product`。

Mac Mini 隔离目录：`/private/tmp/deeptutor-teaching-01a0e337`；网页只通过 SSH 转发到 `http://localhost:18036`。合成账号为 `preview_student`、`preview_parent`、`preview_admin`；仅预览密码均为 `StudyPreview-2026`。

复现实验脚本与合成材料保留在 `/Users/h2h/Documents/ChatGPT/DeepTutor/work/teaching-product-20260927`；生产数据与凭据不在该目录。浏览器已保留学生预览标签页。
