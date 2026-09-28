# 比较与取整：先找边界，再看距离

适用：四年级小数、位值与多位数运算讲解。依据本机已有 IM 四年级第4单元课时目标独立编写。以下例题给出完整条件、答案和推导，计算已核对；知识点对应、难度和正式测试资格仍待教学审核。用于 Chat 讲解，不在 Chat 发起 Quiz，不据此自动认定掌握或升级。

## 核心方法
比较整数从最高不同位判断；取整先找两侧相邻整倍数，再比较距离。遇到恰好一半时按题目约定处理，每次应使用原数。

## 讲解案例1：从最高不同位比较

条件：比较305099和350009，填>、=或<，说明应先比较哪一个数位。能否因为第一个数后面的99更大就认定它更大？

结论：305099<350009；十万位相同，先在万位分出大小。

完整推导：两数十万位都是3。往右看万位，前者是0，后者是5，已经确定后者更大。较低数位的差不能抵消5个万的差距，所以不能只比较末尾的99和09。

## 讲解案例2：排序时逐位核对

条件：把401080、410008、400810、401008从小到大排列，说明中间两个数怎样比较。

结论：400810<401008<401080<410008。

完整推导：先从十万位、万位、千位依次比较。400810的千位为0，小于万位同为0且千位为1的两个数；410008的万位为1，最大。401008与401080前四位相同，十位分别为0、8，所以401008较小。

## 讲解案例3：先找两侧的整倍数

条件：对267300，分别写出它两侧相邻的1000的倍数、10000的倍数、100000的倍数。此题只找边界，暂不取整。

结论：267000与268000；260000与270000；200000与300000。

完整推导：看千位时，数是267个完整的1000再加300；看万位时，是26个完整的10000再加7300；看十万位时，是2个完整的100000再加67300。每组两端相差对应的一单位且中间没有另一个同类倍数。

## 讲解案例4：取最近的整倍数

条件：把267300分别取最接近的整千、整万、整十万。算出它到两侧相邻整倍数的距离，说明选择。

结论：整千267000；整万270000；整十万300000。

完整推导：到267000与268000的距离为300和700，前者更近；到260000与270000为7300和2700，后者更近；到200000与300000为67300和32700，后者更近。每一问都从原数267300判断，不能逐步取整后再取下一位。

## 讲解案例5：取整不能层层接着做

条件：对原数349500，分别四舍五入到千位、万位、十万位，恰好一半时取较大的整倍数。再说明为什么先取到千位、再取到十万位可能出错。

结论：分别为350000、350000、300000。若先变350000再取十万位，会得到400000，与直接取整不同。

完整推导：349500正好在349000与350000中点，按约定取350000。取整万时它距350000为500，小于距340000的9500，仍取350000。直接取整十万时，原数小于350000这个中点，因此取300000。先取千位会丢掉原数在中点哪一侧的信息，不能用中间近似数替代原数。

## 讲解案例6：估计与精确值各有用途

条件：两天的展览入场人次分别为34820和27460。先各取整到最近的千，再估计总人次；然后精确相加，求估计值与实际值的差。若规定总数超过62000须单独报告，能否只用估计值判断？

结论：估计35000+27000＝62000；实际62280，比估计多280；不能只看估计，实际已超过62000。

完整推导：取整便于快速判断规模，但各数的取整误差会影响合计。精算34820+27460=62280，差62280−62000=280。遇到明确阈值时需用原始精确数据，近似数等于阈值并不保证实际值也等于或低于它。

## 教学提醒
连续取整可能改变原数位于中点哪一侧，不能层层用近似值取整。判断精确阈值时应回到原始数据。

## 来源与核验范围
学习目标参考已保存的 Illustrative Mathematics K–5 Math v.I (2021)，源文件注明 CC BY 4.0。例题为 DeepTutor 新编，不是原书官方教师答案或认可，不复用原图或标志。原教材未收录的作答与图形仍保留缺失标记。

- Learning-goal reference: Illustrative Mathematics K–5 Math v.I (2021), Grade 4 Unit 4, lesson 12. DeepTutor authored the Chinese task and independently calculated explanation; not an official IM answer key or endorsement.
  来源：https://curriculum.illustrativemathematics.org/k5/teachers/grade-4/unit-4/ | IM:G4:U4:L12 | retained source line 4522
  原始记录：9b7d1afa4fc633d0918151885c176e47dee7797adcc6bba2c54f6a38917599b2

- Learning-goal reference: Illustrative Mathematics K–5 Math v.I (2021), Grade 4 Unit 4, lesson 13. DeepTutor authored the Chinese task and independently calculated explanation; not an official IM answer key or endorsement.
  来源：https://curriculum.illustrativemathematics.org/k5/teachers/grade-4/unit-4/ | IM:G4:U4:L13 | retained source line 5018
  原始记录：3f0f7772e86c18a7a9e6c83d88571710fbde860730ed2ab71e497e11278159a2

- Learning-goal reference: Illustrative Mathematics K–5 Math v.I (2021), Grade 4 Unit 4, lesson 14. DeepTutor authored the Chinese task and independently calculated explanation; not an official IM answer key or endorsement.
  来源：https://curriculum.illustrativemathematics.org/k5/teachers/grade-4/unit-4/ | IM:G4:U4:L14 | retained source line 5389
  原始记录：e50e109b067e17e01c29f8302c37730bc6cba9d953a1d994805cc279ad7c1a90

- Learning-goal reference: Illustrative Mathematics K–5 Math v.I (2021), Grade 4 Unit 4, lesson 15. DeepTutor authored the Chinese task and independently calculated explanation; not an official IM answer key or endorsement.
  来源：https://curriculum.illustrativemathematics.org/k5/teachers/grade-4/unit-4/ | IM:G4:U4:L15 | retained source line 5818
  原始记录：110db0135c3e0d4857839a9b5550735428c743911fec2cb59e7cf03fe17825e6

- Learning-goal reference: Illustrative Mathematics K–5 Math v.I (2021), Grade 4 Unit 4, lesson 16. DeepTutor authored the Chinese task and independently calculated explanation; not an official IM answer key or endorsement.
  来源：https://curriculum.illustrativemathematics.org/k5/teachers/grade-4/unit-4/ | IM:G4:U4:L16 | retained source line 6282
  原始记录：a1a8ad982e7c23ebad2c06644fbff0f16b221585e979ce700b7cc520543f08e7

- Learning-goal reference: Illustrative Mathematics K–5 Math v.I (2021), Grade 4 Unit 4, lesson 17. DeepTutor authored the Chinese task and independently calculated explanation; not an official IM answer key or endorsement.
  来源：https://curriculum.illustrativemathematics.org/k5/teachers/grade-4/unit-4/ | IM:G4:U4:L17 | retained source line 6878
  原始记录：e94d49501c3aab00dc015a04ef423202bc5cbb2a3a92a544c87eb6455aca6a76
