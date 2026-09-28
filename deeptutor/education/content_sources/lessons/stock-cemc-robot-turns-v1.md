# 机器人转向：把方向和位置分开记录

适用：数学拓展讲解；由 DeepTutor 改编，计算已复核，课程与难度仍待教学审核。用于 Chat 解释概念，不自动创建 Quiz 或认定掌握。

## 学习要点
一条“转向后前进”的指令包含两步。转向改变朝向，但不改变位置；前进改变位置，但不改变朝向。顺时针90°、180°、270°分别相当于向右、掉头、向左。

## 一个完整案例
使用向右为横坐标正方向、向上为纵坐标正方向的方格。机器人从(0,0)出发，最初朝左，在无障碍方格中执行以下指令：
1. 顺时针转180°，前进3格：朝向变为右，到(3,0)。
2. 顺时针转90°，前进2格：朝向变为下，到(3,−2)。
3. 顺时针转90°，前进3格：朝向变为左，到(0,−2)。
三段共走8格，起点和终点直线相隔2格。路程与两点之间的距离是不同概念。

## 从指令走向路径证明
检查完整迷宫程序时，需要逐格核对是否越界、是否经过障碍，不能只检查终点。两个程序可以走到同一个终点，却经过不同的路径。
本案例选用原题的前三条指令解释坐标跟踪，采用明确的无障碍场景；不把这三条指令当成完整迷宫的通关程序。

## 来源与改编
Centre for Education in Mathematics and Computing, University of Waterloo. Help Send Freddy Home, POTWB-25-combined-linked.pdf, PDF第22页。
来源：https://cemc.uwaterloo.ca/sites/default/files/documents/2026/POTWB-25-combined-linked.pdf#page=22
许可：CC BY-NC 4.0，仅限非商业教育使用；https://cemc.uwaterloo.ca/copyright 。中文改编与补充说明由 DeepTutor 编写，未获 CEMC 背书。
原PDF SHA256：8e28ee3f9f982016bdff501d77842fb6c50fbf3efd5e322241569d2a267e542f
原题与解答文本 SHA256：02b6e67b2e29e72fb645208392752b999e0e16ed27a38f5c8f15545c1f4e8e27
