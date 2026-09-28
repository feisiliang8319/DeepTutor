# 明确规则的数列与图案

适用：四年级规律与多位数乘除讲解。依据本机已有 IM 四年级第6单元课时目标独立编写。以下例题给出完整条件、答案和推导，计算已核对；知识点对应、难度和正式测试资格仍待教学审核。用于 Chat 讲解，不在 Chat 发起 Quiz，不据此自动认定掌握或升级。

## 核心方法
先明确规则、起点与位置，再计算后续项。重复图案可按一组的长度计算整组与余位；增长图案要避免重复计数共有部分。

## 讲解案例1：会长大的十字图案

条件：用方块排十字：中央1块，四个方向各伸出n块，四条臂互不重叠且不含中央块；第n幅就是这个图案。第1、2、3、6幅分别多少块？写出第n幅的总数，并求第10幅。

结论：依次5、9、13、25块；第n幅4n+1块；第10幅41块。

完整推导：四条臂各n块，合计4n，再加只计一次的中央1块，共4n+1。每幅到下一幅，四条臂各增加1块，所以总数每次加4。第6幅为4×6+1=25，第10幅为41。完整规则已给出，不是仅凭前三个数猜唯一规律。

## 讲解案例2：重复图案与位置

条件：从第1个开始按“红、蓝、蓝”不断重复。第31个、第32个、第100个各是什么颜色？前30个中红、蓝各有几个？

结论：红、蓝、红；前30个红10个、蓝20个。

完整推导：每3个为一组，第一位红、第二三位蓝。31=3×10+1，所以回到下一组第一位；32余2为蓝；100=3×33+1为红。前30个正好10组，每组1红2蓝，共10红20蓝。

## 讲解案例3：数列规则要说清楚

条件：一个数列第1项为7，以后每项都比前一项多6。写出前5项及第10项。说明所有项为什么都是奇数。

结论：前5项7、13、19、25、31；第10项61；奇数加偶数仍是奇数。

完整推导：第n项是在7上加n−1次6，等于7+6(n−1)，所以第10项7+54=61。6是偶数，从奇数7出发每次加偶数不会改变奇偶性。必须数9次增加，不能把第10项算成加10次6。

## 讲解案例4：倍增数列的特征

条件：从3开始，每一步把前一项乘2。写出前6项，说明每项是否都是3的倍数；为什么除第一项外其余项都是偶数？

结论：3、6、12、24、48、96；都是3的倍数；第二项起都含因数2。

完整推导：第n项可以写成3乘n−1个2。原来的因数3始终保留，因此每项都能被3整除。从第2项开始至少乘过一次2，故为偶数。这里按题目明确给出的倍增规则分析，不能把“同样几个开头数”当作唯一规则的证明。

## 教学提醒
有限几个数不唯一决定无限数列，因此每道例题都明确给出生成规则。

## 来源与核验范围
学习目标参考已保存的 Illustrative Mathematics K–5 Math v.I (2021)，源文件注明 CC BY 4.0。例题为 DeepTutor 新编，不是原书官方教师答案或认可，不复用原图或标志。原教材未收录的作答与图形仍保留缺失标记。

- Learning-goal reference: Illustrative Mathematics K–5 Math v.I (2021), Grade 4 Unit 6, lesson 1. DeepTutor authored the Chinese task and independently calculated explanation; not an official IM answer key or endorsement.
  来源：https://curriculum.illustrativemathematics.org/k5/teachers/grade-4/unit-6/ | IM:G4:U6:L1 | retained source line 11
  原始记录：b4ea7652fee76036d341fd052a5401a548f3e962965e2379d267a36259c9cab0

- Learning-goal reference: Illustrative Mathematics K–5 Math v.I (2021), Grade 4 Unit 6, lesson 2. DeepTutor authored the Chinese task and independently calculated explanation; not an official IM answer key or endorsement.
  来源：https://curriculum.illustrativemathematics.org/k5/teachers/grade-4/unit-6/ | IM:G4:U6:L2 | retained source line 423
  原始记录：f96de6ba2df4e0b813d12fcddfec3da557a08a248a7900dfd96e0eb1df45eede

- Learning-goal reference: Illustrative Mathematics K–5 Math v.I (2021), Grade 4 Unit 6, lesson 3. DeepTutor authored the Chinese task and independently calculated explanation; not an official IM answer key or endorsement.
  来源：https://curriculum.illustrativemathematics.org/k5/teachers/grade-4/unit-6/ | IM:G4:U6:L3 | retained source line 834
  原始记录：000dd3bd2f94bfaf1554e30e743471e39fdc5c125cb9d43e4ab7959ad911a9b8

- Learning-goal reference: Illustrative Mathematics K–5 Math v.I (2021), Grade 4 Unit 6, lesson 4. DeepTutor authored the Chinese task and independently calculated explanation; not an official IM answer key or endorsement.
  来源：https://curriculum.illustrativemathematics.org/k5/teachers/grade-4/unit-6/ | IM:G4:U6:L4 | retained source line 1309
  原始记录：fecc38bc7b00abb3b086839cb9ec8c0bcbff9bade0439f22393db95dc504c155
