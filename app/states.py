from aiogram.fsm.state import State, StatesGroup


class CrowdfundCreate(StatesGroup):
    blogger = State()
    description = State()
    original_price = State()
    purchase_mode = State()
    confirm = State()


class BuyInfoCollect(StatesGroup):
    info = State()


class ResourceUploadCollect(StatesGroup):
    resource = State()


class PaymentSubmit(StatesGroup):
    system_no = State()

class ProfitWithdrawCollect(StatesGroup):
    payout_info = State()

class RefundApplyCollect(StatesGroup):
    payout_info = State()


class ContactSupport(StatesGroup):
    message = State()


class AdminContactReply(StatesGroup):
    message = State()

class AdminSearch(StatesGroup):
    query = State()


class AdminManualVerify(StatesGroup):
    system_no = State()
