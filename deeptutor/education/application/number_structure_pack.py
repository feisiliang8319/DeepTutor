"""Original, reviewable teaching content. Never an automatic publication seed.

The answers and explanations are authored here for inspection. Numeric answer
format checks do not certify the pedagogy, difficulty or mathematical proof.
"""
SOURCE = 'self-authored (DeepTutor AI-assisted number-structure draft, 2026-09-28)'
RECORDS = [
 ('FACTOR_PAIRS',3,'用72个单位正方形拼成整数边长的长方形，旋转视为同一种。一共有多少种拼法？只填写种数。',6,'只需枚举不超过√72的较短边。因数对是1×72、2×36、3×24、4×18、6×12、8×9，共6种；较短边超过8就会重复。'),
 ('FACTOR_PAIRS',4,'一个面积为42平方厘米的长方形，两条边长都是整数厘米。它的最小周长是多少厘米？',26,'因数对为1×42、2×21、3×14、6×7，周长分别是86、46、34、26厘米。比较全部因数对，最小为26厘米。'),
 ('FACTOR_PAIRS',4,'长方形的面积是48平方厘米，周长是28厘米，两条边都是整数厘米。较长的一条边是多少厘米？',8,'两边的和是14，积是48。因数对1与48、2与24、3与16、4与12、6与8中，只有6与8的和为14。'),
 ('FACTOR_PAIRS',3,'36共有多少个不同的正因数？注意平方根不要重复计算。',9,'因数对为1×36、2×18、3×12、4×9、6×6。前四对贡献8个不同因数，最后一对只贡献6这一个因数，共9个。'),
 ('FACTOR_PAIRS',4,'一个长方形面积为60平方厘米，整数边长相差7厘米。它的周长是多少厘米？',34,'检查60的因数对，5和12相差7，其他因数对不符合。周长为2×(5+12)=34厘米。'),
 ('FACTOR_PAIRS',3,'把24颗红珠和36颗蓝珠全部装袋，每袋的红珠数相同、蓝珠数也相同。最多可以装多少袋？',12,'袋数必须同时整除24和36。共同的正因数为1、2、3、4、6、12，最大为12；每袋2颗红珠、3颗蓝珠。'),
 ('FACTOR_PAIRS',3,'18和24有多少个共同的正因数？',4,'18的正因数为1、2、3、6、9、18；24的正因数为1、2、3、4、6、8、12、24。共同的为1、2、3、6，共4个。'),
 ('FACTOR_PAIRS',4,'小于30的正整数中，有且只有3个不同正因数的数有几个？',3,'三个因数必为1、p、p²，其中p是质数。小于30的质数平方为4、9、25，因此有3个。16有5个正因数，不符合。'),
 ('MULTIPLE_OF_FACTORS',3,'两盏灯分别每6秒和每8秒闪一次，现在同时闪亮。至少再过多少秒会同时闪亮？',24,'6的倍数6、12、18、24中，第一个也是8的倍数的是24，所以再过24秒同时闪亮。'),
 ('MULTIPLE_OF_FACTORS',4,'一个大于100且小于150的整数，既是6的倍数，也是7的倍数。这个数是多少？',126,'6和7没有大于1的公因数，公倍数是42的倍数。84太小、168太大，区间内只有126。'),
 ('MULTIPLE_OF_FACTORS',3,'铅笔每盒6支，橡皮每盒8块。各买整盒，铅笔和橡皮的总件数相同且都大于0。至少要买多少盒铅笔？',4,'相同件数的最小值是6和8的最小公倍数24。铅笔需要24÷6=4盒，橡皮需要3盒。'),
 ('MULTIPLE_TEST',2,'从1到100（含两端），有多少个数是7的倍数？',14,'7×14=98，7×15=105超过100，正倍数从7×1到7×14，共14个。'),
 ('MULTIPLE_TEST',4,'从1到100（含两端），有多少个整数是3的倍数或者5的倍数？同时是两者倍数的只算一次。',47,'3的倍数33个，5的倍数20个，15的倍数6个被重复计算。总数为33+20−6=47。'),
 ('MULTIPLE_TEST',2,'三位数4□2中的□是一位数字。要使这个数能被3整除，□最小可以填多少？',0,'各位数字和为6+□。填0时数字为402，各位和6能被3整除。0是一位数字且已是最小值。'),
 ('MULTIPLE_TEST',3,'大于10且小于40的奇数中，3的倍数共有几个？',5,'区间内3的倍数为12、15、18、21、24、27、30、33、36、39，奇数为15、21、27、33、39，共5个。'),
 ('PRIME_COMPOSITE',2,'大于10且小于20的整数中，有多少个质数？',4,'11、13、17、19只有1和自身两个正因数；12、14、15、16、18都是合数，共4个质数。'),
 ('PRIME_COMPOSITE',2,'最小的奇合数是多少？',9,'1既不是质数也不是合数，3、5、7是质数，9=3×3是合数，故最小奇合数是9。'),
 ('PRIME_COMPOSITE',3,'一个质数与另一个质数的和是21，较小的质数是多少？',2,'除2外质数都是奇数，两个奇数相加为偶数。和为奇数21，因此一个质数必须是2，另一个是19。'),
 ('PRIME_COMPOSITE',3,'把84分解成质数相乘的形式，所有质因数连同重复出现的相加，和是多少？',14,'84=2×2×3×7。把重复的2也计算在内，和是2+2+3+7=14。'),
 ('PRIME_COMPOSITE',4,'大于1的整数n使n、n+2、n+4全部是质数。n是多少？',3,'这三个数中恰有一个是3的倍数；作为质数它只能是3。n大于1，所以只能n=3，得到3、5、7。'),
 ('GENERATE_PATTERN',2,'数列从5开始，每次增加7。把5算作第1项，第12项是多少？',82,'从第1项到第12项增加11次7，所以第12项是5+11×7=82。'),
 ('GENERATE_PATTERN',3,'从4开始，依次重复“加3、乘2”。数列前五项为4、7、14、17、34。第六项是多少？',37,'操作按加3、乘2交替进行，34之后应加3，得到37。'),
 ('PATTERN_FEATURES',3,'从2开始，每次增加6。这个数列的第20项除以3，余数是多少？',2,'每次增加的6都能被3整除，所以除以3的余数始终与第一项2相同，为2。'),
 ('PATTERN_FEATURES',4,'依次写出1到20的所有整数。数字1总共出现多少次？',12,'个位上的1出现在1和11，共2次；十位上的1出现在10到19，共10次。11的两个1分别计入，合计12次。'),
 ('MULTISTEP_EQUATION',3,'一个盒子里原有一些卡片，先取出总数的一半，再取出6张，还剩9张。原来有多少张卡片？',30,'取出一半后还剩6+9=15张，这15张是原来的一半，所以原来有30张。'),
 ('MULTISTEP_EQUATION',3,'买3本同价笔记本和一支8元的笔共花44元。每本笔记本多少元？',12,'先去掉笔的费用，三本笔记本共44−8=36元；每本36÷3=12元。'),
 ('REMAINDER_INTERP',2,'53名学生乘车，每辆车最多坐8名学生。至少需要多少辆车？',7,'53÷8=6余5，六辆只能坐48人，余下5人还需一辆，所以至少7辆。'),
 ('REMAINDER_INTERP',3,'一根53厘米长的绳子剪成每段8厘米的绳段，不计剪切损耗。最多能得到多少段完整的8厘米绳段？',6,'53÷8=6余5，可得到6段完整绳段，剩下5厘米不能算作完整的8厘米段。'),
 ('SOLVE_COMPARISON',3,'姐姐有的钱是弟弟的3倍，姐姐比弟弟多24元。弟弟有多少元？',12,'多出的24元相当于弟弟钱数的3−1=2倍，因此弟弟有24÷2=12元。'),
 ('MULT_VS_ADD',3,'甲有5颗珠子。乙比甲多3颗，丙的珠子数是甲的3倍。丙比乙多多少颗？',7,'乙有5+3=8颗，丙有5×3=15颗，两者相差15−8=7颗。'),
 ('REASONABLENESS',2,'一本练习册19元，买6本。用每本20元估算，总价估计为120元。这个估计比实际总价多多少元？',6,'每本多估1元，6本共多估6元。实际总价19×6=114元，120−114=6元。'),
 ('REPRESENT_VERBAL',3,'一条红绳长7米，一条蓝绳的长度是红绳的4倍。两条绳子总长多少米？',35,'蓝绳长7×4=28米，两条总长7+28=35米。'),
]


def package(version):
    items=[]
    for n,(suffix,difficulty,prompt,answer,explanation) in enumerate(RECORDS,1):
        prefix = 'G4.OA.B4.' if suffix in {'FACTOR_PAIRS','MULTIPLE_OF_FACTORS','MULTIPLE_TEST','PRIME_COMPOSITE'} else 'G4.OA.C5.' if suffix in {'GENERATE_PATTERN','PATTERN_FEATURES'} else 'G4.OA.A3.' if suffix in {'MULTISTEP_EQUATION','REMAINDER_INTERP','REASONABLENESS'} else 'G4.OA.A2.' if suffix in {'SOLVE_COMPARISON','MULT_VS_ADD'} else 'G4.OA.A1.'
        items.append(dict(id=f'dt-number-structure-v1-{n:03}',knowledge_node_code=prefix+suffix,
                          item_type='numeric',prompt=prompt,expected_answer=str(answer),
                          explanation=explanation,explanation_source='authored',difficulty=difficulty,
                          content_scope='BUNDLED',source_ref=SOURCE,
                          license_note='Original AI-assisted draft; educational review required.',
                          attribution_text='DeepTutor content workshop, 2026-09-28.'))
    return {'schema_version':1,'course_version_id':version,'source_name':'DeepTutor · 数与结构 · 原创待审课包 v1',
            'known_limits':['Chinese draft, not a complete grade curriculum.','No competition or promotion classification is asserted.','Every item requires content review.'], 'items':items}
