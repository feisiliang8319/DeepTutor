# 构造与上界：配对、邻座和圆环

适用：数学拓展讲解。以下内容由本机已有旧书的数学结构独立改写，已做精确计算或有限枚举核验；课程年级、难度和正式测试资格仍待教学审核。用于 Chat 的完整讲解案例，不在 Chat 发起 Quiz，不据此自动认定学生掌握或升级。

## 核心方法
证明“最多”需要两部分：先找到不能超过的上界，再给出达到它的构造。不要把单条邻接、两个邻座组成的无序组合、队友和对手当成同一个约束。

## 讲解案例1：每天换一位伙伴

条件：12位同学A至L每天分成6个二人组，每人每天恰好参加一个组。要求任意两人至多同组一次。最多能安排多少天？给出达到上限的完整安排，并说明为什么没有重复。每天的小组顺序不重要。

结论：最多11天；任一覆盖全部66对且每天每人出现一次的安排均可。

完整推导：每人只有11位不同伙伴，所以至多11天。以下每行是一天：
AL BK CJ DI EH FG
AK LJ BI CH DG EF
AJ KI LH BG CF DE
AI JH KG LF BE CD
AH IG JF KE LD BC
AG HF IE JD KC LB
AF GE HD IC JB KL
AE FD GC HB IL JK
AD EC FB GL HK IJ
AC DB EL FK GJ HI
AB CL DK EJ FI GH
每天12人各出现一次；11天共66对，且没有重复，正好覆盖12人之间的全部66对。因此上限可以达到。可用固定A、其余位置轮转的方法生成。

## 讲解案例2：合作与对手都公平

条件：12位同学A至L参加11轮四人桌面竞赛，每轮分3桌，每桌分成两个二人队对抗。每人每轮只参加一桌。要求任意两人恰好合作一次、恰好互为对手两次。请构造11轮完整安排，并检验每人的合作次数和对手次数。允许给出构造规则和展开表。

结论：存在；每人11次合作覆盖11位伙伴，22次对手接触使其余11人各出现2次。

完整推导：一个完整构造如下，每行是一轮，竖线分隔3桌：
AB 对 IL | EJ 对 GK | FH 对 CD
AC 对 JB | FK 对 HL | GI 对 DE
AD 对 KC | GL 对 IB | HJ 对 EF
AE 对 LD | HB 对 JC | IK 对 FG
AF 对 BE | IC 对 KD | JL 对 GH
AG 对 CF | JD 对 LE | KB 对 HI
AH 对 DG | KE 对 BF | LC 对 IJ
AI 对 EH | LF 对 CG | BD 对 JK
AJ 对 FI | BG 对 DH | CE 对 KL
AK 对 GJ | CH 对 EI | DF 对 LB
AL 对 HK | DI 对 FJ | EG 对 BC
固定A，将B至L循环替换即可生成各轮。逐轮检查每人出现一次；把每队内的无序人对计作合作、两队之间4个人对计作对手。66个合作人对各出现1次，66个对手人对各出现2次。其他满足条件的完整安排同样正确。

## 讲解案例3：左右邻座作为一组

条件：7位同学A至G围坐圆桌。对每个人，把其左右两位邻座看作一个无序的二人组合。允许再次邻接同一个人，但不允许同一位同学在两轮遇到完全相同的邻座组合。最多能安排几轮？请给出达到上限的安排并验证。每行首尾也相邻。

结论：最多15轮；每个人的15种邻座组合各用一次。

完整推导：固定一位同学，其余6人中选2人作邻座，共6×5÷2=15种，所以轮数不超过15。以下15行构造达到上限：
ABCDEFG
ACDBGEF
ADBCFGE
AGBFECD
AFCEGDB
AEDGFBC
ACEBGFD
ADGCFEB
ABFDEGC
AEFDCGB
AGEBDFC
AFGCBED
AEBFCDG
AGCEDBF
AFDGBCE
逐人记录每行左右邻居，将两字母排序后作为无序组合；每个人得到15个不同组合，恰好覆盖全部可能。这里禁止的是邻座二人组合重复，不能误改为任一邻接都不得重复。

## 讲解案例4：十三人的不重复圆环

条件：13位同学编号0至12围成圆环，每个人有两位邻居，左右不区分。同一对人不能在不同轮次再次相邻。最多能安排多少轮？给出一种构造，并说明为什么达到上限。

结论：最多6轮。

完整推导：每个人只有12位可能邻居，每轮用2位，因此至多6轮。构造方法：对步长s＝1、2、3、4、5、6，依次按0、s、2s、…、12s除以13的余数围成一环。13为素数，这13个余数各不相同；每环的邻接差为±s，不同步长的±s集合互不相同，所以各轮没有重复邻接。6轮各13对，共78对，正好覆盖13×12÷2对。

## 教学提醒
从4人或6人的小例子理解约束，再展示完整构造；表格只是一种答案，其他满足条件的构造也有效。

## 来源与核验范围
数学结构来自已经保存的底本；原始段落和答案范围均由源文件哈希及位置绑定。下列改编未复用原插图与历史人物评价。保留原书美国公有领域来源标记，不扩大为全球权利结论。

- Henry Ernest Dudeney. Amusements in Mathematics, problem 264. DeepTutor independently rewritten mathematical task and explanation; original narrative and illustrations not reproduced. Source SHA256 7e52015850ff1a25cbba577911e2648d7ee200d2f15adbe05c8adf65776543d3.
  来源：https://www.gutenberg.org/ebooks/16713 | Problem 264 | source line 6071
  原始记录：f44358ab9bdaf97a5bf1ee8a6b294e06f84cfa79e9ffdcf75bf1a18a52a73167

- Henry Ernest Dudeney. Amusements in Mathematics, problem 265. DeepTutor independently rewritten mathematical task and explanation; original narrative and illustrations not reproduced. Source SHA256 7e52015850ff1a25cbba577911e2648d7ee200d2f15adbe05c8adf65776543d3.
  来源：https://www.gutenberg.org/ebooks/16713 | Problem 265 | source line 6092
  原始记录：8bba17c6aa14288a233818bbe49d1f3bc717a1122091cdfc32f549d196f61e20

- Henry Ernest Dudeney. The Canterbury Puzzles, problem 90. DeepTutor independently rewritten mathematical task and explanation; original narrative and illustrations not reproduced. Source SHA256 02aa60bc6c3b5982246b0e1ef68428a5b9a7b83980938ceb189df51f26a0762a.
  来源：https://www.gutenberg.org/ebooks/27635 | Problem 90 | source line 3741
  原始记录：79fde6ed3d56bd76cc097cd120b26b3b7e1d9e46c163e705614c2378aa9ece0c

- Henry Ernest Dudeney. The Canterbury Puzzles, problem 100. DeepTutor independently rewritten mathematical task and explanation; original narrative and illustrations not reproduced. Source SHA256 02aa60bc6c3b5982246b0e1ef68428a5b9a7b83980938ceb189df51f26a0762a.
  来源：https://www.gutenberg.org/ebooks/27635 | Problem 100 | source line 4025
  原始记录：6001bbee7caed31f341b80c65b0463634fb021ac2385d8f8cec0f944003810b0
