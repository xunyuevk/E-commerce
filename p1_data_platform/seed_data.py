"""P1 原始种子数据（模拟从业务系统/文件采集来的原始数据，含 PII，需脱敏）。

说明：
  - 引用用 cid/sku 等业务键，不用 PII 做关联键（数据建模好习惯）；
  - 这些数据会走完整「采集 → 清洗 → 脱敏 → 资产化」流水线，而不是直接 INSERT，
    以便演示数据资产平台的真实职责。
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# 客户（含 PII：姓名/手机/邮箱/身份证/城市，脱敏后落 customer 表）
# ---------------------------------------------------------------------------
RAW_CUSTOMERS = [
    {"cid": 1, "name": "张伟", "phone": "13812340001", "email": "zhangwei@example.com", "idcard": "110101199001011234", "city": "北京", "level": "gold"},
    {"cid": 2, "name": "李娜", "phone": "13912340002", "email": "lina@example.com", "idcard": "310101199202022345", "city": "上海", "level": "platinum"},
    {"cid": 3, "name": "王强", "phone": "13712340003", "email": "wangqiang@example.com", "idcard": "440101198803033456", "city": "广州", "level": "normal"},
    {"cid": 4, "name": "刘洋", "phone": "13612340004", "email": "liuyang@example.com", "idcard": "510101199504044567", "city": "成都", "level": "silver"},
    {"cid": 5, "name": "陈静", "phone": "13512340005", "email": "chenjing@example.com", "idcard": "320101199706055678", "city": "南京", "level": "normal"},
    {"cid": 6, "name": "杨帆", "phone": "13412340006", "email": "yangfan@example.com", "idcard": "330101199808066789", "city": "杭州", "level": "gold"},
    {"cid": 7, "name": "赵敏", "phone": "13312340007", "email": "zhaomin@example.com", "idcard": "420101199309077890", "city": "武汉", "level": "normal"},
    {"cid": 8, "name": "孙磊", "phone": "13212340008", "email": "sunlei@example.com", "idcard": "610101199101088901", "city": "西安", "level": "silver"},
    {"cid": 9, "name": "周芳", "phone": "13112340009", "email": "zhoufang@example.com", "idcard": "210101199212099012", "city": "沈阳", "level": "normal"},
    {"cid": 10, "name": "吴昊", "phone": "13012340010", "email": "wuhao@example.com", "idcard": "370101199409101023", "city": "青岛", "level": "gold"},
    {"cid": 11, "name": "徐婷", "phone": "18812340011", "email": "xuting@example.com", "idcard": "500101199507111134", "city": "重庆", "level": "normal"},
    {"cid": 12, "name": "马超", "phone": "18712340012", "email": "machao@example.com", "idcard": "350101199603121245", "city": "厦门", "level": "silver"},
    {"cid": 13, "name": "胡雪", "phone": "18612340013", "email": "huxue@example.com", "idcard": "430101199810131356", "city": "长沙", "level": "normal"},
    {"cid": 14, "name": "郭涛", "phone": "18512340014", "email": "guotao@example.com", "idcard": "530101199205141467", "city": "昆明", "level": "normal"},
    {"cid": 15, "name": "林悦", "phone": "18412340015", "email": "linyue@example.com", "idcard": "450101199311151578", "city": "南宁", "level": "gold"},
    {"cid": 16, "name": "何晨", "phone": "18312340016", "email": "hechen@example.com", "idcard": "140101199612161689", "city": "太原", "level": "normal"},
    {"cid": 17, "name": "高翔", "phone": "18212340017", "email": "gaoxiang@example.com", "idcard": "230101199708171790", "city": "哈尔滨", "level": "silver"},
    {"cid": 18, "name": "罗倩", "phone": "18112340018", "email": "luoqian@example.com", "idcard": "360101199909181801", "city": "南昌", "level": "normal"},
    {"cid": 19, "name": "郑爽", "phone": "18012340019", "email": "zhengshuang@example.com", "idcard": "340101199104191912", "city": "合肥", "level": "normal"},
    {"cid": 20, "name": "谢军", "phone": "17612340020", "email": "xiejun@example.com", "idcard": "620101199508202023", "city": "兰州", "level": "gold"},
]

# ---------------------------------------------------------------------------
# 商品
# ---------------------------------------------------------------------------
RAW_PRODUCTS = [
    {"sku": "SPK-001", "name": "小音智能音箱 Pro", "category": "智能家居", "brand": "小音", "price": 299.00, "stock": 520, "description": "智能语音音箱，支持远场唤醒与多设备联动，音质升级。", "specs": {"color": "黑/白", "wifi": "双频"}},
    {"sku": "SPK-002", "name": "小音智能音箱 Mini", "category": "智能家居", "brand": "小音", "price": 149.00, "stock": 1200, "description": "入门款智能音箱，小体积大音量，适合卧室。", "specs": {"color": "白", "wifi": "2.4G"}},
    {"sku": "SWP-001", "name": "扫地机器人 S1", "category": "智能家居", "brand": "净家", "price": 1999.00, "stock": 180, "description": "激光导航扫地机器人，支持拖扫一体与 APP 划区。", "specs": {"battery": "5200mAh", "suction": "3000Pa"}},
    {"sku": "AFR-001", "name": "空气炸锅 5L", "category": "厨房电器", "brand": "厨享", "price": 399.00, "stock": 340, "description": "5L 大容量空气炸锅，无油低脂，可视窗口。", "specs": {"capacity": "5L", "power": "1500W"}},
    {"sku": "EAR-001", "name": "真无线蓝牙耳机 X", "category": "数码配件", "brand": "声动", "price": 499.00, "stock": 800, "description": "主动降噪真无线耳机，续航 30 小时。", "specs": {"anc": "支持", "battery": "30h"}},
    {"sku": "EAR-002", "name": "运动蓝牙耳机 Y", "category": "数码配件", "brand": "声动", "price": 199.00, "stock": 1500, "description": "IPX5 防水运动耳机，挂耳式防脱落。", "specs": {"waterproof": "IPX5"}},
    {"sku": "PWR-001", "name": "10000mAh 快充充电宝", "category": "数码配件", "brand": "能量", "price": 129.00, "stock": 2200, "description": "10000mAh 双向快充，兼容 PD/QC 协议。", "specs": {"capacity": "10000mAh", "protocol": "PD/QC"}},
    {"sku": "CUP-001", "name": "316 不锈钢保温杯", "category": "家居日用", "brand": "暖阳", "price": 89.00, "stock": 900, "description": "316 不锈钢内胆，保温 12 小时。", "specs": {"capacity": "500ml", "material": "316"}},
    {"sku": "LMP-001", "name": "护眼台灯", "category": "家居日用", "brand": "明眸", "price": 159.00, "stock": 600, "description": "国 AA 级照度，无频闪，三档色温。", "specs": {"level": "国AA", "color_temp": "3档"}},
    {"sku": "FAC-001", "name": "氨基酸洗面奶", "category": "个护美妆", "brand": "净颜", "price": 79.00, "stock": 3000, "description": "氨基酸温和洁面，敏感肌可用。", "specs": {"volume": "120g"}},
    {"sku": "FAC-002", "name": "补水面膜 10 片装", "category": "个护美妆", "brand": "水润", "price": 99.00, "stock": 1800, "description": "玻尿酸补水面膜，深层锁水。", "specs": {"count": "10片"}},
    {"sku": "NUT-001", "name": "每日坚果 30 包", "category": "食品饮料", "brand": "果粒", "price": 129.00, "stock": 2500, "description": "科学配比每日坚果，独立小包。", "specs": {"count": "30包"}},
]

# ---------------------------------------------------------------------------
# 订单（items 里用 sku 关联商品；customer 用 cid 关联）
# ---------------------------------------------------------------------------
RAW_ORDERS = [
    {"order_no": "SO20240101001", "cid": 1, "status": "delivered", "channel": "app", "items": [{"sku": "SPK-001", "quantity": 1, "price": 299.00}]},
    {"order_no": "SO20240102002", "cid": 2, "status": "delivered", "channel": "app", "items": [{"sku": "SWP-001", "quantity": 1, "price": 1999.00}, {"sku": "CUP-001", "quantity": 2, "price": 89.00}]},
    {"order_no": "SO20240103003", "cid": 3, "status": "shipped", "channel": "web", "items": [{"sku": "EAR-001", "quantity": 1, "price": 499.00}]},
    {"order_no": "SO20240104004", "cid": 4, "status": "delivered", "channel": "app", "items": [{"sku": "AFR-001", "quantity": 1, "price": 399.00}]},
    {"order_no": "SO20240105005", "cid": 5, "status": "refunding", "channel": "app", "items": [{"sku": "PWR-001", "quantity": 1, "price": 129.00}]},
    {"order_no": "SO20240106006", "cid": 6, "status": "delivered", "channel": "web", "items": [{"sku": "LMP-001", "quantity": 1, "price": 159.00}]},
    {"order_no": "SO20240107007", "cid": 7, "status": "delivered", "channel": "app", "items": [{"sku": "FAC-001", "quantity": 2, "price": 79.00}]},
    {"order_no": "SO20240108008", "cid": 8, "status": "refunded", "channel": "app", "items": [{"sku": "EAR-002", "quantity": 1, "price": 199.00}]},
    {"order_no": "SO20240109009", "cid": 9, "status": "delivered", "channel": "web", "items": [{"sku": "NUT-001", "quantity": 1, "price": 129.00}]},
    {"order_no": "SO20240110010", "cid": 10, "status": "delivered", "channel": "app", "items": [{"sku": "SPK-002", "quantity": 2, "price": 149.00}]},
    {"order_no": "SO20240111011", "cid": 11, "status": "shipped", "channel": "app", "items": [{"sku": "SWP-001", "quantity": 1, "price": 1999.00}]},
    {"order_no": "SO20240112012", "cid": 12, "status": "delivered", "channel": "web", "items": [{"sku": "CUP-001", "quantity": 1, "price": 89.00}]},
    {"order_no": "SO20240113013", "cid": 13, "status": "delivered", "channel": "app", "items": [{"sku": "EAR-001", "quantity": 1, "price": 499.00}]},
    {"order_no": "SO20240114014", "cid": 14, "status": "refunding", "channel": "app", "items": [{"sku": "AFR-001", "quantity": 1, "price": 399.00}]},
    {"order_no": "SO20240115015", "cid": 15, "status": "delivered", "channel": "web", "items": [{"sku": "PWR-001", "quantity": 1, "price": 129.00}]},
    {"order_no": "SO20240116016", "cid": 16, "status": "delivered", "channel": "app", "items": [{"sku": "LMP-001", "quantity": 1, "price": 159.00}]},
    {"order_no": "SO20240117017", "cid": 17, "status": "delivered", "channel": "app", "items": [{"sku": "FAC-002", "quantity": 3, "price": 99.00}]},
    {"order_no": "SO20240118018", "cid": 18, "status": "delivered", "channel": "web", "items": [{"sku": "NUT-001", "quantity": 2, "price": 129.00}]},
    {"order_no": "SO20240119019", "cid": 19, "status": "shipped", "channel": "app", "items": [{"sku": "SPK-001", "quantity": 1, "price": 299.00}]},
    {"order_no": "SO20240120020", "cid": 20, "status": "delivered", "channel": "app", "items": [{"sku": "EAR-001", "quantity": 1, "price": 499.00}]},
]

# ---------------------------------------------------------------------------
# 客服会话 + 消息（customer 用 cid；P5 会从这里抽取微调语料）
# ---------------------------------------------------------------------------
RAW_CONVERSATIONS = [
    {
        "conversation_no": "CV20240101001", "cid": 1, "channel": "online", "intent": "咨询",
        "satisfaction": 5, "messages": [
            {"role": "customer", "content": "你好，我想问一下小音智能音箱 Pro 支持连接蓝牙吗？"},
            {"role": "agent", "content": "您好，小音智能音箱 Pro 支持蓝牙 5.0 连接，同时也支持 Wi-Fi 双频，您可以放心使用哦。"},
            {"role": "customer", "content": "好的，那和手机连接稳定吗？"},
            {"role": "agent", "content": "蓝牙 5.0 传输更稳定、延迟更低，正常环境下十米内连接都很稳定。"},
        ],
    },
    {
        "conversation_no": "CV20240102002", "cid": 2, "channel": "online", "intent": "售后",
        "satisfaction": 4, "messages": [
            {"role": "customer", "content": "我买的扫地机器人 S1 用了一个月，现在吸力变小了，怎么回事？"},
            {"role": "agent", "content": "您好，很抱歉给您带来不便。吸力变小通常是滤网或滚刷缠绕异物导致，建议您先清理尘盒和滤网。"},
            {"role": "customer", "content": "清理过了，还是感觉小。"},
            {"role": "agent", "content": "那可能是主刷磨损，我帮您登记一个售后工单，工程师会联系您安排检测或更换主刷。"},
        ],
    },
    {
        "conversation_no": "CV20240103003", "cid": 3, "channel": "online", "intent": "物流",
        "satisfaction": 5, "messages": [
            {"role": "customer", "content": "我的耳机什么时候发货？订单号 SO20240103003。"},
            {"role": "agent", "content": "您好，您的订单已出库，预计今天 18:00 前由顺丰揽收，物流单号稍后短信通知您。"},
        ],
    },
    {
        "conversation_no": "CV20240104004", "cid": 5, "channel": "online", "intent": "退款",
        "satisfaction": 3, "messages": [
            {"role": "customer", "content": "我买的充电宝不满意，想退款，怎么操作？"},
            {"role": "agent", "content": "您好，商品签收 7 天内支持无理由退货。您在订单详情页点击申请退款即可，审核通过后 1-3 个工作日原路退回。"},
            {"role": "customer", "content": "那邮费谁出？"},
            {"role": "agent", "content": "非质量问题退货，运费需要您承担；若为质量问题，我们承担运费并优先为您换新。"},
        ],
    },
    {
        "conversation_no": "CV20240105005", "cid": 8, "channel": "online", "intent": "投诉",
        "satisfaction": 2, "messages": [
            {"role": "customer", "content": "你们家的运动耳机用了两周就开不了机，我要投诉！"},
            {"role": "agent", "content": "非常抱歉给您带来不好的体验，我马上为您升级处理，先帮您登记换新，同时记录您的投诉意见。"},
            {"role": "customer", "content": "希望尽快解决。"},
            {"role": "agent", "content": "明白，已为您加急，客服主管会在 2 小时内电话回访您。"},
        ],
    },
    {
        "conversation_no": "CV20240106006", "cid": 10, "channel": "online", "intent": "咨询",
        "satisfaction": 5, "messages": [
            {"role": "customer", "content": "保温杯是 316 不锈钢的吗？能装牛奶吗？"},
            {"role": "agent", "content": "是的，内胆为 316 不锈钢，可装牛奶、咖啡等饮品，建议 6 小时内饮用完毕并及时清洗。"},
        ],
    },
    {
        "conversation_no": "CV20240107007", "cid": 12, "channel": "online", "intent": "咨询",
        "satisfaction": 4, "messages": [
            {"role": "customer", "content": "洗面奶适合敏感肌吗？会不会紧绷？"},
            {"role": "agent", "content": "这款氨基酸洗面奶温和不刺激，敏感肌可用，清洁后不紧绷；如出现不适请立即停用并咨询医生。"},
        ],
    },
    {
        "conversation_no": "CV20240108008", "cid": 15, "channel": "online", "intent": "物流",
        "satisfaction": 5, "messages": [
            {"role": "customer", "content": "我的充电宝显示签收了但我没收到，能帮我查一下吗？"},
            {"role": "agent", "content": "好的，我帮您核查物流，请稍等。已联系快递，反馈放在门卫处，您方便时去取一下；如未找到我们 24 小时内补发。"},
        ],
    },
    {
        "conversation_no": "CV20240109009", "cid": 17, "channel": "online", "intent": "售后",
        "satisfaction": 4, "messages": [
            {"role": "customer", "content": "面膜用了一片脸有点泛红，还能继续用吗？"},
            {"role": "agent", "content": "建议您先停用，并用清水清洁。若 24 小时仍不适请就医。您可申请退货，我们承担运费。"},
        ],
    },
    {
        "conversation_no": "CV20240110010", "cid": 20, "channel": "online", "intent": "退款",
        "satisfaction": 5, "messages": [
            {"role": "customer", "content": "耳机退款什么时候到账？已经三天了。"},
            {"role": "agent", "content": "您好，退款审核通过后 1-3 个工作日原路退回，具体到账以银行入账为准。我帮您查一下，已在今天上午完成打款。"},
        ],
    },
]

# ---------------------------------------------------------------------------
# 工单
# ---------------------------------------------------------------------------
RAW_TICKETS = [
    {"ticket_no": "TK20240101001", "type": "售后", "priority": "P2", "status": "resolved", "assignee": "李工"},
    {"ticket_no": "TK20240102002", "type": "投诉", "priority": "P1", "status": "processing", "assignee": "王主管"},
    {"ticket_no": "TK20240103003", "type": "售后", "priority": "P2", "status": "open", "assignee": None},
    {"ticket_no": "TK20240104004", "type": "技术", "priority": "P3", "status": "resolved", "assignee": "赵工"},
    {"ticket_no": "TK20240105005", "type": "售后", "priority": "P2", "status": "processing", "assignee": "李工"},
]

# ---------------------------------------------------------------------------
# FAQ（结构化知识）
# ---------------------------------------------------------------------------
RAW_FAQ = [
    {"question": "支持 7 天无理由退货吗？", "answer": "支持。自签收之日起 7 天内，商品完好、不影响二次销售即可申请无理由退货；定制类、已拆封的个护类商品除外。", "category": "售后政策", "tags": "退货,无理由,7天", "sku": None},
    {"question": "退货的运费由谁承担？", "answer": "因质量问题导致的退货，运费由我们承担；非质量问题的无理由退货，运费由买家承担。", "category": "售后政策", "tags": "退货,运费", "sku": None},
    {"question": "退款多久能到账？", "answer": "退款审核通过后 1-3 个工作日原路退回，具体到账时间以支付渠道（支付宝/微信/银行卡）入账为准。", "category": "售后政策", "tags": "退款,到账", "sku": None},
    {"question": "如何申请售后？", "answer": "在订单详情页点击“申请售后”，选择退款/换货/维修并提交原因，客服审核通过后按指引寄回即可。", "category": "售后政策", "tags": "售后,申请", "sku": None},
    {"question": "商品保修期是多久？", "answer": "数码家电类商品整机保修 1 年，主要部件保修 3 年；具体以商品页标注为准，保修期内非人为损坏免费维修。", "category": "售后政策", "tags": "保修,质保", "sku": None},
    {"question": "多久发货？", "answer": "现货商品 24 小时内发货，预售商品按商品页标注时间发货；大促期间可能延迟 1-2 天。", "category": "物流配送", "tags": "发货,时效", "sku": None},
    {"question": "支持哪些配送方式？", "answer": "默认顺丰/京东物流配送，偏远地区转邮政 EMS，可在下单时选择配送方式。", "category": "物流配送", "tags": "配送,快递", "sku": None},
    {"question": "可以修改收货地址吗？", "answer": "订单未发货前可联系客服修改收货地址；已发货订单需联系快递员协商改址。", "category": "物流配送", "tags": "地址,修改", "sku": None},
    {"question": "如何查询物流信息？", "answer": "订单详情页点击“查看物流”即可实时查看；也可在“我的-物流助手”中输入运单号查询。", "category": "物流配送", "tags": "物流,查询", "sku": None},
    {"question": "能否开具发票？", "answer": "可以。下单时勾选“开具发票”并填写抬头，电子发票在确认收货后 3 个工作日内发送至邮箱。", "category": "发票财务", "tags": "发票,抬头", "sku": None},
    {"question": "发票类型有哪些？", "answer": "支持增值税普通发票（电子）与增值税专用发票，专票需提供完整开票资料。", "category": "发票财务", "tags": "发票,类型", "sku": None},
    {"question": "小音智能音箱 Pro 支持哪些连接方式？", "answer": "支持 Wi-Fi 双频与蓝牙 5.0 连接，可通过 APP 配网并联动其他智能设备。", "category": "商品咨询", "tags": "音箱,连接,蓝牙", "sku": "SPK-001"},
    {"question": "扫地机器人 S1 的续航多久？", "answer": "S1 内置 5200mAh 电池，标准模式可连续清扫约 150 分钟，覆盖约 120 平米。", "category": "商品咨询", "tags": "扫地机器人,续航", "sku": "SWP-001"},
    {"question": "空气炸锅需要放油吗？", "answer": "空气炸锅利用高速热风循环加热，通常无需放油；肉类自带油脂即可，追求口感可少量喷油。", "category": "商品咨询", "tags": "空气炸锅,用油", "sku": "AFR-001"},
    {"question": "蓝牙耳机 X 支持降噪吗？续航如何？", "answer": "支持主动降噪（ANC），单次续航 8 小时，配合充电盒总续航 30 小时。", "category": "商品咨询", "tags": "耳机,降噪,续航", "sku": "EAR-001"},
    {"question": "充电宝可以带上飞机吗？", "answer": "10000mAh（约 37Wh）符合民航规定（≤100Wh），可随身携带上飞机，不可托运。", "category": "商品咨询", "tags": "充电宝,飞机", "sku": "PWR-001"},
    {"question": "保温杯能装碳酸饮料吗？", "answer": "不建议装碳酸饮料，因气压变化可能损坏杯盖；装热水、咖啡、牛奶等均可。", "category": "商品咨询", "tags": "保温杯,碳酸", "sku": "CUP-001"},
    {"question": "洗面奶开封后保质期多久？", "answer": "开封后建议 6 个月内使用完毕，请存放于阴凉干燥处，避免阳光直射。", "category": "商品咨询", "tags": "洗面奶,保质期", "sku": "FAC-001"},
    {"question": "如何修改或取消订单？", "answer": "未付款订单可在“待付款”中取消；已付款未发货订单可联系客服取消，已发货订单需走退货流程。", "category": "订单问题", "tags": "订单,取消", "sku": None},
    {"question": "优惠券如何使用？", "answer": "结算页选择“优惠券”勾选使用即可，每张券有使用门槛与有效期，详见券面说明。", "category": "订单问题", "tags": "优惠券", "sku": None},
]

# ---------------------------------------------------------------------------
# 知识文档（非结构化知识，正文进 MinIO，P2 切片入库）
# ---------------------------------------------------------------------------
KNOWLEDGE_DOCS = [
    {
        "title": "退换货政策",
        "source_type": "policy",
        "category": "售后政策",
        "content": (
            "# 退换货政策\n\n"
            "一、无理由退货\n"
            "自签收之日起 7 天内，商品保持完好、不影响二次销售，可申请无理由退货。定制类商品、已拆封的一次性用品（如已拆封的个护美妆）不支持无理由退货。\n\n"
            "二、质量问题退换\n"
            "签收后 15 天内出现非人为质量问题，可申请换新或退货，运费由我方承担；15 天至保修期内按保修政策处理。\n\n"
            "三、退货流程\n"
            "订单详情页申请售后 → 选择原因 → 客服审核 → 寄回商品 → 仓库验收 → 退款或换新。\n\n"
            "四、退款时效\n"
            "验收通过后 1-3 个工作日原路退回。\n"
        ),
    },
    {
        "title": "物流配送说明",
        "source_type": "policy",
        "category": "物流配送",
        "content": (
            "# 物流配送说明\n\n"
            "一、发货时效：现货商品 24 小时内发货，预售商品按商品页标注时间发货。\n"
            "二、配送方式：默认顺丰/京东物流，偏远地区转邮政 EMS。\n"
            "三、配送范围：覆盖全国大部分地区，港澳台及海外暂不支持。\n"
            "四、收货注意事项：签收前请检查外包装是否完好，如有破损可拒收并及时联系客服。\n"
        ),
    },
    {
        "title": "保修服务条款",
        "source_type": "policy",
        "category": "售后政策",
        "content": (
            "# 保修服务条款\n\n"
            "数码家电类商品整机保修 1 年，主要部件保修 3 年。\n"
            "以下情况不在保修范围：人为损坏、进水、私自拆修、使用非原装配件。\n"
            "保修期内非人为损坏免费维修，需寄回检测，运费由我方承担。\n"
        ),
    },
    {
        "title": "发票说明",
        "source_type": "policy",
        "category": "发票财务",
        "content": (
            "# 发票说明\n\n"
            "支持开具增值税普通发票（电子）与增值税专用发票。\n"
            "电子发票在确认收货后 3 个工作日内发送至下单邮箱；专票需提供完整开票资料，寄送周期约 7 个工作日。\n"
        ),
    },
    {
        "title": "隐私与数据保护",
        "source_type": "policy",
        "category": "合规",
        "content": (
            "# 隐私与数据保护\n\n"
            "我们仅在提供商品与服务所必需范围内收集个人信息，并对手机号、邮箱、身份证号等敏感信息进行脱敏存储。\n"
            "用户可依法查询、更正、删除个人信息，相关请求可联系客服处理。\n"
        ),
    },
    {
        "title": "小音智能音箱 Pro 使用手册（节选）",
        "source_type": "manual",
        "category": "商品手册",
        "content": (
            "# 小音智能音箱 Pro 使用手册\n\n"
            "一、配网：下载 APP → 添加设备 → 长按音箱按键进入配网模式 → 输入 Wi-Fi 密码完成绑定。\n"
            "二、语音唤醒：默认唤醒词“小音小音”，可在 APP 中修改。\n"
            "三、蓝牙连接：说“打开蓝牙”，在手机蓝牙列表选择音箱即可。\n"
            "四、多设备联动：支持与小音其他智能设备组网，实现场景联动。\n"
            "五、常见故障：无法联网时检查 Wi-Fi 是否为 2.4G 频段并重启路由器。\n"
        ),
    },
]
