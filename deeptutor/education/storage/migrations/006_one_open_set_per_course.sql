-- 006_one_open_set_per_course.sql — 「同一门课最多只能有一组未交」由数据库强制
--
-- 背景（2026-08-21 第三轮质检席 CRITICAL-2）：
--
-- 005 引入 task_sets 之后，`GET /api/edu/set` 的逻辑是"先查有没有未交的组，
-- 有就原样重发，没有才新建"。这个先查后写在事务外，是典型的 TOCTOU：两个并发
-- 请求各自查到"没有未交的组"，于是各自 INSERT，产出两个 set_id **内容相同**的
-- 孪生卷子（select_next_item 的排除集互相看不见）。
--
-- 后果不是"多了一行"，而是绕过整个设计目标：先用 A 卷交垃圾骗出答案，再用 B 卷
-- （合法、未交、从未提交过）照抄拿满分。**任何只在应用层堵"同一个 set_id 不许
-- 重复提交"的补丁都堵不住它** —— 孪生卷子有两个不同的 id，各交一次都是合法的。
--
-- 应用层的窗口只能收窄，收窄不等于关闭。这里用**部分唯一索引**把它变成结构上
-- 不可能：并发的第二个 INSERT 直接撞 IntegrityError，应用层接住后回读那一组
-- 重发即可（fail-closed：撞了就回到"重发已有的那一组"这条正确路径）。
--
-- 为什么是部分索引：已提交的组必须能堆积（那是历史发卷记录，同一门课会有很多组），
-- 只有"未交"这个状态需要唯一。SQLite 3.8.0+ 支持 WHERE 子句的部分索引；本机 3.43。

CREATE UNIQUE INDEX IF NOT EXISTS uq_task_sets_one_open_per_course
  ON task_sets (learner_id, course_version_id)
  WHERE submitted_at IS NULL;
