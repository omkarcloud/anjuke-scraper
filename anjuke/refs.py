"""Reference resolvers, the city table and the URL grammar for /anjuke/*.

ONE param per input (tripadvisor QueryOrIdField convention): `listing`,
`rental`, `community` and `project` each accept a bare anjuke id OR any
anjuke.com link (desktop or mobile) for the same record; `city` accepts the
host label (pinyin, "beijing"), the short alias the mobile site uses ("bj")
or the Chinese name ("北京"). Resolvers raise ValueError with a user-facing
message (schema_fields.RefField turns it into a 400).

Hosts (research 2026-10-30/31, scrapers memory anjuke-scraper-research):
  resale + communities   https://<pinyin>.anjuke.com      (beijing.anjuke.com)
  rentals (desktop)      https://<pinyin>.zu.anjuke.com   (301 -> <alias>.zu.anjuke.com)
  new homes (desktop)    https://<alias>.fang.anjuke.com  (every page is captcha-walled
                                                           for curl; links only)
  mobile twin            https://m.anjuke.com/<alias>/... (also accepts <pinyin>, 301)
Every record id is global: a Shanghai listing / community / project served
under the Beijing host (or the bj mobile prefix) answers 200 or redirects
to its own city, so a bare id needs no city.

City table: www.anjuke.com/sy-city.html's own `allData` block, captured
2026-10-31 — 673 cities with a resale site + 69 new-homes-only cities (a
*.fang.anjuke.com host and no resale/rental/community pages).

Record ids:
  resale listing   16-digit house id ("3048414802945025"), also served as the
                   10-digit prop id and the "S<id>" / "A<id>" forms the list
                   pages link to
  rental           16-digit house id (bj.zu.anjuke.com/fangyuan/<id>,
                   m.anjuke.com/bj/rent/<id>-3/)
  community        numeric id (community/view/<id>, m.anjuke.com/bj/community/<id>/)
  new-home project numeric loupan id (<alias>.fang.anjuke.com/loupan/<id>.html,
                   m.anjuke.com/bj/loupan/<id>/)
"""
import re
from urllib.parse import quote, urlparse

MOBILE = "https://m.anjuke.com"
WWW = "https://www.anjuke.com"
CITY_TABLE_LINK = WWW + "/sy-city.html"

# ---- cities ------------------------------------------------------------------------
# (Chinese name, pinyin host label, short alias, other accepted pinyin
# spellings, new-homes-only). The pinyin label is the canonical city value
# everywhere in this package.
CITY_ROWS = (
    ("阿坝", "aba", "ab", ("eba",), False),
    ("阿克苏", "akesu", "aks", ("ekesu",), False),
    ("阿拉尔", "alaer", "ale", ("elaer",), False),
    ("阿拉善盟", "alashanm", "alsm", ("alashanming", "elashanming", "alashanmeng", "elashanmeng"), False),
    ("阿勒泰", "aletai", "alt", ("eletai", "aleitai", "eleitai"), False),
    ("阿里", "ali", "al", ("eli",), False),
    ("安吉", "anjixian", "anji", ("anji",), False),
    ("安康", "ankang", "ank", (), False),
    ("安宁", "anning", "ann", (), False),
    ("安庆", "anqing", "aq", (), False),
    ("安丘", "anqiu", "anq", (), False),
    ("鞍山", "anshan", "as", (), False),
    ("安顺", "anshun", "ans", (), False),
    ("安溪", "anxi", "ax", ("anqi",), False),
    ("安阳", "anyang", "ay", (), False),
    ("安岳", "anyuexian", "anyuexian", ("anyue",), False),
    ("林州", "aylinzhou", "aylz", ("linzhou",), False),
    ("白城", "baicheng", "bc", (), False),
    ("百色", "baise", "bais", ("bose", "baishai", "boshai"), False),
    ("白山", "baishan", "baish", (), False),
    ("白银", "baiyin", "by", (), False),
    ("西双版纳", "bannan", "bn", ("xishuangbanna",), False),
    ("保定", "baoding", "bd", (), False),
    ("宝鸡", "baoji", "bao", (), False),
    ("保山", "baoshan", "bs", (), False),
    ("包头", "baotou", "bt", (), False),
    ("宝应县", "baoyingxian", "baoyingx", (), False),
    ("巴彦淖尔市", "bayannaoer", "bycem", ("bayannaoershi",), False),
    ("巴音郭楞", "bayinguoleng", "bygl", (), False),
    ("霸州", "bazh", "baz", ("bazhou",), False),
    ("巴中", "bazhong", "ba", ("bazhou", "巴州"), False),
    ("北海", "beihai", "bh", (), False),
    ("北京", "beijing", "bj", (), False),
    ("北流", "beiliu", "beil", (), False),
    ("北票", "beipiao", "bp", (), False),
    ("蚌埠", "bengbu", "bb", ("bangbu",), False),
    ("本溪", "benxi", "bx", ("benqi",), False),
    ("毕节", "bijie", "bij", (), False),
    ("滨州", "binzhou", "bz", (), False),
    ("博白", "bobaixian", "bob", ("bobai",), False),
    ("博尔塔拉", "boertala", "betl", ("boerdala",), False),
    ("博罗", "boluoxian", "boluo", ("boluo",), False),
    ("博兴", "boxingxian", "box", ("boxing",), False),
    ("亳州", "bozhou", "boz", (), False),
    ("苍南", "cangnanxian", "cangnanxian", ("cangnan", "cangna"), False),
    ("沧县", "cangxian", "cxcz", (), False),
    ("沧州", "cangzhou", "cang", (), False),
    ("曹县", "caoxian", "caoxian", (), False),
    ("长春", "cc", "cc", ("zhangchun", "changchun", "nongan", "农安"), False),
    ("岑溪", "cengxi", "cengx", ("cenqi", "cenxi"), False),
    ("常德", "changde", "chd", (), False),
    ("昌都", "changdu", "changd", ("changdou",), False),
    ("长葛", "changge", "cg", ("zhangge",), False),
    ("昌吉", "changji", "cj", (), False),
    ("昌乐", "changle", "cl", ("changyue",), False),
    ("长岭", "changlingxian", "changl", ("zhangling", "changling"), False),
    ("长宁", "changning", "cn", ("zhangning",), False),
    ("常熟", "changshushi", "chss", ("changshou", "changshu"), False),
    ("长兴", "changxingxian", "changxing", ("changxing", "zhangxing"), False),
    ("长垣", "changyuanxian", "changyuan", ("zhangyuan", "changyuan"), False),
    ("长治", "changzhi", "chang", ("zhangzhi",), False),
    ("巢湖", "chaohu", "ch", (), False),
    ("朝阳", "chaoyang", "cy", ("zhaoyang",), False),
    ("潮州", "chaozhou", "chao", (), False),
    ("承德", "chengde", "cheng", (), False),
    ("成都", "chengdu", "cd", ("chengdou", "abazhou", "ebazhou", "阿坝州", "daiyi", "dayi", "大邑", "jintang", "金堂"), False),
    ("郴州", "chenzhou", "chen", (), False),
    ("赤壁", "chibi", "chb", (), False),
    ("赤峰", "chifeng", "cf", (), False),
    ("茌平", "chiping", "cp", (), False),
    ("池州", "chizhou", "chi", (), False),
    ("重庆", "chongqing", "cq", ("zhongqing", "tongliang", "铜梁", "fengdu", "fengdou", "丰都", "zhangshou", "changshou", "长寿", "fuling", "涪陵", "nachuan", "nanchuan", "南川", "yongchuan", "永川", "qijiang", "綦江", "qianjiang", "黔江", "mozhou", "wanzhou", "万州", "jiangjin", "江津", "gechuan", "hechuan", "合川"), False),
    ("崇左", "chongzuo", "chongz", (), False),
    ("楚雄", "chuxiong", "cx", (), False),
    ("滁州", "chuzhou", "chu", (), False),
    ("慈利", "cilixian", "clzjj", ("cili",), False),
    ("慈溪", "cixi", "cix", ("ciqi",), False),
    ("磁县", "cixian", "cixian", (), False),
    ("澄迈", "cm", "cm", ("chengmai", "dengmai"), False),
    ("长沙", "cs", "cs", ("zhangsha", "changsha", "ningxiang", "宁乡"), False),
    ("常州", "cz", "cz", ("changzhou",), False),
    ("定安", "da", "hnda", ("dingan",), False),
    ("大丰", "dafeng", "df", ("daifeng",), False),
    ("大理", "dali", "da", ("daili",), False),
    ("大连", "dalian", "dl", ("dailian", "pulandian", "普兰店"), False),
    ("丹东", "dandong", "dd", (), False),
    ("单县", "danxian", "shanxian", ("chanxian", "shanxian"), False),
    ("丹阳", "danyang", "danyangshi", (), False),
    ("儋州", "danzhou", "danz", (), False),
    ("大庆", "daqing", "dq", ("daiqing", "zhaoyuan", "肇源"), False),
    ("大同", "datong", "dt", ("daitong",), False),
    ("大悟", "dawuxian", "dw", ("dawu", "daiwu"), False),
    ("大亚湾", "dayawana", "dyw", ("dayawan", "daiyawan"), False),
    ("达州", "dazhou", "dzh", (), False),
    ("大竹", "dazhu", "dzsc", ("daizhu",), False),
    ("凤城", "ddfengcheng", "ddfc", ("fengcheng",), False),
    ("德宏", "dehong", "dh", (), False),
    ("灯塔", "dengta", "dengt", ("dengda",), False),
    ("邓州", "dengzhou", "dengz", (), False),
    ("德清", "deqingxian", "deqing", ("deqing",), False),
    ("德阳", "deyang", "de", (), False),
    ("德州", "dezhou", "dz", (), False),
    ("东莞", "dg", "dg", ("dongguan", "dongwan"), False),
    ("定边", "dingbianxian", "db", ("dingbian",), False),
    ("定西", "dingxi", "dx", (), False),
    ("定州", "dingzhou", "ding", (), False),
    ("迪庆", "diqing", "diq", (), False),
    ("东方", "dongfang", "dfx", (), False),
    ("东海", "donghaixian", "donghai", ("donghai",), False),
    ("东明", "dongmingxian", "dm", ("dongming",), False),
    ("东平", "dongpingxian", "dp", ("dongping",), False),
    ("东台", "dongtai", "dongt", (), False),
    ("东阳", "dongyang", "dongyang", (), False),
    ("东营", "dongying", "dy", (), False),
    ("东至", "dongzhixian", "dongz", ("dongzhi",), False),
    ("敦煌", "dunhuang", "dunh", ("duihuang",), False),
    ("都匀", "duyun", "duy", ("douyun",), True),
    ("大兴安岭", "dxanling", "dxal", ("daxinganling", "daixinganling"), False),
    ("禹城", "dzyucheng", "dzyc", ("yucheng",), False),
    ("鄂尔多斯", "eerduosi", "eeds", (), False),
    ("峨眉山", "emeishan", "ems", (), True),
    ("恩施", "enshi", "es", (), False),
    ("鄂州", "ezhou", "ez", (), False),
    ("防城港", "fangchenggang", "fcg", (), False),
    ("范县", "fanxian", "fanx", (), False),
    ("肥城", "feichengshi", "fcs", ("feicheng",), False),
    ("丰城", "fengchengshi", "fengc", ("fengcheng",), False),
    ("丰县", "fengxian", "fengxian", (), False),
    ("分宜", "fenyixian", "fyxy", ("fenyi",), False),
    ("佛山", "foshan", "fs", ("fushan",), False),
    ("福安", "fuan", "fa", (), False),
    ("福鼎", "fuding", "fding", (), False),
    ("府谷", "fuguxian", "gf", ("fugu", "fuyu"), False),
    ("浮梁", "fuliang", "fl", (), False),
    ("阜宁", "funing", "fn", (), False),
    ("福清", "fuqing", "fq", (), False),
    ("抚顺", "fushun", "fsh", (), False),
    ("阜新", "fuxin", "fx", (), False),
    ("阜阳", "fuyang", "fy", (), False),
    ("扶余", "fuyushi", "fuy", ("futu", "fuyu"), False),
    ("抚州", "fuzhoushi", "fuz", ("fuzhou",), False),
    ("福州", "fz", "fz", ("fuzhou", "changle", "changyue", "zhangle", "zhangyue", "长乐", "lianjiang", "连江"), False),
    ("改则", "gaizexian", "gaizexian", ("gaize",), False),
    ("甘南藏族自治州", "gannan", "gn", ("gannazangzuzizhizhou", "gannanzangzuzizhizhou", "gannacangzuzizhizhou", "gannancangzuzizhizhou"), False),
    ("赣州", "ganzhou", "gan", (), False),
    ("甘孜", "ganzi", "gaz", (), False),
    ("高安", "gaoanshi", "gaoanshi", ("gaoan",), False),
    ("高密", "gaomishi", "gms", ("gaomi",), False),
    ("高平", "gaopingshi", "gaop", ("gaoping",), False),
    ("高唐", "gaotangxian", "gaot", ("gaotang",), False),
    ("格尔木", "geermu", "gem", (), False),
    ("公主岭", "gongzhulingshi", "gzls", ("gongzhuling",), False),
    ("固安", "guan", "gua", (), False),
    ("广安", "guangan", "ga", ("anan",), False),
    ("广汉", "guanghan", "gh", ("anhan",), False),
    ("广饶", "guangraoxian", "guangrao", ("guangrao", "anrao"), False),
    ("广元", "guangyuan", "guang", ("anyuan",), False),
    ("广州", "guangzhou", "gz", ("anzhou",), False),
    ("灌南", "guannanxian", "guannan", ("guanna", "guannan"), False),
    ("馆陶", "guantao", "gt", ("guanyao",), False),
    ("冠县", "guanxian", "gx", (), False),
    ("灌云", "guanyunxian", "guanyun", ("guanyun",), False),
    ("谷城", "gucheng", "gc", ("yucheng",), False),
    ("贵港", "guigang", "gg", (), False),
    ("桂林", "guilin", "gl", (), False),
    ("桂平", "guiping", "gp", (), False),
    ("桂阳", "guiyangxian", "guiy", ("guiyang",), False),
    ("果洛", "guoluo", "guo", (), False),
    ("固始", "gushixian", "gs", ("gushi",), False),
    ("固原", "guyuan", "gu", (), False),
    ("贵阳", "gy", "gy", ("guiyang",), False),
    ("海安", "haianxian", "haian", ("haian",), False),
    ("海北", "haibei", "haib", (), False),
    ("海东", "haidong", "haid", (), False),
    ("海丰", "haifengxian", "haifengxian", ("haifeng",), False),
    ("海口", "haikou", "hai", ("baishaxian", "白沙县", "qiongzhong", "琼中"), False),
    ("海拉尔", "hailaer", "hlr", (), False),
    ("海门", "haimen", "hm", (), False),
    ("海南藏族自治州", "hainan", "hain", ("hainazangzuzizhizhou", "hainancangzuzizhizhou", "hainacangzuzizhizhou", "hainanzangzuzizhizhou"), False),
    ("海宁", "haining", "haining", (), False),
    ("海盐", "haiyan", "haiyan", (), False),
    ("哈密", "hami", "hami", ("kami",), False),
    ("韩城", "hancheng", "hanch", (), False),
    ("汉川", "hanchuanshi", "hanchuansh", ("hanchuan",), False),
    ("邯郸", "handan", "hd", (), False),
    ("杭州", "hangzhou", "hz", ("chunan", "淳安", "fuyang", "富阳", "linan", "临安", "tonglu", "桐庐"), False),
    ("汉中", "hanzhong", "han", (), False),
    ("哈尔滨", "heb", "heb", ("kaerbin", "haerbin"), False),
    ("鹤壁", "hebi", "hb", (), False),
    ("河池", "hechi", "hc", (), False),
    ("鹤岗", "hegang", "heg", (), False),
    ("黑河", "heihe", "heih", (), False),
    ("河间", "hejian", "hj", (), False),
    ("衡东", "hengdongxian", "hengd", ("hengdong",), False),
    ("衡水", "hengshui", "hs", (), False),
    ("衡阳", "hengyang", "hy", (), False),
    ("和田", "hetian", "ht", ("haitian", "hutian", "huotian"), False),
    ("海西", "hexi", "hx", ("haixi",), False),
    ("和县", "hexian", "hex", ("haixian", "huxian", "huoxian"), False),
    ("河源", "heyuan", "he", (), False),
    ("菏泽", "heze", "hez", (), False),
    ("贺州", "hezhou", "hezh", (), False),
    ("合肥", "hf", "hf", ("gefei", "hefei", "feidong", "肥东", "feixi", "肥西", "lujiang", "庐江", "zhangfeng", "changfeng", "长丰"), False),
    ("永城", "hnyongcheng", "hnyc", ("yongcheng",), False),
    ("红河", "honghe", "hong", ("gonghe",), False),
    ("淮安", "huaian", "ha", (), False),
    ("淮北", "huaibei", "huai", (), False),
    ("淮滨", "huaibinxian", "huaib", ("huaibin",), False),
    ("怀化", "huaihua", "hh", (), False),
    ("淮南", "huainan", "hn", ("huaina",), False),
    ("黄冈", "huanggang", "hg", (), False),
    ("黄骅", "huanghua", "huangh", (), False),
    ("黄南", "huangnan", "huangn", ("huangna",), False),
    ("黄山", "huangshan", "hsh", (), False),
    ("黄石", "huangshi", "huang", ("huangdan",), False),
    ("桓台", "huantaixian", "huantaixian", ("huantai",), False),
    ("华容", "huarongxian", "hr", ("huarong",), False),
    ("滑县", "huaxian", "huax", ("guxian",), False),
    ("呼和浩特", "huhehaote", "hhht", ("huhaihaote", "huhuhaote", "huhuohaote"), False),
    ("惠东", "huidongxian", "huidong", ("huidong",), False),
    ("惠州", "huizhou", "hui", (), False),
    ("葫芦岛", "huludao", "hld", (), False),
    ("呼伦贝尔", "hulunbeier", "hlbe", (), False),
    ("霍邱", "huoqiu", "hq", (), False),
    ("胡杨河", "huyanghe", "huyanghe", (), False),
    ("湖州", "huzhou", "hu", (), False),
    ("常宁", "hychangning", "hycn", ("changning",), False),
    ("加尔玛", "jiaerma.fang", "jem", ("jiaerma",), False),
    ("佳木斯", "jiamusi", "jms", (), False),
    ("吉安", "jian", "ja", (), False),
    ("江门", "jiangmen", "jm", (), False),
    ("姜堰", "jiangyan", "jiangyan", (), False),
    ("江阴", "jiangyin", "jiangy", (), False),
    ("建湖", "jianhuxian", "jianhu", ("jianhu",), False),
    ("简阳", "jianyangshi", "jys", ("jianyang",), False),
    ("焦作", "jiaozuo", "jiao", (), False),
    ("嘉善", "jiashanxian", "jiashanx", ("jiashan",), False),
    ("嘉峪关", "jiayuguan", "jyg", (), False),
    ("嘉鱼", "jiayuxian", "jiay", ("jiayu",), False),
    ("揭阳", "jieyang", "jy", (), False),
    ("吉林", "jilin", "jl", (), False),
    ("济南", "jinan", "jn", ("jina", "pingyin", "平阴", "jiyang", "济阳", "shanghe", "商河"), False),
    ("金昌", "jinchang", "jinc", (), False),
    ("晋城", "jincheng", "jc", (), False),
    ("靖边", "jingbianxian", "jb", ("jingbian",), False),
    ("景德镇", "jingdezhen", "jdz", ("yingdezhen",), False),
    ("靖江", "jingjiang", "jingj", (), False),
    ("荆门", "jingmen", "jing", (), False),
    ("荆州", "jingzhou", "jzh", (), False),
    ("金湖", "jinhu", "jinh", (), False),
    ("金华", "jinhua", "jh", (), False),
    ("济宁", "jining", "ji", (), False),
    ("晋江", "jinjiangshi", "jinjiangs", ("jinjiang",), False),
    ("金坛", "jintan", "jint", (), False),
    ("进贤", "jinxian", "jinx", (), False),
    ("晋中", "jinzhong", "jin", (), False),
    ("锦州", "jinzhou", "jz", (), False),
    ("吉首", "jishou", "jish", (), False),
    ("九江", "jiujiang", "jj", (), False),
    ("酒泉", "jiuquan", "jq", (), False),
    ("鸡西", "jixi", "jixi", (), False),
    ("济源", "jiyuan", "jiy", (), False),
    ("昌邑", "jlchangyi", "jlcy", ("changyi",), False),
    ("桦甸", "jlhuadian", "jlhd", ("huadian",), False),
    ("京山", "jmjingshan", "jmjs", ("jingshan",), False),
    ("钟祥", "jmzhongxiang", "jmzx", ("zhongxiang",), False),
    ("鄄城", "juanchengxian", "juanc", ("juancheng",), False),
    ("句容", "jurong", "jr", ("gourong",), False),
    ("莒县", "juxian", "juxian", (), False),
    ("巨野", "juyexian", "jyhz", ("juye",), False),
    ("嘉兴", "jx", "jx", ("jiaxing",), False),
    ("孟州", "jzmengzhou", "jzmz", ("mengzhou",), False),
    ("开封", "kaifeng", "kf", (), False),
    ("凯里", "kaili", "kli", (), True),
    ("开平", "kaiping", "kp", (), False),
    ("喀什", "kashi", "ka", ("keshi", "kashen", "keshe", "keshen", "kashe"), False),
    ("可克达拉", "kekedala", "kekedl", (), False),
    ("克拉玛依", "kelamayi", "klmy", (), False),
    ("垦利", "kenli", "kl", (), False),
    ("兰考", "kflankao", "kflk", ("lankao",), False),
    ("凯里", "kli", "kli", ("kaili",), False),
    ("昆明", "km", "km", ("kunming", "yiliang", "宜良"), False),
    ("昆山", "ks", "ks", ("kunshan",), False),
    ("来宾", "laibin", "lb", (), False),
    ("莱芜", "laiwu", "lw", (), False),
    ("莱阳", "laiyang", "lay", (), False),
    ("莱州", "laizhoushi", "lzs", ("laizhou",), False),
    ("廊坊", "langfang", "lf", ("wenan", "文安"), False),
    ("兰州", "lanzhou", "lz", ("yongdeng", "永登", "yuzhong", "榆中"), False),
    ("拉萨", "lasa", "ls", (), False),
    ("乐陵", "leling", "ll", ("yueling",), False),
    ("冷水江", "lengshuijiang", "lshj", (), False),
    ("乐平", "lepingshi", "lp", ("leping", "yueping"), False),
    ("乐山", "leshan", "le", ("yueshan",), False),
    ("克孜勒苏", "lezilesu", "kzls", ("kezileisu", "kezilesu"), False),
    ("凉山", "liangshan", "liang", (), False),
    ("梁山", "liangshanxian", "liangs", ("liangshan",), False),
    ("涟源", "lianyuan", "liany", (), False),
    ("连云港", "lianyungang", "lyg", (), False),
    ("聊城", "liaocheng", "lc", (), False),
    ("辽阳", "liaoyang", "liao", (), False),
    ("辽源", "liaoyuan", "liaoy", (), False),
    ("丽江", "lijiang", "lj", (), False),
    ("利津", "lijingxian", "lij", ("lijin",), False),
    ("醴陵", "lilingshi", "lls", ("liling",), False),
    ("临汾", "linfen", "lin", (), False),
    ("灵宝", "lingbaoshi", "lingb", ("lingbao",), False),
    ("临沧", "lingcang", "linc", ("lincang",), False),
    ("陵水", "lingshui", "lingshui", (), False),
    ("临海", "linhaishi", "lihs", ("linhai",), False),
    ("临朐", "linju", "linj", ("linqu",), False),
    ("临清", "linqing", "linq", (), False),
    ("临夏", "linxia", "lx", ("linjia",), False),
    ("临沂", "linyi", "liny", (), False),
    ("临猗", "linyishi", "linyis", ("linyi",), False),
    ("临邑", "linyixian", "lydz", ("linyi",), False),
    ("林芝", "linzhi", "lizh", (), False),
    ("丽水", "lishui", "li", (), False),
    ("梨树县", "lishuxian", "lis", (), False),
    ("柳林", "liulinxian", "liul", ("liulin",), False),
    ("六盘水", "liupanshui", "lps", ("lupanshui",), False),
    ("柳州", "liuzhou", "lzh", (), False),
    ("澧县", "lixian", "lxcd", (), False),
    ("溧阳", "liyang", "liy", (), False),
    ("龙口", "longkou", "lk", (), False),
    ("龙门", "longmen", "longmen", (), False),
    ("陇南", "longnan", "ln", ("longna",), False),
    ("龙岩", "longyan", "long", (), False),
    ("娄底", "loudi", "ld", ("loude",), False),
    ("六安", "luan", "la", ("liuan",), False),
    ("滦南", "luannan", "luann", ("luanna",), False),
    ("陆丰", "lufengshi", "lufengshi", ("lufeng", "liufeng"), False),
    ("漯河", "luohe", "lh", ("tahe",), False),
    ("洛阳", "luoyang", "ly", ("ruyang", "汝阳"), False),
    ("鹿邑", "luyixian", "luy", ("luyi",), False),
    ("泸州", "luzhou", "lu", (), False),
    ("吕梁", "lvliang", "lvl", ("lu:liang",), False),
    ("宜阳", "lyyiyang", "lyyiy", ("yiyang",), False),
    ("马鞍山", "maanshan", "mas", ("dangtu", "当涂"), False),
    ("茂名", "maoming", "mm", (), False),
    ("梅河口", "meihekou", "mhk", (), False),
    ("眉山", "meishan", "ms", (), False),
    ("梅州", "meizhou", "mz", (), False),
    ("孟津", "mengjin", "mj", (), False),
    ("渑池", "mianchixian", "mc", ("mianchi", "shengchi"), False),
    ("绵阳", "mianyang", "my", (), False),
    ("弥勒", "mileshi", "ml", ("milei", "mile"), False),
    ("明港", "minggang", "mg", (), False),
    ("牡丹江", "mudanjiang", "mdj", (), False),
    ("南安", "nananshi", "na", ("nanan", "naan"), False),
    ("南城", "nanchengxian", "nanc", ("nacheng", "nancheng"), False),
    ("南充", "nanchong", "nan", ("nachong",), False),
    ("南京", "nanjing", "nj", ("najing",), False),
    ("南宁", "nanning", "nn", ("naning", "binyang", "宾阳", "hengxian", "横县"), False),
    ("南平", "nanping", "np", ("naping",), False),
    ("南通", "nantong", "nt", ("natong",), False),
    ("南县", "nanxian", "nx", ("naxian",), False),
    ("南阳", "nanyang", "ny", ("nayang",), False),
    ("南漳", "nanzhangxian", "nz", ("nazhang", "nanzhang"), False),
    ("那曲", "naqu", "nq", ("neiqu",), False),
    ("宁波", "nb", "nb", ("ningpo", "ningbo", "ninghai", "宁海"), False),
    ("南昌", "nc", "nc", ("nanchang", "nachang", "xinjian", "新建"), False),
    ("内江", "neijiang", "nei", (), False),
    ("宁德", "ningde", "nd", (), False),
    ("宁国", "ningguo", "ningg", (), False),
    ("宁津", "ningjinxian", "ningj", ("ningjin",), False),
    ("宁阳", "ningyangxian", "ningy", ("ningyang",), False),
    ("怒江", "nujiang", "nu", (), False),
    ("盘锦", "panjin", "pj", (), False),
    ("磐石", "panshishi", "ps", ("pandan", "panshi"), False),
    ("攀枝花", "panzhihua", "pzh", ("panqihua",), False),
    ("蓬莱", "penglaishi", "pls", ("penglai",), False),
    ("平顶山", "pingdingsha", "pds", ("pingdingshan",), False),
    ("平湖", "pinghu", "ph", (), False),
    ("平凉", "pingliang", "pl", (), False),
    ("平潭", "pingtan", "pingtan", (), False),
    ("萍乡", "pingxiang", "px", (), False),
    ("平阳", "pingyang", "pingyangxian", (), False),
    ("平邑", "pingyi", "pingy", (), False),
    ("邳州", "pizhou", "piz", (), False),
    ("普洱", "puer", "pe", (), False),
    ("普宁", "puning", "pn", (), True),
    ("莆田", "putian", "pt", (), False),
    ("濮阳", "puyang", "py", (), False),
    ("青岛", "qd", "qd", ("qingdao", "jimo", "即墨", "jiaonan", "jiaona", "胶南"), False),
    ("迁安市", "qiananshi", "qns", (), False),
    ("黔东南", "qiandongnan", "qdn", ("qiandongna",), False),
    ("潜江", "qianjiang", "qian", (), False),
    ("黔南", "qiannan", "qn", ("qianna",), False),
    ("迁西", "qianxi", "qianx", (), False),
    ("黔西南", "qianxinan", "qxn", ("qianxina",), False),
    ("启东", "qidong", "qid", (), False),
    ("祁东", "qidongxian", "qidongxian", ("qidong",), False),
    ("齐河", "qihexian", "qih", ("jihe", "qihe"), False),
    ("清徐", "qingxu", "qx", (), False),
    ("庆阳", "qingyang", "qing", (), False),
    ("清远", "qingyuan", "qy", (), False),
    ("清镇", "qingzhen", "qzh", (), False),
    ("青州", "qingzhoushi", "qzs", ("qingzhou",), False),
    ("秦皇岛", "qinhuangdao", "qhd", (), False),
    ("沁阳", "qinyangshi", "qinyangshi", ("qinyang", "shenyang"), False),
    ("钦州", "qinzhou", "qin", (), False),
    ("琼海", "qionghai", "qh", (), False),
    ("齐齐哈尔", "qiqihaer", "qqhe", ("qijihaer", "jijihaer", "qijikaer", "jijikaer", "jiqihaer", "qiqikaer", "jiqikaer"), False),
    ("七台河", "qitaihe", "qth", (), False),
    ("栖霞", "qixia", "qix", ("xixia",), False),
    ("淇县", "qixian", "qxhb", (), False),
    ("杞县", "qixianqu", "qixianqu", ("qixian",), False),
    ("祁阳", "qiyangxian", "qiy", ("qiyang",), False),
    ("泉州", "quanzhou", "qz", ("jinan", "晋安"), False),
    ("曲靖", "qujing", "qj", (), False),
    ("渠县", "quxian", "qux", (), False),
    ("衢州", "quzhou", "qu", (), False),
    ("江山", "qzjiangshan", "qzjs", ("jiangshan",), False),
    ("仁怀", "renhuai", "rh", (), False),
    ("任丘", "renqiushi", "rqs", ("renqiu",), False),
    ("仁寿", "renshouxian", "renshouxian", ("renshou",), False),
    ("日喀则", "rikeze", "rkz", ("rikaze",), False),
    ("日土", "rituxian", "rituxian", ("ritu",), False),
    ("日照", "rizhao", "rz", (), False),
    ("荣成", "rongchengshi", "rcheng", ("rongcheng",), False),
    ("如东", "rudongxian", "rudong", ("rudong",), False),
    ("如皋", "rugao", "rg", (), False),
    ("瑞安", "ruian", "ra", (), False),
    ("乳山", "rushanshi", "rsh", ("rushan",), False),
    ("汝州", "ruzhoushi", "rzs", ("ruzhou",), False),
    ("三河", "sanheshi", "shs", ("sanhe",), False),
    ("三门峡", "sanmenxia", "smx", (), False),
    ("三明", "sanming", "sm", (), False),
    ("三沙", "sansha", "sansh", (), False),
    ("三亚", "sanya", "sy", ("baoting", "保亭", "dongfangshi", "东方市"), False),
    ("上杭", "shagnhangxian", "shly", ("shanghang",), False),
    ("安达", "shanda", "shad", ("anda",), False),
    ("上海", "shanghai", "sh", (), False),
    ("商洛", "shangluo", "sl", (), False),
    ("商丘", "shangqiu", "sq", (), False),
    ("上饶", "shangrao", "sr", (), False),
    ("商水", "shangshui", "ss", (), False),
    ("山南", "shannan", "shn", ("shanna",), False),
    ("汕头", "shantou", "st", (), False),
    ("汕尾", "shanwei", "sw", ("shanyi",), False),
    ("邵东", "shaodongxian", "shaod", ("shaodong",), False),
    ("韶关", "shaoguan", "sg", (), False),
    ("绍兴", "shaoxing", "sx", ("shangyu", "上虞"), False),
    ("邵阳", "shaoyang", "shao", (), False),
    ("邵阳县", "shaoyangxian", "syx", (), False),
    ("沙洋", "shayangxian", "shay", ("shayang",), False),
    ("射洪", "shehongxian", "sheh", ("shehong", "yehong", "shihong"), False),
    ("嵊州", "shengzhou", "shzhou", (), False),
    ("神木", "shenmuxian", "shenmu", ("shenmu",), False),
    ("神农架", "shennongjia", "snj", (), False),
    ("沈丘", "shenqiuxian", "shenq", ("chenqiu", "shenqiu"), False),
    ("深圳", "shenzhen", "sz", (), False),
    ("涉县", "shexian", "sxhd", (), False),
    ("射阳", "sheyangxian", "syyc", ("sheyang", "yeyang", "shiyang"), False),
    ("石河子", "shihezi", "shz", ("danhezi",), False),
    ("石狮", "shishi", "shis", ("danshi",), False),
    ("十堰", "shiyan", "shi", (), False),
    ("石嘴山", "shizuishan", "szs", ("danzuishan",), False),
    ("寿光", "shouguang", "shg", (), False),
    ("双峰", "shuangfengxian", "sf", ("shuangfeng",), False),
    ("双鸭山", "shuangyashan", "sys", (), False),
    ("顺德", "shunde", "sd", (), False),
    ("朔州", "shuozhou", "shuo", (), False),
    ("沭阳", "shuyang", "shuy", (), False),
    ("肇东", "shzhaodong", "shzd", ("zhaodong",), False),
    ("泗洪", "sihongxian", "sihong", ("sihong",), False),
    ("四平", "siping", "sip", (), False),
    ("泗阳", "siyangxian", "siyang", ("siyang",), False),
    ("石家庄", "sjz", "sjz", ("danjiezhuang", "shijiezhuang", "shijiazhuang", "danguzhuang", "shiguzhuang", "danjiazhuang", "moji", "wuji", "无极", "xinji", "辛集", "yuanshi", "yuanzhi", "元氏"), False),
    ("松原", "songyuan", "song", (), False),
    ("松滋", "songzi", "songz", (), False),
    ("绥化", "suihua", "sui", (), False),
    ("遂宁", "suining", "sn", (), False),
    ("睢宁", "suiningx", "suiningx", ("suining",), False),
    ("随县", "suixia", "szsx", ("suixian",), False),
    ("睢县", "suixian", "sxsq", (), False),
    ("随州", "suizhou", "suiz", (), False),
    ("宿迁", "suqian", "suq", ("xiuqian",), False),
    ("苏州", "suzhou", "su", (), False),
    ("宿州", "suzhoushi", "suz", ("xiuzhou", "suzhou"), False),
    ("孝义", "sxxiaoyi", "sxxy", ("xiaoyi",), False),
    ("沈阳", "sy", "shen", ("shenyang", "chenyang", "liaozhong", "辽中", "xinmin", "新民"), False),
    ("广水", "szguangshui", "szgs", ("guangshui", "anshui"), False),
    ("泰安", "taian", "ta", (), False),
    ("太仓", "taicang", "taic", (), False),
    ("太康", "taikangxian", "tk", ("taikang",), False),
    ("台山", "taishan", "taish", (), False),
    ("泰兴", "taixing", "taix", (), False),
    ("台州", "taiz", "tai", ("taizhou",), False),
    ("泰州", "taizhou", "tz", (), False),
    ("郯城", "tanchengxian", "tancheng", ("tancheng",), False),
    ("唐山", "tangshan", "ts", ("leting", "yueting", "乐亭", "luanxian", "滦县"), False),
    ("滕州", "tengzhoushi", "tzs", ("tengzhou",), False),
    ("天长", "tianchang", "tch", ("tianzhang",), False),
    ("天津", "tianjin", "tj", (), False),
    ("天门", "tianmen", "tm", (), False),
    ("天水", "tianshui", "tian", (), False),
    ("铁岭", "tieling", "tl", (), False),
    ("开原", "tlkaiyuan", "tlky", ("kaiyuan",), False),
    ("桐城", "tongcheng", "tongc", (), False),
    ("铜川", "tongchuan", "tc", (), False),
    ("通化", "tonghua", "th", (), False),
    ("通辽", "tongliao", "tongl", (), False),
    ("铜陵", "tongling", "tong", (), False),
    ("铜仁", "tongren", "tr", (), False),
    ("桐乡", "tongxiang", "tx", (), False),
    ("通许", "tongxuxian", "tongxu", ("tongxu",), False),
    ("吐鲁番", "tulufan", "tlf", ("tulupan",), False),
    ("图木舒克", "tumushuke", "tmsk", (), False),
    ("屯昌", "tunchang", "tunchang", ("zhunchang",), False),
    ("塔城", "tuscaloosa", "tac", ("dacheng", "tacheng"), False),
    ("太原", "ty", "ty", ("taiyuan",), False),
    ("瓦房店", "wafangdian", "wfd", (), False),
    ("万宁", "wanning", "wann", ("moning",), False),
    ("潍坊", "weifang", "wf", (), False),
    ("威海", "weihai", "wei", (), False),
    ("渭南", "weinan", "wn", ("weina",), False),
    ("微山", "weishanxian", "wsjn", ("weishan",), False),
    ("尉氏", "weishixian", "weishixian", ("yuzhi", "weishi", "yushi", "weizhi"), False),
    ("中卫", "weizhong", "zw", ("zhongwei",), False),
    ("文昌", "wenchang", "wenchangshi", (), False),
    ("文山", "wenshan", "ws", (), False),
    ("汶上", "wenshangxian", "wsj", ("wenshang",), False),
    ("温县", "wenxian", "wenxian", (), False),
    ("温州", "wenzhou", "wz", (), False),
    ("温岭", "wnelingshi", "wls", ("wenling",), False),
    ("武安", "wuanshi", "was", ("wuan",), False),
    ("无棣", "wudi", "wd", ("modi",), False),
    ("乌海", "wuhai", "wuhai", (), False),
    ("武汉", "wuhan", "wh", (), False),
    ("芜湖", "wuhu", "wuh", (), False),
    ("五家渠", "wujiaqu", "wjq", ("wujiequ", "wuguqu"), False),
    ("乌兰察布", "wulanchabu", "wlcb", (), False),
    ("乌鲁木齐", "wulumuqi", "wlmq", ("wulumuji",), False),
    ("武威", "wuwei", "wuwei", (), False),
    ("无为", "wuweixian", "ww", ("wuwei", "mowei"), False),
    ("无锡", "wuxi", "wx", ("moxi",), False),
    ("武穴", "wuxue", "wux", (), False),
    ("武义县", "wuyi", "wy", ("wuyixian",), False),
    ("武夷山", "wuyishan", "wys", (), False),
    ("五指山", "wuzhishan", "wzs", (), False),
    ("吴忠", "wuzhong", "wuz", (), False),
    ("梧州", "wuzhou", "wu", (), False),
    ("西安", "xa", "xa", ("xian", "zhouzhi", "周至", "huxian", "户县", "latian", "lantian", "蓝田"), False),
    ("安陆", "xganlu", "xgal", ("anliu", "anlu"), False),
    ("项城", "xiangchengshi", "xiangch", ("xiangcheng",), False),
    ("香河", "xianghe", "xiangh", (), False),
    ("象山", "xiangshanxian", "xiangshanxian", ("xiangshan",), False),
    ("响水", "xiangshuixian", "xs", ("xiangshui",), False),
    ("湘潭", "xiangtan", "xiang", (), False),
    ("湘西", "xiangxi", "xiangx", (), False),
    ("襄阳", "xiangyang", "xy", (), False),
    ("湘阴", "xiangyin", "xyyy", (), False),
    ("襄垣", "xiangyuanxian", "xiangyuanxian", ("xiangyuan",), False),
    ("咸宁", "xianning", "xiann", (), False),
    ("仙桃", "xiantao", "xiant", (), False),
    ("咸阳", "xianyang", "xiany", (), False),
    ("孝昌", "xiaochangxian", "xiaochang", ("xiaochang",), False),
    ("孝感", "xiaogan", "xg", (), False),
    ("锡林郭勒", "xilinguole", "xl", ("xilinguolei",), False),
    ("新安", "xinan", "xina", (), False),
    ("新昌", "xinchang", "xcsx", (), False),
    ("兴安盟", "xinganmeng", "xam", ("xinganming",), False),
    ("兴化", "xinghuashi", "xh", ("xinghua",), False),
    ("邢台", "xingtai", "xt", (), False),
    ("西宁", "xining", "xn", (), False),
    ("新泰", "xintaishi", "xts", ("xintai",), False),
    ("莘县", "xinxian", "xxlc", ("shenxian",), False),
    ("新乡", "xinxiang", "xx", (), False),
    ("信阳", "xinyang", "xiny", ("shenyang",), False),
    ("新野", "xinyexian", "xyny", ("xinye",), False),
    ("新沂", "xinyishi", "xinyi", ("xinyi",), False),
    ("新余", "xinyu", "xinyu", ("xintu",), False),
    ("忻州", "xinzhou", "xin", (), False),
    ("厦门", "xm", "xm", ("shamen", "xiamen"), False),
    ("沙河", "xtshahe", "xtsh", ("shahe",), False),
    ("宣城", "xuancheng", "xuan", (), False),
    ("宣汉", "xuanhanxian", "xuanhan", ("xuanhan",), False),
    ("宣威", "xuanwei", "xuanw", (), False),
    ("许昌", "xuchang", "xc", (), False),
    ("浚县", "xunxian", "juanxian", ("junxian",), False),
    ("盱眙", "xuyuxian", "xyha", ("xuyi",), False),
    ("徐州", "xuzhou", "xz", (), False),
    ("老河口", "xylaohekou", "xylhk", ("laohekou",), False),
    ("宜城", "xyyicheng", "xyyc", ("yicheng",), False),
    ("沛县", "xzpeixian", "xzpeixian", ("peixian",), False),
    ("雅安", "yaan", "ya", (), False),
    ("延安", "yanan", "yanan", (), False),
    ("延边", "yanbian", "yanb", (), False),
    ("盐城", "yancheng", "yan", (), False),
    ("阳春", "yangchun", "yang", (), False),
    ("阳谷", "yangguxian", "yg", ("yanggu", "yangyu"), False),
    ("阳江", "yangjiang", "yj", (), False),
    ("阳泉", "yangquan", "yq", (), False),
    ("扬中", "yangzhong", "yzh", (), False),
    ("扬州", "yangzhou", "yz", ("jiangdou", "jiangdu", "江都"), False),
    ("燕郊", "yanjiao", "lfyanjiao", (), False),
    ("鄢陵", "yanling", "yanl", (), False),
    ("当阳", "ycdangyang", "ycdy", ("dangyang",), False),
    ("宜宾", "yibin", "yb", (), False),
    ("宜昌", "yichang", "yi", (), False),
    ("伊川", "yichuan", "yichuan", (), False),
    ("宜春", "yichun", "ych", (), False),
    ("伊春", "yichunshi", "yichuns", ("yichun",), False),
    ("宜都", "yidou", "yd", ("yidu",), False),
    ("伊犁", "yili", "yili", (), False),
    ("沂南", "yinanxian", "yn", ("yinan", "yina"), False),
    ("银川", "yinchuan", "yin", (), False),
    ("营口", "yingkou", "yk", (), False),
    ("鹰潭", "yingtan", "ying", (), False),
    ("义乌", "yiwu", "yw", (), False),
    ("宜兴", "yixing", "yix", (), False),
    ("益阳", "yiyang", "yiy", (), False),
    ("沂源", "yiyuanxian", "yiyuan", ("yiyuan",), False),
    ("永春", "yongchun", "yongc", (), False),
    ("永康", "yongkangshi", "yks", ("yongkang",), False),
    ("永新", "yongxin", "yxx", (), False),
    ("永兴", "yongxingxian", "yongxing", ("yongxing",), False),
    ("永州", "yongzhou", "yong", (), False),
    ("攸县", "youxian", "youx", (), False),
    ("烟台", "yt", "yt", ("yintai", "yantai"), False),
    ("乐清", "yueqing", "yue", ("leqing",), False),
    ("岳阳", "yueyang", "yy", (), False),
    ("云浮", "yufu", "yf", ("yunfu",), False),
    ("玉环", "yuhuanxian", "yuhuan", ("yuhuan",), False),
    ("余江", "yujiangc", "yuj", ("yujiang", "tujiang"), False),
    ("榆林", "yulin", "yl", (), False),
    ("玉林", "yulinshi", "yu", ("yulin",), False),
    ("运城", "yuncheng", "yun", (), False),
    ("郓城", "yunchengxian", "yc", ("yuncheng",), False),
    ("云梦", "yunmengxian", "ym", ("yunmeng",), False),
    ("玉树", "yushu", "ys", (), False),
    ("玉田", "yutian", "yut", (), False),
    ("玉溪", "yuxi", "yx", ("yuqi",), False),
    ("余姚", "yuyao", "yuy", ("tuyao",), False),
    ("禹州", "yuzhou", "yuzh", (), False),
    ("沅江", "yyruanjiang", "yyrj", ("yuanjiang",), False),
    ("枣阳", "zaoyangshi", "zys", ("zaoyang",), False),
    ("枣庄", "zaozhuang", "zao", (), False),
    ("泽州", "zezhouxian", "zezhou", ("zezhou",), False),
    ("珠海", "zh", "zh", ("zhuhai",), False),
    ("张北", "zhangbei", "zhangb", (), False),
    ("张家港", "zhangjiagang", "zhjg", ("zhangjiegang", "zhanggugang"), False),
    ("张家界", "zhangjiajie", "zjj", ("zhanggujie", "zhangjiejie"), False),
    ("张家口", "zhangjiakou", "zjk", ("zhanggukou", "zhangjiekou"), False),
    ("漳浦", "zhangpu", "zp", (), False),
    ("章丘", "zhangqiu", "zhq", (), False),
    ("樟树", "zhangshu", "zhsh", (), False),
    ("张掖", "zhangye", "zhangy", ("zhangyi",), False),
    ("漳州", "zhangzhou", "zhang", (), False),
    ("湛江", "zhanjiang", "zhan", (), False),
    ("肇庆", "zhaoqing", "zq", (), False),
    ("昭通", "zhaotong", "zt", (), False),
    ("赵县", "zhaoxian", "zx", (), False),
    ("招远", "zhaoyuanshi", "zhys", ("zhaoyuan",), False),
    ("肇州", "zhaozhou", "zhaoz", (), False),
    ("正定", "zhengding", "zd", (), False),
    ("郑州", "zhengzhou", "zz", ("zhongmu", "zhongmou", "中牟", "gongyi", "巩义"), False),
    ("镇江", "zhenjiang", "zj", (), False),
    ("枝江", "zhijiang", "zhij", ("qijiang",), False),
    ("中国香港", "zhongguoxianggang", "hk", (), True),
    ("周口", "zhoukou", "zk", (), False),
    ("舟山", "zhoushan", "zhou", (), False),
    ("庄河", "zhuanghe", "pld", (), False),
    ("诸城", "zhucheng", "zc", (), False),
    ("诸暨", "zhuji", "zhj", (), False),
    ("驻马店", "zhumadian", "zmd", (), False),
    ("涿州", "zhuozhoushi", "zzs", ("zhuozhou",), False),
    ("株洲", "zhuzhou", "zhu", (), False),
    ("淄博", "zibo", "zb", (), False),
    ("自贡", "zigong", "zg", (), False),
    ("资兴", "zixing", "zixing", (), False),
    ("资阳", "ziyang", "zi", (), False),
    ("邹城", "zouchengshi", "zcs", ("zoucheng",), False),
    ("邹平", "zoupingxian", "zouping", ("zouping",), False),
    ("中山", "zs", "zs", ("zhongshan",), False),
    ("遵化市", "zunhua", "zunh", ("zunhuashi",), False),
    ("遵义", "zunyi", "zy", (), False),
)

CITIES = {}
_CITY_LOOKUP = {}
for _name, _pinyin, _alias, _extra, _new_only in CITY_ROWS:
    CITIES[_pinyin] = {"name": _name, "pinyin": _pinyin, "alias": _alias,
                       "other_pinyin": list(_extra), "new_homes_only": _new_only}
for _name, _pinyin, _alias, _extra, _new_only in CITY_ROWS:
    _CITY_LOOKUP.setdefault(_pinyin, _pinyin)
    _CITY_LOOKUP.setdefault(_name, _pinyin)
# aliases and alternative spellings never shadow another city's pinyin label
for _name, _pinyin, _alias, _extra, _new_only in CITY_ROWS:
    for _key in (_alias, *_extra):
        if _key:
            _CITY_LOOKUP.setdefault(_key, _pinyin)

HOT_CITIES = ("beijing", "shanghai", "guangzhou", "shenzhen", "chengdu", "nanjing",
              "tianjin", "hangzhou", "suzhou", "chongqing", "wuhan", "zhengzhou")


def resolve_city(value):
    """Pinyin host label, short alias or Chinese name -> the pinyin label."""
    value = (value or "").strip()
    if not value:
        raise ValueError("Give a city: its pinyin (beijing), short alias (bj) or Chinese name (北京).")
    key = value.lower().replace("市", "") if not value.isascii() else value.lower()
    pinyin = _CITY_LOOKUP.get(key) or _CITY_LOOKUP.get(value)
    if pinyin is None:
        raise ValueError(f"Unknown city {value!r}: use the pinyin host label (beijing), the short "
                         "alias (bj) or the Chinese name (北京); /anjuke/cities/list has them all.")
    return pinyin


def city_record(pinyin):
    """The public city row: names, links, what the city has."""
    row = CITIES[pinyin]
    new_only = row["new_homes_only"]
    return {
        "name": row["name"],
        "pinyin": pinyin,
        "alias": row["alias"],
        "other_pinyin": row["other_pinyin"],
        "link": None if new_only else pc_host(pinyin) + "/",
        "mobile_link": f"{MOBILE}/{row['alias']}/",
        "new_homes_link": fang_host(pinyin) + "/",
        "has_resale": not new_only,
        "has_rentals": not new_only,
        "has_communities": not new_only,
        "has_new_homes": True,
        "is_hot": pinyin in HOT_CITIES,
    }


def pc_host(city):
    return f"https://{city}.anjuke.com"


def rent_host(city):
    return f"https://{city}.zu.anjuke.com"


def fang_host(city):
    return f"https://{CITIES.get(city, {}).get('alias') or city}.fang.anjuke.com"


def city_alias(city):
    return CITIES.get(city, {}).get("alias") or city


# ---- record references ---------------------------------------------------------------

_DIGITS_RE = re.compile(r"^[SA]?(\d{1,20})$", re.I)
_SALE_LINK_RE = re.compile(r"/(?:prop/view|sale)/([SA]?\d{6,20})(?:[/?#]|$)", re.I)
_RENT_LINK_RE = re.compile(r"/(?:fangyuan|rent)/(\d{6,20})(?:[-x./?#]|$)", re.I)
_COMMUNITY_LINK_RE = re.compile(r"/(?:community/(?:view/)?|gufangjia/xiaoqu-|esf/[a-z]+-cm)(\d{1,12})(?:[/?#.]|$)", re.I)
_PROJECT_LINK_RE = re.compile(r"/(?:loupan/|xf/[a-z]+-lp)(\d{1,12})(?:[/?#.]|$)", re.I)


def _is_anjuke(url):
    host = (urlparse(url).hostname or "").lower()
    return host == "anjuke.com" or host.endswith(".anjuke.com")


def _city_from_link(url):
    """The city a desktop or mobile anjuke link belongs to, or None."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    labels = host.split(".")
    if host in ("m.anjuke.com", "mobile.anjuke.com"):
        first = [p for p in parsed.path.split("/") if p][:1]
        if first and first[0] in _CITY_LOOKUP and first[0] not in ("sale", "rent", "community", "loupan", "xinfang", "esf", "xf"):
            return _CITY_LOOKUP[first[0]]
        match = re.search(r"/(?:esf|xf)/([a-z]+)-(?:cm|lp)\d+", parsed.path)
        if match:
            return _CITY_LOOKUP.get(match.group(1))
        return None
    if len(labels) >= 3 and labels[0] not in ("www", "m", "mobile"):
        return _CITY_LOOKUP.get(labels[0])
    return None


def city_from_link(url):
    """The pinyin city of any desktop or mobile anjuke link, or None. Records
    fetched by a bare id take their city from the page's own links (an id is
    global, so the page is served under any city prefix)."""
    return _city_from_link(url) if url else None


def _resolve_ref(value, link_re, kind, example):
    value = (value or "").strip()
    match = _DIGITS_RE.match(value)
    if match:
        return {"id": _normalize_id(value, kind), "city": None}
    if value.startswith(("http://", "https://", "//")):
        url = value if not value.startswith("//") else "https:" + value
        if not _is_anjuke(url):
            raise ValueError("Must be an anjuke.com link.")
        match = link_re.search(urlparse(url).path)
        if match:
            return {"id": _normalize_id(match.group(1), kind), "city": _city_from_link(url)}
        raise ValueError(f"Must be an anjuke.com {kind} link ({example}).")
    raise ValueError(f"Must be an anjuke {kind} id or an anjuke.com {kind} link ({example}).")


def _normalize_id(raw, kind):
    raw = raw.strip()
    if kind == "listing" and raw[:1].upper() in ("S", "A"):
        # the list pages prefix the 16-digit house id with S (resale) or A
        # (mobile); the bare digits are served at the same route
        return raw[1:]
    return raw.lstrip("SA") if kind == "listing" else raw


def resolve_listing(value):
    """Resale listing: bare id (3048414802945025 / S3048414802945025) or a
    <city>.anjuke.com/prop/view/<id> or m.anjuke.com/<alias>/sale/<id>/ link."""
    return _resolve_ref(value, _SALE_LINK_RE, "listing",
                        "https://beijing.anjuke.com/prop/view/3048414802945025")


def resolve_rental(value):
    """Rental: bare id or a <alias>.zu.anjuke.com/fangyuan/<id> or
    m.anjuke.com/<alias>/rent/<id>-3/ link."""
    return _resolve_ref(value, _RENT_LINK_RE, "rental",
                        "https://bj.zu.anjuke.com/fangyuan/4732633159429128")


def resolve_community(value):
    """Community (小区): bare id or a community/view/<id>,
    gufangjia/xiaoqu-<id>/ or m.anjuke.com/<alias>/community/<id>/ link."""
    return _resolve_ref(value, _COMMUNITY_LINK_RE, "community",
                        "https://beijing.anjuke.com/community/view/53195")


def resolve_project(value):
    """New-home project (楼盘): bare id or a <alias>.fang.anjuke.com/loupan/<id>.html
    or m.anjuke.com/<alias>/loupan/<id>/ link."""
    return _resolve_ref(value, _PROJECT_LINK_RE, "project",
                        "https://bj.fang.anjuke.com/loupan/523824.html")


# ---- canonical links -----------------------------------------------------------------

def listing_link(city, listing_id):
    return f"{pc_host(city or 'beijing')}/prop/view/{listing_id}"


def listing_mobile_link(city, listing_id):
    return f"{MOBILE}/{city_alias(city or 'beijing')}/sale/{listing_id}/"


def rental_link(city, rental_id):
    return f"https://{city_alias(city or 'beijing')}.zu.anjuke.com/fangyuan/{rental_id}"


def rental_mobile_link(city, rental_id):
    return f"{MOBILE}/{city_alias(city or 'beijing')}/rent/{rental_id}-3/"


def community_link(city, community_id):
    return f"{pc_host(city or 'beijing')}/community/view/{community_id}"


def community_mobile_link(city, community_id):
    return f"{MOBILE}/{city_alias(city or 'beijing')}/community/{community_id}/"


def project_link(city, project_id):
    return f"{fang_host(city or 'beijing')}/loupan/{project_id}.html"


def project_mobile_link(city, project_id):
    return f"{MOBILE}/{city_alias(city or 'beijing')}/loupan/{project_id}/"


# ---- resale (二手房) list grammar -----------------------------------------------------
# <city>.anjuke.com/sale/<district>[-q-<area>]/<mark><value>-...-p<N>/?prices=a_b&areas=a_b&kw=..&comm_id=..
# Marks and ids are the site's own filter block (sale list __NUXT__ `filter`,
# Beijing 2026-10-30); the rooms / type / age / fitment / orientation /
# floor / property-type ids are global, the price and area buckets are per
# city and the custom ranges go in the query string instead (the path form
# m200_300 is ignored by the server; ?prices=200_300 is honoured and shows
# up as listParams.isPricesCustom). Metro filters share the "b" mark with
# rooms and are not exposed.

SALE_ROOMS = {"1": "b15", "2": "b17", "3": "b23", "4": "b24", "5": "b25", "6": "b26"}
SALE_TYPES = {"residential": "t9", "apartment": "t7", "villa": "t8", "bungalow": "t12", "other": "t10"}
SALE_AGES = {"under_2": "y1", "2_5": "y2", "5_10": "y3", "over_10": "y4"}
SALE_FITMENTS = {"rough": "d5", "simple": "d6", "fine": "d7", "luxury": "d8"}
SALE_ORIENTATIONS = {"east": "l1", "south": "l2", "west": "l3", "north": "l4", "southeast": "l5",
                     "northeast": "l6", "southwest": "l7", "northwest": "l8", "north_south": "l9",
                     "east_west": "l10"}
SALE_FLOOR_LEVELS = {"ground": "fl1", "low": "fl2", "middle": "fl3", "high": "fl4", "top": "fl5"}
SALE_PROPERTY_TYPES = {"commercial_housing": "z1", "mixed_use": "z2", "affordable": "z3", "public": "z5",
                       "relocation": "z782513", "other": "z6"}
SALE_FEATURES = {"near_metro": "dt1", "over_5_years": "oy1", "over_2_years": "oy2", "verified": "fv1",
                 "vr": "v3", "owner_urgent": "ls1"}
SALE_SORTS = {"default": None, "price_asc": "o4", "price_desc": "o5", "area_desc": "o2"}
SALE_RINGS = {"inside_2nd": "f1", "2nd_3rd": "f2", "3rd_4th": "f3", "4th_5th": "f4", "5th_6th": "f5",
              "outside_6th": "f6"}
SALE_PAGE_SIZE = 60
SALE_MAX_PAGE = 50        # the server clamps p51+ back to page 1
OPEN_BOUND = 2147483640   # the site's own "no upper bound" sentinel (value_str "1000_2147483640")

SLUG_RE = re.compile(r"^[a-z][a-z0-9]{0,40}$")


def area_segment(district=None, area=None):
    """'chaoyang' / 'chaoyang-q-cbd' / None."""
    if not district:
        return None
    return f"{district}-q-{area}" if area else district


def marks_segment(marks, page=1):
    parts = [m for m in marks if m]
    if page and page > 1:
        parts.append(f"p{page}")
    return "-".join(parts) if parts else None


def range_param(low, high):
    """'200_300' / '200_2147483640' / '0_300' / None for an open range."""
    if low is None and high is None:
        return None
    lo = int(low or 0)
    hi = int(high) if high is not None else OPEN_BOUND
    return f"{lo}_{hi}"


def sale_path(city, district=None, area=None, marks=(), page=1, query=None):
    segments = [s for s in (area_segment(district, area), marks_segment(marks, page)) if s]
    path = "/sale/" + "".join(s + "/" for s in segments)
    return pc_host(city) + path + _query_string(query)


def _query_string(query):
    if not query:
        return ""
    pairs = [f"{k}={quote(str(v), safe='_')}" for k, v in query.items() if v not in (None, "")]
    return "?" + "&".join(pairs) if pairs else ""


# ---- communities (小区) list grammar ---------------------------------------------------
# <city>.anjuke.com/community/<district>[-q-<area>]/<marks>-p<N>/?kw=..
# (community list __NUXT__ `filter`, Beijing 2026-10-30: age f1-6 and sort
# o1-4/9/10 are global; the unit-price buckets (m239..) and brands (w1000..)
# are per city and not exposed).
COMMUNITY_AGES = {"under_5": "f1", "5_10": "f2", "10_15": "f3", "15_20": "f4", "20_30": "f5", "over_30": "f6"}
COMMUNITY_SORTS = {"default": None, "price_asc": "o1", "price_desc": "o2", "popularity_asc": "o3",
                   "popularity_desc": "o4", "score_desc": "o10", "score_asc": "o9"}
COMMUNITY_FEATURES = {"near_metro": "s200", "video": "s204"}
COMMUNITY_PAGE_SIZE = 25
COMMUNITY_MAX_PAGE = 50   # like resale, page 51+ is served as page 1 (Shanghai, 2026-11-02)


def community_list_path(city, district=None, area=None, marks=(), page=1, query=None):
    segments = [s for s in (area_segment(district, area), marks_segment(marks, page)) if s]
    path = "/community/" + "".join(s + "/" for s in segments)
    return pc_host(city) + path + _query_string(query)


def community_price_link(city, community_id):
    return f"{pc_host(city or 'beijing')}/gufangjia/xiaoqu-{community_id}/"


# ---- rentals (租房) mobile list grammar ------------------------------------------------
# m.anjuke.com/<alias>/rent/<district>[-q-<area>]|all/a<min>_<max>-b<rooms>-<type>-<fitment>-f<source>/
# (the filter links of m.anjuke.com/bj/rent/, 2026-10-30/31: a = monthly
# rent band in yuan, b = bedrooms 1-5 (5 = five or more), 3rd field 1 整租 /
# 2 合租, 4th field fitment 1 毛坯 / 2 简单装修 / 3 精装修 / 4 豪华装修, f1 经纪人
# / f2 个人 房源).
#
# The rendered page is NOT paginated: ?page=N serves the same 30 rentals
# reshuffled (pages 1-3 of Shanghai shared 21-28 of 30, 2026-11-02). Paging
# is the page's own "load more" XHR, RENT_API (zufang/m/house/
# api_houselist_data_Jgs?page=N&search_firstpage=1&search_param=<json>), fed
# with the `search_param` object the rendered page carries for its path (58
# city id, district / business-area ids, rent band, rooms, type...). It
# returns 30 rows a page plus the live total, and stops at page 116
# (Shanghai, 2026-11-02: page 116 full, 117 empty) — about 3,480 rentals per
# query. The desktop list (<alias>.zu.anjuke.com/fangyuan/p2/) is the geetest
# wall on every exit and profile (18/18, 2026-11-02).
RENT_TYPES = {"whole": "1", "shared": "2"}
RENT_FITMENTS = {"rough": "1", "simple": "2", "fine": "3", "luxury": "4"}
RENT_SOURCES = {"agent": "1", "owner": "2"}
RENT_PAGE_SIZE = 30
RENT_MAX_PAGE = 116
RENT_API = MOBILE + "/zufang/m/house/api_houselist_data_Jgs"


def rent_list_path(city, district=None, area=None, rent_min=None, rent_max=None, rooms=None,
                   rental_type=None, fitment=None, source=None):
    """The rendered rental list page for a filter set (its search_param feeds RENT_API)."""
    where = area_segment(district, area) or "all"
    band = f"a{int(rent_min or 0)}_{int(rent_max or 0)}"
    filters = f"{band}-b{rooms or 0}-{rental_type or 0}-{fitment or 0}-f{source or 0}"
    return f"{MOBILE}/{city_alias(city)}/rent/{where}/{filters}/"


# ---- new homes (新房 / 楼盘) mobile list grammar -------------------------------------------
# m.anjuke.com/<alias>/loupan/<district>|all/<marks joined by ->/
# (the filter links of m.anjuke.com/bj/loupan/all/, 2026-10-30/31). The
# per-m² price buckets (d7279..) and ring roads (loopline19..) are per city
# and not exposed; the rest is global.
#
# The rendered page is NOT paginated (/p2/ serves page 1 again, 2026-11-02).
# Paging is the page's own XHR, LOUPAN_API (xinfang/api/loupan/list/?args=
# <json>&location_url=<page url>), whose args object is the rendered page's
# state.loupan.loupan.params: {"cid": <new-home city id>, "page": N,
# "pageSize": 20, "args": {"regions": {"<district>": ""}, "<mark letter>":
# "<mark value>", ...}, ...}. Several feature marks go in as one
# comma-joined value and match projects with ANY of them (q=9,56 -> 1,357 =
# q=9 715 + q=56 932 - overlap, Shanghai 2026-11-02). It serves every
# project (Shanghai: 2,248 = 113 pages, page 113 holds 8, 114 is empty).
LOUPAN_STATUSES = {"on_sale": "a1", "upcoming": "a2", "sold_out": "a4", "tail": "a6", "new_permit": "a105"}
LOUPAN_ROOMS = {"1": "h1", "2": "h2", "3": "h3", "4": "h4", "5": "h5"}
LOUPAN_SIZES = {"under_70": "m562", "70_90": "m563", "90_120": "m564", "120_140": "m565",
                "140_160": "m566", "160_200": "m567", "over_200": "m568"}
LOUPAN_PROPERTY_TYPES = {"residential": "w1", "low_density": "w2", "commercial": "w3", "shop": "w4", "office": "w5"}
LOUPAN_OPENINGS = {"this_month": "o1", "next_month": "o2", "next_3_months": "o3", "last_month": "o5", "opened": "o8"}
LOUPAN_DELIVERIES = {"ready": "n9", "within_1_month": "n10", "within_3_months": "n11", "within_6_months": "n12"}
LOUPAN_FITMENTS = {"rough": "z1", "simple": "z2", "furnished": "z3"}
LOUPAN_FEATURES = {"brand_developer": "q50", "near_metro": "q9", "parking": "q56", "near_school": "q69",
                   "state_owned": "q482", "popular": "q9997", "vr": "q263"}
# s1 / s2 / s4 are on every city's page (均价从低到高 / 均价从高到低 / 开盘时间倒序);
# the rest are per city (Shanghai s10-s12 认购, Beijing s14-s17 摇号, 2026-11-02).
LOUPAN_SORTS = {"default": None, "price_asc": "s1", "price_desc": "s2", "opening_desc": "s4"}
LOUPAN_PAGE_SIZE = 20
LOUPAN_API = MOBILE + "/xinfang/api/loupan/list/"
_MARK_RE = re.compile(r"^([a-z]+)(\d+)$")


def loupan_list_path(city, district=None, marks=()):
    where = district or "all"
    url = f"{MOBILE}/{city_alias(city)}/loupan/{where}/"
    marks = [m for m in marks if m]
    if marks:
        url += "-".join(marks) + "/"
    return url


def loupan_args(district=None, marks=()):
    """The XHR's filter object for a district slug + url marks: {"regions":
    {"pudong": ""}, "a": "1", "q": "9,56", ...} (repeated letters join with ",")."""
    args = {}
    if district:
        args["regions"] = {district: ""}
    for mark in marks:
        match = _MARK_RE.match(mark or "")
        if not match:
            continue
        letter, value = match.groups()
        args[letter] = f"{args[letter]},{value}" if letter in args else value
    return args


def loupan_query(cid, args, page):
    """The full params object LOUPAN_API takes as its JSON `args` parameter."""
    return {"cid": cid, "kw": "", "page": page, "pageSize": LOUPAN_PAGE_SIZE, "args": args,
            "commerce": 0, "commerce_type": 0, "school_id": None, "seoPage": None}


def loupan_page_link(city, project_id, sub=""):
    return f"{MOBILE}/{city_alias(city or 'beijing')}/loupan/{project_id}/{sub}"
