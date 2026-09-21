"""A-share–first sector lexicon: keywords → board / ETF hints.

Global macro/geopolitical keywords are included but mapped to A-share
transmission channels (what local boards may move).
"""

from __future__ import annotations

from typing import Any

# Each rule: keywords (any hit), sector name, optional ETF codes, weight, region bias.
# BOARD_ALIASES: needles matched against East Money industry/concept board names.
BOARD_ALIASES: dict[str, list[str]] = {
    "半导体": ["半导体", "芯片", "集成电路", "电子元件"],
    "人工智能": ["人工智能", "软件开发", "计算机设备"],
    "通信": ["通信设备", "通信服务", "5G"],
    "新能源/锂电": ["电池", "光伏设备", "风电设备", "储能", "锂电"],
    "创新药/医药": ["化学制药", "生物制品", "医疗器械", "中药", "医药"],
    "白酒/消费": ["白酒", "啤酒", "食品饮料", "旅游"],
    "银行": ["银行"],
    "证券": ["证券"],
    "房地产": ["房地产开发", "房地产服务", "装修装饰"],
    "煤炭": ["煤炭行业", "煤炭"],
    "有色/贵金属": ["有色金属", "贵金属", "小金属", "能源金属"],
    "石油石化": ["石油行业", "油气开采", "炼化", "油服工程"],
    "军工": ["航天航空", "船舶制造", "军工"],
    "电力/公用": ["电力行业", "电网设备", "公用事业"],
    "农业": ["农牧饲渔", "种植业", "养殖业"],
    "红利/高股息": ["银行", "煤炭行业", "电力行业"],
    "大盘/宏观": [],  # no single board
    "港股科技映射": ["互联网服务", "软件开发"],
    "美股映射/风险偏好": [],
}

SECTOR_RULES: list[dict[str, Any]] = [
    {
        "sector": "半导体",
        "etfs": ["512480", "159995"],
        "weight": 1.2,
        "priority": "A",
        "keywords": [
            "半导体", "芯片", "光刻", "存储芯片", "HBM", "先进封装", "EDA",
            "台积电", "中芯国际", "寒武纪", "英伟达", "NVIDIA", "GPU",
            "出口管制", "实体清单", "制裁芯片",
        ],
    },
    {
        "sector": "人工智能",
        "etfs": ["159819", "515980"],
        "weight": 1.15,
        "priority": "A",
        "keywords": [
            "人工智能", "AI", "大模型", "算力", "ChatGPT", "DeepSeek",
            "智能驾驶", "机器人", "人形机器人",
        ],
    },
    {
        "sector": "通信",
        "etfs": ["515050"],
        "weight": 1.1,
        "priority": "A",
        "keywords": ["5G", "6G", "光模块", "CPO", "光纤", "运营商", "电信", "移动", "联通"],
    },
    {
        "sector": "新能源/锂电",
        "etfs": ["516160", "159755"],
        "weight": 1.05,
        "priority": "A",
        "keywords": [
            "新能源", "光伏", "风电", "储能", "锂电池", "碳酸锂", "宁德时代",
            "新能源汽车", "充电桩", "固态电池",
        ],
    },
    {
        "sector": "创新药/医药",
        "etfs": ["512010", "513120"],
        "weight": 1.1,
        "priority": "A",
        "keywords": [
            "创新药", "医药", "CXO", "集采", "药监", "FDA", "临床试验",
            "减肥药", "GLP-1", "中药", "医疗器械",
        ],
    },
    {
        "sector": "白酒/消费",
        "etfs": ["159928"],
        "weight": 1.0,
        "priority": "A",
        "keywords": ["白酒", "茅台", "五粮液", "消费", "社零", "免税", "旅游", "酒店"],
    },
    {
        "sector": "银行",
        "etfs": ["512800"],
        "weight": 1.0,
        "priority": "A",
        "keywords": ["银行", "净息差", "降准", "MLF", "LPR", "信贷", "坏账"],
    },
    {
        "sector": "证券",
        "etfs": ["512880"],
        "weight": 1.05,
        "priority": "A",
        "keywords": ["券商", "证券", "IPO", "注册制", "两融", "成交额", "印花税"],
    },
    {
        "sector": "房地产",
        "etfs": ["512200"],
        "weight": 1.0,
        "priority": "A",
        "keywords": ["房地产", "楼市", "房贷", "保交楼", "城中村", "土地出让", "住建"],
    },
    {
        "sector": "煤炭",
        "etfs": ["515220"],
        "weight": 1.05,
        "priority": "A",
        "keywords": ["煤炭", "动力煤", "焦煤", "煤价", "电厂日耗"],
    },
    {
        "sector": "有色/贵金属",
        "etfs": ["512400", "518880"],
        "weight": 1.1,
        "priority": "A",
        "keywords": ["黄金", "白银", "铜", "铝", "稀土", "锂", "钴", "镍", "金价"],
    },
    {
        "sector": "石油石化",
        "etfs": ["159930"],
        "weight": 1.1,
        "priority": "A",
        "keywords": ["原油", "油价", "OPEC", "布伦特", "WTI", "成品油", "石化", "中石油", "中石化"],
    },
    {
        "sector": "军工",
        "etfs": ["512660"],
        "weight": 1.15,
        "priority": "A",
        "keywords": ["军工", "国防", "航天", "航空", "导弹", "舰船", "卫星", "大飞机"],
    },
    {
        "sector": "电力/公用",
        "etfs": ["159611"],
        "weight": 0.95,
        "priority": "A",
        "keywords": ["电力", "火电", "水电", "核电", "电网", "电价", "抽水蓄能"],
    },
    {
        "sector": "农业",
        "etfs": ["159825"],
        "weight": 1.0,
        "priority": "A",
        "keywords": ["粮食", "大豆", "玉米", "猪肉", "养殖", "化肥", "种子", "农产品"],
    },
    {
        "sector": "红利/高股息",
        "etfs": ["510880"],
        "weight": 0.9,
        "priority": "A",
        "keywords": ["高股息", "分红", "红利", "央企改革", "中特估"],
    },
    # Global → A-share transmission
    {
        "sector": "大盘/宏观",
        "etfs": ["510300", "510500"],
        "weight": 0.85,
        "priority": "A",
        "keywords": [
            "降息", "加息", "美联储", "Fed", "CPI", "非农", "衰退", "通胀",
            "人民币", "汇率", "北向资金", "外资", "稳增长", "财政", "专项债",
        ],
    },
    {
        "sector": "港股科技映射",
        "etfs": ["513180", "513050"],
        "weight": 0.95,
        "priority": "HK",
        "keywords": ["港股", "恒生", "腾讯", "阿里", "美团", "南向", "互联互通"],
    },
    {
        "sector": "美股映射/风险偏好",
        "etfs": ["513100", "159941"],
        "weight": 0.8,
        "priority": "US",
        "keywords": [
            "纳斯达克", "标普", "道琼斯", "美股", "标普500", "纳指",
            "科技股大涨", "科技股大跌",
        ],
    },
]
