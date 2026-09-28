# 时间线与总量：先统一比较对象

适用：数学拓展讲解。中文内容由 DeepTutor 独立改写，计算与枚举已核验；课程和难度仍待教学审核。用于 Chat 解释概念，不自动创建 Quiz 或升级学生。

## 方法
时间题先把已知时刻放到同一条时间线上，分清“现在”与“50分钟前”的量。平均速度则先累计总路程和总时间；两个速度所占时间不同时，不能直接各取一半。

## 讲解案例1：倒推时刻
情境与条件：现在是下午某个时刻。50分钟前，距离15:00已经过去的分钟数，恰好等于现在距离18:00还剩分钟数的4倍。现在是几点几分？请检验。

结论：17:34。

推导：15:00到18:00共180分钟，扣去50分钟，剩130分钟分成“现在距18:00的1份”和“50分钟前距15:00的4份”，每份26分钟。现在18:00前26分钟，即17:34；50分钟前16:44，距15:00为104分钟，104=4×26。

## 讲解案例2：总路程与总时间
情境与条件：一辆模型车从甲站到乙站，路程60米，速度每分钟10米；原路返回时速度每分钟15米，全程没有停留。平均速度定义为总路程除以总时间。往返平均速度是多少？为什么不能直接取10与15的平均数？

结论：每分钟12米。

推导：去程60÷10=6分钟，回程60÷15=4分钟，总路程120米，总时间10分钟，所以120÷10=12米/分钟。两个速度持续的时间不相同，不能各占一半直接平均。

## 检查
得到时刻后，沿时间线倒回50分钟，重新检查倍数关系。得到平均速度后，用它乘总时间，应该还原总路程。
本讲义的速度按每分钟计算；不要在同一步混用每小时与每分钟。

## 来源与改编
本讲义只改编数学关系，不沿用原书历史叙事、插图或人物评价。所用底本已在本机存量中，保留其美国公有领域来源标记；未声称在所有地区都自动取得同样的权利。

- Henry Ernest Dudeney. Amusements in Mathematics, problem 58. DeepTutor independently rewritten mathematical task and explanation; original narrative and illustrations not reproduced. Source SHA256 7e52015850ff1a25cbba577911e2648d7ee200d2f15adbe05c8adf65776543d3.
  来源：https://www.gutenberg.org/ebooks/16713 | Problem 58 | source line 1314
  原始记录：8b7c7dfe0fa43e5c93fe47533bcd3a0b82eaab7aa47afdb0f587cd3f13e9f8f9

- Henry Ernest Dudeney. Amusements in Mathematics, problem 67. DeepTutor independently rewritten mathematical task and explanation; original narrative and illustrations not reproduced. Source SHA256 7e52015850ff1a25cbba577911e2648d7ee200d2f15adbe05c8adf65776543d3.
  来源：https://www.gutenberg.org/ebooks/16713 | Problem 67 | source line 1447
  原始记录：f7fb62b0830b17b9adf9bcd899e5480439f400e9acb00e60a7a30850fa9c3302
