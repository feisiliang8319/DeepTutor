# 不变量与等价：钟表、立方体和混合模型

适用：数学拓展讲解。以下内容由本机已有旧书的数学结构独立改写，已做精确计算或有限枚举核验；课程年级、难度和正式测试资格仍待教学审核。用于 Chat 的完整讲解案例，不在 Chat 发起 Quiz，不据此自动认定学生掌握或升级。

## 核心方法
先明确什么被视为相同、什么量保持不变。钟表问题区分真实时间与显示时间；立方体问题区分固定面和允许旋转；混合问题必须明示体积可加的理想模型。

## 讲解案例1：再次同时指向十二点

条件：三只12小时制指针钟同时从12:00开始。甲准确；每过真实的24小时，乙恰好多走1分钟，丙恰好少走1分钟。三钟始终以各自固定速度运行。至少经过多少个真实的24小时，三钟的时针和分针才会再次同时指向12:00？不考虑秒针与日历。

结论：720天。

完整推导：甲指向12:00时，已经过k个半天。乙比甲多走k/2分钟，丙少走k/2分钟。乙、丙也显示12:00，须使k/2是720分钟的正整数倍，最小k=1440个半天，即720天。代回可知乙恰好多走12小时、丙恰好少走12小时，三钟同时满足。

## 讲解案例2：给立方体编号

条件：在立方体六个面分别写1至6，每个数字用一次，要求1与6、2与5、3与4分别在相对的面。第一问：六个空间位置固定为上、下、左、右、前、后，转动得到的编号也算不同，共有多少种？第二问：允许转动整个立方体，能转成一样的算同一种，但镜像不能直接算相同，共有多少种？

结论：第一问48种，第二问2种。

完整推导：固定位置时，1有6处可选，6的位置随之确定；2有4处可选，5随之确定；3有2处可选，4随之确定，所以6×4×2=48。每种编号有24个不同旋转姿态，因为朝上的面有6种，固定上面后绕竖轴有4种。数字各异，非恒等转动不能保持所有面不变，所以每类恰有24种，48÷24=2。

## 讲解案例3：来回转移的守恒

条件：在理想化混合模型中，甲杯装1000毫升红液，乙杯装1000毫升蓝液；两种液体混合后总体积按加法计算且不反应。先从甲取25毫升倒入乙并充分混匀，再从乙取25毫升混合液倒回甲。最终甲中的红液与蓝液体积比是多少？甲中混入的蓝液与乙中留下的红液谁更多？

结论：甲中红:蓝＝40:1；两杯中混入的对方液体体积相等，均为1000/41毫升。

完整推导：乙混匀后有1025毫升，其中红25、蓝1000。倒回的25毫升含蓝25×1000/1025=1000/41，含红25×25/1025=25/41。甲最终仍有1000毫升，其中红40000/41、蓝1000/41，比例40:1。乙留下红25−25/41=1000/41，与甲的蓝相同。两杯最终体积都回到原值，也可直接用体积守恒说明交换量相等。

## 教学提醒
优先解释条件，再计算；不要把旋转当成镜像，也不要把理想混合模型当作所有真实液体都满足的物理规律。

## 来源与核验范围
数学结构来自已经保存的底本；原始段落和答案范围均由源文件哈希及位置绑定。下列改编未复用原插图与历史人物评价。保留原书美国公有领域来源标记，不扩大为全球权利结论。

- Henry Ernest Dudeney. Amusements in Mathematics, problem 64. DeepTutor independently rewritten mathematical task and explanation; original narrative and illustrations not reproduced. Source SHA256 7e52015850ff1a25cbba577911e2648d7ee200d2f15adbe05c8adf65776543d3.
  来源：https://www.gutenberg.org/ebooks/16713 | Problem 64 | source line 1398
  原始记录：d66f0df584566080e712439e1857f49b08392a5b4b44f52138c4e602124271ef

- Henry Ernest Dudeney. Amusements in Mathematics, problem 286. DeepTutor independently rewritten mathematical task and explanation; original narrative and illustrations not reproduced. Source SHA256 7e52015850ff1a25cbba577911e2648d7ee200d2f15adbe05c8adf65776543d3.
  来源：https://www.gutenberg.org/ebooks/16713 | Problem 286 | source line 6643
  原始记录：6c3ce932b3a9f2e2b1cd670471b02c83a752e4b6979e94f2b14026c3d2d16b98

- Henry Ernest Dudeney. Amusements in Mathematics, problem 363. DeepTutor independently rewritten mathematical task and explanation; original narrative and illustrations not reproduced. Source SHA256 7e52015850ff1a25cbba577911e2648d7ee200d2f15adbe05c8adf65776543d3.
  来源：https://www.gutenberg.org/ebooks/16713 | Problem 363 | source line 8852
  原始记录：95cf151d0bb52b9a68a6c95348bfe2eeab6c0b21b0164d0101e73f6f17093e62
