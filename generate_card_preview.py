from pathlib import Path
from datetime import datetime
from app.messages import cute

sections = []

def add(title, text, buttons=None):
    block = f'## {title}\n\n```text\n{text}\n```\n'
    if buttons:
        block += f'按钮：\n```text\n{buttons}\n```\n'
    sections.append(block)

progress = '🔥 拼车进度：6/8\n🟩🟩🟩🟩🟩🟩⬜⬜\n还差 2 人满员'
add('1. 首页 /start', cute.welcome(), '🚗 发起众筹\n🔥 热门众筹    📋 我的众筹')
add('2.1 发起众筹入口', cute.crowdfunding_start(creator_prepay_seats=2, seat_price=30, creator_amount=60), '我知道啦，开始发车（自动进入填写）')
add('2.2 资源说明', cute.crowdfunding_description_prompt('某博主'), '✅ 描述发送完毕，填写原价')
add('2.3 资源描述回执', cute.crowdfunding_description_ack(3), '✅ 描述发送完毕，填写原价')
add('2.4 原价填写', cute.crowdfunding_price_prompt())
add('2.5 小算盘结果', cute.crowdfunding_price_calc(price=188, total=235, base_seats=7, seats=8, seat_price=30, creator_prepay_seats=2), '🙋 我来垫付\n🤖 平台代购\n📦 我已持有资源')
add('2.6 发车前确认', cute.crowdfunding_confirm(blogger='某博主', description='合集/补档/限定内容', media_note='描述附件：有图片/视频/文件，将与拼车详情合并发布。', price=188, total=235, seats=8, seat_price=30, creator_amount=60, mode_name='🤖 平台代购资源'), '🚗 发车！提交审核\n⛔ 不发了')
add('2.7 提交审核成功', cute.crowdfunding_submitted('P.012'))
add('2.8 审核群新众筹', cute.crowdfunding_admin_new(creator='@user', project_no='P.012', blogger='某博主', description='合集/补档/限定内容', price=188, seats=8, mode='platform'), '✅ 通过发车\n🔍 打开项目卡片\n❌ 拒绝')
add('2.9 审核通过通知', cute.crowdfunding_creator_approved(project_title='P.012｜某博主', prepay_seats=2, amount=60), '💸 点击支付\n✅ 我已支付，去验票\n🗑 取消这班车')
add('3.1 热门众筹第 1 页', cute.hot_page_text(page=1, pages=2, start=1, end=10, total=20), '🚗 某博主A｜🔥 6/8｜差2人\n🚗 某博主B｜🎉 已满员｜可补票\n➡️ 下一页')
add('3.2 热门众筹第 2 页', cute.hot_page_text(page=2, pages=2, start=11, end=20, total=20), '⬅️ 上一页')
add('3.3 热门众筹为空', cute.hot_empty())
add('4.1 项目详情卡片', cute.project_public_card(project_no_text='P.012', blogger='某博主', description='合集/补档/限定内容', progress_text=progress, seat_price=30, original_price=188, mode_name='🤖 小掌柜代买', status_name='众筹中', total_amount=235, required_seats=8, creator_prepay_seats=2, creator_prepay_amount=60), '🚗 我要上车！')
add('4.2 满员后项目详情', cute.project_public_card(project_no_text='P.012', blogger='某博主', description='合集/补档/限定内容', progress_text='🎉 已满员', seat_price=30, original_price=188, mode_name='🤖 小掌柜代买', status_name='已满员', total_amount=235, required_seats=8, creator_prepay_seats=2, creator_prepay_amount=60, after_full=True, extra_fund_count=2), '🔓 满员后支付30元拿资源')
add('5. 生成车票 / 支付提示', cute.payment_created(project_no='P.012', blogger='某博主', description='合集/补档/限定内容', amount=30, ticket_no='T.023'), '💸 点击支付\n✅ 我已支付，去验票\n🗑 取消这班车')
add('6.1 普通电子车票', cute.ticket_card(order_type='crowdfunding_normal', project_no='P.012', blogger='某博主', description='合集/补档/限定内容', amount=30, ticket_no='T.023', seat_no='NO.023', seed='某博主'), '📎 提交订单号\n🔄 刷新车票状态\n⬅️ 返回待付车票')
add('6.2 车主卡密', cute.ticket_card(order_type='crowdfunding_creator_prepay', project_no='P.012', blogger='某博主', description='合集/补档/限定内容', amount=60, ticket_no='T.001', seat_no='NO.001', seed='某博主'), '📎 提交订单号\n🔄 刷新车票状态\n⬅️ 返回待付车票')
add('6.3 满员后补票', cute.ticket_card(order_type='crowdfunding_after_full', project_no='P.012', blogger='某博主', description='合集/补档/限定内容', amount=30, ticket_no='T.031', seat_no='NO.031', seed='某博主'))
add('7.1 提交订单号', cute.submit_order_prompt(payment_label='待绑定车票：T.023', target='项目：P.012\n博主：某博主\n描述：合集/补档/限定内容', amount=30))
add('7.2 正在验票', cute.verifying('VP202606101234567890'))
add('7.3 验票成功', cute.verify_success('OK'))
add('7.4 验票失败', cute.verify_failed('订单号格式错误'), '💬 联系小掌柜\n⬅️ 返回待付车票')
add('7.5 验票服务异常', cute.verify_service_error(), '💬 联系小掌柜\n⬅️ 返回待付车票')
add('8.1 我的众筹 / 订单中心', cute.order_center(), '💳 待付车票\n📋 已上车票\n💸 退款车票\n🙋 我是车主记录\n📦 我的宝贝资源\n💬 联系小掌柜')
add('8.2 待付车票列表', cute.pending_orders_list(page=1, pages=1, total=2), 'P.012｜某博主｜待验票｜6/8\n📋 返回车票小仓库')
add('8.3 待付车票详情', cute.pending_order_detail(ticket_label='T.023', project_no='P.012', blogger='某博主', description='合集/补档/限定内容', order_type='普通上车', amount=30, expires_at='2026-06-10 21:00', remaining=25), '💸 点击支付\n✅ 我已支付，去验票\n🗑 取消这班车\n⬅️ 返回待付车票')
add('8.4 已上车票详情', cute.participated_detail(ticket_label='T.023', project_no='P.012', blogger='某博主', description='合集/补档/限定内容', order_type='普通上车', amount=30, paid_at='2026-06-10 20:30', resource_status='宝贝待审核'), '📦 领取资源（资源可领取时出现）\n💸 查看退款进度（有退款时出现）\n⬅️ 返回已上车票')
add('9.1 资源为空', cute.resource_empty(), '🔥 去看热门众筹\n🔙 返回我的众筹')
add('9.2 资源领取面板', cute.resource_claim_panel(project_no='P.012', blogger='某博主', photo=6, video=2, text=1, file=1), '🎁 一键领取全部（10）\n🖼 查看图片（6）\n🎬 查看视频（2）\n📄 查看文本（1）\n📎 查看文件/其他（1）\n🔙 返回我的资源')
add('9.3 资源上传面板', cute.resource_upload_panel(project_no='P.012', blogger='某博主', total=3, text=1, photo=2, video=0, file=0), '✅ 上传好啦，提交审核\n⛔ 不传了，取消')
add('10.1 退款车票列表', cute.refund_orders_list(page=1, pages=1, total=1), 'P.012｜某博主｜退款中\n📋 返回车票小仓库')
add('10.2 退款小票详情', cute.refund_detail(refund_no='R.002', project_no='P.012', blogger='某博主', description='合集/补档/限定内容', amount=30, status='待申请', created_at='2026-06-10 20:30', payment_label='T.023', system_no='VP202606101234567890'), '💸 申请退款\n💬 联系小掌柜\n⬅️ 返回退款车票')
add('10.3 退款申请', cute.refund_apply_prompt(refund_no='R.002', project_no='P.012', blogger='某博主', description='合集/补档/限定内容', amount=30, payment_label='T.023', system_no='VP202606101234567890'), '⛔ 先不申请了')
add('10.4 退款资料提交成功', cute.refund_user_submitted('R.002'))
add('10.5 审核群新退款小票', cute.refund_admin_new(refund_no='R.002', user_label='@user', user_id=123456789, amount=30, payment_label='T.023', system_no='VP202606101234567890', pay_no='PAY123', project_no='P.012', blogger='某博主', description='合集/补档/限定内容', payout_info='支付宝：user@example.com'), '✅ 确认已退款')
add('10.6 退款完成通知用户', cute.refund_done_user(refund_no='R.002', amount=30))
add('10.7 退款完成审核群回执', cute.refund_done_admin(refund_no='R.002', user_id=123456789, amount=30))
add('10.8 车主项目详情', cute.creator_project_detail(project_no='P.012', blogger='某博主', description='合集/补档/限定内容', progress_text='🔥 拼车进度：8/8\n🟩🟩🟩🟩🟩🟩🟩🟩\n🎉 已满员', original_price=188, seat_price=30, extra_count=20, batches=2), '💸 申请提现\n📊 收益明细\n⬅️ 返回车主记录')
add('11.1 客服窗口', cute.support_open())
add('11.2 用户发送内容回执', cute.support_user_confirm('S.018'))
add('11.3 审核群客服小纸条', cute.support_admin_new(ticket_no='S.018', user_label='@user', user_id=123456789, context_text='来源页面：待付车票详情\n项目：P.012\n博主：某博主\n描述：合集/补档/限定内容\n车票：T.023\n当前状态：pending\n最近错误：订单号格式错误', user_message='我支付了，但是验票失败，这是截图'), '💬 回复用户\n✅ 关闭工单')
add('11.4 客服回复输入提示', cute.support_reply_prompt('S.018'))
add('11.5 用户收到客服回复', cute.support_user_reply('S.018', '宝贝，截图看起来是复制到了支付单号，不是系统单号～\n请回到发卡平台订单详情里，复制 VP 开头的系统单号再提交一次哦。'))
add('11.6 审核群送达回执', cute.support_receipt(ticket_no='S.018', user_label='@user', reply_kind='文字', admin_name='@admin', answered_at=datetime(2026,6,10,20,30)))
add('12.1 管理待办中心', cute.admin_dashboard_text(pending_review=2, wait_upload=4, pending_payout=1, pending_withdraw=0, pending_refunds=1, support_open=3, risks=1, unresolved_events=0, new_projects=3, paid_orders=18, income=540, full_projects=2), '🧺 待审核车车\n📤 待补资源\n💰 报销/提现小篮子\n🧾 退款小票\n💬 客服小纸条\n⚠️ 风控提醒\n💹 资金账本\n🚨 异常小雷达\n🩺 系统健康\n🔎 项目搜索')
add('12.2 管理端项目详情', cute.admin_project_detail(project_no='P.012', blogger='某博主', description='合集/补档/限定内容', status='众筹中', progress_text=progress, paid_amount=180, pending_orders=2, refunds=0, resource_status='待上传 / 待审核 / 已发布'), '🔍 打开项目卡片\n✅ 已支付用户\n💳 待付车票\n🎫 手动补票\n📦 查看上传资源\n🧭 状态历史\n🔁 重新上传/修正资源\n❌ 取消并生成退款清单')
add('13.1 项目搜索入口', cute.admin_search_help())
add('13.2 搜索结果头', cute.admin_search_results_header('P.012') + '\n\n🚗 项目小车：\n• P.012｜某博主｜众筹中｜🔥 6/8\n\n💰 报销/提现：C.003', '🔍 P.012 项目卡片｜某博主\n✅ 已支付    💳 待付    📦 资源\n⬅️ 返回待办中心')

header = '# 小掌柜可爱风｜全部核心面板预览（卡片间距版）\n\n> 本版按用户文案整理，并统一卡片规则：标题在外；正文内容放在上下两条 `━━━━━━━━━━━━━━` 之间；卡片正文前后各空一行；第二条线下方的提示/碎碎念/处理建议紧贴显示，不额外空一行。\n\n'
root = Path(__file__).resolve().parent
out = header + '\n---\n\n'.join(sections)
(root / 'docs' / '全部面板预览_卡片间距版.md').write_text(out, encoding='utf-8')
Path('/mnt/data/all_panels_preview_card_spacing.md').write_text(out, encoding='utf-8')
print('/mnt/data/all_panels_preview_card_spacing.md')
