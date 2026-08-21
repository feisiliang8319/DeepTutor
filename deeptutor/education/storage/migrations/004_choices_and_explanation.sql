-- 004_choices_and_explanation.sql — 选择题的选项变成结构化数据；讲解从
-- 「阅卷用的 rubric」里分出来单独存
--
-- 背景（2026-08-21，Sol 提的两条）：
--
--   1. 选择题的四个选项此前是**烤进 prompt 散文**里的（"(A) …\n(B) …"），
--      前端拿到的只是一坨文本，渲染不出单选按钮，孩子只能在输入框里手打
--      字母。prompt 末尾那句 `Answer with the letter only (A, B, C, or D).`
--      就是这个缺陷的止血贴，不是设计。
--
--   2. 答完题要给讲解，但讲解素材现在全埋在 rubric_json 里，而
--      rubric_json 有一条硬不变量：**永不出服务端**（见
--      tests/test_leak_prevention.py —— 上游 quiz_judge 曾把参考答案同时
--      写进日志和孩子的浏览器）。rubric 里混着阅卷标准、评分尺度、给大人看
--      的判分口径；为了给孩子看讲解而把整个 rubric 放行，等于用一条真需求
--      拆掉一道真闸门。所以讲解单开一列：它**本来就是要给孩子看的**，只是
--      要等全部提交之后才给。
--
-- 两列都允许 NULL，且不回填任何"猜出来的"内容：
--   - choices_json 只有选择题才有；
--   - explanation 只回填**出版社官方解答**（CEMC 的 official_solution，19 条）。
--     其余 160 条留空，界面显示"讲解待补"+ 关联知识点，不编。
--     尤其 AP World History 那 9 道选择题：本书不含答案键，答案是三方独立
--     盲解推导出来的；给一个推导答案配一段自信的讲解，等于把不确定性洗白。
--
-- explanation_source 记来源，因为"这段讲解权威不权威"直接决定家长该不该信它。

ALTER TABLE assessment_items ADD COLUMN choices_json TEXT;
ALTER TABLE assessment_items ADD COLUMN explanation TEXT;
ALTER TABLE assessment_items ADD COLUMN explanation_source TEXT
  CHECK (explanation_source IS NULL OR explanation_source IN
    ('publisher_official', 'authored', 'derived'));

-- 回填：只搬 CEMC 的官方解答，一个字不改写。
-- json_extract 在 SQLite 3.38+ 可用；本机 3.43。rubric_json 本身**不动**，
-- 它仍是服务端专用；这里只是把其中"本来就该给孩子看"的那一段复制出来。
UPDATE assessment_items
   SET explanation = json_extract(rubric_json, '$.official_solution'),
       explanation_source = 'publisher_official'
 WHERE rubric_json IS NOT NULL
   AND json_valid(rubric_json)
   AND json_extract(rubric_json, '$.official_solution') IS NOT NULL;
