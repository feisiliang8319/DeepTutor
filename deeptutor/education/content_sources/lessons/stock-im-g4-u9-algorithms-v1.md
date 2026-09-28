# 算法复习：结构、部分积与部分商

适用：四年级综合复习与开放推理讲解。依据本机已有 IM 四年级第9单元课时目标独立编写。以下例题给出完整条件、答案和推导，计算已核对；知识点对应、难度和正式测试资格仍待教学审核。用于 Chat 讲解，不在 Chat 发起 Quiz，不据此自动认定掌握或升级。

## 核心方法
竖式与拆分方法描述同一个数量关系。接近整值时可补足求差，乘法拆分保持无遗漏，除法还要核对余数范围。

## 讲解案例1：退位与补足都能求差

条件：计算70000−39875。除竖式外，也可先从39875补到40000，再补到70000。写出两个补数，并说明为什么相加就是答案。

结论：先补125，再补30000；差30125。

完整推导：从较小数一路增加到较大数，总共增加量就是两数之差。39875+125=40000，40000+30000=70000，所以差125+30000=30125。检验39875+30125=70000；这一方法利用接近整万的结构，避免连续跨零退位。

## 讲解案例2：把两行乘法展开看

条件：计算58×24。先写两行部分积58×20、58×4，再各自拆成十位与个位的乘积，说明两种记录为何相等。

结论：1160+232＝1392；也等于1000+160+200+32。

完整推导：24=20+4，得到1160与232。再用58=50+8，第一部分为50×20+8×20=1000+160，第二部分为50×4+8×4=200+32。四项覆盖全部乘积，重新分组不改变总和。

## 讲解案例3：部分商与最终余数

条件：求1847÷7的整数商和余数。先扣除7×200、7×60、7×3，记录各次剩余并验证结果。

结论：依次余447、27、6；商263余6。

完整推导：1847−1400=447，447−420=27，27−21=6。部分商200+60+3=263，余6小于7。检查7×263+6=1847，同时满足还原关系与余数范围。

## 教学提醒
计算过程与结果都需要对照单位和等式检查，单凭最终数值接近不能确认推理正确。

## 来源与核验范围
学习目标参考已保存的 Illustrative Mathematics K–5 Math v.I (2021)，源文件注明 CC BY 4.0。例题为 DeepTutor 新编，不是原书官方教师答案或认可，不复用原图或标志。原教材未收录的作答与图形仍保留缺失标记。

- Learning-goal reference: Illustrative Mathematics K–5 Math v.I (2021), Grade 4 Unit 9, lesson 4. DeepTutor authored the Chinese task and independently calculated explanation; not an official IM answer key or endorsement.
  来源：https://curriculum.illustrativemathematics.org/k5/teachers/grade-4/unit-9/ | IM:G4:U9:L4 | retained source line 1192
  原始记录：221571136267bd20152b5698c67c7c96e6ce038227d05fe71fa1ffcc8e13c55b

- Learning-goal reference: Illustrative Mathematics K–5 Math v.I (2021), Grade 4 Unit 9, lesson 5. DeepTutor authored the Chinese task and independently calculated explanation; not an official IM answer key or endorsement.
  来源：https://curriculum.illustrativemathematics.org/k5/teachers/grade-4/unit-9/ | IM:G4:U9:L5 | retained source line 1606
  原始记录：fa401b4108ff31ab0a6e406934fb8892eb14abe965304f0e939eaaa1d798c545

- Learning-goal reference: Illustrative Mathematics K–5 Math v.I (2021), Grade 4 Unit 9, lesson 6. DeepTutor authored the Chinese task and independently calculated explanation; not an official IM answer key or endorsement.
  来源：https://curriculum.illustrativemathematics.org/k5/teachers/grade-4/unit-9/ | IM:G4:U9:L6 | retained source line 2011
  原始记录：5c3da1c1371dd37f38fe4776e1c4642d9230e4d9d9cbb69a2a6308635f00dd11
