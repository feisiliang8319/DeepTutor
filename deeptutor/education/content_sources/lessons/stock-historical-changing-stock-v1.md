# 既有总量，又有持续增长：分开两个来源

适用：数学拓展讲解。中文内容由 DeepTutor 独立改写，计算与枚举已核验；课程和难度仍待教学审核。用于 Chat 解释概念，不自动创建 Quiz 或升级学生。

## 方法
数量一边增加一边减少时，可以先把不同情形的总消耗相比，消去共同的初始量，再求每段时间的变化。另一种相关方法是先选择一个简单基准，再追踪每次替换使总量增加多少。
这些方法都要写清不变的条件。草场例子采用恒定生长和恒定消耗的数学模型，不能直接作为现实养殖结论。

## 讲解案例1：一边增长一边消耗
情境与条件：理想化草场模型中，牛每天吃草量相同且固定，草每天均匀生长；各块草场开始时每公顷草量相同，每公顷每天新增草量也相同。10公顷草场供12头牛吃16天刚好吃完，或供18头牛吃8天刚好吃完。40公顷草场供多少头牛吃6天刚好吃完？

结论：88头。

推导：以一头牛一天吃的量为1份。10公顷16天提供12×16=192份，8天提供18×8=144份，多8天多长48份，每天新长6份；初始草量144−8×6=96份。40公顷初始有384份，每天长24份，6天总计384+24×6=528份，供528÷6=88头。

## 讲解案例2：三种花苗
情境与条件：买100株花苗共用100元。甲种每株3元，乙种每株2元，丙种每株0.5元，三种都买了，乙种株数是甲种的5倍。三种各买多少株？

结论：甲种5株，乙种25株，丙种70株。

推导：若100株全买丙种，只用50元，还需增加50元。每1株甲种与5株乙种为一组，用13元；同样6株丙种只用3元，每组增加10元。因此这样的组有5组：甲5株、乙25株，丙100−30=70株。检验5×3+25×2+70×0.5=100。

## 检查
求出初始草量和增长速度后，分别代回12头牛16天、18头牛8天两组条件；两个条件都成立才完整。
花苗例子同时核对总株数100、总价100元，以及乙种株数是甲种5倍，不能只核对总价。

## 来源与改编
本讲义只改编数学关系，不沿用原书历史叙事、插图或人物评价。所用底本已在本机存量中，保留其美国公有领域来源标记；未声称在所有地区都自动取得同样的权利。

- Henry Ernest Dudeney. The Canterbury Puzzles, problem 111. DeepTutor independently rewritten mathematical task and explanation; original narrative and illustrations not reproduced. Source SHA256 02aa60bc6c3b5982246b0e1ef68428a5b9a7b83980938ceb189df51f26a0762a.
  来源：https://www.gutenberg.org/ebooks/27635 | Problem 111 | source line 4321
  原始记录：26767025a1595cf480633c17a62d607a44f472e85281fa8cc3d4722fee3ad0ab

- Henry Ernest Dudeney. Amusements in Mathematics, problem 110. DeepTutor independently rewritten mathematical task and explanation; original narrative and illustrations not reproduced. Source SHA256 7e52015850ff1a25cbba577911e2648d7ee200d2f15adbe05c8adf65776543d3.
  来源：https://www.gutenberg.org/ebooks/16713 | Problem 110 | source line 2202
  原始记录：85311f56d34f630686634ec289d5349ebd1d5c5860c5f96f3ef3301fe8f86b8a
