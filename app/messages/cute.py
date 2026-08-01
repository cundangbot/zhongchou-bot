from __future__ import annotations

from datetime import datetime
import html

LINE = '━━━━━━━━━━━━━━'


def crowdfunding_blogger_invalid() -> str:
    return '🧸 小掌柜需要文字形式的博主名字 / ID 哦～\n例如：超可爱小兔酱'


def crowdfunding_description_invalid() -> str:
    return '📦 请发送资源描述文字，或发送图片/视频/文件并配一点说明哦～'


def crowdfunding_need_description() -> str:
    return '还没有收到资源说明哦～请至少发送一条文字、图片、视频或文件。'


def crowdfunding_price_invalid() -> str:
    return '💰 这个金额看起来不太对哦～请直接发送数字，例如 88 或 188。'


def crowdfunding_cancelled() -> str:
    return '⛔ 已取消这次发车～资料不会提交，想重新发车时随时点「🚗 发起众筹」。'


def admin_refund_list_item(*, refund_no: str, user_id: int, amount: float, payment_label: str, system_no: str, pay_no: str, project_no: str, blogger: str, description: str, status: str) -> str:
    order_no = system_no or pay_no or payment_label or refund_no
    return (
        f'\n💸 {refund_no}\n'
        f'用户：<code>{user_id}</code>\n'
        f'金额：{amount:g} 元\n'
        f'订单号：<code>{order_no}</code>'
    )


def admin_search_need_query() -> str:
    return '🔎 请发送项目编号、系统单号、用户ID或博主名，小掌柜才能帮你找哦～'


def admin_search_no_match() -> str:
    return '\n没有找到匹配记录。可以换成 P.编号、VP系统单号、用户ID 或博主关键词再试一次。'


def admin_search_error(error: object) -> str:
    return (
        f'❌ 项目搜索执行失败：{error}\n\n'
        '可以重试 /search 关键词；如果持续失败，请查看系统健康或日志。'
    )


# 统一卡片规则：标题在卡片外，正文位于上下分隔线之间，提示紧随卡片显示。

def _body(*parts: object) -> str:
    return '\n'.join(str(part).strip('\n') for part in parts if part is not None and str(part).strip('\n') != '')


def _panel(title: str, body: str, tip: str | None = None) -> str:
    # 卡片统一排版：标题在外；上下分隔线之间的正文前后各空一行；
    # 第二条分隔线下方的提示/碎碎念紧贴显示，不额外空一行。
    text = f'{title}\n{LINE}\n\n{body.strip()}\n\n{LINE}'
    if tip:
        text += f'\n{tip.strip()}'
    return text


def hot_page_text(*, page: int, pages: int, start: int, end: int, total: int) -> str:
    page_line = f'当前第 {page}/{pages} 页 · 本页 {start}-{end} 辆' if page <= 1 else f'第 {page}/{pages} 页｜本页 {start}-{end} 辆'
    return _panel(
        '🔥 热门众筹小车库',
        _body(
            page_line,
            '小掌柜会优先把快满员、最新发布、以及已满员还能补票的小车排在前面，帮你一眼看到最值得上的车～',
            '点任意一辆车，就能弹出项目小卡片，看博主、看资源、看余位，想上就上 ✨',
        ),
        '看对眼了就别犹豫，好车不等人的哦 🎀',
    )


def hot_empty() -> str:
    return _panel(
        '🔥 热门众筹小车库',
        _body('哎呀，这里暂时空空的呢～', '小掌柜正在四处搜罗新车，\n一有好项目就会挂上来。\n你也可以当第一个发起人，\n开上第一辆小车车 🎀'),
        '过会儿再来看看，说不定就有惊喜 ✨',
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
            f'🎟️ 车主预占：{creator_prepay_seats} 个车位',
            f'💰 每个车位 {seat_price:g} 元，共 {creator_amount:g} 元',
            '发车流程：\n1️⃣ 填写博主名字 / ID\n2️⃣ 发送资源说明、预览图或文件\n3️⃣ 填写原价，小掌柜自动计算车位\n4️⃣ 选择购买方式并提交审核\n5️⃣ 审核通过后，车主完成双车位支付并由系统自动核验',
            '为什么要预占呀？\n✨ 证明你是认真的小司机\n✨ 让其他用户更放心上车\n✨ 让拼车更快坐满发车\n✨ 报销、分润更好结算',
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
        _body(f'项目编号：{project_no}', '当前状态：等待审核', '审核通过后，小掌柜会通知你支付车主预占座位。\n自动核验成功后，这辆小车就会正式进入拼车流程啦～'),
        '先耐心等一下下，小掌柜很快就好 🎀',
    )


def crowdfunding_admin_new(*, creator: str, project_no: str, blogger: str, description: str, price: float, seats: int, mode: str, seat_price: float = 30) -> str:
    return _panel(
        '📝 新众筹待审核｜小掌柜发车单',
        _body(f'发起人：{creator}', f'项目：{project_no}', f'博主：{blogger}', f'描述：{description}', f'原价：{price:g} 元', f'车位：{seats} 人', f'单价：{seat_price:g} 元/座', f'模式：{mode}'),
        '请审核资料是否清晰、价格是否合理、资源类型是否允许发布。\n通过后会发布到频道，并通知发起人支付双车位，由系统自动核验。',
    )


def crowdfunding_creator_approved(*, project_title: str, prepay_seats: int, amount: float) -> str:
    footer = (
        '1️⃣ 点击下方「💳 立即支付」\n'
        '2️⃣ 支付成功后订单自动核验中，拼车权益将于 10–60 秒内绑定至账户\n'
        '3️⃣ 若付款后仍显示待付，可点「🔄 已付款，查询状态」\n\n'
        '请使用当前 Telegram 账号完成下单 🎀'
    )
    return _panel(
        '✅ 你的众筹已通过审核啦～',
        _body(
            f'项目：{project_title}',
            '小车已经在频道里等候乘客，接下来需要车主完成预占付款。',
            f'👑 车主预占：{prepay_seats} 个车位',
            f'💰 应付金额：{amount:g} 元',
        ),
        footer,
    )

def crowdfunding_rejected(project_title: str) -> str:
    return _panel('❌ 这次发车申请没有通过审核～', project_title, '可能是资源说明不够清楚、价格需要核对，或资料暂时不适合发布。\n你可以整理一下说明后重新发起，写得越清楚越容易通过哦～')


def payment_created(*, project_no: str, blogger: str, description: str, amount: float, ticket_no: str) -> str:
    footer = (
        '1️⃣ 点击下方「💳 立即支付」\n'
        '2️⃣ 支付成功后订单自动核验中，拼车权益将于 10–60 秒内绑定至账户\n'
        '3️⃣ 若付款后仍显示待付，可点「🔄 已付款，查询状态」\n\n'
        '请使用当前 Telegram 账号完成下单 🎀'
    )
    return _panel(
        '🎟️ 拼车项目专属小票～',
        _body(
            f'项目：{project_no}',
            f'博主：{blogger}',
            f'内容：{description}',
            f'应付金额：{amount:g} 元',
            f'车票编号：{ticket_no}',
            '当前状态：等待付款',
        ),
        footer,
    )

def ticket_card(*, order_type: str, project_no: str, blogger: str, description: str, amount: float, ticket_no: str, seat_no: str, seed: str) -> str:
    status = '🧾 状态：等待自动核验中...'
    footer = (
        '系统暂时还没有完成自动核验。若刚付款，可稍后再次查询\n'
        '若长时间未更新，请点「💬 联系小掌柜」'
    )
    if order_type == 'crowdfunding_creator_prepay':
        return _panel(
            '👑 车主预占车票',
            _body(
                f'🔑 车主卡密：VIP-{project_no}-{seed}',
                f'📦 项目编号：{project_no}',
                f'🧸 博主：{blogger}',
                f'📁 资源：{description}',
                f'💰 预占金额：{amount:g} 元',
                '🎁 车主权益：满员后按规则参与报销/分润',
                status,
            ),
            footer,
        )
    if order_type == 'crowdfunding_after_full':
        return _panel(
            '🔓 满员后补票',
            _body(
                f'🚗 车票编号：{ticket_no}',
                f'💺 座位编号：{seat_no}',
                f'📦 项目编号：{project_no}',
                f'🧸 博主：{blogger}',
                f'📁 资源：{description}',
                f'💰 票价：{amount:g} 元',
                status,
                '🎁 资源审核通过后也可以领取宝贝',
            ),
            footer,
        )
    return _panel(
        '🎟️ 小掌柜电子车票',
        _body(
            f'🚗 车票编号：{ticket_no}',
            f'📦 项目编号：{project_no}',
            f'🧸 博主：{blogger}',
            f'📁 资源：{description}',
            f'💰 票价：{amount:g} 元',
            status,
        ),
        footer,
    )

def order_center() -> str:
    return _panel(
        '📋 我的小车库',
        '你的车票、退款、资源和车主记录，\n统统收在这里啦～\n\n想看哪一格，点下面的小按钮就好，\n小掌柜随时帮你翻 🎀',
        '每次拼车都是一个小脚印，\n常回来看看，说不定有新惊喜 ✨',
    )


def pending_orders_list(*, page: int, pages: int, total: int) -> str:
    return _panel(
        '💳 待付车票',
        f'第 {page}/{pages} 页｜共 {total} 条',
        '点开对应项目后点击「💳 立即支付」，付款成功会自动核验并主动通知上车。\n\n若已经付款但状态没有更新，可进入车票详情点「🔄 已付款，查询状态」。',
    )

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
    footer = (
        '1️⃣ 点击下方「💳 立即支付」\n'
        '2️⃣ 支付成功后订单自动核验中，拼车权益将于 10–60 秒内绑定至账户\n'
        '3️⃣ 若付款后仍显示待付，可点「🔄 已付款，查询状态」'
    )
    return _panel(
        '💳 待付车票详情',
        _body(
            f'🎟️ {ticket_label}',
            f'项目：{project_no}',
            f'博主：{blogger}',
            f'描述：{description}',
            f'🧾 车票类型：{order_type}',
            f'💰 应付金额：{amount:g} 元',
            '⏳ 当前状态：等待付款 / 自动核验',
            f'🕒 过期时间：{expires_at}',
            f'⏰ 剩余时间：约 {remaining} 分钟',
        ),
        footer,
    )

def participated_detail(*, ticket_label: str, project_no: str, blogger: str, description: str, order_type: str, amount: float, paid_at: str, resource_status: str) -> str:
    return _panel(
        '🚗 已上车票小卡片',
        _body(f'🎟️ {ticket_label}', f'项目：{project_no}', f'博主：{blogger}', f'描述：{description}', f'🧾 车票类型：{order_type}', f'💰 已付金额：{amount:g} 元', '✅ 当前状态：已上车', f'🕒 核验时间：{paid_at}', f'📦 资源状态：{resource_status}'),
        '小掌柜提醒：资源审核通过后，这里会出现领取按钮。',
    )


def refund_detail(*, refund_no: str, project_no: str, blogger: str, description: str, amount: float, status: str, created_at: str, payment_label: str = '-', system_no: str = '-', payout_info: str | None = None, refunded_at: str | None = None, user_id: int | str | None = None) -> str:
    safe_payout = html.escape(str(payout_info or '尚未提交'))
    body = _body(
        f'退款单：{html.escape(str(refund_no or "-"))}',
        f'项目：{html.escape(str(project_no or "-"))}',
        f'博主：{html.escape(str(blogger or "-"))}',
        f'描述：{html.escape(str(description or "-"))}',
        f'退款状态：{html.escape(str(status or "-"))}',
        f'💰 退款金额：{amount:g} 元',
        f'🎫 原车票：{html.escape(str(payment_label or "-"))}',
        f'🔎 系统单号：<code>{html.escape(str(system_no or "-"))}</code>',
        f'🕒 创建时间：{html.escape(str(created_at or "-"))}',
        f'📮 收款资料：{safe_payout}',
        f'✅ 退款完成时间：{html.escape(str(refunded_at))}' if refunded_at else None,
    )
    if refunded_at:
        tip = '这笔退款已经处理完成，记录会继续保留在退款车票中。'
    elif payout_info:
        tip = '收款资料已提交，正在等待管理员确认退款；有补充说明可联系小掌柜。'
    else:
        tip = '还没有提交收款资料，请点击「💸 申请退款」补齐后进入管理员处理流程。'
    return _panel('💸 退款小票', body, tip)


def refund_apply_prompt(*, refund_no: str, project_no: str, blogger: str, description: str, amount: float, payment_label: str, system_no: str) -> str:
    return _panel(
        '💸 退款申请｜小掌柜退款台',
        _body(f'退款单：{refund_no}', f'项目：{project_no}', f'博主：{blogger}', f'描述：{description}', f'💰 退款金额：{amount:g} 元', f'🎫 原车票：{payment_label}', f'🔎 系统单号：<code>{system_no}</code>', '请像聊天一样发送你的退款收款资料：\n1️⃣ TRX / USDT 地址\n2️⃣ 支付宝账号 / 支付宝收款码\n3️⃣ 其他可收款方式', '支持内容：\n📝 文字账号\n🖼 收款码截图\n📎 文件凭证'),
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


def refund_done_user(*, refund_no: str, amount: float) -> str:
    return _panel('✅ 退款已处理完成啦～', f'退款单：{refund_no}\n退款金额：{amount:g} 元', '这张退款小票已经更新为「退款完成」。\n可以在「我的众筹 → 退款车票」里随时查看记录。\n\n这次没上车没关系，下次有缘再拼 ✨')


def refund_done_admin(*, refund_no: str, user_id: int, amount: float, notify_error: object | None = None) -> str:
    notify_line = '用户通知：已通过机器人私聊送达。' if not notify_error else f'用户通知：发送失败，需要人工提醒。原因：{notify_error}'
    return _panel('✅ 退款小票已完成', f'退款单：{refund_no}\n用户ID：{user_id}\n退款金额：{amount:g} 元\n{notify_line}', '状态已更新为退款完成，资金账本已记一笔退款支出。')


def admin_refund_empty() -> str:
    return _panel('🧾 退款小票', '暂时没有待处理退款～', '说明小车库里的退款小票都已经处理干净啦。\n有新的退款申请时，会在待办中心显示数量。')


def admin_refund_list_header(total: int) -> str:
    return _panel('🧾 退款小票待办', f'当前待处理：{total} 张')


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


def support_admin_new(*, ticket_no: str, user_label: str, user_id: int, context_text: str, user_message: str) -> str:
    return _panel(
        f'💬 新客服小纸条 {ticket_no}',
        _body('📌 状态：待回复', f'👤 用户：{user_label}', f'🆔 用户ID：<code>{user_id}</code>', context_text or '来源页面：通用客服入口', '🧸 对话记录', f'用户：{user_message}'),
        '小掌柜提示：点「回复用户」后，可发送文字、图片、视频、文件或语音。\n发送成功后，本群会显示“已送达用户”回执。',
    )


def support_reply_prompt(ticket_no: str) -> str:
    return _panel(f'💬 正在回复工单 {ticket_no}', '请像聊天一样，把要发给用户的内容直接发送出来。\n\n支持内容：\n📝 文字\n🖼 图片/截图\n🎬 视频\n📎 文件\n🎙 语音', '发送成功后，审核群会出现明确的“已送达用户”回执；失败时会保留工单，方便继续重试。')


def support_send_failed(*, ticket_no: str, user_label: str, error: object) -> str:
    return _panel('❌ 工单回复未能发送给用户', f'工单：{ticket_no}\n用户：{user_label}\n失败原因：{error}', '工单仍保持待回复状态，可以点「回复用户」重新发送。')


def admin_search_results_header(query: str) -> str:
    return _panel(f'🔎 搜索结果：{query}', '下面是小掌柜找到的相关记录。', '按钮在消息下方，可以直接跳转处理～')


def admin_project_detail(*, project_no: str, blogger: str, description: str, status: str, progress_text: str,
                         paid_amount: float, pending_orders: int, refunds: int, resource_status: str) -> str:
    return _panel(
        '🛠 小掌柜项目待办卡',
        _body(f'项目：{project_no}', f'博主：{blogger}', f'描述：{description}', f'状态：{status}', progress_text, '财务：', f'💰 已收：{paid_amount:g} 元', f'🧾 待付车票：{pending_orders} 张', f'💸 退款：{refunds} 张', '资源：', f'📤 当前：{resource_status}'),
        '小掌柜提醒：优先处理卡片下方待办按钮。',
    )


def ticket_other_status(*, ticket_no: str, project_no: str, blogger: str, status: str, reason: str | None) -> str:
    return _panel(
        '⚠️ 这张车票暂时不能自动核验～',
        _body(
            f'车票：{ticket_no}',
            f'项目：{project_no}',
            f'博主：{blogger}',
            f'当前状态：{status}',
            f'原因：{reason or "-"}',
        ),
        '可以返回待付车票重新查看；如果确认已付款，请联系小掌柜。',
    )


# ---------------------------------------------------------------------------
# v1.6.0.8 满员成功频道提醒卡片
# 让“拼车成功”独立频道通知复用全站统一面板风格：标题在卡片外，正文在上下分隔线中，
# 小掌柜提醒放在卡片外，避免和旧版硬编码文案视觉不一致。
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# v1.6.0.9 客服回复换接口 + 用户主动拉取兜底
# ---------------------------------------------------------------------------

def _support_ticket_status_label(status: str | None) -> str:
    return {
        'open': '等待小掌柜回复',
        'answered': '小掌柜已回复',
        'closed': '已关闭',
    }.get(status or '', status or '-')


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

# 用户和管理员均使用当前机器人内置客服中心。

def welcome() -> str:
    return _panel(
        '🎀 欢迎来到拼车小车库～',
        '我是你的小掌柜，专门帮你把发车、上车、支付、收资源这些事儿打理得明明白白 ✨\n\n'
        '你可以这样玩转小车库：\n'
        '🚗 发起众筹\n'
        '把你珍藏的博主和资源丢进来，小掌柜帮你审核发车，一步到位\n\n'
        '🔥 热门众筹\n'
        '看看大家正在拼什么好东西，心动就上车，不用犹豫\n\n'
        '💎 会员购买\n'
        '一次加入，获取目前已发布以及未来完成的众筹项目资源\n\n'
        '📋 我的众筹\n'
        '待付车票、已上车票、退款和资源都在这里，随时翻随时看\n\n'
        '💬 联系小掌柜\n'
        '遇到支付核验异常等问题，可以直接在本机器人里留言',
        '💡 小掌柜温馨提醒\n联系小掌柜时，小掌柜回复前请勿点击“结束对话”，以免失联。\n拼车上车要选对哦～选好项目再上车，支付后就不能换座位啦\n\n坐稳扶好，我们稳稳出发不迷路 ✨',
    )


def member_group_purchase(*, payment_ready: bool = True) -> str:
    body = _body(
        '加入会员群后，可持续获取：',
        '📦 目前已经发布的全部众筹项目资源',
        '🚗 未来新发起并完成的众筹项目资源',
        '🔔 会员群内后续资源更新与领取提醒',
        '',
        '这是会员群整库权益，不需要再按单个项目逐一购买。',
    )
    if payment_ready:
        tip = '点击下方「💳 立即购买会员」进入支付页面。支付完成后请按支付页面提示入群；若没有自动开通，可以联系小掌柜处理。'
    else:
        tip = '⚠️ 会员群支付链接暂未配置，请联系小掌柜处理。'
    return _panel('💎 会员购买', body, tip)

def admin_panel_startup() -> str:
    return _panel(
        '🛠 小掌柜待办中心',
        '待办数据正在加载中～',
        '处理建议：先看业务审核，再看客服小纸条。退款/报销/提现是业务单，用户普通咨询是客服单，两个入口分开处理。',
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
        '💬 联系小掌柜｜外部客服应急模式',
        _body(
            f'客服机器人：{bot_username}',
            f'来源页面：{source_label}',
            ref_line,
            '当前仅在 SUPPORT_EXTERNAL_ONLY=true 时使用。正常模式下，咨询会直接回到本众筹机器人内置客服中心。',
        ),
        f'请点下方按钮打开 {bot_username}。',
    )


def support_external_only_notice(*, bot_username: str) -> str:
    return _panel(
        '💬 客服入口临时切到外部机器人',
        _body(
            f'人工咨询请打开：{bot_username}',
            '这是应急配置 SUPPORT_EXTERNAL_ONLY=true 时才会出现的提示。',
            '退款、报销、提现、补票、资源审核这些业务待办仍会正常发送到审核群。',
        ),
        '正常情况下可把 SUPPORT_EXTERNAL_ONLY 改回 false，让用户直接在众筹机器人里联系客服。',
    )


def refund_admin_new(*, refund_no: str, user_label: str, user_id: int, amount: float, payment_label: str, system_no: str, pay_no: str, project_no: str, blogger: str, description: str, payout_info: str) -> str:
    return _panel(
        f'💸 业务审核｜新退款小票 {refund_no}',
        _body(
            '📌 类型：退款业务单（审核群处理，不是客服咨询）',
            '📌 状态：待确认退款',
            f'👤 用户：{user_label}',
            f'🆔 用户ID：<code>{user_id}</code>',
            f'项目：{project_no}',
            f'博主：{blogger}',
            f'描述：{description}',
            f'🎫 原车票：{payment_label}',
            f'🔎 系统单号：<code>{system_no}</code>',
            f'💳 支付单号：<code>{pay_no}</code>',
            f'💰 应退金额：{amount:g} 元',
            '📮 用户收款资料',
            payout_info,
        ),
        '处理边界：这张卡片是业务审核单，请管理员在本审核群核对并点击「✅ 确认已退款」。用户只是补充说明时，可让用户点「联系小掌柜」生成客服小纸条。',
    )


def admin_search_help() -> str:
    return _panel(
        '🔎 项目搜索｜小掌柜放大镜',
        '这条消息本身不是按钮，点它不会触发搜索。\n\n请用下面任意一种方式：\n1）直接回复这条消息发送关键词；\n2）直接发送命令：/search 关键词；\n3）在机器人私聊里发 P.012 / T.012 / VP系统单号。\n\n支持这些查法：\n• P.012 / P012 / 12：按项目编号搜索\n• T.012：按车票编号搜索\n• VP开头系统单号：按自动核验记录搜索\n• 支付单号：按第三方支付单号搜索\n• 用户数字ID：查用户车票/退款/客服\n• 博主名字 / 资源描述：查相关项目',
        '搜索结果只展示安全查看入口：项目详情、已支付用户、资源、车票详情、退款和客服。\n待付车票、直接补单和同项目待付入口已从搜索结果隐藏，避免误触。',
    )


# ---------------------------------------------------------------------------
# v1.6.1.3 内置私聊客服桥
# 用户消息直接同步到 SUPPORT_ADMIN_ID 私聊；管理员回复对应消息即可回给用户。
# ---------------------------------------------------------------------------

def support_open() -> str:
    return _panel(
        '💬 小掌柜私聊窗口已打开～',
        _body(
            '你已经进入客服对话状态啦～',
            '直接发送文字、截图、文件、视频或语音，',
            '小掌柜都能收到。',
            '',
            '有什么问题、需要什么帮助，',
            '直接丢过来就好 🎀',
            '',
            '小掌柜看到消息会第一时间来敲你，',
            '别客气，随时找我 ✨',
        ),
        '想结束时点「结束联系客服」，或发送“结束客服”。',
    )


def support_user_confirm(ticket_no: str) -> str:
    return (
        '你还可以继续补充文字、图片，\n'
        '有什么不明白的，直接丢过来就好，\n'
        '小掌柜看到后会第一时间在当前私聊里回复你。'
    )


def support_user_reply(ticket_no: str, reply_text: str | None = None) -> str:
    # 旧审核群回复链路仍会调用这个函数；私聊桥新链路会原样发送管理员内容。
    return _panel(
        f'💬 小掌柜回复（{ticket_no}）',
        reply_text or '小掌柜给你发来了一条回复。',
        '有需要可以继续补充消息，小掌柜会接着看～',
    )


def support_user_closed() -> str:
    return _panel(
        '✅ 客服对话已结束',
        '本次和小掌柜的对话已经关闭。',
        '后面还有问题，可以再次点「联系小掌柜」重新打开对话。',
    )


def support_private_user_forward_failed(*, error: object) -> str:
    return _panel(
        '⚠️ 暂时没有成功转给小掌柜',
        f'失败原因：{error}',
        '你还停留在客服对话里，可以稍后再发一次；也请检查 SUPPORT_ADMIN_ID 是否已配置并且管理员已经打开过本机器人。',
    )


def support_private_admin_incoming_header(*, ticket_no: str, user_label: str, user_id: int, context_text: str, message_kind: str) -> str:
    return (
        f'客服对话 {ticket_no}\n'
        f'{context_text or "来源页面：通用客服入口"}\n'
        f'用户名称：{user_label}\n'
        f'用户ID：{user_id}'
    )


def support_private_admin_text(*, header: str, user_message: str) -> str:
    body = (user_message or '-').strip()
    return f'{header}\n\n{body}'


def support_private_admin_caption(*, header: str, user_caption: str | None = None) -> str:
    caption = f'{header}'
    if user_caption:
        caption += f'\n\n{user_caption}'
    return caption


def support_private_admin_hold(*, user_name: str, user_id: int, ticket_no: str) -> str:
    return (
        f'📌 已保持对话 {ticket_no}\n'
        f'当前回复对象：{user_name}\n'
        f'用户ID：{user_id}'
    )


def support_private_admin_sent(*, user_label: str, ticket_no: str, delivery_method: str | None = None) -> str:
    return f'✅ 已发送给用户 {user_label}'


def support_private_admin_failed(*, user_label: str, ticket_no: str, error: object) -> str:
    return (
        f'❌ 没有发送成功给 {user_label}（{ticket_no}）\n'
        f'原因：{error}\n'
        '这个对话还保持着，可以处理后重新发送。'
    )


# ---------------------------------------------------------------------------
# v1.6.1.4 管理员私聊会话中心增强
# ---------------------------------------------------------------------------

def support_user_closed_by_admin() -> str:
    return _panel(
        '✅ 您的对话已结束',
        _body(
            '小掌柜已经结束了本次客服对话。',
            '这次问题如果已经处理好，可以去热门众筹瞧瞧看看～',
            '后续还有新问题，也可以再次点「联系小掌柜」重新打开对话。',
        ),
        '小掌柜提醒：退款、报销、提现等业务进度仍然可以在「我的众筹」里查看。',
    )


def support_private_admin_closed(*, user_label: str, ticket_no: str, notify_error: object | None = None) -> str:
    if notify_error:
        return (
            f'✅ 已结束客服对话 {ticket_no}\n'
            f'用户：{user_label}\n\n'
            f'⚠️ 但通知用户失败：{notify_error}'
        )
    return f'✅ 已结束客服对话 {ticket_no}\n用户：{user_label}\n已通知用户本次对话结束。'


def support_private_admin_switched_from_business(*, ticket_no: str, user_label: str, user_id: int, source_label: str, detail: str) -> str:
    return (
        f'💬 已切到用户对话 {ticket_no}\n'
        f'👤 用户：{user_label}\n'
        f'🆔 用户 ID：{user_id}\n'
        f'来源：{source_label}\n'
        f'{detail or "-"}\n\n'
        '你可以直接回复这条消息，也可以点「保持这个对话」后连续发送。\n'
        '审核群继续处理退款、报销、提现等业务动作；沟通内容统一放在这里。'
    )


def support_private_admin_active_missing() -> str:
    return (
        '⚠️ 当前没有保持中的客服对话。\n\n'
        '你可以：\n'
        '1. 回复某条带 S.xxx 的用户消息；\n'
        '2. 在退款/报销/提现审核卡片里点「切到用户对话」；\n'
        '3. 等用户从「联系小掌柜」进入客服。'
    )


# 客服交流统一在管理员私聊，审核群只保留业务审核。
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
            '💬 管理员私聊客服：',
            f'进行中/历史会话：{support_open}',
            f'⚠️ 风控提醒：{risks}',
            f'🚨 当前异常类型：{unresolved_events} 类',
        ),
        '边界说明：审核群只处理退款、报销、提现、资源、补票等业务动作；凡是需要和用户来回沟通的内容，统一切到 SUPPORT_ADMIN_ID 的私聊客服窗口。',
    )
