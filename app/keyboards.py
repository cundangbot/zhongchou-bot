from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from app.config import get_settings


def _join_deeplink(project_id: int) -> str:
    settings = get_settings()
    username = (settings.BOT_USERNAME or '').strip().lstrip('@')
    if not username:
        # main.py 启动时会从 Telegram 自动读取 username；若仍为空则拒绝生成公开频道回调按钮。
        raise RuntimeError('BOT_USERNAME 未就绪，无法生成频道私聊深链')
    return f'https://t.me/{username}?start=join_{project_id}'


def _support_bot_username() -> str:
    settings = get_settings()
    username = (settings.SUPPORT_BOT_USERNAME or '@jingpinhybot').strip().lstrip('@')
    return username or 'jingpinhybot'


def support_bot_display_name() -> str:
    return '@' + _support_bot_username()


def support_external_url(source: str = 'generic', ref_id: int | str | None = 0) -> str:
    """外部双向客服机器人深链。

    payload 约定：<SUPPORT_BOT_START_PREFIX>_<来源>_<业务ID>
    例：cf_error_123、cf_refund_8、cf_generic_0。
    Telegram start payload 仅使用字母数字下划线，方便 @jingpinhybot 解析。
    """
    settings = get_settings()
    username = _support_bot_username()
    safe_source = ''.join(ch for ch in str(source or 'generic').lower() if ch.isascii() and (ch.isalnum() or ch == '_')) or 'generic'
    try:
        safe_ref = int(ref_id or 0)
    except (TypeError, ValueError):
        safe_ref = 0
    prefix = ''.join(ch for ch in str(settings.SUPPORT_BOT_START_PREFIX or 'cf').lower() if ch.isascii() and (ch.isalnum() or ch == '_')) or 'cf'
    payload = f'{prefix}_{safe_source}_{safe_ref}'[:64]
    return f'https://t.me/{username}?start={payload}'


def support_contact_button(text: str = '💬 联系小掌柜', source: str = 'generic', ref_id: int | str | None = 0) -> InlineKeyboardButton:
    """统一客服入口。

    默认使用众筹机器人内置客服工单：用户点按钮后直接在当前机器人留言，
    管理员在待办中心/审核群里回复。只有 SUPPORT_EXTERNAL_ONLY=true 时，
    才临时切回外部客服机器人。
    """
    settings = get_settings()
    if bool(settings.SUPPORT_EXTERNAL_ONLY):
        return InlineKeyboardButton(text=text, url=support_external_url(source, ref_id))
    try:
        safe_ref = int(ref_id or 0)
    except (TypeError, ValueError):
        safe_ref = 0
    safe_source = ''.join(ch for ch in str(source or 'generic').lower() if ch.isascii() and (ch.isalnum() or ch == '_')) or 'generic'
    return InlineKeyboardButton(text=text, callback_data=f'support:start:{safe_source}:{safe_ref}')


def external_support_keyboard(source: str = 'generic', ref_id: int | str | None = 0, back_callback: str | None = 'orders:center') -> InlineKeyboardMarkup:
    settings = get_settings()
    if bool(settings.SUPPORT_EXTERNAL_ONLY):
        first_text = f'💬 打开 {support_bot_display_name()} 联系小掌柜'
    else:
        first_text = '💬 在众筹机器人里联系小掌柜'
    rows = [[support_contact_button(first_text, source, ref_id)]]
    if back_callback:
        rows.append([InlineKeyboardButton(text='📋 返回我的众筹', callback_data=back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# 底部常驻菜单：可爱版，显示在 Telegram 输入框下方。
def main_menu() -> ReplyKeyboardMarkup:
    # 底部常驻菜单只保留用户最常用的 3 个入口。
    # /start、/admin_dashboard 等放到 Telegram 左侧“/”命令菜单里。
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text='🚗 发起众筹')],
            [KeyboardButton(text='🔥 热门众筹'), KeyboardButton(text='📋 我的众筹')],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder='选个小功能，滴滴出发～🚗✨',
    )


def non_member_keyboard() -> ReplyKeyboardMarkup:
    return main_menu()


def order_center_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='💳 待付车票', callback_data='orders:pending:0')],
        [InlineKeyboardButton(text='📋 已上车票', callback_data='orders:participated:0')],
        [InlineKeyboardButton(text='💸 退款车票', callback_data='orders:refunds:0')],
        [InlineKeyboardButton(text='🙋 我是车主记录', callback_data='orders:created:0')],
        [InlineKeyboardButton(text='📦 我的宝贝资源', callback_data='resources:mine')],
        [support_contact_button('💬 联系小掌柜', 'generic', 0)],
    ])


def pending_order_actions_keyboard(order_id: int, payment_link: str | None = None) -> InlineKeyboardMarkup:
    rows = []
    if payment_link:
        rows.append([InlineKeyboardButton(text='💸 点击支付', url=payment_link)])
    rows.append([InlineKeyboardButton(text='✅ 我已支付，去验票', callback_data=f'pay:ticket:{order_id}')])
    rows.append([InlineKeyboardButton(text='🗑 取消这班车', callback_data=f'orders:cancel_pending:{order_id}')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def order_center_back_keyboard() -> InlineKeyboardMarkup:
    return order_center_keyboard()


def hot_projects_keyboard(projects, page: int = 0, page_size: int = 10) -> InlineKeyboardMarkup:
    """热门众筹固定最多 20 个，分两页展示，每页 10 个。"""
    safe_page = 0 if page <= 0 else 1
    total = min(len(projects), 20)
    start = safe_page * page_size
    end = min(start + page_size, total)
    rows = []
    for p in list(projects)[start:end]:
        paid = int(p.paid_seats or 0)
        required = max(1, int(p.required_seats or 0))
        if paid >= required:
            progress = '🎉 已满员｜可补票'
        else:
            progress = f'🔥 {paid}/{required}｜差{required - paid}人'
        rows.append([InlineKeyboardButton(text=f'🚗 {p.blogger}｜{progress}'[:58], callback_data=f'hot:view:{p.id}')])
    nav = []
    if safe_page > 0:
        nav.append(InlineKeyboardButton(text='⬅️ 上一页', callback_data='hot:list:0'))
    if end < total and safe_page < 1:
        nav.append(InlineKeyboardButton(text='➡️ 下一页', callback_data='hot:list:1'))
    if nav:
        rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)



def carpool_price_keyboard() -> InlineKeyboardMarkup:
    settings = get_settings()
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f'🎟️ {settings.CARPOOL_PRICE_30:g} 元车位', callback_data=f'cf:seat_price:{int(settings.CARPOOL_PRICE_30)}'),
            InlineKeyboardButton(text=f'🎟️ {settings.CARPOOL_PRICE_60:g} 元车位', callback_data=f'cf:seat_price:{int(settings.CARPOOL_PRICE_60)}'),
        ],
        [InlineKeyboardButton(text='⛔ 不发了', callback_data='cf:price_cancel')],
    ])

def purchase_mode_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🙋 我来垫付', callback_data='cf:mode:prepaid')],
        [InlineKeyboardButton(text='🤖 平台代购', callback_data='cf:mode:platform')],
        [InlineKeyboardButton(text='📦 我已持有资源', callback_data='cf:mode:owned')],
    ])


def confirm_project_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🚗 发车！提交审核', callback_data='cf:confirm')],
        [InlineKeyboardButton(text='⛔ 不发了', callback_data='cf:cancel')],
    ])


def admin_review_keyboard(project_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ 通过发车', callback_data=f'admin:approve:{project_id}')],
        [InlineKeyboardButton(text='🔍 打开项目卡片', callback_data=f'admin:project:{project_id}')],
        [InlineKeyboardButton(text='❌ 拒绝', callback_data=f'admin:reject:{project_id}')],
    ])


def join_project_keyboard(project_id: int, full: bool = False, cancelled: bool = False, seat_price: float | int | None = None) -> InlineKeyboardMarkup:
    settings = get_settings()
    if cancelled:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='⛔ 已取消本次拼车', callback_data=f'cf:cancelled:{project_id}')]
        ])

    # 公开频道只使用 URL 深链，绝不使用会在频道触发 callback 的个人上车按钮。
    if full:
        price = float(seat_price if seat_price is not None else settings.SEAT_PRICE)
        text = f'🔓 满员后支付{price:g}元拿资源'
    else:
        text = '🚗 我要上车！'
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, url=_join_deeplink(project_id))]
    ])


def creator_resource_keyboard(project_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='📤 上传资源', callback_data=f'creator:upload_resource:{project_id}')],
    ])


def creator_buyinfo_keyboard(project_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='📝 填写购买渠道资料', callback_data=f'creator:buyinfo:{project_id}')],
    ])


def admin_project_full_keyboard(project_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='📤 上传资源', callback_data=f'admin:upload_resource:{project_id}')],
        [InlineKeyboardButton(text='🔎 项目详情', callback_data=f'admin:project:{project_id}')],
        [InlineKeyboardButton(text='❌ 取消并生成退款清单', callback_data=f'admin:cancel_project:{project_id}')],
    ])


def admin_project_detail_keyboard(project_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🔍 打开项目卡片', callback_data=f'admin:project:{project_id}')],
        [InlineKeyboardButton(text='✅ 已支付用户', callback_data=f'admin:paid_users:{project_id}')],
        [InlineKeyboardButton(text='💳 待付车票', callback_data=f'admin:pending_orders:{project_id}')],
        [InlineKeyboardButton(text='🎫 手动补票', callback_data=f'admin:manual_verify:{project_id}')],
        [InlineKeyboardButton(text='🧾 支付闭环检查', callback_data=f'admin:audit_project:{project_id}')],
        [InlineKeyboardButton(text='🔧 同步进度/权限', callback_data=f'admin:sync_project:{project_id}')],
        [InlineKeyboardButton(text='📦 查看上传资源', callback_data=f'admin:view_resources:{project_id}')],
        [InlineKeyboardButton(text='🧭 状态历史', callback_data=f'admin:state_history:{project_id}')],
        [InlineKeyboardButton(text='🔁 重新上传/修正资源', callback_data=f'admin:reset_resource:{project_id}')],
        [InlineKeyboardButton(text='✅ 手动标记满员', callback_data=f'admin:mark_full:{project_id}')],
        [InlineKeyboardButton(text='⏰ 延长上传时间3小时', callback_data=f'admin:extend_resource:{project_id}:3')],
        [InlineKeyboardButton(text='❌ 手动取消项目', callback_data=f'admin:cancel_project:{project_id}')],
    ])


def resource_upload_collect_keyboard(project_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ 上传好啦，提交审核', callback_data=f'resource:finish:{project_id}')],
        [InlineKeyboardButton(text='⛔ 不传了，取消', callback_data=f'resource:cancel:{project_id}')],
    ])


def admin_resource_upload_done_keyboard(project_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ 上传好啦，私发资源', callback_data=f'admin:publish_resource:{project_id}')],
        [InlineKeyboardButton(text='⛔ 不传了，取消', callback_data=f'resource:cancel:{project_id}')],
    ])


def resource_review_keyboard(project_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ 审核通过，放宝贝', callback_data=f'admin:publish_resource:{project_id}')],
        [InlineKeyboardButton(text='❌ 驳回并要求重传', callback_data=f'admin:reject_resource:{project_id}')],
    ])


def payment_order_keyboard(order_id: int, payment_link: str | None = None) -> InlineKeyboardMarkup:
    return pending_order_actions_keyboard(order_id, payment_link)


def withdraw_project_keyboard(project_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='💰 申请提现', callback_data=f'creator:withdraw:{project_id}')],
        [InlineKeyboardButton(text='📊 收益明细', callback_data=f'creator:income:{project_id}')],
        [InlineKeyboardButton(text='📋 返回我发起的', callback_data='orders:created:0')],
    ])


def withdrawal_admin_keyboard(withdrawal_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ 确认已支付提现/报销', callback_data=f'admin:withdraw_paid:{withdrawal_id}')],
        [InlineKeyboardButton(text='💬 切到申请人对话', callback_data=f'admin:support_link:payout:{withdrawal_id}')],
        [InlineKeyboardButton(text='❌ 驳回申请', callback_data=f'admin:withdraw_reject:{withdrawal_id}')],
    ])


def description_collect_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ 描述发送完毕，填写原价', callback_data='cf:desc_done')],
    ])


def resource_claim_keyboard(project_id: int, counts: dict) -> InlineKeyboardMarkup:
    rows = []
    total = sum(int(v or 0) for v in counts.values())
    if total > 0:
        rows.append([InlineKeyboardButton(text=f'🎁 一键领取全部（{total}）', callback_data=f'resource:page:{project_id}:all:0')])
    if counts.get('photo', 0) > 0:
        rows.append([InlineKeyboardButton(text=f'🖼 查看图片（{counts["photo"]}）', callback_data=f'resource:page:{project_id}:photo:0')])
    if counts.get('video', 0) > 0:
        rows.append([InlineKeyboardButton(text=f'🎬 查看视频（{counts["video"]}）', callback_data=f'resource:page:{project_id}:video:0')])
    if counts.get('text', 0) > 0:
        rows.append([InlineKeyboardButton(text=f'📄 查看文本（{counts["text"]}）', callback_data=f'resource:page:{project_id}:text:0')])
    file_count = counts.get('document', 0) + counts.get('animation', 0) + counts.get('copy', 0)
    if file_count > 0:
        rows.append([InlineKeyboardButton(text=f'📎 查看文件/其他（{file_count}）', callback_data=f'resource:page:{project_id}:file:0')])
    if not rows:
        rows.append([InlineKeyboardButton(text='📦 查看资源', callback_data=f'resource:page:{project_id}:all:0')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def resource_next_page_keyboard(project_id: int, kind: str, next_page: int | None) -> InlineKeyboardMarkup | None:
    if next_page is None:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='📖 下一页', callback_data=f'resource:page:{project_id}:{kind}:{next_page}')]
    ])


def reimbursement_apply_keyboard(project_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='💰 点击报销', callback_data=f'creator:reimburse:{project_id}')],
        [InlineKeyboardButton(text='📋 返回我发起的', callback_data='orders:created:0')],
    ])


def refund_apply_keyboard(refund_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='💸 申请退款', callback_data=f'refund:apply:{refund_id}')],
    ])


def refund_item_keyboard(refund_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ 确认已退款', callback_data=f'admin:refund_done:{refund_id}')],
        [InlineKeyboardButton(text='💬 切到退款用户对话', callback_data=f'admin:support_link:refund:{refund_id}')],
    ])


def admin_dashboard_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🧺 待审核车车', callback_data='admin:list:pending_review')],
        [InlineKeyboardButton(text='📤 待补资源', callback_data='admin:list:wait_upload')],
        [InlineKeyboardButton(text='💰 报销/提现小篮子', callback_data='admin:list:payouts')],
        [InlineKeyboardButton(text='🧾 退款小票', callback_data='admin:list:refunds')],
        [InlineKeyboardButton(text='💬 私聊客服记录', callback_data='admin:list:support')],
        [InlineKeyboardButton(text='⚠️ 风控提醒', callback_data='admin:list:risks')],
        [InlineKeyboardButton(text='💹 资金账本', callback_data='admin:list:ledger')],
        [InlineKeyboardButton(text='🚨 异常小雷达', callback_data='admin:list:exceptions')],
        [InlineKeyboardButton(text='🩺 系统健康', callback_data='admin:health')],
        [InlineKeyboardButton(text='🔎 项目搜索', callback_data='admin:search_help')],
    ])


def admin_list_item_keyboard(project_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🔍 打开项目卡片', callback_data=f'admin:project:{project_id}')],
    ])


# ===== v1.4.8 分页列表 / 详情页按钮 =====
def _page_rows(prefix: str, page: int, has_prev: bool, has_next: bool) -> list[list[InlineKeyboardButton]]:
    rows = []
    nav = []
    if has_prev:
        nav.append(InlineKeyboardButton(text='⬅️ 上一页', callback_data=f'{prefix}:{page-1}'))
    if has_next:
        nav.append(InlineKeyboardButton(text='➡️ 下一页', callback_data=f'{prefix}:{page+1}'))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text='📋 返回车票小仓库', callback_data='orders:center')])
    return rows


def verify_failure_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [support_contact_button('💬 联系小掌柜', 'error', 0)],
        [InlineKeyboardButton(text='⬅️ 返回待付车票', callback_data='orders:pending:0')],
    ])


def paged_item_keyboard(item_prefix: str, page_prefix: str, items, page: int, label_func, page_size: int = 5) -> InlineKeyboardMarkup:
    total = len(items)
    start = max(0, page) * page_size
    end = start + page_size
    rows = []
    for obj in items[start:end]:
        rows.append([InlineKeyboardButton(text=label_func(obj), callback_data=f'{item_prefix}:{getattr(obj, "id", obj)}')])
    rows.extend(_page_rows(page_prefix, page, page > 0, end < total))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def pending_order_detail_keyboard(order_id: int, payment_link: str | None = None) -> InlineKeyboardMarkup:
    rows = []
    if payment_link:
        rows.append([InlineKeyboardButton(text='💸 点击支付', url=payment_link)])
    rows.append([InlineKeyboardButton(text='✅ 我已支付，去验票', callback_data=f'pay:ticket:{order_id}')])
    rows.append([InlineKeyboardButton(text='🗑 取消这班车', callback_data=f'orders:cancel_pending:{order_id}')])
    rows.append([InlineKeyboardButton(text='⬅️ 返回待付车票', callback_data='orders:pending:0')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def ticket_verify_keyboard(order_id: int, back_to_pending: bool = True) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text='📎 提交订单号', callback_data=f'pay:submit:{order_id}')],
        [InlineKeyboardButton(text='🔄 刷新车票状态', callback_data=f'pay:refresh:{order_id}')],
    ]
    if back_to_pending:
        rows.append([InlineKeyboardButton(text='⬅️ 返回待付车票', callback_data='orders:pending:0')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def participated_detail_keyboard(project_id: int, can_claim: bool = False, has_refund: bool = False, refund_id: int | None = None) -> InlineKeyboardMarkup:
    rows = []
    if can_claim:
        rows.append([InlineKeyboardButton(text='📦 领取资源', callback_data=f'resource:claim_panel:{project_id}')])
    if has_refund and refund_id:
        rows.append([InlineKeyboardButton(text='💸 查看退款进度', callback_data=f'orders:refund_detail:{refund_id}')])
    rows.append([InlineKeyboardButton(text='⬅️ 返回已上车票', callback_data='orders:participated:0')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def refund_detail_keyboard(refund_id: int, can_apply: bool = False, relaunch_project_id: int | None = None) -> InlineKeyboardMarkup:
    rows = []
    if relaunch_project_id:
        rows.append([InlineKeyboardButton(text='🔁 重新拼车', callback_data=f'creator:relaunch:{relaunch_project_id}')])
    if can_apply:
        rows.append([InlineKeyboardButton(text='💸 申请退款', callback_data=f'refund:apply:{refund_id}')])
    rows.append([support_contact_button('💬 联系小掌柜', 'refund', refund_id)])
    rows.append([InlineKeyboardButton(text='⬅️ 返回退款车票', callback_data='orders:refunds:0')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def creator_project_detail_keyboard(project_id: int, *, can_relaunch: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if can_relaunch:
        rows.append([InlineKeyboardButton(text='🔁 重新拼车', callback_data=f'creator:relaunch:{project_id}')])
    rows.extend([
        [InlineKeyboardButton(text='💸 申请提现', callback_data=f'creator:withdraw:{project_id}')],
        [InlineKeyboardButton(text='📊 收益明细', callback_data=f'creator:income:{project_id}')],
        [InlineKeyboardButton(text='⬅️ 返回车主记录', callback_data='orders:created:0')],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def support_start_keyboard() -> InlineKeyboardMarkup:
    return external_support_keyboard('generic', 0, back_callback='orders:center')


def contact_admin_keyboard(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='💬 回复用户', callback_data=f'admin:support_reply:{ticket_id}')],
        [InlineKeyboardButton(text='✅ 关闭工单', callback_data=f'admin:support_close:{ticket_id}')],
    ])


def contact_answered_keyboard(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='💬 继续回复用户', callback_data=f'admin:support_reply:{ticket_id}')],
        [InlineKeyboardButton(text='✅ 关闭工单', callback_data=f'admin:support_close:{ticket_id}')],
    ])


def support_private_admin_keyboard(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='📌 保持这个对话', callback_data=f'admin:support_hold:{ticket_id}')],
        [InlineKeyboardButton(text='✅ 结束这个对话', callback_data=f'admin:support_close:{ticket_id}')],
    ])


def support_private_user_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ 结束联系客服', callback_data='support:end')],
        [InlineKeyboardButton(text='📋 返回我的众筹', callback_data='orders:center')],
    ])


def support_admin_switch_keyboard(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='📌 保持这个对话', callback_data=f'admin:support_hold:{ticket_id}')],
        [InlineKeyboardButton(text='✅ 结束这个对话', callback_data=f'admin:support_close:{ticket_id}')],
    ])


def support_closed_by_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🔥 去热门众筹瞧瞧', callback_data='hot:list')],
        [InlineKeyboardButton(text='📋 返回我的众筹', callback_data='orders:center')],
    ])


def support_ticket_user_keyboard(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🔄 查看小掌柜回复', callback_data=f'support:ticket:{ticket_id}')],
        [support_contact_button('💬 继续联系客服', 'generic', 0)],
        [InlineKeyboardButton(text='📋 返回我的众筹', callback_data='orders:center')],
    ])

def contact_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [support_contact_button('💬 继续联系客服', 'generic', 0)],
        [InlineKeyboardButton(text='📋 返回我的众筹', callback_data='orders:center')],
    ])


def empty_orders_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🔥 去看热门众筹', callback_data='hot:list')],
        [InlineKeyboardButton(text='🔙 返回', callback_data='orders:center')],
    ])


def empty_resources_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🔥 去看热门众筹', callback_data='hot:list')],
        [InlineKeyboardButton(text='🔙 返回我的众筹', callback_data='orders:center')],
    ])


def payment_error_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [support_contact_button('💬 联系小掌柜', 'error', order_id)],
        [InlineKeyboardButton(text='🔙 返回待付车票', callback_data='orders:pending:0')],
    ])


def refund_detail_context_keyboard(refund_id: int, can_apply: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if can_apply:
        rows.append([InlineKeyboardButton(text='💸 申请退款', callback_data=f'refund:apply:{refund_id}')])
    rows.append([support_contact_button('💬 联系小掌柜', 'refund', refund_id)])
    rows.append([InlineKeyboardButton(text='⬅️ 返回退款车票', callback_data='orders:refunds:0')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def resource_progress_keyboard(project_id: int, progress: dict[str, int], totals: dict[str, int]) -> InlineKeyboardMarkup:
    labels = {'photo': '🖼 图片', 'video': '🎬 视频', 'text': '📝 文本', 'file': '📎 文件'}
    page_size = max(1, int(get_settings().RESOURCE_PAGE_SIZE))
    rows = []
    for kind, label in labels.items():
        total = int(totals.get(kind, 0))
        if total <= 0:
            continue
        next_page = int(progress.get(kind, 0))
        delivered = min(total, next_page * page_size)
        if delivered < total:
            action = '继续领取' if delivered else '开始领取'
            rows.append([InlineKeyboardButton(text=f'{action}{label}（{delivered}/{total}）', callback_data=f'resource:page:{project_id}:{kind}:{next_page}')])
        else:
            rows.append([InlineKeyboardButton(text=f'✅ {label}已全部领取（{total}/{total}）', callback_data=f'resources:detail:{project_id}')])
        if delivered:
            rows.append([InlineKeyboardButton(text=f'🔁 从头领取{label}', callback_data=f'resource:restart:{project_id}:{kind}')])
    rows.append([InlineKeyboardButton(text='🔙 返回我的资源', callback_data='resources:mine')])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def admin_search_results_keyboard(projects=None, orders=None, refunds=None, tickets=None, payouts=None) -> InlineKeyboardMarkup:
    """项目搜索结果快捷按钮：尽量复用已有管理回调，避免只返回纯文本。"""
    rows: list[list[InlineKeyboardButton]] = []
    seen_projects: set[int] = set()

    for p in list(projects or [])[:5]:
        pid = int(getattr(p, 'id', 0) or 0)
        if not pid or pid in seen_projects:
            continue
        seen_projects.add(pid)
        label = f'🔍 {"P.%03d" % pid} 项目卡片｜{getattr(p, "blogger", "-")}'[:58]
        rows.append([InlineKeyboardButton(text=label, callback_data=f'admin:project:{pid}')])
        rows.append([
            InlineKeyboardButton(text='✅ 已支付', callback_data=f'admin:paid_users:{pid}'),
            InlineKeyboardButton(text='💳 待付', callback_data=f'admin:pending_orders:{pid}'),
            InlineKeyboardButton(text='📦 资源', callback_data=f'admin:view_resources:{pid}'),
        ])

    for o in list(orders or [])[:5]:
        pid = int(getattr(o, 'project_id', 0) or 0)
        oid = int(getattr(o, 'id', 0) or 0)
        if not oid:
            continue
        rows.append([InlineKeyboardButton(text=f'🎫 打开车票 T.{oid:03d}', callback_data=f'admin:order:{oid}')])
        row = []
        if pid:
            row.append(InlineKeyboardButton(text='🔍 对应项目', callback_data=f'admin:project:{pid}'))
        if getattr(o, 'status', '') == 'pending':
            row.append(InlineKeyboardButton(text='🛠 直接补单', callback_data=f'admin:manual_verify_select:{oid}'))
        elif pid:
            row.append(InlineKeyboardButton(text='💳 同项目待付', callback_data=f'admin:pending_orders:{pid}'))
        if row:
            rows.append(row)

    if refunds:
        rows.append([InlineKeyboardButton(text='🧾 打开退款小票列表', callback_data='admin:list:refunds')])

    for t in list(tickets or [])[:3]:
        tid = int(getattr(t, 'id', 0) or 0)
        if tid:
            rows.append([InlineKeyboardButton(text=f'💬 回复客服工单 S.{tid:03d}', callback_data=f'admin:support_reply:{tid}')])

    if not rows:
        rows.append([InlineKeyboardButton(text='🔎 再搜一次', callback_data='admin:search_help')])
    rows.append([InlineKeyboardButton(text='⬅️ 返回待办中心', callback_data='admin:dashboard')])
    return InlineKeyboardMarkup(inline_keyboard=rows)
