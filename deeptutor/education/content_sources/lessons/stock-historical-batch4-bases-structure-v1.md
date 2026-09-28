# 比例基数与代数结构：相等背后的条件

适用：数学拓展讲解。以下内容由本机已有旧书的数学结构独立改写，已做精确计算或有限枚举核验；课程年级、难度和正式测试资格仍待教学审核。用于 Chat 的完整讲解案例，不在 Chat 发起 Quiz，不据此自动认定学生掌握或升级。

## 核心方法
百分数必须注明基数，均摊必须说明固定总费用，离散数值条件可转化为整数因数对。用等价变形连接条件和完整解集。

## 讲解案例1：同价卖出的两件器材

条件：两件器材各以600元售出。第一件的售价比它自己的买入价高20%，第二件的售价比它自己的买入价低20%；忽略所有其他费用。合起来赚了还是亏了，金额是多少，占总买入价的百分之几？进阶：若每件售价都为S，两件分别按自己的买入价赚p、亏p，其中S>0、0<p<1，求总亏损率。

结论：亏50元，占总买入价的4%；一般总亏损率为p²。

完整推导：第一件成本600÷1.2=500元；第二件成本600÷0.8=750元。合计成本1250元，收入1200元，亏50元，亏损率50/1250=4%。一般成本合计S/(1+p)+S/(1−p)=2S/(1−p²)，收入为2S，所以亏损率为1−[2S÷(2S/(1−p²))]=p²。两个20%的基数不同，不能直接抵消。

## 讲解案例2：固定费用由谁分担

条件：一次活动的材料总费用固定为80元，原计划由所有参加者均摊。后来有2人退出，费用仍是80元，其余人重新均摊后，每人比原计划多付2元。原计划有多少人？请说明为什么不会有另一组正整数人数。

结论：原计划10人；原来每人8元，后来8人各付10元。

完整推导：设原来n人，其中n>2。条件为80/(n−2)−80/n=2，整理得n(n−2)=80，即(n−1)²=81。因n>2，n−1为正数，只能n−1=9，故n=10。代回80/10=8、80/8=10，差2元。负平方根会给出n=−8，不是人数，所以正整数解唯一。

## 讲解案例3：和与积恰好相等

条件：两个正数x、y都是1/4的整数倍，且x+y=xy，交换x、y视为同一组。已知x=y=2时和与积都为4。求比4更大的最小共同结果，并证明不存在介于4与它之间的结果。请列出符合条件的全部数对。

结论：最小的下一结果是9/2＝4.5，对应(3/2,3)。全部数对是(2,2)、(3/2,3)、(5/4,5)。

完整推导：由x+y=xy可得(x−1)(y−1)=1。x、y都必须大于1：若0<x≤1，则y(x−1)=x的左边不大于0而右边大于0，矛盾。令a=4x−4、b=4y−4，则a、b是正整数且ab=16。忽略顺序，正因数对只有(1,16)、(2,8)、(4,4)，对应(x,y)为(5/4,5)、(3/2,3)、(2,2)，共同结果依次为25/4、9/2、4。枚举的是16的全部因数对，所以没有遗漏，4之后最小是9/2。

## 教学提醒
进阶百分比公式和因式分解属于拓展讲解，具体年级和难度仍待校准。正负根和数值单位都要回到实际条件检查。

## 来源与核验范围
数学结构来自已经保存的底本；原始段落和答案范围均由源文件哈希及位置绑定。下列改编未复用原插图与历史人物评价。保留原书美国公有领域来源标记，不扩大为全球权利结论。

- Henry Ernest Dudeney. Amusements in Mathematics, problem 9. DeepTutor independently rewritten mathematical task and explanation; original narrative and illustrations not reproduced. Source SHA256 7e52015850ff1a25cbba577911e2648d7ee200d2f15adbe05c8adf65776543d3.
  来源：https://www.gutenberg.org/ebooks/16713 | Problem 9 | source line 406
  原始记录：a7c40d8107fb63376964c0919dc3068e24ea7cab9cfe9aca6606ef7ffeaf0140

- Henry Ernest Dudeney. Amusements in Mathematics, problem 11. DeepTutor independently rewritten mathematical task and explanation; original narrative and illustrations not reproduced. Source SHA256 7e52015850ff1a25cbba577911e2648d7ee200d2f15adbe05c8adf65776543d3.
  来源：https://www.gutenberg.org/ebooks/16713 | Problem 11 | source line 428
  原始记录：8a3f33f653256d72f94bd6e229b3ff607b8a2ac1d595dc246db427c827478be4

- Henry Ernest Dudeney. Amusements in Mathematics, problem 14. DeepTutor independently rewritten mathematical task and explanation; original narrative and illustrations not reproduced. Source SHA256 7e52015850ff1a25cbba577911e2648d7ee200d2f15adbe05c8adf65776543d3.
  来源：https://www.gutenberg.org/ebooks/16713 | Problem 14 | source line 467
  原始记录：65de6f3e139986d7aa01fa26b5102166094e6906f072d3d00a899b010bdbdaf5
