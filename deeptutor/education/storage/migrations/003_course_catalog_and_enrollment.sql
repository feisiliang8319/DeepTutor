-- 003_course_catalog_and_enrollment.sql — 把「课程目录」和「谁在上这门课」
-- 分成两件事
--
-- 背景（2026-08-15，Sol 定的架构主线）：内容按「学科 × 年级/等级」组织，学生
-- 只是挂上去。加到第 10 个学生也不该动内容结构。此前有两处与这条线相悖：
--
--   1. courses 只有 subject_key 和 title，年级埋在 title 字符串里（'Grade 4
--      Math'）。要"按学科类别拉取对应年级"就只能去猜 title，等级不可查询。
--      开第二门课（AP World History，高中线）时这个问题立刻变成阻塞：
--      subject_key 能区分学科，但区分不了 G4 数学与 AP 数学。
--
--   2. 完全没有 enrollment 概念（全代码库 grep 'enroll' 零命中）。"谁上哪门
--      课"只能靠有没有作答记录反推——学生注册了但还没答第一题时，系统不知道
--      他该上什么。反推还有个更糟的后果：它把"学过"和"选了"混为一谈，退选、
--      预选、同时选两门都无法表达。
--
-- level 允许为 NULL：SQLite 不支持给已有行的新列加 NOT NULL 而不给默认值，
-- 而"默认 G4"对将来任何一门非 G4 的课都是错的。宁可留空让写入层拒绝，也不
-- 埋一个静默的错值。已有的 course-math-g4 由本次迁移显式回填。
ALTER TABLE courses ADD COLUMN level TEXT;

UPDATE courses SET level = 'G4' WHERE id = 'course-math-g4';

-- 课程目录的查询形态就是 (subject_key, level) → 取 active 版本。
CREATE INDEX IF NOT EXISTS idx_courses_subject_level ON courses (subject_key, level);

-- 选课关系：多对多，加学生只加行，不碰任何内容表。
--
-- 关联到 course_version_id 而非 course_id，是因为教材换版后旧版仍要能查
-- （某个学生的历史进度属于他当时学的那一版），而"自动跟随最新版"是产品决策，
-- 不该由外键结构替产品做主。
--
-- status 而非物理删除：退选后作答记录仍在 student_attempts 里，enrollment 行
-- 消失会让那些记录变成无来源的孤儿。
CREATE TABLE IF NOT EXISTS enrollments (
  learner_id        TEXT NOT NULL REFERENCES learner_profiles(id),
  course_version_id TEXT NOT NULL REFERENCES course_versions(id),
  status            TEXT NOT NULL DEFAULT 'active'
                      CHECK (status IN ('active', 'withdrawn', 'completed')),
  enrolled_at       TEXT NOT NULL,
  updated_at        TEXT NOT NULL,
  PRIMARY KEY (learner_id, course_version_id)
);

CREATE INDEX IF NOT EXISTS idx_enrollments_version
  ON enrollments (course_version_id, status);
