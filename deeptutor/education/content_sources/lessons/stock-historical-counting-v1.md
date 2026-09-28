# 完整计数：分类、唯一对应和上界

适用：数学拓展讲解。中文内容由 DeepTutor 独立改写，计算与枚举已核验；课程和难度仍待教学审核。用于 Chat 解释概念，不自动创建 Quiz 或升级学生。

## 三种证明方式
完整计数需要同时避免重复与遗漏。分类时，每种结果只能落入一类，而且所有结果都有归属；用边界决定图形时，需要证明一组边界只对应一个图形；声称最多时，需要给出无法超过的上界，并展示达到它的安排。
下面是完整的讲解案例，不作为 Chat 中的测验，也不据此认定学生已经掌握。

## 讲解案例1：全部拿错的方法数
情境与条件：A、B、C、D各有一个同名字母标记的袋子。把4个袋子分给4人，每人1个，要求每人都不拿自己的袋子。有多少种分法？可按A拿到的袋子分类，说明没有遗漏。

结论：9种。

推导：按A拿B、C、D分为互不重叠的3类。A拿B时，按B拿A、C、D，剩下人的袋子分别只能是CD→DC、CD→DA、CD→AC，得到按A、B、C、D领取顺序的BADC、BCDA、BDAC，共3种。另两类由交换字母得到，同样各3种，所以3×3=9。

## 讲解案例2：网格里的长方形
情境与条件：一张完整网格由4行5列单位正方形组成。只数边与网格线重合的长方形，其中包括正方形。共有多少个长方形？其中正方形多少个，非正方形多少个？解释计数方法。

结论：长方形150个，其中正方形40个，非正方形110个。

推导：5条水平线中选2条有4+3+2+1=10种，6条竖直线中选2条有5+4+3+2+1=15种；每组边界唯一对应一个长方形，共10×15=150。边长1、2、3、4的正方形分别有4×5、3×4、2×3、1×2个，共40，非正方形150−40=110。

## 讲解案例3：不重复的邻座
情境与条件：7位同学A至G围坐圆桌。每次每人有左右两个邻座，某两人只要相邻，就记一次，不区分左右。要求不同轮次不能出现同一对邻座。给出的三轮顺序为ABCDEFG、AFBDGEC、AEBGCFD，每行首尾也相邻。验证它们可行，并证明不可能安排第4轮。

结论：三轮可行，最多3轮。

推导：把每轮7对邻座写成无序对：第1轮AB、BC、CD、DE、EF、FG、AG；第2轮AF、BF、BD、DG、EG、CE、AC；第3轮AE、BE、BG、CG、CF、DF、AD。21对全部不同。每个人只有6位可能的邻座，每轮用2位，最多6÷2=3轮，所以三轮已达上限。

## 常见误区
网格长方形的数量不是小方格数量，面积相同的长方形也可能位置不同。
邻座问题把AB和BA看成同一对；圆桌的第一人与最后一人也相邻。漏掉首尾关系，会把无效的安排误判为可行。

## 来源与改编
本讲义只改编数学关系，不沿用原书历史叙事、插图或人物评价。所用底本已在本机存量中，保留其美国公有领域来源标记；未声称在所有地区都自动取得同样的权利。

- Henry Ernest Dudeney. Amusements in Mathematics, problem 267. DeepTutor independently rewritten mathematical task and explanation; original narrative and illustrations not reproduced. Source SHA256 7e52015850ff1a25cbba577911e2648d7ee200d2f15adbe05c8adf65776543d3.
  来源：https://www.gutenberg.org/ebooks/16713 | Problem 267 | source line 6112
  原始记录：bc32b7780403ca66b6b48e5e794eb89ad59ee9f74405b6f91bfc5a5b3bf9eb04

- Henry Ernest Dudeney. Amusements in Mathematics, problem 347. DeepTutor independently rewritten mathematical task and explanation; original narrative and illustrations not reproduced. Source SHA256 7e52015850ff1a25cbba577911e2648d7ee200d2f15adbe05c8adf65776543d3.
  来源：https://www.gutenberg.org/ebooks/16713 | Problem 347 | source line 8567
  原始记录：ba65282dabd47eb7a3a4be6367c3edc46fa3a1f6af29396dfe951f4e2b4266ab

- Henry Ernest Dudeney. Amusements in Mathematics, problem 263. DeepTutor independently rewritten mathematical task and explanation; original narrative and illustrations not reproduced. Source SHA256 7e52015850ff1a25cbba577911e2648d7ee200d2f15adbe05c8adf65776543d3.
  来源：https://www.gutenberg.org/ebooks/16713 | Problem 263 | source line 6058
  原始记录：62fa7d9ec705ad9198dd660b6a2d7642eb3508af9191fe9f054b33b9eeced152
