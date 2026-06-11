from __future__ import annotations

from datetime import datetime

LINE = '━━━━━━━━━━━━━━'


def welcome() -> str:
    return (
        '🎀 欢迎来到拼车小车库～\n'
        f'{LINE}\n\n'
        '我是你的小掌柜，专门帮你把发车、上车、验票、收资源这些事儿打理得明明白白 ✨\n\n'
        '你可以这样玩转小车库：\n\n'
        '🚗 发起众筹\n'
        '把你珍藏的博主和资源丢进来，小掌柜帮你审核发车，一步到位\n\n'
        '🔥 热门众筹\n'
        '看看大家正在拼什么好东西，心动就上车，不用犹豫\n\n'
        '📋 我的众筹\n'
        '车票、退款、资源、客服小纸条，都在这里，随时翻随时看\n\n'
        '💡 小掌柜温馨提醒\n'
        '付完款记得回来验票哦，验票成功才算真正坐上座位，稳稳发车不迷路～\n\n'
        f'{LINE}\n'
        '车位有限，遇到喜欢的就赶紧占座啦 🎀'
    )


def admin_panel_startup() -> str:
    return '🛠 小掌柜待办中心\n' + LINE + '\n处理建议：先看待审核、待资源、客服小纸条和异常小雷达，会更不容易漏掉着急的小车～'


def admin_dashboard_text(*, pending_review: int, wait_upload: int, pending_payout: int, pending_withdraw: int,
                         pending_refunds: int, support_open: int, risks: int, unresolved_events: int,
                         new_projects: int | None = None, paid_orders: int | None = None,
                         income: float | int | None = None, full_projects: int | None = None) -> str:
    if new_projects is None:
        new_projects = 0
    return (
        '🛠 小掌柜待办中心\n'
        f'{LINE}\n'
        '今日小车库概览：\n'
        f'🚗 新发车：{new_projects} 辆｜🎟️ 已上车：{paid_orders or 0} 次\n'
        f'💰 今日收入：{float(income or 0):g} 元｜🎉 满员：{full_projects or 0} 辆\n\n'
        '🧺 待处理小篮子：\n'
        f'📝 待审核车车：{pending_review}\n'
        f'📤 待补/待审资源：{wait_upload}\n'
        f'💸 报销待确认：{pending_payout}\n'
        f'💰 提现待确认：{pending_withdraw}\n'
        f'🧾 退款小票：{pending_refunds}\n'
        f'💬 客服小纸条：{support_open}\n'
        f'⚠️ 风控提醒：{risks}\n'
        f'🚨 系统异常：{unresolved_events}\n'
        f'{LINE}\n'
        '处理建议：先看待审核、待资源、客服小纸条和异常小雷达，会更不容易漏掉着急的小车～'
    )


def hot_page_text(*, page: int, pages: int, start: int, end: int, total: int) -> str:
    page_line = f'当前第 {page}/{pages} 页 · 本页 {start}-{end} 辆' if page <= 1 else f'第 {page}/{pages} 页｜本页 {start}-{end} 辆'
    return (
        '🔥 热门众筹小车库\n'
        f'{LINE}\n\n'
        f'{page_line}\n\n'
        '小掌柜会优先把快满员、最新发布、以及已满员还能补票的小车排在前面，帮你一眼看到最值得上的车～\n\n'
        '点任意一辆车，就能弹出可爱项目小卡片，看博主、看资源、看余位，想上就上 ✨\n\n'
        f'{LINE}\n'
        '看对眼了就别犹豫，好车不等人的哦 🎀'
    )


def hot_empty() -> str:
    return (
        '🔥 热门众筹小车库\n'
        f'{LINE}\n\n'
        '哎呀，这里暂时空空的呢～\n\n'
        '小掌柜正在四处搜罗新车，\n'
        '一有好项目就会挂上来。\n'
        '你也可以当第一个发起人，\n'
        '开上第一辆小车车 🎀\n\n'
        f'{LINE}\n'
        '过会儿再来看看，说不定就有惊喜 ✨。'
    )


def project_public_card(*, project_no_text: str, blogger: str, description: str, progress_text: str,
                        seat_price: float, original_price: float, mode_name: str, status_name: str,
                        total_amount: float | None = None, required_seats: int | None = None,
                        creator_prepay_seats: int | None = None, creator_prepay_amount: float | None = None,
                        after_full: bool = False, extra_fund_count: int = 0, extra_note: str | None = None) -> str:
    total = float(total_amount if total_amount is not None else original_price)
    seats = int(required_seats or 0)
    prepay_seats = int(creator_prepay_seats or 0)
    prepay_amount = float(creator_prepay_amount or 0)
    if after_full:
        return (
            '🚗✨ 拼车项目小卡片\n'
            f'{LINE}\n'
            f'🎫 项目编号：{project_no_text}\n'
            f'🧸 博主：{blogger}\n'
            f'📦 资源说明：{description}\n\n'
            f'💰 原价：{float(original_price):g} 元\n'
            f'🧮 预计凑齐：{total:g} 元\n'
            f'💺 车位：{seats} 人\n'
            f'🎟️ 每人：{float(seat_price):g} 元\n'
            f'🙋 车主预占：{prepay_seats} 个座位（{prepay_amount:g} 元）\n'
            f'🛒 购买方式：{mode_name}\n\n'
            '🎉 满员啦！这辆小车已经坐满～\n\n'
            f'🔓 还可以「满员后支付 {float(seat_price):g} 元」补票拿资源，补票金额会变成车主的小奖励～\n'
            f'🎁 满员后补票：+{int(extra_fund_count or 0)} 人\n'
            f'{LINE}\n'
            '喜欢这辆车的话，点下面按钮就可以上车啦～'
        )
    return (
        '🚗✨ 拼车项目小卡片\n'
        f'{LINE}\n'
        f'🎫 项目编号：{project_no_text}\n'
        f'🧸 博主：{blogger}\n'
        f'📦 资源说明：{description}\n\n'
        f'💰 原价：{float(original_price):g} 元\n'
        f'🧮 预计凑齐：{total:g} 元\n'
        f'💺 车位：{seats} 人\n'
        f'🎟️ 每人：{float(seat_price):g} 元\n'
        f'🙋 车主预占：{prepay_seats} 个座位（{prepay_amount:g} 元）\n'
        f'🛒 购买方式：{mode_name}\n\n'
        f'{progress_text}\n'
        f'{LINE}\n'
        '喜欢这辆车的话，点下面按钮就可以上车啦～'
    )


def crowdfunding_start(*, creator_prepay_seats: int, seat_price: float, creator_amount: float) -> str:
    return (
        '🚗 发起众筹｜小掌柜发车台\n'
        f'{LINE}\n\n'
        '你要当车主啦～小掌柜先帮你把发车资料收齐，再送去审核。\n\n'
        '🎟️ 车主预占规则：\n'
        f'需先锁定 {creator_prepay_seats} 个车位\n'
        f'💰 每个车位 {seat_price:g} 元，共 {creator_amount:g} 元\n\n'
        '发车流程：\n'
        '1️⃣ 填写博主名字 / ID\n'
        '2️⃣ 发送资源说明、预览图或文件\n'
        '3️⃣ 填写原价，小掌柜自动计算车位\n'
        '4️⃣ 选择购买方式并提交审核\n'
        '5️⃣ 审核通过后，车主先验票预占座位\n\n'
        '车主预占规则：\n'
        f'🎟️ 需要先付 {creator_prepay_seats} 个车位\n'
        f'💰 每个车位 {seat_price:g} 元，共 {creator_amount:g} 元\n\n'
        '为什么要预占呀？\n'
        '✨ 证明你是认真的小司机\n'
        '✨ 让其他用户更放心上车\n'
        '✨让拼车更快的坐满发车\n'
        '✨ 报销、分润将更好结算\n\n'
        f'{LINE}\n'
        '请先发送【博主名字 / ID】吧～\n'
        '例如：超可爱小兔酱 🎀'
    )


def crowdfunding_blogger_invalid() -> str:
    return '🧸 小掌柜需要文字形式的博主名字 / ID 哦～\n例如：超可爱小兔酱'


def crowdfunding_description_prompt(blogger: str) -> str:
    return (
        '📦 资源说明｜小掌柜收资料中\n'
        f'{LINE}\n'
        f'博主：{blogger}\n\n'
        '请描述一下这次想拼的资源，可以直接像聊天一样发送：\n'
        '📝 文字说明：合集、补档、限定内容等\n'
        '🖼 预览图片：封面、目录、截图\n'
        '🎬 视频/动图：资源预览或说明\n'
        '📎 文件：清单、说明文档等\n\n'
        '可以连续发送多条，发送完成后点击「✅ 描述发送完毕，填写原价」。'
    )


def crowdfunding_description_invalid() -> str:
    return '📦 请发送资源描述文字，或发送图片/视频/文件并配一点说明哦～'


def crowdfunding_description_ack(count: int) -> str:
    return (
        '✅ 小掌柜开始接收描述啦～\n'
        f'{LINE}\n'
        f'已确认收到 {count} 条描述/附件。\n\n'
        '你可以继续补充文字、照片、视频或文件。\n'
        '全部发完后，点下面按钮进入原价填写～'
    )


def crowdfunding_need_description() -> str:
    return '还没有收到资源说明哦～请至少发送一条文字、图片、视频或文件。'


def crowdfunding_price_prompt() -> str:
    return (
        '💰 原价填写｜小掌柜小算盘\n'
        f'{LINE}\n\n'
        '请告诉小掌柜这个资源原价是多少元～\n\n'
        '直接发送数字就可以啦，例如：\n'
        '88\n'
        '188\n\n'
        '小掌柜会按原价自动算出总众筹金额、\n'
        '车位数和每人车票，\n'
        '帮你把账算得明明白白 ✨\n\n'
        f'{LINE}\n'
        '原价发出来，剩下的交给小掌柜 🎀'
    )


def crowdfunding_price_invalid() -> str:
    return '💰 这个金额看起来不太对哦～请直接发送数字，例如 88 或 188。'


def crowdfunding_price_calc(*, price: float, total: float, base_seats: int, seats: int, seat_price: float, creator_prepay_seats: int) -> str:
    return (
        '🎰 小掌柜小算盘打好啦～\n'
        f'{LINE}\n'
        f'📦 资源原价：{price:g} 元\n'
        '🧾 平台维护费：15%\n'
        '💳 代收手续费：10%\n'
        f'💰 预计总共要凑：{total:g} 元\n\n'
        f'🪑 基础车位：{base_seats} 人\n'
        f'🚗 最终车位：{seats} 人\n'
        f'🎟️ 每人车票：{seat_price:g} 元\n'
        f'👑 车主预占：{creator_prepay_seats} 个座位，共 {creator_prepay_seats * seat_price:g} 元\n\n'
        '请选择这辆车的购买方式～'
    )


def crowdfunding_confirm(*, blogger: str, description: str, media_note: str, price: float, total: float, seats: int, seat_price: float, creator_amount: float, mode_name: str) -> str:
    media = media_note or ''
    return (
        '📌 发车前确认｜小掌柜再检查一遍\n'
        f'{LINE}\n'
        f'🧸 博主：{blogger}\n'
        f'📦 资源说明：{description}\n'
        f'{media}\n\n'
        f'💰 原价：{price:g} 元\n'
        f'🧮 预计凑齐：{total:g} 元\n'
        f'💺 车位：{seats} 人\n'
        f'🎟️ 每人：{seat_price:g} 元\n'
        f'👑 车主先付：{creator_amount:g} 元\n'
        f'🛒 购买方式：{mode_name}\n\n'
        '确认没问题就点「🚗 发车！提交审核」。\n'
        '小掌柜会把资料送去审核，通过后就能正式发车啦～'
    )


def crowdfunding_cancelled() -> str:
    return '⛔ 已取消这次发车～资料不会提交，想重新发车时随时点「🚗 发起众筹」。'


def crowdfunding_submitted(project_no: str) -> str:
    return (
        '✅ 发车申请已送到小掌柜后台啦～\n'
        f'{LINE}\n\n'
        f'项目编号：{project_no}\n'
        '当前状态：等待审核\n\n'
        '审核通过后，小掌柜会通知你支付车主预占座位。\n'
        '验票成功后，这辆小车就会正式进入拼车流程啦～\n\n'
        f'{LINE}\n'
        '先耐心等一下下，小掌柜很快就好 🎀'
    )


def crowdfunding_admin_new(*, creator: str, project_no: str, blogger: str, description: str, price: float, seats: int, mode: str) -> str:
    return (
        '📝 新众筹待审核｜小掌柜发车单\n'
        f'{LINE}\n'
        f'发起人：{creator}\n'
        f'项目：{project_no}\n'
        f'博主：{blogger}\n'
        f'描述：{description}\n'
        f'原价：{price:g} 元\n'
        f'车位：{seats} 人\n'
        f'模式：{mode}\n\n'
        '请审核资料是否清晰、价格是否合理、资源类型是否允许发布。\n'
        '通过后会发布到频道，并通知发起人支付双车位验票。'
    )


def crowdfunding_creator_approved(*, project_title: str, prepay_seats: int, amount: float) -> str:
    return (
        '✅ 你的众筹已通过审核啦～\n'
        f'{LINE}\n\n'
        f'项目：{project_title}\n\n'
        '小车已经在频道里等候乘客啦，接下来需要车主先完成预占验票～\n\n'
        f'👑 车主预占：{prepay_seats} 个车位\n'
        f'💰 应付金额：{amount:g} 元\n\n'
        '为什么要先验票呀？\n'
        '✨ 这辆车是真实发起\n'
        '✨ 让小车更快坐满发车\n'
        '✨ 报销、分润结算更顺滑\n\n'
        f'{LINE}\n'
        '请点击下方支付，\n'
        '付完回来戳「✅ 我已支付，去验票」，\n'
        '把 VP 开头的系统单号发给我就搞定啦 🎀'
    )


def crowdfunding_rejected(project_title: str) -> str:
    return (
        '❌ 这次发车申请没有通过审核～\n'
        f'{LINE}\n'
        f'{project_title}\n\n'
        '可能是资源说明不够清楚、价格需要核对，或资料暂时不适合发布。\n'
        '你可以整理一下说明后重新发起，写得越清楚越容易通过哦～'
    )


def payment_created(*, project_no: str, blogger: str, description: str, amount: float, ticket_no: str) -> str:
    return (
        '✅ 拼车项目专属小票～\n'
        f'{LINE}\n\n'
        f'项目：{project_no}\n'
        f'博主：{blogger}\n'
        f'内容：{description}\n'
        f'车票：{amount:g} 元\n'
        f'票号：{ticket_no}\n\n'
        f'{LINE}\n\n'
        '点下方支付，付完回来戳一下\n'
        '「✅ 我已支付，去验票」\n\n'
        '验票成功才算稳稳上车哦 🎀'
    )


def ticket_card(*, order_type: str, project_no: str, blogger: str, description: str, amount: float, ticket_no: str, seat_no: str, seed: str) -> str:
    if order_type == 'crowdfunding_creator_prepay':
        return (
            '👑 小掌柜车主卡密\n'
            f'{LINE}\n'
            f'🔑 车主卡密：VIP-{project_no}-{seed}\n'
            f'📦 项目编号：{project_no}\n'
            f'🧸 博主：{blogger}\n'
            f'📁 资源：{description}\n\n'
            f'💰 预占金额：{amount:g} 元\n'
            '🎁 车主权益：满员后按规则参与报销/分润\n'
            '🧾 状态：等待验票中...\n'
            f'{LINE}\n'
            '小掌柜提醒：\n'
            '付款后请点「📎 提交订单号」，把发卡平台返回的 VP 开头系统单号发给我。\n'
            '验票成功后，这辆车就正式由你发起啦～'
        )
    if order_type == 'crowdfunding_after_full':
        return (
            '🔓 满员后补票小卡片\n'
            f'{LINE}\n'
            f'🚗 车票编号：{ticket_no}\n'
            f'💺 座位编号：{seat_no}\n'
            f'📦 项目编号：{project_no}\n\n'
            f'🧸 博主：{blogger}\n'
            f'📁 资源：{description}\n\n'
            f'💰 票价：{amount:g} 元\n'
            '🧾 状态：等待验票中...\n'
            '⏳ 小提醒：记得尽快提交系统单号哦\n'
            '🎁 这是一张满员后补票，资源审核通过后也可以领取宝贝～\n'
            f'{LINE}\n'
            '小掌柜碎碎念：\n'
            '付完款戳一下「📎 提交订单号」，把发卡平台返回的系统单号丢给我就好～\n'
            '验票通过，这张车票就激活啦，稳稳落座等发车 🎀'
        )
    return (
        '🎟️ 小掌柜电子车票\n'
        f'{LINE}\n'
        f'🚗 车票编号：{ticket_no}\n'
        f'💺 座位编号：{seat_no}\n'
        f'📦 项目编号：{project_no}\n\n'
        f'🧸 博主：{blogger}\n'
        f'📁 资源：{description}\n\n'
        f'💰 票价：{amount:g} 元\n'
        '🧾 状态：等待验票中...\n'
        '⏳ 小提醒：记得尽快提交系统单号哦\n'
        f'{LINE}\n'
        '小掌柜碎碎念：\n'
        '付完款戳一下「📎 提交订单号」，把发卡平台返回的系统单号丢给我就好～\n'
        '验票通过，这张车票就激活啦，稳稳落座等发车 🎀'
    )


def submit_order_prompt(*, payment_label: str, target: str, amount: float) -> str:
    return (
        '📎 提交订单号｜小掌柜验票台\n'
        f'{LINE}\n'
        f'{payment_label}\n'
        f'{target}\n'
        f'💰 应付金额：{amount:g} 元\n\n'
        '请直接回复【发卡平台返回的系统单号】。\n'
        '一般长这样：VP2026xxxxxxxxxxxx\n\n'
        '小掌柜会帮你检查：\n'
        '1️⃣ 单号格式是否正确\n'
        '2️⃣ 是否已经支付成功\n'
        '3️⃣ 金额和这张车票是否匹配\n'
        '4️⃣ 是否已经被其他车票用过\n\n'
        '验票通过后，你就会正式上车啦～'
    )


def system_no_empty() -> str:
    return (
        '📎 小掌柜还没收到系统单号哦～\n\n'
        '请发送发卡平台返回的 VP 开头系统单号。\n'
        '如果你还没付款，可以先点支付链接完成付款再回来验票。'
    )


def verifying(system_no: str) -> str:
    return (
        '🔍 小掌柜正在验票中～\n'
        f'{LINE}\n\n'
        f'收到系统单号：{system_no}\n\n'
        '小掌柜正在帮你核对支付状态、金额，\n'
        '以及是否被重复使用，稍微等一下下就好 ✨\n\n'
        f'{LINE}\n'
        '不会让你等太久的 🎀'
    )


def verify_success(reason: str) -> str:
    return (
        '✅ 验票成功，座位坐稳啦～\n'
        f'{LINE}\n\n'
        '车票已核验，你已正式上车 🎀\n\n'
        '接下来小掌柜会继续盯着拼车进度。\n'
        '车车满员、资源到货或可领取时，\n'
        '都会第一时间来戳你，不会让你错过～\n\n'
        f'{LINE}\n'
        '安心等着就好，有消息我滴你 ✨'
    )


def verify_failed(reason: str) -> str:
    return (
        '❌ 这次还没验上票～\n'
        f'{LINE}\n\n'
        '原因：订单号格式不太对哦，\n'
        '小掌柜只认 VP 开头的那串数字～\n\n'
        '正确格式长这样：\n'
        'VP2026...\n\n'
        '你可以这样检查一下：\n'
        '1️⃣ 系统单号是不是 VP 开头\n'
        '2️⃣ 是否已经付款成功\n'
        '3️⃣ 是否复制错了空格或符号\n'
        '4️⃣ 是否拿了别人的单号/重复用过\n'
        f'{LINE}\n'
        '请检查一下，然后重新提交试试～\n'
        '还是不行的话，戳下方「联系小掌柜」，\n'
        '我来帮你手动核对 🎀'
    )


def verify_service_error() -> str:
    return (
        '❌ 验票小雷达暂时连不上～\n'
        f'{LINE}\n'
        '可能是发卡平台或网络暂时不稳定。\n'
        '你可以稍后重新提交系统单号；如果一直失败，请联系小掌柜帮你人工核对。\n'
        f'{LINE}'
    )


def order_center() -> str:
    return (
        '📋 我的小车库\n'
        f'{LINE}\n\n'
        '你的车票、退款、资源和车主记录，\n'
        '统统收在这里啦～\n\n'
        '想看哪一格，点下面的小按钮就好，\n'
        '小掌柜随时帮你翻 🎀\n\n'
        f'{LINE}\n'
        '每次拼车都是一个小脚印，\n'
        '常回来看看，说不定有新惊喜 ✨'
    )


def pending_orders_list(*, page: int, pages: int, total: int) -> str:
    return (
        '💳 待付车票\n'
        f'{LINE}\n\n'
        f'第 {page}/{pages} 页｜共 {total} 条\n\n'
        '你还差两步就能稳稳上车啦～\n'
        '点下面任意一条查看详情，然后完成支付，\n'
        '付完记得回来验票哦 🎀\n\n'
        f'{LINE}\n'
        '别让小座位空太久，快来锁位 ✨'
    )


def participated_orders_list(*, page: int, pages: int, total: int) -> str:
    return (
        '📋 已上车票\n'
        f'{LINE}\n\n'
        f'第 {page}/{pages} 页｜共 {total} 条\n\n'
        '你的小车票都在这里啦，\n'
        '每一张都是稳稳占好的座位～\n\n'
        '点开任意一条，就能查看详情，\n'
        '看看进度、看看资源、看看啥时候发车 🎀\n\n'
        f'{LINE}\n'
        '已上车，就安心等着收资源吧 ✨'
    )


def refund_orders_list(*, page: int, pages: int, total: int) -> str:
    return (
        '💸 退款车票小抽屉\n'
        f'{LINE}\n\n'
        f'第 {page}/{pages} 页｜共 {total} 条\n\n'
        '这里收着需要退款、正在退款、已经退好的小票～\n\n'
        '点开任意一张，就能看到退款金额、收款资料、处理进度和下一步该做什么。\n'
        '如果还没提交收款资料，小掌柜会在详情里提醒你补齐。\n\n'
        f'{LINE}\n'
        '退款也要清清楚楚，小掌柜陪你把小票处理完 🎀'
    )


def no_pending_orders() -> str:
    return (
        '🚗 拼车车库\n'
        f'{LINE}\n\n'
        '哎呀，这里暂时还是空空的呢～\n\n'
        '快去热门众筹逛逛，\n'
        '遇到心动的就赶紧占个座，\n'
        '每次拼车都是一次小收藏 🎀\n\n'
        f'{LINE}\n'
        '等你上车了，小掌柜再来帮你打理 ✨'
    )


def no_participated_orders() -> str:
    return no_pending_orders()


def no_refund_orders() -> str:
    return (
        '💸 退款车票小抽屉\n'
        f'{LINE}\n\n'
        '这里还没有退款小票呢～\n\n'
        '说明当前没有需要处理的退款，\n'
        '你的小车票都在稳稳往前跑 🎀\n\n'
        f'{LINE}\n'
        '有退款记录时，小掌柜会把进度放在这里，随时可以回来查看 ✨'
    )


def no_creator_projects() -> str:
    return (
        '🚗 发起众筹\n'
        f'{LINE}\n\n'
        '你还没当过车主呢～\n\n'
        '点一下「发起众筹」试试看，\n'
        '把你珍藏的博主开上第一辆小车车，\n'
        '当一回小司机，超有成就感的 🎀\n\n'
        f'{LINE}\n'
        '试试嘛，说不定一呼百应 ✨'
    )


def pending_order_detail(*, ticket_label: str, project_no: str, blogger: str, description: str, order_type: str, amount: float, expires_at: str, remaining: int) -> str:
    return (
        '💳 待付车票小卡片\n'
        f'{LINE}\n'
        f'🎟️ {ticket_label}\n\n'
        f'项目：{project_no}\n'
        f'博主：{blogger}\n'
        f'描述：{description}\n\n'
        f'🧾 车票类型：{order_type}\n'
        f'💰 应付金额：{amount:g} 元\n'
        '⏳ 当前状态：待验票\n'
        f'🕒 过期时间：{expires_at}\n'
        f'⏰ 剩余时间：约 {remaining} 分钟\n'
        f'{LINE}\n'
        '小掌柜提醒：\n'
        '1️⃣ 先点击「💸 点击支付」完成付款。\n'
        '2️⃣ 付款后回来点「✅ 我已支付，去验票」。\n'
        '3️⃣ 把发卡平台返回的系统单号发给我，就能确认上车啦～'
    )


def participated_detail(*, ticket_label: str, project_no: str, blogger: str, description: str, order_type: str, amount: float, paid_at: str, resource_status: str) -> str:
    return (
        '🚗 已上车票小卡片\n'
        f'{LINE}\n'
        f'🎟️ {ticket_label}\n\n'
        f'项目：{project_no}\n'
        f'博主：{blogger}\n'
        f'描述：{description}\n\n'
        f'🧾 车票类型：{order_type}\n'
        f'💰 已付金额：{amount:g} 元\n'
        '✅ 当前状态：已上车\n'
        f'🕒 验票时间：{paid_at}\n'
        f'📦 资源状态：{resource_status}\n'
        f'{LINE}\n'
        '小掌柜提醒：资源审核通过后，这里会出现领取按钮。'
    )


def refund_detail(*, refund_no: str, project_no: str, blogger: str, description: str, amount: float, status: str, created_at: str, payment_label: str = '-', system_no: str = '-', payout_info: str | None = None, refunded_at: str | None = None) -> str:
    step_map = {
        '还没申请退款': '下一步：请点击「💸 申请退款」，把收款资料发给小掌柜。',
        '待申请': '下一步：请点击「💸 申请退款」，把收款资料发给小掌柜。',
        '申请退款审核中': '小掌柜已经收到资料，正在等管理员确认退款。',
        '退款完成': '这张退款小票已经处理完成啦，可以安心收好记录。',
        '退款被驳回': '这张退款小票暂时被驳回，可以联系小掌柜核对原因。',
    }
    next_step = step_map.get(status, '小掌柜会继续盯着这张退款小票，有进度会及时更新。')
    payout_line = payout_info or '暂未提交'
    refunded_line = f'\n✅ 完成时间：{refunded_at}' if refunded_at else ''
    return (
        '💸 退款小票卡片\n'
        f'{LINE}\n'
        f'🧾 退款编号：{refund_no}\n'
        f'🎫 原车票：{payment_label}\n'
        f'项目：{project_no}\n'
        f'博主：{blogger}\n'
        f'描述：{description}\n\n'
        f'💰 退款金额：{amount:g} 元\n'
        f'📌 当前状态：{status}\n'
        f'🔎 系统单号：{system_no}\n'
        f'📮 收款资料：{payout_line}\n'
        f'🕒 创建时间：{created_at}{refunded_line}\n'
        f'{LINE}\n'
        f'小掌柜提醒：{next_step}\n\n'
        '退款期间如果资料填错、收款码过期，\n'
        '可以点「联系小掌柜」补充说明，不用重新解释项目背景～'
    )



def refund_apply_prompt(*, refund_no: str, project_no: str, blogger: str, description: str, amount: float, payment_label: str, system_no: str) -> str:
    return (
        '💸 退款申请｜小掌柜退款台\n'
        f'{LINE}\n'
        f'退款单：{refund_no}\n'
        f'项目：{project_no}\n'
        f'博主：{blogger}\n'
        f'描述：{description}\n\n'
        f'💰 退款金额：{amount:g} 元\n'
        f'🎫 原车票：{payment_label}\n'
        f'🔎 系统单号：{system_no}\n\n'
        '请像聊天一样发送你的退款收款资料：\n'
        '1️⃣ TRX / USDT 地址\n'
        '2️⃣ 支付宝账号 / 支付宝收款码\n'
        '3️⃣ 其他可收款方式\n\n'
        '支持内容：\n'
        '📝 文字账号\n'
        '🖼 收款码截图\n'
        '📎 文件凭证\n\n'
        f'{LINE}\n'
        '提交后，小掌柜会把这张退款小票送到审核群，\n'
        '管理员确认打款后，你会收到完成通知 🎀'
    )


def refund_need_payout_info() -> str:
    return (
        '📮 小掌柜还没收到收款资料哦～\n'
        f'{LINE}\n'
        '请发送文字账号、收款码图片或文件凭证。\n\n'
        '例如：\n'
        '• TRX/USDT 地址\n'
        '• 支付宝账号\n'
        '• 支付宝/微信收款码截图\n\n'
        '资料越清楚，退款就越不容易卡住 🎀'
    )


def refund_apply_cancelled() -> str:
    return (
        '⛔ 已取消填写退款资料～\n'
        f'{LINE}\n\n'
        '这张退款小票不会被提交给审核群。\n'
        '需要退款时，可以回到「退款车票」重新点开申请。'
    )

def refund_already_submitted(refund_no: str) -> str:
    return (
        '🧾 这张退款小票已经交给小掌柜啦～\n'
        f'{LINE}\n'
        f'退款单：{refund_no}\n'
        '当前状态：等待管理员确认退款\n\n'
        '不用重复提交资料。\n'
        '如果收款资料写错了，可以从退款详情里联系小掌柜补充说明。'
    )


def refund_already_done(*, refund_no: str, amount: float) -> str:
    return (
        '✅ 这张退款小票已经处理完成啦～\n'
        f'{LINE}\n'
        f'退款单：{refund_no}\n'
        f'退款金额：{amount:g} 元\n\n'
        '可以在退款车票小抽屉里继续查看记录。'
    )


def refund_user_submitted(refund_no: str) -> str:
    return (
        '✅ 退款资料已送到小掌柜这里啦～\n'
        f'{LINE}\n'
        f'退款单：{refund_no}\n'
        '当前状态：等待管理员确认退款\n\n'
        '小掌柜已经把收款资料和原车票一起打包给审核群。\n'
        '退款完成后，会第一时间通过机器人通知你～\n\n'
        f'{LINE}\n'
        '请留意私信提醒，别把小掌柜静音啦 🎀'
    )


def refund_admin_new(*, refund_no: str, user_label: str, user_id: int, amount: float, payment_label: str, system_no: str, pay_no: str, project_no: str, blogger: str, description: str, payout_info: str) -> str:
    return (
        f'💸 新退款小票 {refund_no}\n'
        f'{LINE}\n'
        '📌 状态：待确认退款\n'
        f'👤 用户：{user_label}\n'
        f'🆔 用户ID：{user_id}\n\n'
        f'项目：{project_no}\n'
        f'博主：{blogger}\n'
        f'描述：{description}\n\n'
        f'🎫 原车票：{payment_label}\n'
        f'🔎 系统单号：{system_no}\n'
        f'💳 支付单号：{pay_no}\n'
        f'💰 应退金额：{amount:g} 元\n\n'
        '📮 用户收款资料\n'
        f'{payout_info}\n\n'
        f'{LINE}\n'
        '小掌柜提示：确认已经线下/原路退款后，再点击「✅ 确认已退款」。\n'
        '确认后会写入资金账本，并通知用户退款完成。'
    )


def refund_done_user(*, refund_no: str, amount: float) -> str:
    return (
        '✅ 退款已处理完成啦～\n'
        f'{LINE}\n'
        f'退款单：{refund_no}\n'
        f'退款金额：{amount:g} 元\n\n'
        '这张退款小票已经更新为「退款完成」。\n'
        '可以在「我的众筹 → 退款车票」里随时查看记录。\n\n'
        f'{LINE}\n'
        '这次没上车没关系，下次有缘再拼 ✨'
    )


def refund_done_admin(*, refund_no: str, user_id: int, amount: float, notify_error: object | None = None) -> str:
    notify_line = '用户通知：已通过机器人私聊送达。' if not notify_error else f'用户通知：发送失败，需要人工提醒。原因：{notify_error}'
    return (
        '✅ 退款小票已完成\n'
        f'{LINE}\n'
        f'退款单：{refund_no}\n'
        f'用户ID：{user_id}\n'
        f'退款金额：{amount:g} 元\n'
        f'{notify_line}\n\n'
        '状态已更新为退款完成，资金账本已记一笔退款支出。'
    )


def admin_refund_empty() -> str:
    return (
        '🧾 退款小票\n'
        f'{LINE}\n\n'
        '暂时没有待处理退款～\n\n'
        '说明小车库里的退款小票都已经处理干净啦。\n'
        '有新的退款申请时，会在待办中心显示数量。'
    )


def admin_refund_list_header(total: int) -> str:
    return (
        '🧾 退款小票待办\n'
        f'{LINE}\n\n'
        f'当前待处理：{total} 张\n\n'
        '这里会显示还没提交资料、等待管理员确认的退款小票。\n'
        '如果状态是「还没申请退款」，说明用户还没发收款资料；\n'
        '如果状态是「申请退款审核中」，就可以核对资料后确认退款。\n'
    )


def admin_refund_list_item(*, refund_no: str, user_id: int, amount: float, payment_label: str, system_no: str, pay_no: str, project_no: str, blogger: str, description: str, status: str) -> str:
    return (
        f'\n💸 {refund_no}\n'
        f'用户：{user_id}\n'
        f'金额：{amount:g} 元\n'
        f'原车票：{payment_label}\n'
        f'系统单号：{system_no}\n'
        f'支付单号：{pay_no}\n'
        f'项目：{project_no}\n'
        f'博主：{blogger}\n'
        f'描述：{description}\n'
        f'状态：{status}'
    )

def creator_project_detail(*, project_no: str, blogger: str, description: str, progress_text: str, original_price: float, seat_price: float, extra_count: int, batches: int) -> str:
    return (
        '🙋 车主项目小卡片\n'
        f'{LINE}\n'
        f'项目：{project_no}\n'
        f'博主：{blogger}\n'
        f'描述：{description}\n\n'
        f'{progress_text}\n\n'
        f'💰 原价：{original_price:g} 元\n'
        f'🎟️ 每人：{seat_price:g} 元\n'
        f'🍬 满员后补票奖励：{extra_count} 人\n'
        f'💸 可提现批次：{batches} 批\n'
        f'{LINE}\n'
        '小掌柜提醒：每累计 10 个满员后补票，可申请一次提现。'
    )


def resource_empty() -> str:
    return (
        '📦 资源小仓库\n'
        f'{LINE}\n\n'
        '这里暂时还没有可领取的宝贝呢～\n\n'
        '等车车满员、资源整理好，\n'
        '小掌柜会第一时间来敲你，\n'
        '把新鲜出炉的资源送到你手里 🎀\n\n'
        f'{LINE}\n'
        '再等等，好东西值得期待 ✨'
    )


def resource_claim_panel(*, project_no: str, blogger: str, photo: int, video: int, text: int, file: int) -> str:
    return (
        '📦 宝贝资源领取面板\n'
        f'{LINE}\n\n'
        f'项目：{project_no}\n'
        f'博主：{blogger}\n\n'
        '📂 资源清单：\n'
        f'🖼 图片：{photo} 张\n'
        f'🎬 视频：{video} 部\n'
        f'📝 文本：{text} 份\n'
        f'📎 文件/其他：{file} 个\n\n'
        f'{LINE}\n\n'
        '小掌柜提醒：\n'
        '资源可能会比较多，可以分批慢慢领哦～\n'
        '已领过的也可以再领一遍，不会丢也不会少 🎀\n\n'
        f'{LINE}\n'
        '宝贝到手，稳稳收藏 ✨'
    )


def resource_upload_panel(*, project_no: str, blogger: str, total: int, text: int, photo: int, video: int, file: int) -> str:
    return (
        '📤 资源上传面板\n'
        f'{LINE}\n'
        f'项目：{project_no}\n'
        f'博主：{blogger}\n\n'
        f'✅ 已确认收到 {total} 条资源\n\n'
        '当前分类：\n'
        f'📝 文本：{text}\n'
        f'🖼 图片：{photo}\n'
        f'🎬 视频：{video}\n'
        f'📎 文件：{file}\n\n'
        '你可以继续发送资源。\n'
        '发送完成后点击「上传好啦，提交审核」。'
    )


def support_open() -> str:
    return (
        '💬 小掌柜窗口已打开～\n'
        f'{LINE}\n'
        '当前页面、订单和错误信息会自动带给小掌柜，不用重复解释太多啦。\n\n'
        '你可以像聊天一样继续发送：\n'
        '📝 文字说明\n'
        '🖼 截图/收款码\n'
        '📎 文件/凭证\n'
        '🎬 视频/语音补充\n\n'
        '发送后会生成一张客服小纸条，小掌柜回复会直接推送到这里～'
    )


def support_admin_new(*, ticket_no: str, user_label: str, user_id: int, context_text: str, user_message: str) -> str:
    return (
        f'💬 新客服小纸条 {ticket_no}\n'
        f'{LINE}\n'
        '📌 状态：待回复\n'
        f'👤 用户：{user_label}\n'
        f'🆔 用户ID：{user_id}\n'
        f'{context_text or "来源页面：通用客服入口"}\n\n'
        '🧸 对话记录\n'
        f'用户：{user_message}\n\n'
        f'{LINE}\n'
        '小掌柜提示：点「回复用户」后，可发送文字、图片、视频、文件或语音。\n'
        '发送成功后，本群会显示“已送达用户”回执。'
    )


def support_user_confirm(ticket_no: str) -> str:
    return (
        '✅ 小掌柜收到啦～\n'
        f'{LINE}\n'
        f'工单编号：{ticket_no}\n'
        '当前状态：等待小掌柜回复\n\n'
        '你可以继续补充截图、收款码或文件。\n'
        '小掌柜回复后，会直接通过机器人发给你，请留意私信提醒～'
    )


def support_reply_prompt(ticket_no: str) -> str:
    return (
        f'💬 正在回复工单 {ticket_no}\n'
        f'{LINE}\n'
        '请像聊天一样，把要发给用户的内容直接发送出来。\n\n'
        '支持内容：\n'
        '📝 文字\n'
        '🖼 图片/截图\n'
        '🎬 视频\n'
        '📎 文件\n'
        '🎙 语音\n\n'
        '发送成功后，审核群会出现明确的“已送达用户”回执；失败时会保留工单，方便继续重试。'
    )


def support_user_reply(ticket_no: str, reply_text: str | None = None) -> str:
    if reply_text:
        return (
            f'💬 小掌柜回复（{ticket_no}）\n'
            f'{LINE}\n'
            f'{reply_text}\n\n'
            '有需要可以继续补充消息，小掌柜会接着看～'
        )
    return f'💬 小掌柜回复（{ticket_no}）\n{LINE}'


def support_receipt(*, ticket_no: str, user_label: str, reply_kind: str, admin_name: str, answered_at: datetime) -> str:
    return (
        '✅ 已送达用户｜小掌柜回复发送成功\n'
        f'{LINE}\n'
        f'工单：{ticket_no}\n'
        f'用户：{user_label}\n'
        f'回复类型：{reply_kind}\n'
        f'回复管理员：{admin_name}\n'
        f'发送时间：{answered_at:%Y-%m-%d %H:%M:%S}\n\n'
        '状态：Telegram 已接受消息并投递到用户私聊。\n'
        '小掌柜提示：如用户继续补充内容，会生成新的客服小纸条。'
    )


def support_send_failed(*, ticket_no: str, user_label: str, error: object) -> str:
    return (
        '❌ 工单回复未能发送给用户\n'
        f'{LINE}\n'
        f'工单：{ticket_no}\n'
        f'用户：{user_label}\n'
        f'失败原因：{error}\n\n'
        '工单仍保持待回复状态，可以点「回复用户」重新发送。'
    )


def admin_search_help() -> str:
    return (
        '🔎 项目搜索｜小掌柜放大镜\n'
        f'{LINE}\n'
        '请直接回复这条消息发送关键词：\n'
        '• P.012：按项目编号搜索\n'
        '• VP开头系统单号：按验票单搜索\n'
        '• 用户数字ID：查用户车票/退款/客服\n'
        '• 博主名字：查相关项目\n\n'
        '搜索结果会带快捷按钮，可以一键打开项目卡片、查看已支付用户、待付车票、资源或客服小纸条。\n\n'
        '如果群里普通消息被 Telegram 隐私模式拦截，也可以发送：/search 关键词'
    )


def admin_search_need_query() -> str:
    return '🔎 请发送项目编号、系统单号、用户ID或博主名，小掌柜才能帮你找哦～'


def admin_search_results_header(query: str) -> str:
    return (
        f'🔎 搜索结果：{query}\n'
        f'{LINE}\n'
        '下面是小掌柜找到的相关记录。按钮在消息下方，可以直接跳转处理～'
    )


def admin_search_no_match() -> str:
    return '\n没有找到匹配记录。可以换成 P.编号、VP系统单号、用户ID 或博主关键词再试一次。'


def admin_search_error(error: object) -> str:
    return (
        f'❌ 项目搜索执行失败：{error}\n\n'
        '可以重试 /search 关键词；如果持续失败，请查看系统健康或日志。'
    )


def admin_project_detail(*, project_no: str, blogger: str, description: str, status: str, progress_text: str,
                         paid_amount: float, pending_orders: int, refunds: int, resource_status: str) -> str:
    return (
        '🛠 小掌柜项目待办卡\n'
        f'{LINE}\n'
        f'项目：{project_no}\n'
        f'博主：{blogger}\n'
        f'描述：{description}\n'
        f'状态：{status}\n\n'
        f'{progress_text}\n\n'
        '财务：\n'
        f'💰 已收：{paid_amount:g} 元\n'
        f'🧾 待付车票：{pending_orders} 张\n'
        f'💸 退款：{refunds} 张\n\n'
        '资源：\n'
        f'📤 当前：{resource_status}\n'
        f'{LINE}\n'
        '小掌柜提醒：优先处理卡片下方待办按钮。'
    )


def ticket_paid_status(*, payment_label: str, target: str, paid_at: str) -> str:
    return (
        '✅ 这张车票已经验票成功～\n'
        f'{LINE}\n'
        f'{payment_label}\n'
        f'{target}\n'
        '状态：已上车\n'
        f'验票时间：{paid_at}\n\n'
        '小掌柜会继续盯着资源进度，有新消息会来敲你～'
    )


def ticket_pending_status(*, payment_label: str, expires_at: str, remaining: int) -> str:
    return (
        '🎟️ 车票还在等待验票～\n'
        f'{LINE}\n'
        f'{payment_label}\n'
        '状态：待验票\n'
        f'过期时间：{expires_at}\n'
        f'剩余时间：约 {remaining} 分钟\n\n'
        '如果已经付款，请点「📎 提交订单号」发送 VP 开头系统单号。'
    )


def ticket_other_status(*, status: str, reason: str | None) -> str:
    return (
        '⚠️ 这张车票暂时不能验票～\n'
        f'{LINE}\n'
        f'当前状态：{status}\n'
        f'原因：{reason or "-"}\n\n'
        '可以返回待付车票重新查看；如果确认已付款，可从错误页面联系小掌柜。'
    )

# ---------------------------------------------------------------------------
# v1.6.0.7 卡片样式统一覆盖
# 规则：标题在卡片外；卡片主体上下都必须有 LINE；小掌柜提醒/碎碎念/处理建议放在卡片外。
# 这些同名函数会覆盖上方历史实现，避免旧面板只有单边分隔线。
# ---------------------------------------------------------------------------

def _body(*parts: object) -> str:
    return '\n'.join(str(part).strip('\n') for part in parts if part is not None and str(part).strip('\n') != '')


def _panel(title: str, body: str, tip: str | None = None) -> str:
    # 卡片统一排版：标题在外；上下分隔线之间的正文前后各空一行；
    # 第二条分隔线下方的提示/碎碎念紧贴显示，不额外空一行。
    text = f'{title}\n{LINE}\n\n{body.strip()}\n\n{LINE}'
    if tip:
        text += f'\n{tip.strip()}'
    return text


def welcome() -> str:
    return _panel(
        '🎀 欢迎来到拼车小车库～',
        _body(
            '我是你的小掌柜，专门帮你把发车、上车、验票、收资源这些事儿打理得明明白白 ✨',
            '你可以这样玩转小车库：',
            '🚗 发起众筹\n把你珍藏的博主和资源丢进来，小掌柜帮你审核发车，一步到位',
            '🔥 热门众筹\n看看大家正在拼什么好东西，心动就上车，不用犹豫',
            '📋 我的众筹\n车票、退款、资源、客服小纸条，都在这里，随时翻随时看',
        ),
        '💡 小掌柜温馨提醒\n付完款记得回来验票哦，验票成功才算真正坐上座位，稳稳发车不迷路～\n\n车位有限，遇到喜欢的就赶紧占座啦 🎀',
    )


def admin_panel_startup() -> str:
    return _panel('🛠 小掌柜待办中心', '待办数据正在加载中～', '处理建议：先看待审核、待资源、客服小纸条和异常小雷达，会更不容易漏掉着急的小车～')


def admin_dashboard_text(*, pending_review: int, wait_upload: int, pending_payout: int, pending_withdraw: int,
                         pending_refunds: int, support_open: int, risks: int, unresolved_events: int,
                         new_projects: int | None = None, paid_orders: int | None = None,
                         income: float | int | None = None, full_projects: int | None = None) -> str:
    return _panel(
        '🛠 小掌柜待办中心',
        _body(
            '今日小车库概览：',
            f'🚗 新发车：{new_projects or 0} 辆｜🎟️ 已上车：{paid_orders or 0} 次',
            f'💰 今日收入：{float(income or 0):g} 元｜🎉 满员：{full_projects or 0} 辆',
            '🧺 待处理小篮子：',
            f'📝 待审核车车：{pending_review}',
            f'📤 待补/待审资源：{wait_upload}',
            f'💸 报销待确认：{pending_payout}',
            f'💰 提现待确认：{pending_withdraw}',
            f'🧾 退款小票：{pending_refunds}',
            f'💬 客服小纸条：{support_open}',
            f'⚠️ 风控提醒：{risks}',
            f'🚨 系统异常：{unresolved_events}',
        ),
        '处理建议：先看待审核、待资源、客服小纸条和异常小雷达，会更不容易漏掉着急的小车～',
    )


def hot_page_text(*, page: int, pages: int, start: int, end: int, total: int) -> str:
    page_line = f'当前第 {page}/{pages} 页 · 本页 {start}-{end} 辆' if page <= 1 else f'第 {page}/{pages} 页｜本页 {start}-{end} 辆'
    return _panel(
        '🔥 热门众筹小车库',
        _body(
            page_line,
            '小掌柜会优先把快满员、最新发布、以及已满员还能补票的小车排在前面，帮你一眼看到最值得上的车～',
            '点任意一辆车，就能弹出可爱项目小卡片，看博主、看资源、看余位，想上就上 ✨',
        ),
        '看对眼了就别犹豫，好车不等人的哦 🎀',
    )


def hot_empty() -> str:
    return _panel(
        '🔥 热门众筹小车库',
        _body('哎呀，这里暂时空空的呢～', '小掌柜正在四处搜罗新车，\n一有好项目就会挂上来。\n你也可以当第一个发起人，\n开上第一辆小车车 🎀'),
        '过会儿再来看看，说不定就有惊喜 ✨。',
    )


def project_public_card(*, project_no_text: str, blogger: str, description: str, progress_text: str,
                        seat_price: float, original_price: float, mode_name: str, status_name: str,
                        total_amount: float | None = None, required_seats: int | None = None,
                        creator_prepay_seats: int | None = None, creator_prepay_amount: float | None = None,
                        after_full: bool = False, extra_fund_count: int = 0, extra_note: str | None = None) -> str:
    total = float(total_amount if total_amount is not None else original_price)
    seats = int(required_seats or 0)
    prepay_seats = int(creator_prepay_seats or 0)
    prepay_amount = float(creator_prepay_amount or 0)
    common = _body(
        f'🎫 项目编号：{project_no_text}',
        f'🧸 博主：{blogger}',
        f'📦 资源说明：{description}',
        f'💰 原价：{float(original_price):g} 元',
        f'🧮 预计凑齐：{total:g} 元',
        f'💺 车位：{seats} 人',
        f'🎟️ 每人：{float(seat_price):g} 元',
        f'🙋 车主预占：{prepay_seats} 个座位（{prepay_amount:g} 元）',
        f'🛒 购买方式：{mode_name}',
    )
    if after_full:
        body = _body(
            common,
            '🎉 满员啦！这辆小车已经坐满～',
            f'🔓 还可以「满员后支付 {float(seat_price):g} 元」补票拿资源，补票金额会变成车主的小奖励～',
            f'🎁 满员后补票：+{int(extra_fund_count or 0)} 人',
        )
    else:
        body = _body(common, progress_text)
    return _panel('🚗✨ 拼车项目小卡片', body, '喜欢这辆车的话，点下面按钮就可以上车啦～')


def crowdfunding_start(*, creator_prepay_seats: int, seat_price: float, creator_amount: float) -> str:
    return _panel(
        '🚗 发起众筹｜小掌柜发车台',
        _body(
            '你要当车主啦～小掌柜先帮你把发车资料收齐，再送去审核。',
            '🎟️ 车主预占规则：',
            f'需先锁定 {creator_prepay_seats} 个车位',
            f'💰 每个车位 {seat_price:g} 元，共 {creator_amount:g} 元',
            '发车流程：\n1️⃣ 填写博主名字 / ID\n2️⃣ 发送资源说明、预览图或文件\n3️⃣ 填写原价，小掌柜自动计算车位\n4️⃣ 选择购买方式并提交审核\n5️⃣ 审核通过后，车主先验票预占座位',
            '车主预占规则：',
            f'🎟️ 需要先付 {creator_prepay_seats} 个车位',
            f'💰 每个车位 {seat_price:g} 元，共 {creator_amount:g} 元',
            '为什么要预占呀？\n✨ 证明你是认真的小司机\n✨ 让其他用户更放心上车\n✨让拼车更快的坐满发车\n✨ 报销、分润将更好结算',
        ),
        '请先发送【博主名字 / ID】吧～\n例如：超可爱小兔酱 🎀',
    )


def crowdfunding_description_prompt(blogger: str) -> str:
    return _panel(
        '📦 资源说明｜小掌柜收资料中',
        _body(f'博主：{blogger}', '请描述一下这次想拼的资源，可以直接像聊天一样发送：\n📝 文字说明：合集、补档、限定内容等\n🖼 预览图片：封面、目录、截图\n🎬 视频/动图：资源预览或说明\n📎 文件：清单、说明文档等'),
        '可以连续发送多条，发送完成后点击「✅ 描述发送完毕，填写原价」。',
    )


def crowdfunding_description_ack(count: int) -> str:
    return _panel(
        '✅ 小掌柜开始接收描述啦～',
        f'已确认收到 {count} 条描述/附件。',
        '你可以继续补充文字、照片、视频或文件。\n全部发完后，点下面按钮进入原价填写～',
    )


def crowdfunding_price_prompt() -> str:
    return _panel(
        '💰 原价填写｜小掌柜小算盘',
        _body('请告诉小掌柜这个资源原价是多少元～', '直接发送数字就可以啦，例如：\n88\n188', '小掌柜会按原价自动算出总众筹金额、\n车位数和每人车票，\n帮你把账算得明明白白 ✨'),
        '原价发出来，剩下的交给小掌柜 🎀',
    )


def crowdfunding_price_calc(*, price: float, total: float, base_seats: int, seats: int, seat_price: float, creator_prepay_seats: int) -> str:
    return _panel(
        '🎰 小掌柜小算盘打好啦～',
        _body(
            f'📦 资源原价：{price:g} 元',
            '🧾 平台维护费：15%',
            '💳 代收手续费：10%',
            f'💰 预计总共要凑：{total:g} 元',
            f'🪑 基础车位：{base_seats} 人',
            f'🚗 最终车位：{seats} 人',
            f'🎟️ 每人车票：{seat_price:g} 元',
            f'👑 车主预占：{creator_prepay_seats} 个座位，共 {creator_prepay_seats * seat_price:g} 元',
        ),
        '请选择这辆车的购买方式～',
    )


def crowdfunding_confirm(*, blogger: str, description: str, media_note: str, price: float, total: float, seats: int, seat_price: float, creator_amount: float, mode_name: str) -> str:
    return _panel(
        '📌 发车前确认｜小掌柜再检查一遍',
        _body(
            f'🧸 博主：{blogger}',
            f'📦 资源说明：{description}',
            media_note or '',
            f'💰 原价：{price:g} 元',
            f'🧮 预计凑齐：{total:g} 元',
            f'💺 车位：{seats} 人',
            f'🎟️ 每人：{seat_price:g} 元',
            f'👑 车主先付：{creator_amount:g} 元',
            f'🛒 购买方式：{mode_name}',
        ),
        '确认没问题就点「🚗 发车！提交审核」。\n小掌柜会把资料送去审核，通过后就能正式发车啦～',
    )


def crowdfunding_submitted(project_no: str) -> str:
    return _panel(
        '✅ 发车申请已送到小掌柜后台啦～',
        _body(f'项目编号：{project_no}', '当前状态：等待审核', '审核通过后，小掌柜会通知你支付车主预占座位。\n验票成功后，这辆小车就会正式进入拼车流程啦～'),
        '先耐心等一下下，小掌柜很快就好 🎀',
    )


def crowdfunding_admin_new(*, creator: str, project_no: str, blogger: str, description: str, price: float, seats: int, mode: str) -> str:
    return _panel(
        '📝 新众筹待审核｜小掌柜发车单',
        _body(f'发起人：{creator}', f'项目：{project_no}', f'博主：{blogger}', f'描述：{description}', f'原价：{price:g} 元', f'车位：{seats} 人', f'模式：{mode}'),
        '请审核资料是否清晰、价格是否合理、资源类型是否允许发布。\n通过后会发布到频道，并通知发起人支付双车位验票。',
    )


def crowdfunding_creator_approved(*, project_title: str, prepay_seats: int, amount: float) -> str:
    return _panel(
        '✅ 你的众筹已通过审核啦～',
        _body(f'项目：{project_title}', '小车已经在频道里等候乘客啦，接下来需要车主先完成预占验票～', f'👑 车主预占：{prepay_seats} 个车位', f'💰 应付金额：{amount:g} 元', '为什么要先验票呀？\n✨ 这辆车是真实发起\n✨ 让小车更快坐满发车\n✨ 报销、分润结算更顺滑'),
        '请点击下方支付，\n付完回来戳「✅ 我已支付，去验票」，\n把 VP 开头的系统单号发给我就搞定啦 🎀',
    )


def crowdfunding_rejected(project_title: str) -> str:
    return _panel('❌ 这次发车申请没有通过审核～', project_title, '可能是资源说明不够清楚、价格需要核对，或资料暂时不适合发布。\n你可以整理一下说明后重新发起，写得越清楚越容易通过哦～')


def payment_created(*, project_no: str, blogger: str, description: str, amount: float, ticket_no: str) -> str:
    return _panel(
        '✅ 拼车项目专属小票～',
        _body(f'项目：{project_no}', f'博主：{blogger}', f'内容：{description}', f'车票：{amount:g} 元', f'票号：{ticket_no}'),
        '点下方支付，付完回来戳一下\n「✅ 我已支付，去验票」\n\n验票成功才算稳稳上车哦 🎀',
    )


def ticket_card(*, order_type: str, project_no: str, blogger: str, description: str, amount: float, ticket_no: str, seat_no: str, seed: str) -> str:
    if order_type == 'crowdfunding_creator_prepay':
        return _panel(
            '👑 小掌柜车主卡密',
            _body(f'🔑 车主卡密：VIP-{project_no}-{seed}', f'📦 项目编号：{project_no}', f'🧸 博主：{blogger}', f'📁 资源：{description}', f'💰 预占金额：{amount:g} 元', '🎁 车主权益：满员后按规则参与报销/分润', '🧾 状态：等待验票中...'),
            '小掌柜提醒：\n付款后请点「📎 提交订单号」，把发卡平台返回的 VP 开头系统单号发给我。\n验票成功后，这辆车就正式由你发起啦～',
        )
    if order_type == 'crowdfunding_after_full':
        return _panel(
            '🔓 满员后补票小卡片',
            _body(f'🚗 车票编号：{ticket_no}', f'💺 座位编号：{seat_no}', f'📦 项目编号：{project_no}', f'🧸 博主：{blogger}', f'📁 资源：{description}', f'💰 票价：{amount:g} 元', '🧾 状态：等待验票中...', '⏳ 小提醒：记得尽快提交系统单号哦', '🎁 这是一张满员后补票，资源审核通过后也可以领取宝贝～'),
            '小掌柜碎碎念：\n付完款戳一下「📎 提交订单号」，把发卡平台返回的系统单号丢给我就好～\n验票通过，这张车票就激活啦，稳稳落座等发车 🎀',
        )
    return _panel(
        '🎟️ 小掌柜电子车票',
        _body(f'🚗 车票编号：{ticket_no}', f'💺 座位编号：{seat_no}', f'📦 项目编号：{project_no}', f'🧸 博主：{blogger}', f'📁 资源：{description}', f'💰 票价：{amount:g} 元', '🧾 状态：等待验票中...', '⏳ 小提醒：记得尽快提交系统单号哦'),
        '小掌柜碎碎念：\n付完款戳一下「📎 提交订单号」，把发卡平台返回的系统单号丢给我就好～\n验票通过，这张车票就激活啦，稳稳落座等发车 🎀',
    )


def submit_order_prompt(*, payment_label: str, target: str, amount: float) -> str:
    return _panel(
        '📎 提交订单号｜小掌柜验票台',
        _body(payment_label, target, f'💰 应付金额：{amount:g} 元', '请直接回复【发卡平台返回的系统单号】。\n一般长这样：VP2026xxxxxxxxxxxx', '小掌柜会帮你检查：\n1️⃣ 单号格式是否正确\n2️⃣ 是否已经支付成功\n3️⃣ 金额和这张车票是否匹配\n4️⃣ 是否已经被其他车票用过'),
        '验票通过后，你就会正式上车啦～',
    )


def verifying(system_no: str) -> str:
    return _panel('🔍 小掌柜正在验票中～', f'收到系统单号：{system_no}', '小掌柜正在帮你核对支付状态、金额，\n以及是否被重复使用，稍微等一下下就好 ✨\n\n不会让你等太久的 🎀')


def verify_success(reason: str) -> str:
    return _panel('✅ 验票成功，座位坐稳啦～', '车票已核验，你已正式上车 🎀', '接下来小掌柜会继续盯着拼车进度。\n车车满员、资源到货或可领取时，\n都会第一时间来戳你，不会让你错过～\n\n安心等着就好，有消息我滴你 ✨')


def verify_failed(reason: str) -> str:
    return _panel(
        '❌ 这次还没验上票～',
        _body('原因：订单号格式不太对哦，\n小掌柜只认 VP 开头的那串数字～', '正确格式长这样：\nVP2026...', '你可以这样检查一下：\n1️⃣ 系统单号是不是 VP 开头\n2️⃣ 是否已经付款成功\n3️⃣ 是否复制错了空格或符号\n4️⃣ 是否拿了别人的单号/重复用过'),
        '请检查一下，然后重新提交试试～\n还是不行的话，戳下方「联系小掌柜」，\n我来帮你手动核对 🎀',
    )


def verify_service_error() -> str:
    return _panel('❌ 验票小雷达暂时连不上～', '可能是发卡平台或网络暂时不稳定。', '你可以稍后重新提交系统单号；如果一直失败，请联系小掌柜帮你人工核对。')


def order_center() -> str:
    return _panel('📋 我的小车库', '你的车票、退款、资源和车主记录，\n统统收在这里啦～\n\n想看哪一格，点下面的小按钮就好，\n小掌柜随时帮你翻 🎀', '每次拼车都是一个小脚印，\n常回来看看，说不定有新惊喜 ✨')


def pending_orders_list(*, page: int, pages: int, total: int) -> str:
    return _panel('💳 待付车票', f'第 {page}/{pages} 页｜共 {total} 条', '你还差两步就能稳稳上车啦～\n点下面任意一条查看详情，然后完成支付，\n付完记得回来验票哦 🎀\n\n别让小座位空太久，快来锁位 ✨')


def participated_orders_list(*, page: int, pages: int, total: int) -> str:
    return _panel('📋 已上车票', f'第 {page}/{pages} 页｜共 {total} 条', '你的小车票都在这里啦，\n每一张都是稳稳占好的座位～\n\n点开任意一条，就能查看详情，\n看看进度、看看资源、看看啥时候发车 🎀\n\n已上车，就安心等着收资源吧 ✨')


def refund_orders_list(*, page: int, pages: int, total: int) -> str:
    return _panel('💸 退款车票小抽屉', f'第 {page}/{pages} 页｜共 {total} 条', '这里收着需要退款、正在退款、已经退好的小票～\n\n点开任意一张，就能看到退款金额、收款资料、处理进度和下一步该做什么。\n如果还没提交收款资料，小掌柜会在详情里提醒你补齐。\n\n退款也要清清楚楚，小掌柜陪你把小票处理完 🎀')


def no_pending_orders() -> str:
    return _panel('🚗 拼车车库', '哎呀，这里暂时还是空空的呢～', '快去热门众筹逛逛，\n遇到心动的就赶紧占个座，\n每次拼车都是一次小收藏 🎀\n\n等你上车了，小掌柜再来帮你打理 ✨')


def no_participated_orders() -> str:
    return no_pending_orders()


def no_refund_orders() -> str:
    return _panel('💸 退款车票小抽屉', '这里还没有退款小票呢～', '说明当前没有需要处理的退款，\n你的小车票都在稳稳往前跑 🎀\n\n有退款记录时，小掌柜会把进度放在这里，随时可以回来查看 ✨')


def no_creator_projects() -> str:
    return _panel('🚗 发起众筹', '你还没当过车主呢～', '点一下「发起众筹」试试看，\n把你珍藏的博主开上第一辆小车车，\n当一回小司机，超有成就感的 🎀\n\n试试嘛，说不定一呼百应 ✨')


def pending_order_detail(*, ticket_label: str, project_no: str, blogger: str, description: str, order_type: str, amount: float, expires_at: str, remaining: int) -> str:
    return _panel(
        '💳 待付车票小卡片',
        _body(f'🎟️ {ticket_label}', f'项目：{project_no}', f'博主：{blogger}', f'描述：{description}', f'🧾 车票类型：{order_type}', f'💰 应付金额：{amount:g} 元', '⏳ 当前状态：待验票', f'🕒 过期时间：{expires_at}', f'⏰ 剩余时间：约 {remaining} 分钟'),
        '小掌柜提醒：\n1️⃣ 先点击「💸 点击支付」完成付款。\n2️⃣ 付款后回来点「✅ 我已支付，去验票」。\n3️⃣ 把发卡平台返回的系统单号发给我，就能确认上车啦～',
    )


def participated_detail(*, ticket_label: str, project_no: str, blogger: str, description: str, order_type: str, amount: float, paid_at: str, resource_status: str) -> str:
    return _panel(
        '🚗 已上车票小卡片',
        _body(f'🎟️ {ticket_label}', f'项目：{project_no}', f'博主：{blogger}', f'描述：{description}', f'🧾 车票类型：{order_type}', f'💰 已付金额：{amount:g} 元', '✅ 当前状态：已上车', f'🕒 验票时间：{paid_at}', f'📦 资源状态：{resource_status}'),
        '小掌柜提醒：资源审核通过后，这里会出现领取按钮。',
    )


def refund_detail(*, refund_no: str, project_no: str, blogger: str, description: str, amount: float, status: str, created_at: str, payment_label: str = '-', system_no: str = '-', payout_info: str | None = None, refunded_at: str | None = None) -> str:
    step_map = {
        '还没申请退款': '下一步：请点击「💸 申请退款」，把收款资料发给小掌柜。',
        '待申请': '下一步：请点击「💸 申请退款」，把收款资料发给小掌柜。',
        '申请退款审核中': '小掌柜已经收到资料，正在等管理员确认退款。',
        '退款完成': '这张退款小票已经处理完成啦，可以安心收好记录。',
        '退款被驳回': '这张退款小票暂时被驳回，可以联系小掌柜核对原因。',
    }
    next_step = step_map.get(status, '小掌柜会继续盯着这张退款小票，有进度会及时更新。')
    refunded_line = f'✅ 完成时间：{refunded_at}' if refunded_at else None
    return _panel(
        '💸 退款小票卡片',
        _body(f'🧾 退款编号：{refund_no}', f'🎫 原车票：{payment_label}', f'项目：{project_no}', f'博主：{blogger}', f'描述：{description}', f'💰 退款金额：{amount:g} 元', f'📌 当前状态：{status}', f'🔎 系统单号：{system_no}', f'📮 收款资料：{payout_info or "暂未提交"}', f'🕒 创建时间：{created_at}', refunded_line),
        f'小掌柜提醒：{next_step}\n\n退款期间如果资料填错、收款码过期，可以点「联系小掌柜」补充说明，不用重新解释项目背景～',
    )


def refund_apply_prompt(*, refund_no: str, project_no: str, blogger: str, description: str, amount: float, payment_label: str, system_no: str) -> str:
    return _panel(
        '💸 退款申请｜小掌柜退款台',
        _body(f'退款单：{refund_no}', f'项目：{project_no}', f'博主：{blogger}', f'描述：{description}', f'💰 退款金额：{amount:g} 元', f'🎫 原车票：{payment_label}', f'🔎 系统单号：{system_no}', '请像聊天一样发送你的退款收款资料：\n1️⃣ TRX / USDT 地址\n2️⃣ 支付宝账号 / 支付宝收款码\n3️⃣ 其他可收款方式', '支持内容：\n📝 文字账号\n🖼 收款码截图\n📎 文件凭证'),
        '提交后，小掌柜会把这张退款小票送到审核群，\n管理员确认打款后，你会收到完成通知 🎀',
    )


def refund_need_payout_info() -> str:
    return _panel('📮 小掌柜还没收到收款资料哦～', '请发送文字账号、收款码图片或文件凭证。\n\n例如：\n• TRX/USDT 地址\n• 支付宝账号\n• 支付宝/微信收款码截图', '资料越清楚，退款就越不容易卡住 🎀')


def refund_apply_cancelled() -> str:
    return _panel('⛔ 已取消填写退款资料～', '这张退款小票不会被提交给审核群。', '需要退款时，可以回到「退款车票」重新点开申请。')


def refund_already_submitted(refund_no: str) -> str:
    return _panel('🧾 这张退款小票已经交给小掌柜啦～', f'退款单：{refund_no}\n当前状态：等待管理员确认退款', '不用重复提交资料。\n如果收款资料写错了，可以从退款详情里联系小掌柜补充说明。')


def refund_already_done(*, refund_no: str, amount: float) -> str:
    return _panel('✅ 这张退款小票已经处理完成啦～', f'退款单：{refund_no}\n退款金额：{amount:g} 元', '可以在退款车票小抽屉里继续查看记录。')


def refund_user_submitted(refund_no: str) -> str:
    return _panel('✅ 退款资料已送到小掌柜这里啦～', f'退款单：{refund_no}\n当前状态：等待管理员确认退款', '小掌柜已经把收款资料和原车票一起打包给审核群。\n退款完成后，会第一时间通过机器人通知你～\n\n请留意私信提醒，别把小掌柜静音啦 🎀')


def refund_admin_new(*, refund_no: str, user_label: str, user_id: int, amount: float, payment_label: str, system_no: str, pay_no: str, project_no: str, blogger: str, description: str, payout_info: str) -> str:
    return _panel(
        f'💸 新退款小票 {refund_no}',
        _body('📌 状态：待确认退款', f'👤 用户：{user_label}', f'🆔 用户ID：{user_id}', f'项目：{project_no}', f'博主：{blogger}', f'描述：{description}', f'🎫 原车票：{payment_label}', f'🔎 系统单号：{system_no}', f'💳 支付单号：{pay_no}', f'💰 应退金额：{amount:g} 元', '📮 用户收款资料', payout_info),
        '小掌柜提示：确认已经线下/原路退款后，再点击「✅ 确认已退款」。\n确认后会写入资金账本，并通知用户退款完成。',
    )


def refund_done_user(*, refund_no: str, amount: float) -> str:
    return _panel('✅ 退款已处理完成啦～', f'退款单：{refund_no}\n退款金额：{amount:g} 元', '这张退款小票已经更新为「退款完成」。\n可以在「我的众筹 → 退款车票」里随时查看记录。\n\n这次没上车没关系，下次有缘再拼 ✨')


def refund_done_admin(*, refund_no: str, user_id: int, amount: float, notify_error: object | None = None) -> str:
    notify_line = '用户通知：已通过机器人私聊送达。' if not notify_error else f'用户通知：发送失败，需要人工提醒。原因：{notify_error}'
    return _panel('✅ 退款小票已完成', f'退款单：{refund_no}\n用户ID：{user_id}\n退款金额：{amount:g} 元\n{notify_line}', '状态已更新为退款完成，资金账本已记一笔退款支出。')


def admin_refund_empty() -> str:
    return _panel('🧾 退款小票', '暂时没有待处理退款～', '说明小车库里的退款小票都已经处理干净啦。\n有新的退款申请时，会在待办中心显示数量。')


def admin_refund_list_header(total: int) -> str:
    return _panel('🧾 退款小票待办', f'当前待处理：{total} 张', '这里会显示还没提交资料、等待管理员确认的退款小票。\n如果状态是「还没申请退款」，说明用户还没发收款资料；\n如果状态是「申请退款审核中」，就可以核对资料后确认退款。')


def creator_project_detail(*, project_no: str, blogger: str, description: str, progress_text: str, original_price: float, seat_price: float, extra_count: int, batches: int) -> str:
    return _panel(
        '🙋 车主项目小卡片',
        _body(f'项目：{project_no}', f'博主：{blogger}', f'描述：{description}', progress_text, f'💰 原价：{original_price:g} 元', f'🎟️ 每人：{seat_price:g} 元', f'🍬 满员后补票奖励：{extra_count} 人', f'💸 可提现批次：{batches} 批'),
        '小掌柜提醒：每累计 10 个满员后补票，可申请一次提现。',
    )


def resource_empty() -> str:
    return _panel('📦 资源小仓库', '这里暂时还没有可领取的宝贝呢～', '等车车满员、资源整理好，\n小掌柜会第一时间来敲你，\n把新鲜出炉的资源送到你手里 🎀\n\n再等等，好东西值得期待 ✨')


def resource_claim_panel(*, project_no: str, blogger: str, photo: int, video: int, text: int, file: int) -> str:
    return _panel(
        '📦 宝贝资源领取面板',
        _body(f'项目：{project_no}', f'博主：{blogger}', '📂 资源清单：', f'🖼 图片：{photo} 张', f'🎬 视频：{video} 部', f'📝 文本：{text} 份', f'📎 文件/其他：{file} 个'),
        '小掌柜提醒：\n资源可能会比较多，可以分批慢慢领哦～\n已领过的也可以再领一遍，不会丢也不会少 🎀\n\n宝贝到手，稳稳收藏 ✨',
    )


def resource_upload_panel(*, project_no: str, blogger: str, total: int, text: int, photo: int, video: int, file: int) -> str:
    return _panel(
        '📤 资源上传面板',
        _body(f'项目：{project_no}', f'博主：{blogger}', f'✅ 已确认收到 {total} 条资源', '当前分类：', f'📝 文本：{text}', f'🖼 图片：{photo}', f'🎬 视频：{video}', f'📎 文件：{file}'),
        '你可以继续发送资源。\n发送完成后点击「上传好啦，提交审核」。',
    )


def support_open() -> str:
    return _panel(
        '💬 小掌柜窗口已打开～',
        _body('当前页面、订单和错误信息会自动带给小掌柜，不用重复解释太多啦。', '你可以像聊天一样继续发送：\n📝 文字说明\n🖼 截图/收款码\n📎 文件/凭证\n🎬 视频/语音补充'),
        '发送后会生成一张客服小纸条，小掌柜回复会直接推送到这里～',
    )


def support_admin_new(*, ticket_no: str, user_label: str, user_id: int, context_text: str, user_message: str) -> str:
    return _panel(
        f'💬 新客服小纸条 {ticket_no}',
        _body('📌 状态：待回复', f'👤 用户：{user_label}', f'🆔 用户ID：{user_id}', context_text or '来源页面：通用客服入口', '🧸 对话记录', f'用户：{user_message}'),
        '小掌柜提示：点「回复用户」后，可发送文字、图片、视频、文件或语音。\n发送成功后，本群会显示“已送达用户”回执。',
    )


def support_user_confirm(ticket_no: str) -> str:
    return _panel('✅ 小掌柜收到啦～', f'工单编号：{ticket_no}\n当前状态：等待小掌柜回复', '你可以继续补充截图、收款码或文件。\n小掌柜回复后，会直接通过机器人发给你，请留意私信提醒～')


def support_reply_prompt(ticket_no: str) -> str:
    return _panel(f'💬 正在回复工单 {ticket_no}', '请像聊天一样，把要发给用户的内容直接发送出来。\n\n支持内容：\n📝 文字\n🖼 图片/截图\n🎬 视频\n📎 文件\n🎙 语音', '发送成功后，审核群会出现明确的“已送达用户”回执；失败时会保留工单，方便继续重试。')


def support_user_reply(ticket_no: str, reply_text: str | None = None) -> str:
    return _panel(f'💬 小掌柜回复（{ticket_no}）', reply_text or '小掌柜给你发来了一条回复。', '有需要可以继续补充消息，小掌柜会接着看～' if reply_text else None)


def support_receipt(*, ticket_no: str, user_label: str, reply_kind: str, admin_name: str, answered_at: datetime) -> str:
    return _panel('✅ 已送达用户｜小掌柜回复发送成功', f'工单：{ticket_no}\n用户：{user_label}\n回复类型：{reply_kind}\n回复管理员：{admin_name}\n发送时间：{answered_at:%Y-%m-%d %H:%M:%S}\n\n状态：Telegram 已接受消息并投递到用户私聊。', '小掌柜提示：如用户继续补充内容，会生成新的客服小纸条。')


def support_send_failed(*, ticket_no: str, user_label: str, error: object) -> str:
    return _panel('❌ 工单回复未能发送给用户', f'工单：{ticket_no}\n用户：{user_label}\n失败原因：{error}', '工单仍保持待回复状态，可以点「回复用户」重新发送。')


def admin_search_help() -> str:
    return _panel('🔎 项目搜索｜小掌柜放大镜', '请直接回复这条消息发送关键词：\n• P.012：按项目编号搜索\n• VP开头系统单号：按验票单搜索\n• 用户数字ID：查用户车票/退款/客服\n• 博主名字：查相关项目', '搜索结果会带快捷按钮，可以一键打开项目卡片、查看已支付用户、待付车票、资源或客服小纸条。\n\n如果群里普通消息被 Telegram 隐私模式拦截，也可以发送：/search 关键词')


def admin_search_results_header(query: str) -> str:
    return _panel(f'🔎 搜索结果：{query}', '下面是小掌柜找到的相关记录。', '按钮在消息下方，可以直接跳转处理～')


def admin_project_detail(*, project_no: str, blogger: str, description: str, status: str, progress_text: str,
                         paid_amount: float, pending_orders: int, refunds: int, resource_status: str) -> str:
    return _panel(
        '🛠 小掌柜项目待办卡',
        _body(f'项目：{project_no}', f'博主：{blogger}', f'描述：{description}', f'状态：{status}', progress_text, '财务：', f'💰 已收：{paid_amount:g} 元', f'🧾 待付车票：{pending_orders} 张', f'💸 退款：{refunds} 张', '资源：', f'📤 当前：{resource_status}'),
        '小掌柜提醒：优先处理卡片下方待办按钮。',
    )


def ticket_paid_status(*, payment_label: str, target: str, paid_at: str) -> str:
    return _panel('✅ 这张车票已经验票成功～', _body(payment_label, target, '状态：已上车', f'验票时间：{paid_at}'), '小掌柜会继续盯着资源进度，有新消息会来敲你～')


def ticket_pending_status(*, payment_label: str, expires_at: str, remaining: int) -> str:
    return _panel('🎟️ 车票还在等待验票～', _body(payment_label, '状态：待验票', f'过期时间：{expires_at}', f'剩余时间：约 {remaining} 分钟'), '如果已经付款，请点「📎 提交订单号」发送 VP 开头系统单号。')


def ticket_other_status(*, status: str, reason: str | None) -> str:
    return _panel('⚠️ 这张车票暂时不能验票～', f'当前状态：{status}\n原因：{reason or "-"}', '可以返回待付车票重新查看；如果确认已付款，可从错误页面联系小掌柜。')



# ---------------------------------------------------------------------------
# v1.6.0.8 满员成功频道提醒卡片
# 让“拼车成功”独立频道通知复用全站统一面板风格：标题在卡片外，正文在上下分隔线中，
# 小掌柜提醒放在卡片外，避免和旧版硬编码文案视觉不一致。
# ---------------------------------------------------------------------------

def project_full_success_card(*, project_no_text: str, blogger: str, description: str,
                              seat_price: float, required_seats: int, paid_seats: int,
                              purchase_mode_name: str, status_name: str,
                              pending_extra: int = 0) -> str:
    seats = int(required_seats or 0)
    paid = max(int(paid_seats or 0), seats) if seats else int(paid_seats or 0)
    return _panel(
        '🎉🚗 拼车成功｜车车已满员',
        _body(
            f'🎫 项目编号：{project_no_text}',
            f'🧸 博主：{blogger}',
            f'📦 资源说明：{description}',
            f'💺 车位进度：{paid}/{seats} 已坐满',
            f'🎟️ 补票金额：{float(seat_price):g} 元 / 人',
            f'🛒 购买方式：{purchase_mode_name}',
            f'📌 当前状态：{status_name}',
            '🎉 满员啦！这辆小车已经成功坐满～',
            '小掌柜正在推动资源整理、上传和审核流程，审核通过后会开放领取。',
            f'🔓 后来的宝子仍可「满员后支付 {float(seat_price):g} 元」补票拿资源。',
            f'🎁 当前满员后补票：+{int(pending_extra or 0)} 人',
        ),
        '小掌柜提醒：点下方按钮私聊机器人补票；资源审核通过后，就可以在「我的众筹」里领取宝贝啦 🎀',
    )

# ---------------------------------------------------------------------------
# v1.6.0.9 客服回复换接口 + 用户主动拉取兜底
# ---------------------------------------------------------------------------

def _support_ticket_status_label(status: str | None) -> str:
    return {
        'open': '等待小掌柜回复',
        'answered': '小掌柜已回复',
        'closed': '已关闭',
    }.get(status or '', status or '-')


def support_user_confirm(ticket_no: str) -> str:
    return _panel(
        '✅ 小掌柜收到啦～',
        f'工单编号：{ticket_no}\n当前状态：等待小掌柜回复',
        '你可以点下面「🔄 查看小掌柜回复」主动刷新；小掌柜回复后也会通过新的原生接口推送到这里。',
    )


def support_receipt(*, ticket_no: str, user_label: str, reply_kind: str, admin_name: str, answered_at: datetime, delivery_method: str | None = None) -> str:
    method_line = f'投递通道：{delivery_method}' if delivery_method else '投递通道：默认机器人通道'
    return _panel(
        '✅ 已送达用户｜小掌柜回复发送成功',
        f'工单：{ticket_no}\n用户：{user_label}\n回复类型：{reply_kind}\n回复管理员：{admin_name}\n发送时间：{answered_at:%Y-%m-%d %H:%M:%S}\n{method_line}\n\n状态：Telegram 接口已接受本次投递。',
        '如果用户说没弹提醒，让用户打开工单里的「🔄 查看小掌柜回复」主动拉取，回复内容也已经落库。',
    )


def support_ticket_user_status(*, ticket_no: str, status: str, user_message: str, admin_reply: str | None = None, answered_at: datetime | None = None, last_error: str | None = None) -> str:
    status_label = _support_ticket_status_label(status)
    if status == 'answered' and admin_reply:
        body = _body(
            f'工单编号：{ticket_no}',
            f'当前状态：{status_label}',
            f'回复时间：{answered_at:%Y-%m-%d %H:%M:%S}' if answered_at else None,
            '🧸 你的留言',
            user_message or '-',
            '💬 小掌柜回复',
            admin_reply,
        )
        tip = '这条回复来自工单记录，即使手机没弹出推送，也可以在这里查看。需要继续沟通就点「继续联系客服」。'
    else:
        body = _body(
            f'工单编号：{ticket_no}',
            f'当前状态：{status_label}',
            '🧸 你的留言',
            user_message or '-',
            f'最近投递提示：{last_error}' if last_error else None,
        )
        tip = '小掌柜还没回复时，可以稍后点这个按钮刷新；如果已经补充了新问题，也可以继续联系客服。'
    return _panel('💬 客服小纸条状态', body, tip)

# ---------------------------------------------------------------------------
# v1.6.1.0 用户侧客服入口外置到 @jingpinhybot
# ---------------------------------------------------------------------------

def support_external_redirect(*, bot_username: str, source: str = 'generic', ref_id: int | None = 0) -> str:
    source_label = {
        'generic': '通用客服入口',
        'error': '验票/支付异常入口',
        'pending': '待付车票入口',
        'refund': '退款详情入口',
        'project': '项目详情入口',
    }.get(source or 'generic', source or '通用客服入口')
    ref_line = f'关联编号：{int(ref_id or 0)}' if int(ref_id or 0) else '关联编号：-'
    return _panel(
        '💬 联系小掌柜｜已切换到独立客服机器人',
        _body(
            f'客服机器人：{bot_username}',
            f'来源页面：{source_label}',
            ref_line,
            '为了避免当前机器人客服链路继续卡住，用户侧咨询统一交给独立双向机器人处理。',
        ),
        f'请点下方按钮打开 {bot_username}，在那里可以直接双向联系小掌柜。',
    )

# ---------------------------------------------------------------------------
# v1.6.1.1 外置客服后，业务审核与人工咨询彻底分层
# ---------------------------------------------------------------------------

def welcome() -> str:
    return _panel(
        '🎀 欢迎来到拼车小车库～',
        _body(
            '我是你的小掌柜，专门帮你把发车、上车、验票、收资源这些事儿打理得明明白白 ✨',
            '你可以这样玩转小车库：',
            '🚗 发起众筹\n把你珍藏的博主和资源丢进来，小掌柜帮你审核发车，一步到位',
            '🔥 热门众筹\n看看大家正在拼什么好东西，心动就上车，不用犹豫',
            '📋 我的众筹\n车票、退款、报销、提现和资源都在这里，随时翻随时看',
            '💬 联系小掌柜\n人工咨询统一打开独立客服机器人，不再走本机器人旧工单链路',
        ),
        '💡 小掌柜温馨提醒\n付完款记得回来验票哦，验票成功才算真正坐上座位。退款、报销、提现这些业务申请仍在本机器人提交，提交后会进入审核群待办。',
    )


def admin_panel_startup() -> str:
    return _panel(
        '🛠 小掌柜待办中心',
        '待办数据正在加载中～',
        '处理建议：先看待审核、待资源、退款/报销/提现和异常小雷达。人工咨询已外置到客服机器人；这里的「旧客服工单」只处理历史遗留单。',
    )


def admin_dashboard_text(*, pending_review: int, wait_upload: int, pending_payout: int, pending_withdraw: int,
                         pending_refunds: int, support_open: int, risks: int, unresolved_events: int,
                         new_projects: int | None = None, paid_orders: int | None = None,
                         income: float | int | None = None, full_projects: int | None = None) -> str:
    return _panel(
        '🛠 小掌柜待办中心',
        _body(
            '今日小车库概览：',
            f'🚗 新发车：{new_projects or 0} 辆｜🎟️ 已上车：{paid_orders or 0} 次',
            f'💰 今日收入：{float(income or 0):g} 元｜🎉 满员：{full_projects or 0} 辆',
            '🧺 审核群业务待办：',
            f'📝 待审核车车：{pending_review}',
            f'📤 待补/待审资源：{wait_upload}',
            f'💸 报销待确认：{pending_payout}',
            f'💰 提现待确认：{pending_withdraw}',
            f'🧾 退款小票：{pending_refunds}',
            f'💬 旧客服工单：{support_open}',
            f'⚠️ 风控提醒：{risks}',
            f'🚨 系统异常：{unresolved_events}',
        ),
        '边界说明：用户咨询走外部客服机器人；退款、报销、提现、资源审核、手动补票仍是本群业务待办，不会发到外部客服。',
    )


def support_external_redirect(*, bot_username: str, source: str = 'generic', ref_id: int | None = 0) -> str:
    source_label = {
        'generic': '通用客服入口',
        'error': '验票/支付异常入口',
        'pending': '待付车票入口',
        'refund': '退款详情入口',
        'project': '项目详情入口',
    }.get(source or 'generic', source or '通用客服入口')
    ref_line = f'关联编号：{int(ref_id or 0)}' if int(ref_id or 0) else '关联编号：-'
    return _panel(
        '💬 联系小掌柜｜请打开独立客服机器人',
        _body(
            f'客服机器人：{bot_username}',
            f'来源页面：{source_label}',
            ref_line,
            '这只是人工咨询入口；退款申请、报销/提现申请、验票、领取资源等业务操作仍在当前机器人完成。',
        ),
        f'请点下方按钮打开 {bot_username}，在那里可以双向联系小掌柜。',
    )


def support_external_only_notice(*, bot_username: str) -> str:
    return _panel(
        '💬 客服入口已经迁移啦～',
        _body(
            f'人工咨询请打开：{bot_username}',
            '当前机器人不再生成新的客服小纸条，避免咨询消息和退款/报销/提现审核单混在一起。',
            '退款、报销、提现、补票、资源审核这些业务待办仍会正常发送到审核群。',
        ),
        '点下面按钮就能继续联系小掌柜。',
    )


def refund_admin_new(*, refund_no: str, user_label: str, user_id: int, amount: float, payment_label: str, system_no: str, pay_no: str, project_no: str, blogger: str, description: str, payout_info: str) -> str:
    return _panel(
        f'💸 业务审核｜新退款小票 {refund_no}',
        _body(
            '📌 类型：退款业务单（仍在审核群处理，不走外部客服机器人）',
            '📌 状态：待确认退款',
            f'👤 用户：{user_label}',
            f'🆔 用户ID：{user_id}',
            f'项目：{project_no}',
            f'博主：{blogger}',
            f'描述：{description}',
            f'🎫 原车票：{payment_label}',
            f'🔎 系统单号：{system_no}',
            f'💳 支付单号：{pay_no}',
            f'💰 应退金额：{amount:g} 元',
            '📮 用户收款资料',
            payout_info,
        ),
        '处理边界：这张卡片是业务审核单，请管理员在本审核群核对并点击「✅ 确认已退款」。用户如果只是补充说明，再引导去外部客服机器人。',
    )


def admin_search_help() -> str:
    return _panel(
        '🔎 项目搜索｜小掌柜放大镜',
        '请直接回复这条消息发送关键词：\n• P.012：按项目编号搜索\n• VP开头系统单号：按验票单搜索\n• 用户数字ID：查用户车票/退款/历史客服\n• 博主名字：查相关项目',
        '搜索结果会带快捷按钮，可以一键打开项目卡片、查看已支付用户、待付车票、资源或历史客服工单。\n\n人工咨询已经外置到客服机器人，本搜索只查当前机器人内的业务数据。',
    )
