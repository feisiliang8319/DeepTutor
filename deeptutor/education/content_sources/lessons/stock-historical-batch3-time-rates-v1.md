# 时间与变化率：先确定计量基准

适用：数学拓展讲解。以下内容由本机已有旧书的数学结构独立改写，已做精确计算或有限枚举核验；课程年级、难度和正式测试资格仍待教学审核。用于 Chat 的完整讲解案例，不在 Chat 发起 Quiz，不据此自动认定学生掌握或升级。

## 核心方法
区分时刻与时长、真实时间与手表显示时间、固定初值与每次变化后的当前基数。把条件写成等式或乘法因子，可以避免靠直觉抵消百分比。

## 讲解案例1：从中午开始计时

条件：现在位于今天中午12:00至明天中午12:00之间。把“今天中午到现在的时长”的四分之一，加上“现在到明天中午的时长”的二分之一，结果恰好等于“今天中午到现在的时长”。现在是几点？请用24小时制作答，并说明为什么只有一个答案。

结论：今天21:36。

完整推导：设今天中午以后经过t小时，则剩下24−t小时。条件为t/4+(24−t)/2=t，两边乘4得t+48−2t=4t，故5t=48，t=9.6小时＝9小时36分。中午加9小时36分是21:36。这个一次方程只有一个解，且0≤t<24，符合时间范围。代回：2小时24分+7小时12分＝9小时36分。

## 讲解案例2：手表走快了多少

条件：一只12小时制指针手表匀速走动，分针的角速度始终是时针的12倍。用另一只准确计时器观察，手表的两根指针每隔65分钟真实时间重合一次。这只手表走快还是走慢？每经过真实的1小时，手表比准确时间多走或少走多少分钟？请给出精确分数。

结论：走快；每真实1小时多走60/143分钟，约25.17秒。

完整推导：准确手表的分针每分钟转6°，时针每分钟转1/2°，相对速度11/2°，所以相邻重合应相隔720/11分钟。现在只过65分钟就完成同样的相对转动，走速为(720/11)÷65＝144/143倍。每真实60分钟，显示时间增加60×144/143分钟，故多走60/143分钟。若65分钟读自这只手表本身，则与正常12:1传动比矛盾；题目明确用真实时间测量。

## 讲解案例3：先增加再减少

条件：一个数值计量器初始读数为64。它要执行6次操作，其中3次把当时读数增加50%，另3次把当时读数减少50%；读数按精确数值计算，允许小数，不作四舍五入。6次操作可以任意排列。最终读数是多少？顺序会不会影响结果？再把结论推广到各执行k次，其中k为正整数。

结论：最终27；顺序不影响。各k次时，最终为64×(3/4)^k，小于64。

完整推导：增加50%对应乘3/2，减少50%对应乘1/2。任意顺序的乘积都是64×(3/2)³×(1/2)³＝64×27/64＝27。乘法交换律允许把因子重新分组，每对操作的因子乘积是3/4。各k次便得64×(3/4)^k。增加和减少的百分数虽然相等，作用的基数不同，不能简单相互抵消。

## 教学提醒
使用精确分数后再给近似数；百分比作用于当前读数，先增加50%再减少50%并不会回到原值。

## 来源与核验范围
数学结构来自已经保存的底本；原始段落和答案范围均由源文件哈希及位置绑定。下列改编未复用原插图与历史人物评价。保留原书美国公有领域来源标记，不扩大为全球权利结论。

- Henry Ernest Dudeney. Amusements in Mathematics, problem 57. DeepTutor independently rewritten mathematical task and explanation; original narrative and illustrations not reproduced. Source SHA256 7e52015850ff1a25cbba577911e2648d7ee200d2f15adbe05c8adf65776543d3.
  来源：https://www.gutenberg.org/ebooks/16713 | Problem 57 | source line 1303
  原始记录：fbb9d70eeb1ac8aaa6ee0cc7dc998ffe306d208e9d50819762e7a4ed601c7e71

- Henry Ernest Dudeney. Amusements in Mathematics, problem 59. DeepTutor independently rewritten mathematical task and explanation; original narrative and illustrations not reproduced. Source SHA256 7e52015850ff1a25cbba577911e2648d7ee200d2f15adbe05c8adf65776543d3.
  来源：https://www.gutenberg.org/ebooks/16713 | Problem 59 | source line 1320
  原始记录：a6b04cc2466961e6a9a03160b6718b5aa51a5a2c44d202aabc57d2d3a587ed31

- Henry Ernest Dudeney. Amusements in Mathematics, problem 121. DeepTutor independently rewritten mathematical task and explanation; original narrative and illustrations not reproduced. Source SHA256 7e52015850ff1a25cbba577911e2648d7ee200d2f15adbe05c8adf65776543d3.
  来源：https://www.gutenberg.org/ebooks/16713 | Problem 121 | source line 2379
  原始记录：fd9fb34fcdee6e3870658c7411c7a677acc43623dd088a4c9633ba79e86d736f
