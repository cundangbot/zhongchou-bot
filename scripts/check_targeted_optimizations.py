from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding='utf-8')


main = read('app/main.py')
start = read('app/handlers/start.py')
keyboards = read('app/keyboards.py')
runtime = read('app/services/project_runtime.py')
messages = read('app/messages/cute.py')
config = read('app/config.py')
listener = read('app/services/payment_auto_listener.py')

checks = {
    'startup schema preflight': 'check_database_schema' in main and 'schema_status.ready' in main,
    'startup warning once': 'startup_schema_warning_signature' in main,
    'scheduler blocked on bad schema': 'if schema_status.ready:\n            scheduler = setup_scheduler' in main,
    'health traffic lights': all(x in start for x in ('🟢 正常', '🟡 注意', '🔴 异常', '💳 支付核验情况')),
    'five payment recovery actions': all(x in keyboards for x in (
        '查看 faka 核验结果', '查看匹配待付车票', '选择项目绑定', '重新执行本地绑定', '联系付款用户'
    )),
    'payment recovery callbacks': all(x in start for x in (
        'admin:payment_result:', 'admin:payment_matches:', 'admin:payment_projects:',
        'admin:payment_retry:', 'admin:payment_bind_order:', 'admin:payment_bind_project:'
    )),
    'saved result local retry': 'async def retry_verified_payment' in listener,
    'project panel debounce': all(x in runtime for x in ('_panel_update_tasks', '_run_debounced_panel_update', 'PROJECT_PANEL_DEBOUNCE_SECONDS')),
    'refund detail completed': all(x in messages for x in ('退款原因：', '原支付金额：', '支付单号：', '支付方式：', '支付时间：')),
    'refund eligibility enforced twice': start.count('_refund_is_open_for_project(project)') >= 2,
    'self-cancel refund denied': '个人临时不想参加不能退款' in start and '个人临时不想参加不能申请退款' in messages,
    'support full first context': all(x in start for x in (
        '相关项目当前状态：', '相关车票状态：', '相关 VP 状态：', '最后一次错误：', '用户最近三个操作：'
    )),
    'support context once per ticket': '_support_has_previous_user_message' in start and 'has_previous_user_message' in start,
    'no historical creator recovery': 'recover_creator_virtual_prepays' not in main,
    'menu unchanged': "[KeyboardButton(text='💎 会员购买'), KeyboardButton(text='📋 我的众筹')]" in keyboards,
    'old commands remain removed': "Command('version')" not in start and "Command('menu')" not in start,
    'debounce env config': 'PROJECT_PANEL_DEBOUNCE_SECONDS: float = 3.0' in config,
}

failed = [name for name, ok in checks.items() if not ok]
if failed:
    for name in failed:
        print(f'FAIL: {name}')
    raise SystemExit(1)
for name in checks:
    print(f'OK: {name}')
