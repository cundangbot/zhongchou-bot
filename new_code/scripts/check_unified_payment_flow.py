from __future__ import annotations

"""Static/isolated acceptance checks for the pure automatic payment flow.

The production Telegram dependencies are intentionally not required. The parser
is imported with small stubs so this script can still verify the four accepted
merchant products in a source-only review environment.
"""

import ast
import importlib
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault('BOT_TOKEN', '123456:test')
os.environ.setdefault('ADMIN_GROUP_ID', '-1001')
os.environ.setdefault('PUBLIC_CHANNEL_ID', '-1002')
os.environ.setdefault('MEMBER_GROUP_ID', '-1003')
os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://x:x@127.0.0.1/x')


def _install_import_stubs() -> None:
    telethon = types.ModuleType('telethon')

    class TelegramClient:  # pragma: no cover - import-only stub
        pass

    telethon.TelegramClient = TelegramClient
    sys.modules.setdefault('telethon', telethon)

    db_base = types.ModuleType('app.db.base')
    db_base.SessionLocal = object()
    sys.modules['app.db.base'] = db_base

    system_events = types.ModuleType('app.services.system_events')

    async def _noop(*args, **kwargs):
        return None

    system_events.record_event = _noop
    system_events.set_metric = _noop
    sys.modules['app.services.system_events'] = system_events

    proxy = types.ModuleType('app.telethon_proxy')
    proxy.build_telethon_proxy = lambda settings: None
    sys.modules['app.telethon_proxy'] = proxy


def _assert_parser() -> None:
    _install_import_stubs()
    checker = importlib.import_module('app.services.payment_checker')
    cases = {
        '车位支付链接[拼车单车位30元支付链接]': ('seat_30', 30.0),
        '车位支付链接[拼车单车位60元支付链接]': ('seat_60', 60.0),
        '车位支付链接[发起人双车位60元支付链接 ]': ('creator_60', 60.0),
        '车位支付链接[发起人双车位120元支付链接 ]': ('creator_120', 120.0),
    }
    for index, (product, (kind, expected)) in enumerate(cases.items(), start=1):
        text = (
            '🎉恭喜用户：测试用户，购买成功！\n'
            '购买内容如下：\n'
            f'商品：{product}\n'
            f'订单号：VP20260801000000000{index}\n'
            f'成交总额：{expected:g} 元\n'
            '支付方式：微信\n'
        )
        parsed = checker.parse_purchase_confirmation(text)
        assert parsed is not None, product
        assert parsed.product_kind == kind, parsed
        assert parsed.amount == expected, parsed
    assert checker.parse_purchase_confirmation(
        '🎉恭喜用户：测试，购买成功！\n商品：会员充值链接\n订单号：VP2026080100000011111\n成交总额：30 元'
    ) is None
    assert checker.parse_purchase_confirmation(
        '商品：车位支付链接[拼车单车位30元支付链接]\n订单号：VP2026080100000011111\n成交总额：30 元'
    ) is None


def _assert_source_contracts() -> None:
    listener = (ROOT / 'app/services/payment_auto_listener.py').read_text()
    binding = (ROOT / 'app/services/payment_binding.py').read_text()
    start = (ROOT / 'app/handlers/start.py').read_text()
    crowd = (ROOT / 'app/handlers/crowdfund.py').read_text()
    states = (ROOT / 'app/states.py').read_text()
    keyboards = (ROOT / 'app/keyboards.py').read_text()

    assert listener.count('faka_query_client.query_order(system_no)') == 1
    dispatch = listener[listener.index('async def _dispatch_verified_payment'):listener.index('async def _process_purchase_confirmation_locked')]
    assert 'query_order(' not in dispatch
    assert "existing.status == 'verified_unbound'" in listener
    assert "record.status = 'awaiting_selection' if sent else 'attention'" in listener
    assert 'send_payment_success_notice' in listener
    assert '_system_locks' in listener
    assert 'await _process_purchase_confirmation_locked(notice, bot)' in listener
    assert "claimed.status = 'processing'" in listener
    assert 'resume_unbound_verified_payments' in listener

    assert '选择项目：{html.escape(project_line)}' in binding
    assert "order.order_type == 'crowdfunding_creator_prepay'" in binding
    assert "'👑', '发起人双车位'" in binding or '发起人双车位' in binding
    assert '用户已经拥有该项目的已支付车票或资源权限' in binding
    assert binding.count('prefetched_result=verified_result(record)') == 2
    assert 'PaymentOrder.status == \'paid\'' in binding
    assert 'ResourceAccess.project_id' in binding

    assert 'pay:verified_order:' in keyboards
    assert 'pay:verified_project:' in keyboards
    assert 'pay:auto_pending:' not in start
    assert 'pay:auto_project:' not in start
    assert 'PaymentSubmit' not in states
    assert 'user_plain_vp_auto_verify' not in start
    assert 'submit_faka_order_with_id' not in crowd
    assert 'submit_faka_order' not in crowd

    user_failure = binding[binding.index('def payment_binding_failure_text'):binding.index('def verified_result')]
    for technical in ('金额不匹配', '重复提交', '订单状态不是已支付', '系统单号格式错误'):
        assert technical not in user_failure


def _assert_no_duplicate_top_level_functions() -> None:
    for path in (ROOT / 'app').rglob('*.py'):
        tree = ast.parse(path.read_text())
        seen: set[str] = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                assert node.name not in seen, f'duplicate top-level definition: {path}:{node.name}'
                seen.add(node.name)


def main() -> None:
    _assert_parser()
    _assert_source_contracts()
    _assert_no_duplicate_top_level_functions()
    print('OK：纯自动支付商品识别、单次查单、已核实记录复用、动态项目绑定和旧 VP 流程清理检查通过。')


if __name__ == '__main__':
    main()
