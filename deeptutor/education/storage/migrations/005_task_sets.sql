-- 005_task_sets.sql — 「一组题」变成服务端状态，而不是客户端的自觉
--
-- 背景（2026-08-21 第二轮质检席 G-1，CRITICAL）：
--
-- 上一版把出题/交卷拆成 /api/edu/set 与 /api/edu/set/submit 两个来回，但
-- **组是客户端说了算的** —— 服务端只认"你交上来的这批题"。于是"答案必须等
-- 所有题提交之后才给"这条要求，实际强度等于"前端愿不愿意遵守"：
--
--   1. 旧的 /api/edu/attempt 还活着，直接 POST 就能对同一道选择题连猜 A/B/C/D，
--      逐次拿到 is_correct，四次以内必中。质检席实测复现。
--      （该端点与 /api/edu/next 已随本次改动一并删除。）
--   2. 即使删掉它，只要客户端能自选"这一组就一道题"，交上去立刻拿到答案，
--      仍然等于逐题即时反馈。
--
-- 所以组必须由服务端发、服务端记：发了哪几道、交没交。只有当交上来的题
-- **恰好等于**发出去的那一组时，才回吐答案与讲解。
--
-- 顺带堵掉"重开一组换简单题"：同一门课有未交的组时，/api/edu/set 直接把
-- 原组发回去，而不是另抽一组。
--
-- 为什么不引用 assessment_items 做外键：item_ids 是一个 JSON 数组（一行一组，
-- 而不是一组 N 行）。这里存的是"当时发了什么"的快照，题目后来被 retire 或
-- 修订都不该改写历史发卷记录 —— 与 student_attempts 的 append-only 精神一致。

CREATE TABLE IF NOT EXISTS task_sets (
  id                TEXT PRIMARY KEY,
  learner_id        TEXT NOT NULL REFERENCES learner_profiles(id),
  course_version_id TEXT NOT NULL REFERENCES course_versions(id),
  item_ids_json     TEXT NOT NULL,
  issued_at         TEXT NOT NULL,
  submitted_at      TEXT
);

-- 查询形态就两种：找某人某课**未交**的那一组；按 id 取一组。
CREATE INDEX IF NOT EXISTS idx_task_sets_open
  ON task_sets (learner_id, course_version_id, submitted_at);
