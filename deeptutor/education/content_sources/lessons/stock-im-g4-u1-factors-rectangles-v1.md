# 因数与整数矩形：条件决定方案数

适用：四年级因数与倍数讲解。根据已保存的 IM 第1单元目标整理，例题条件与解答完整，计算已核对；知识点对应、难度与正式测试资格仍待教学审核。用于 Chat 讲解，不在 Chat 发起 Quiz，不据此自动认定掌握或升级。

## 核心方法
用正整数边长把面积问题转成因数对。旋转是否计为新方案、是否允许非整数边长，都必须在题干中明确。

## 讲解案例1：固定宽度能拼哪些面积

条件：用单位正方形拼长方形，宽固定为4个单位，长必须是正整数。列出不超过40平方单位的所有可能面积与对应长度。38平方单位可行吗？再给出两个超过40的可行面积。

结论：长1至10依次对应面积4、8、12、16、20、24、28、32、36、40；38不可行；超过40如44和48。

完整推导：面积=4×长。要求正整数长且面积≤40，得到长只能为1到10，因此列表没有遗漏。38除以4余2，不能用整数长实现；大于40的正倍数仍可行，例如长11、12时面积44、48。

## 讲解案例2：面积与因数对

条件：用36个单位正方形无空隙、无重叠地拼长方形，两边长度为正整数。旋转视为同一种。列出全部边长方案，说明为什么找完较短边后就不必继续。

结论：1×36、2×18、3×12、4×9、6×6，共5种。

完整推导：较短边不超过6，因为两边都大于6时面积就超过36。逐个检查1、2、3、4、5、6，只有1、2、3、4、6能整除36，对应所列因数对。超过6的因数只是把较长边与较短边互换，不能重复计数。

## 讲解案例3：矩形计数必须限定整数边长

条件：Use positive whole-number side lengths measured in unit lengths, and count rotations as the same rectangle. For each area 2, 10, 48, 11, 21, 23, 60, 32, 42, 31 and 56 square units, find the number of distinct rectangles and decide whether the area number is prime or composite. List factor pairs to show that none are missing.

结论：2: 1 rectangle(s), prime; 10: 2 rectangle(s), composite; 48: 5 rectangle(s), composite; 11: 1 rectangle(s), prime; 21: 2 rectangle(s), composite; 23: 1 rectangle(s), prime; 60: 6 rectangle(s), composite; 32: 3 rectangle(s), composite; 42: 4 rectangle(s), composite; 31: 1 rectangle(s), prime; 56: 4 rectangle(s), composite.

完整推导：Use positive whole-number side lengths and count a rotated rectangle only once. For each area n, test potential shorter sides from 1 through floor(√n); a divisor d gives exactly one pair (d,n/d). The complete pairs are: 2: 1×2; 10: 1×10, 2×5; 48: 1×48, 2×24, 3×16, 4×12, 6×8; 11: 1×11; 21: 1×21, 3×7; 23: 1×23; 60: 1×60, 2×30, 3×20, 4×15, 5×12, 6×10; 32: 1×32, 2×16, 4×8; 42: 1×42, 2×21, 3×14, 6×7; 31: 1×31; 56: 1×56, 2×28, 4×14, 7×8. A prime number greater than 1 has only the pair 1×n; a composite number has another factor pair.

## 讲解案例4：用已知乘积支持邻近乘积

条件：已知8×6＝48，求9×6、7×8、9×8。说明怎样用相邻的组数增加或减少一组，而不是每次从头数。

结论：54、56、72。

完整推导：9组6比8组6多一组，所以48+6=54。7组8可由6组8的48再加8得到56。9组8可由10组8的80减一组8得到72。利用交换律把8×6与6×8联系，再按实际份数调整。

## 教学提醒
第3课修订版补齐整数边长限制；原候选保留追溯。第4课为可选乘法练习。

## 来源与核验范围
课时目标参考已保存的 Illustrative Mathematics K–5 Math v.I (2021)，源文件注明 CC BY 4.0；不复用标志或第三方图形。例题与解答为独立编写或对旧候选的明确条件修订，不是官方教师答案或认可。原教材缺失的作答与图形仍保留缺失记录。

- Learning-goal reference: Illustrative Mathematics K–5 Math v.I (2021), Grade 4 Unit 1, lesson 1. DeepTutor authored the Chinese task and independently calculated explanation; not an official IM answer key or endorsement.
  来源：https://curriculum.illustrativemathematics.org/k5/teachers/grade-4/unit-1/ | IM:G4:U1:L1 | retained source line 11
  原始记录：2d60f541407d8860e832225fbbdd4a1c9fb6dee0e1d6839356be5a56def7c0cb

- Learning-goal reference: Illustrative Mathematics K–5 Math v.I (2021), Grade 4 Unit 1, lesson 2. DeepTutor authored the Chinese task and independently calculated explanation; not an official IM answer key or endorsement.
  来源：https://curriculum.illustrativemathematics.org/k5/teachers/grade-4/unit-1/ | IM:G4:U1:L2 | retained source line 458
  原始记录：02e48edba62f3c059542c67ade728e1ba7384f59b06c2c9f9272eeb3c8d66b5d

- Learning-goal reference: Illustrative Mathematics K–5 Math v.I (2021), Grade 4 Unit 1, lesson 3. DeepTutor authored the Chinese task and independently calculated explanation; not an official IM answer key or endorsement.
  来源：https://curriculum.illustrativemathematics.org/k5/teachers/grade-4/unit-1/ | IM:G4:U1:L3 | retained source line 871
  原始记录：cb716cb3f3eb3d441a603195a597047710731ba871b9fc0e532a45991b9b3ec0

- Learning-goal reference: Illustrative Mathematics K–5 Math v.I (2021), Grade 4 Unit 1, lesson 4. DeepTutor authored the Chinese task and independently calculated explanation; not an official IM answer key or endorsement.
  来源：https://curriculum.illustrativemathematics.org/k5/teachers/grade-4/unit-1/ | IM:G4:U1:L4 | retained source line 1289
  原始记录：12d6e99db9c736024d7f8368919417079d48259747acb7f19a79caefe49bea3c
