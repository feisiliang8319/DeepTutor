# 整数条件：从方程到完整解集

适用：数学拓展讲解。以下内容由本机已有旧书的数学结构独立改写，已做精确计算或有限枚举核验；课程年级、难度和正式测试资格仍待教学审核。用于 Chat 的完整讲解案例，不在 Chat 发起 Quiz，不据此自动认定学生掌握或升级。

## 核心方法
把数量、价格和交换条件写成方程；正整数约束、独立设想和下界必须明确。用余数缩小范围，再用覆盖所有可能值的枚举证明唯一或完整。

## 讲解案例1：三种贴纸恰好用完积分

条件：甲、乙、丙三种贴纸每张分别需要4、2、5积分。用120积分恰好买完，三种都至少买1张，且乙种张数是甲种的6倍。各买了多少张？请证明只有一种买法。

结论：甲5张、乙30张、丙8张。

完整推导：设甲x张，乙6x张，丙z张。总价为4x+2×6x+5z=120，即16x+5z=120。按除以5的余数看，x必须是5的倍数；又因x、z均为正整数，1≤x≤7，所以只能x=5。于是z=(120−80)/5=8，乙30张。代回20+60+40=120，三种均为正数，所以答案存在且唯一。

## 讲解案例2：三个独立的交换设想

条件：甲、乙、丙三个小组各有一些积木。以下每个设想都从原来的数量单独开始，不能接着上一个设想做。①乙给甲6块，同时甲给乙1块，之后甲的数量是乙的2倍。②丙给乙14块，同时乙给丙1块，之后乙的数量是丙的3倍。③甲给丙4块，同时丙给甲1块，之后丙的数量是甲的6倍。求三个小组原来各有多少块，并核对每次交换都确实拿得出积木。

结论：甲7块、乙11块、丙21块。

完整推导：用J、H、D表示甲、乙、丙的原数。三句话给出J+5=2(H−5)、H+13=3(D−13)、D+3=6(J−3)。因此H=(J+15)/2，D=6J−21。代入第二式得(J+15)/2=18J−115，于是35J=245，J=7，H=11，D=21。三次分别得到(甲12,乙6)、(乙24,丙8)、(丙24,甲4)，均满足倍数关系；原来乙有11≥6、丙有21≥14、甲有7≥4，另一个小组也都能拿出1块。线性代入确定唯一解。

## 讲解案例3：两种材料包的完整清单

条件：A材料包每包3积分，B材料包每包5积分。恰好花110积分，至少买1包A且至少买2包B。共有多少种购买数量组合？请全部列出并证明没有遗漏。

结论：6种：(A,B)＝(5,19)、(10,16)、(15,13)、(20,10)、(25,7)、(30,4)。

完整推导：设购买a包A、b包B，有3a+5b=110，a≥1，b≥2。除以5看余数可知a是5的倍数；由b≥2可得3a≤100，所以1≤a≤33。可行a只能为5、10、15、20、25、30，对应b为19、16、13、10、7、4。这6组全部符合条件，因此无遗漏。若题目允许B只有1包，还会多出(35,1)，所以不能靠日常语言的单复数暗猜数量限制。

## 教学提醒
三个交换设想都从原库存开始。至少两包是数学条件，不能靠语言中的单复数猜测。每次求出答案都要代回条件。

## 来源与核验范围
数学结构来自已经保存的底本；原始段落和答案范围均由源文件哈希及位置绑定。下列改编未复用原插图与历史人物评价。保留原书美国公有领域来源标记，不扩大为全球权利结论。

- Henry Ernest Dudeney. Amusements in Mathematics, problem 1. DeepTutor independently rewritten mathematical task and explanation; original narrative and illustrations not reproduced. Source SHA256 7e52015850ff1a25cbba577911e2648d7ee200d2f15adbe05c8adf65776543d3.
  来源：https://www.gutenberg.org/ebooks/16713 | Problem 1 | source line 297
  原始记录：1efa782ad00248377efe1f80d5b56ef294ad76b162bf2a25df9e35c32e085b25

- Henry Ernest Dudeney. Amusements in Mathematics, problem 3. DeepTutor independently rewritten mathematical task and explanation; original narrative and illustrations not reproduced. Source SHA256 7e52015850ff1a25cbba577911e2648d7ee200d2f15adbe05c8adf65776543d3.
  来源：https://www.gutenberg.org/ebooks/16713 | Problem 3 | source line 333
  原始记录：9b823bb409ad0d87bd0958725457aa882437287471661af1770b74e2db78ddb8

- Henry Ernest Dudeney. Amusements in Mathematics, problem 6. DeepTutor independently rewritten mathematical task and explanation; original narrative and illustrations not reproduced. Source SHA256 7e52015850ff1a25cbba577911e2648d7ee200d2f15adbe05c8adf65776543d3.
  来源：https://www.gutenberg.org/ebooks/16713 | Problem 6 | source line 374
  原始记录：41c0131dbe6875636adeb1ef1c5decd1922b762c96cf2196f61d2dab3f397bd2
