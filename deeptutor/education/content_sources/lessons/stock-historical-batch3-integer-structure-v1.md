# 整数结构：平方条件、数字移位与同余

适用：数学拓展讲解。以下内容由本机已有旧书的数学结构独立改写，已做精确计算或有限枚举核验；课程年级、难度和正式测试资格仍待教学审核。用于 Chat 的完整讲解案例，不在 Chat 发起 Quiz，不据此自动认定学生掌握或升级。

## 核心方法
从相同余数得到差的公因数，从数字移位得到位值方程，从两个平方条件得到有界整数枚举。最小或最大都需要排除更优解的理由。

## 讲解案例1：相邻的两个平方条件

条件：找出大于48的三个最小正整数N，使N+1和N/2+1都是整数的平方。除了写出N，还要给出相应平方根，并说明怎样证明没有遗漏更小的数。可以用短程序或系统枚举，但须说明枚举范围为何足够。

结论：N＝1680、57120、1940448；相应平方根(a,b)＝(41,29)、(239,169)、(1393,985)。

完整推导：令N+1=a²、N/2+1=b²，则N=2(b²−1)，且a²=2b²−1。逐个枚举整数b，从2到985，检查2b²−1是否为完全平方数，得到N＝48、1680、57120、1940448。去掉48即得所求。N随正整数b严格递增，所以所有小于第三个答案的N都对应b≤985，枚举覆盖了全部较小可能。验证：41²=1681、29²=841；239²=57121、169²=28561；1393²=1940449、985²=970225。

## 讲解案例2：把首位3移到最后

条件：寻找至少两位、首位为3的最小正整数N。把首位的3移到个位，其余数字顺序不变，所得整数恰好为原数的3/2。请给出N并证明没有位数更短的解。

结论：N＝3529411764705882；移位后为5294117647058823，等于N×3/2。

完整推导：设首位后还有k位，用x表示这k位的数值（允许其中有前导零），则N=3×10^k+x，移位数为10x+3。由2(10x+3)=3(3×10^k+x)得17x=9×10^k−6。逐个检查k=1至15，9×10^k−6除以17的余数依次为16、10、1、13、14、7、5、2、6、12、4、9、8、15、0。首次整除为k=15，x=529411764705882，且0≤x<10^15，所以N如上。所有更短位数均不满足整除条件，任意更长位数的正整数都更大。

## 讲解案例3：余数相同的最大除数

条件：把701、1059、1417、2312分别除以同一个正整数d，得到的四个余数完全相同，且余数采用0≤r<d的通常约定。求最大的d及共同余数，并说明最大性的理由。

结论：d＝179，共同余数164。

完整推导：余数相同意味着各数与701的差都能被d整除，因此d同时整除358、716、1611。它们的最大公约数为179：716=2×358，1611=4×358+179，358=2×179。故任何可行d都不超过179。代回四数：701=3×179+164，1059=5×179+164，1417=7×179+164，2312=12×179+164，且164<179，所以179可行且最大。

## 教学提醒
区分找到一个答案和证明最优；枚举必须写明变量、范围与覆盖理由。16位移位数属于高阶拓展，不应仅凭放入课程容器就视作四年级必修。

## 来源与核验范围
数学结构来自已经保存的底本；原始段落和答案范围均由源文件哈希及位置绑定。下列改编未复用原插图与历史人物评价。保留原书美国公有领域来源标记，不扩大为全球权利结论。

- Henry Ernest Dudeney. Amusements in Mathematics, problem 114. DeepTutor independently rewritten mathematical task and explanation; original narrative and illustrations not reproduced. Source SHA256 7e52015850ff1a25cbba577911e2648d7ee200d2f15adbe05c8adf65776543d3.
  来源：https://www.gutenberg.org/ebooks/16713 | Problem 114 | source line 2255
  原始记录：5638350035d5cb21e76ed297af5c7e2c2c9d78f66dbaa0d746967befdbdacdd0

- Henry Ernest Dudeney. Amusements in Mathematics, problem 126. DeepTutor independently rewritten mathematical task and explanation; original narrative and illustrations not reproduced. Source SHA256 7e52015850ff1a25cbba577911e2648d7ee200d2f15adbe05c8adf65776543d3.
  来源：https://www.gutenberg.org/ebooks/16713 | Problem 126 | source line 2439
  原始记录：1613596d167fc8f504aa4995d219c8bd7ac0f7176b9f8bca78019107e7011a8d

- Henry Ernest Dudeney. Amusements in Mathematics, problem 127. DeepTutor independently rewritten mathematical task and explanation; original narrative and illustrations not reproduced. Source SHA256 7e52015850ff1a25cbba577911e2648d7ee200d2f15adbe05c8adf65776543d3.
  来源：https://www.gutenberg.org/ebooks/16713 | Problem 127 | source line 2454
  原始记录：ef2a251b2df04a6bd9bde9390192e7890b465efd4eba3d51b77181fb56791fe4
