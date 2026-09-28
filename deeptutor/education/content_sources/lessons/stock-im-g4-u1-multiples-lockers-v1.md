# 倍数与翻转游戏：先读完整规则

适用：四年级因数与倍数讲解。根据已保存的 IM 第1单元目标整理，例题条件与解答完整，计算已核对；知识点对应、难度与正式测试资格仍待教学审核。用于 Chat 讲解，不在 Chat 发起 Quiz，不据此自动认定掌握或升级。

## 核心方法
装满包装用整除与公倍数判断；更衣柜触碰规则把学生编号与柜号的因数关联，初始状态和每次操作决定最终开关。

## 讲解案例1：恰好装满与同时满足两个包装

条件：一种盒子每盒6枚徽章，另一种每盒8枚。若只选一种盒子并且每盒装满，30枚能分别用哪一种？另一个独立问题：总徽章数至少30枚，要求既能用6枚盒装满、也能用8枚盒装满，最少总数是多少？

结论：30枚可用5个6枚盒，不能恰用8枚盒；独立问题最少48枚。

完整推导：30能被6整除，不能被8整除。两种包装都恰好装满的总数是6与8的公倍数，最小正公倍数为24。独立问题还要求至少30，所以24不够，下一公倍数48符合。条件“至少30”不能在求公倍数时丢掉。

## 讲解案例2：更衣柜游戏：把规则完整交给解题者

条件：There are 20 lockers numbered 1 through 20 and 20 students numbered 1 through 20. All lockers start closed. Students take turns in numerical order. Student d visits exactly the lockers whose numbers are positive multiples of d (starting at locker d), touching each such locker once; every touch changes a closed locker to open or an open locker to closed. Which lockers do students 3 and 5 touch? How many students touch locker 17? Which lockers are touched exactly twice, exactly three times, and the greatest number of times? Explain using factors. Optional: which lockers remain open after student 20?

结论：Student 3: 3,6,9,12,15,18. Student 5: 5,10,15,20. Locker 17: two students (1 and 17). Exactly two touches: 2,3,5,7,11,13,17,19. Exactly three touches: 4,9. Most touches: 12,18,20, each six times. Optional final answer: 1,4,9,16 remain open.

完整推导：Student d touches exactly the locker numbers divisible by d. Therefore a locker n is touched once for each positive divisor of n. Primes have two divisors. 4 has divisors 1,2,4 and 9 has 1,3,9. The complete divisor counts for 1–20 show a maximum of six for 12,18,20. All lockers start closed and every touch toggles the state, so an odd number of divisors leaves a locker open. Divisors pair as d and n/d except at a square root, so precisely the perfect squares 1,4,9,16 stay open.

## 讲解案例3：因数与倍数的方向

条件：列出24的所有正因数及前5个正倍数。选一个因数写出两句互相对应的“因数”和“倍数”陈述，并说明为什么不能直接颠倒两词。

结论：因数1、2、3、4、6、8、12、24；倍数24、48、72、96、120。例如3是24的因数，24是3的倍数，因为3×8＝24。

完整推导：因数能把24整分，用因数对1×24、2×12、3×8、4×6列完。倍数来自24乘正整数1至5。3是24的因数不意味着3是24的倍数；关系方向由乘法等式决定，1和24本身也都是24的因数。

## 讲解案例4：矩形拼画中的总量

条件：一张12厘米乘8厘米的长方形画纸，用一条与8厘米边平行的直线分为宽5厘米和宽7厘米的两个长方形。求两块面积、总面积和原画纸周长。切分线是否应加到原画纸的外周长中？

结论：两块面积40、56平方厘米，总面积96平方厘米；外周长40厘米；内部切分线不计入外周长。

完整推导：两块共用高度8，面积5×8=40、7×8=56，总面积96与12×8一致，体现(5+7)×8。外周长2×(12+8)=40厘米。切分改变内部图案，不改变外边界；不能因多画一条线就增加外周长。

## 教学提醒
更衣柜修订版包含编号、访问倍数、全部初始关闭、逐次翻转和轮次顺序。第8课保留为可选矩形拼画拓展。

## 来源与核验范围
课时目标参考已保存的 Illustrative Mathematics K–5 Math v.I (2021)，源文件注明 CC BY 4.0；不复用标志或第三方图形。例题与解答为独立编写或对旧候选的明确条件修订，不是官方教师答案或认可。原教材缺失的作答与图形仍保留缺失记录。

- Learning-goal reference: Illustrative Mathematics K–5 Math v.I (2021), Grade 4 Unit 1, lesson 5. DeepTutor authored the Chinese task and independently calculated explanation; not an official IM answer key or endorsement.
  来源：https://curriculum.illustrativemathematics.org/k5/teachers/grade-4/unit-1/ | IM:G4:U1:L5 | retained source line 1654
  原始记录：5f277a4ebd06bb10a36d195c1e88818a01e23553f792d9e067256c130257ec36

- Learning-goal reference: Illustrative Mathematics K–5 Math v.I (2021), Grade 4 Unit 1, lesson 6. DeepTutor authored the Chinese task and independently calculated explanation; not an official IM answer key or endorsement.
  来源：https://curriculum.illustrativemathematics.org/k5/teachers/grade-4/unit-1/ | IM:G4:U1:L6 | retained source line 2012
  原始记录：9a8b385f94de1fe78700ecf78b6cb74982a84b95e6b48bdc7d04fe4e3f264692

- Learning-goal reference: Illustrative Mathematics K–5 Math v.I (2021), Grade 4 Unit 1, lesson 7. DeepTutor authored the Chinese task and independently calculated explanation; not an official IM answer key or endorsement.
  来源：https://curriculum.illustrativemathematics.org/k5/teachers/grade-4/unit-1/ | IM:G4:U1:L7 | retained source line 2392
  原始记录：023e670ada2bc54370f35327242732c7ed587ec2c3a4a87ffc754e662e6c913a

- Learning-goal reference: Illustrative Mathematics K–5 Math v.I (2021), Grade 4 Unit 1, lesson 8. DeepTutor authored the Chinese task and independently calculated explanation; not an official IM answer key or endorsement.
  来源：https://curriculum.illustrativemathematics.org/k5/teachers/grade-4/unit-1/ | IM:G4:U1:L8 | retained source line 2811
  原始记录：d7bf955d3da83ceabd29bd4833d0d34ef6bbba99d21506986e5bbef5ee8c534f
