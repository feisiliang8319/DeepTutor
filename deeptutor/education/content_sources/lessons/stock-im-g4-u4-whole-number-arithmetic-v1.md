# 整数加减：进位、跨零退位与验算

适用：四年级小数、位值与多位数运算讲解。依据本机已有 IM 四年级第4单元课时目标独立编写。以下例题给出完整条件、答案和推导，计算已核对；知识点对应、难度和正式测试资格仍待教学审核。用于 Chat 讲解，不在 Chat 发起 Quiz，不据此自动认定掌握或升级。

## 核心方法
竖式对齐的是相同计数单位。进位与退位是保持总量不变的重新组合；减法可以用加回原数来检验。

## 讲解案例1：进位加法与退位减法

条件：计算48576+27648和48576−27648。按数位对齐，说明加法中至少一次进位，并用另一种运算检验减法答案。

结论：和为76224，差为20928。

完整推导：加法个位6+8=14，写4向十位进1；十位7+4+1=12，写2向百位进1；继续逐位得76224。减法逐位退位得20928。验算20928+27648=48576，可检查退位后是否漏减。每次进位或退位都是相邻数位十进关系的重新组合。

## 讲解案例2：连续退位仍要保持总量

条件：计算7204−3686。把7204重新分组为6000+1100+90+14，再分位相减，并说明这个展开式为何仍等于原数。

结论：3518。

完整推导：6000+1100+90+14=7204，所以重新分组没有改变总量。3686=3000+600+80+6；对应相减得3000+500+10+8=3518。验算3518+3686=7204。这里11个百、9个十和14个一是计算中间的组合，不是把原数字直接拼成新数。

## 讲解案例3：多次进退位的六位数运算

条件：先计算486759+278685，再用900000减去所得的和。写出两个结果，并用加法检查最终差。

结论：和为765444；最终差为134556。

完整推导：逐位相加并处理进位得到765444。然后900000−765444=134556，需要跨越多个0重新分组。检查765444+134556=900000，且原两个加数相加确为765444，两个步骤都吻合。

## 讲解案例4：跨零退位的每一位

条件：计算500000−278946。用400000+90000+9000+900+90+10表示被减数，再逐项减去278946的各位值，并检查总和。

结论：221054。

完整推导：重新分组之和仍为500000。依次相减：(400000−200000)+(90000−70000)+(9000−8000)+(900−900)+(90−40)+(10−6)=200000+20000+1000+0+50+4=221054。这里百位结果为0，写答案时必须保留。验算221054+278946=500000。

## 讲解案例5：多步骤大数问题

条件：图书馆原有128450册书，新购37865册，同时移出9867册破损书。现在多少册？若书架可放160000册，还能放多少册？

结论：现有156448册，还能放3552册。

完整推导：先把新购书加进来：128450+37865=166315。再减去移出书：166315−9867=156448。剩余容量160000−156448=3552。检查现有量加剩余容量等于160000；不能把移出书也当作新增，或忽略中间操作的方向。

## 教学提醒
跨多个0退位时写清每位变成多少，答案中间的0也必须保留。第23课保留为可选情境活动参考。

## 来源与核验范围
学习目标参考已保存的 Illustrative Mathematics K–5 Math v.I (2021)，源文件注明 CC BY 4.0。例题为 DeepTutor 新编，不是原书官方教师答案或认可，不复用原图或标志。原教材未收录的作答与图形仍保留缺失标记。

- Learning-goal reference: Illustrative Mathematics K–5 Math v.I (2021), Grade 4 Unit 4, lesson 18. DeepTutor authored the Chinese task and independently calculated explanation; not an official IM answer key or endorsement.
  来源：https://curriculum.illustrativemathematics.org/k5/teachers/grade-4/unit-4/ | IM:G4:U4:L18 | retained source line 7365
  原始记录：275829f4cbea2909e9a168b422fff9f80f82bd0ab63850359e26cb9e9562a252

- Learning-goal reference: Illustrative Mathematics K–5 Math v.I (2021), Grade 4 Unit 4, lesson 19. DeepTutor authored the Chinese task and independently calculated explanation; not an official IM answer key or endorsement.
  来源：https://curriculum.illustrativemathematics.org/k5/teachers/grade-4/unit-4/ | IM:G4:U4:L19 | retained source line 7724
  原始记录：44e78e0ef540203a211a5681409adc01ab3f4ba3981e837524ea0d84ec358a76

- Learning-goal reference: Illustrative Mathematics K–5 Math v.I (2021), Grade 4 Unit 4, lesson 20. DeepTutor authored the Chinese task and independently calculated explanation; not an official IM answer key or endorsement.
  来源：https://curriculum.illustrativemathematics.org/k5/teachers/grade-4/unit-4/ | IM:G4:U4:L20 | retained source line 8121
  原始记录：3b59dca98ca70131f3cfa490ca70f9b224d516fffa170e5106aa4a6b6cd30f44

- Learning-goal reference: Illustrative Mathematics K–5 Math v.I (2021), Grade 4 Unit 4, lesson 21. DeepTutor authored the Chinese task and independently calculated explanation; not an official IM answer key or endorsement.
  来源：https://curriculum.illustrativemathematics.org/k5/teachers/grade-4/unit-4/ | IM:G4:U4:L21 | retained source line 8508
  原始记录：726437fed7012022a0679856d448f38f3dc6cf974dd60c94113718dbaa31eb2e

- Learning-goal reference: Illustrative Mathematics K–5 Math v.I (2021), Grade 4 Unit 4, lesson 22. DeepTutor authored the Chinese task and independently calculated explanation; not an official IM answer key or endorsement.
  来源：https://curriculum.illustrativemathematics.org/k5/teachers/grade-4/unit-4/ | IM:G4:U4:L22 | retained source line 8888
  原始记录：57e6f01598498416800c9749e7a6f338da5e0377521cbf6a04dc646fb9def852
