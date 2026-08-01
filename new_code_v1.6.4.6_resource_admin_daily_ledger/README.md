# v1.6.4.5 全项目交互闭环优化版

本版本在 v1.6.4.4 纯自动支付基础上完成全项目交互闭环整理：

- 按最新交互文案统一自动核验术语、支付成功字段、客服按钮、退款详情和管理员搜索入口；
- 补齐发车、购买资料、资源、退款、报销/提现、管理员搜索、客服回复和手动补单的取消/返回路径；
- 资源提交审核后统一锁定，旧按钮、命令和延迟消息不能继续上传、补充、删除或清空；
- 新增 `scripts/check_flow_closure.py`，检查按钮处理器、输入状态退出、资源审核锁和旧入口清理。


本版本将“自动购买通知”和旧“用户提交 VP”两套路径合并为一条纯自动支付链：

```text
购买成功通知
→ 精确识别商品类型
→ 提取 VP
→ faka 只查询一次
→ 核对用户、商品、金额、支付方式和下单机器人
→ 保存已核实付款记录
→ 自动绑定或让用户选择动态项目
```

仅接受下面四种商品，空格差异会忽略，其他商品不会提取 VP，也不会查询 faka：

| 商品 | 付款含义 | 可绑定项目 |
|---|---|---|
| `车位支付链接[拼车单车位30元支付链接]` | 普通/满员后单车位 30 元 | 单车位价格 30 元项目 |
| `车位支付链接[拼车单车位60元支付链接]` | 普通/满员后单车位 60 元 | 单车位价格 60 元项目 |
| `车位支付链接[发起人双车位60元支付链接]` | 发起人双车位 60 元 | 本人发起、单车位 30 元、等待车主预付项目 |
| `车位支付链接[发起人双车位120元支付链接]` | 发起人双车位 120 元 | 本人发起、单车位 60 元、等待车主预付项目 |

- 唯一匹配待付车票：自动绑定并发送动态项目成功卡片。
- 多张匹配待付车票：按钮动态显示项目、博主和车票类型，由用户选择后本地绑定，不再查 faka。
- 没有待付车票：faka 先确认 Telegram 数字用户 ID，保存“已核实但尚未绑定”的付款记录，直接发送项目选择页；候选项目会排除用户已有已支付车票、资源权限和已参加项目。
- 发起人双车位成功后展示专属车主卡密、动态项目、预占金额和车主权益。
- 用户端不展示金额不符、重复 VP、未支付等技术错误，只展示“付款已确认但座位暂未绑定”的恢复提示；管理员端保留真实技术原因和「查询用户并联系」按钮。
- 恢复绑定消息发送成功/失败都会通知管理员；无法私信时显示用户 ID 和系统单号。
- 重复购买通知不会重复查单、重复入账或重复弹选择页；首次成功通知未送达时，只补发成功卡片。
- 已核实付款写入 `verified_payments`。进程在查单后重启时，调度器会恢复未完成分派。
- 用户手动提交 VP、空闲状态直接发送 VP、旧金额/重复/未支付错误页已经从公开用户流程移除；管理员补单、转绑和冷启动验收仍保留。

配置：

```env
PAYMENT_AUTO_CONFIRM_ENABLED=true
PAYMENT_CONFIRM_BOT_USERNAME=@jingpinhybot
EXPECTED_FAKA_ORDER_BOT=@jingpinhybot
PAYMENT_EXPECTED_PRODUCT_KEYWORDS=车位支付链接
```

`PAYMENT_CONFIRM_BOT_USERNAME` 必须填写实际向 Telethon 商家账号发送“购买成功”通知的机器人用户名。

上线前必须执行：

```bash
alembic upgrade head
```

# 频道详情与拼车面板

- 审核通过后，先把投稿详情和媒体发送到公开频道。
- 详情发送完成后，再发送一条独立拼车面板，展示价格、进度、状态和上车按钮。
- 项目进度、满员、取消和补票状态只更新这条独立拼车面板，不再依赖评论区。
- 图片与视频优先合并为媒体组，文件单独组成文件媒体组，减少频道占屏。
- 管理员可在项目详情点击「🧩 生成拼车模板」，补发丢失的面板并切换后续更新目标。

上线前请执行：

```bash
alembic upgrade head
```

审核通过后，机器人会先把投稿详情/媒体发送到频道，再发送独立的拼车面板和上车按钮；后续人数与状态只更新拼车面板。

# v1.6.1.2 内置客服中心版

- 已拆分数据库 Base/模型依赖，移除 `app.db.base ↔ app.db.models` 循环。
- 已将跨 Handler 的验票后处理、频道更新和满员通知移到 Service 层。
- `start.py` 不再反向导入 `crowdfund.py`。
- 已实际运行数据库初始化、路由注册、调度器注册和完整启动到 polling 入口。
- 客服回复默认切换为原生 Telegram Bot API HTTP 投递；用户侧新增「查看小掌柜回复」主动拉取兜底。

# 拼拼小车库 v1.6.0.3 — PostgreSQL 生产稳定版

> v1.6.0.3：管理员通过项目详情按钮或 `/force_verify` 完成手动补票后，机器人会自动私信通知对应用户；私信失败只在审核群提示，不会污染公开频道。
>
> v1.6.0.2：审核群项目详情新增“🎫 手动补票”按钮。
>
> v1.6.0.1：清理 `start.py` 中 f-string 表达式内部反斜杠写法，兼容 Python 3.11 及更早语法规则；新增 `scripts/check_fstring_compat.py`。

本版本在 v1.5.3 的众筹、验票、资源、退款、报销、分润和客服流程上，集中升级了生产稳定性与长期运营能力：

- PostgreSQL + Alembic 数据库迁移
- 项目状态机与状态历史
- 统一资金流水账本
- 验票、退款、打款、资源发布等关键操作幂等
- PostgreSQL 单实例锁，防止重复 polling / scheduler
- 用户订单面板的返回路径、到期时间和状态刷新
- 带订单上下文的客服工单
- 客服回复原生 Bot API 投递与用户主动拉取兜底
- 热门众筹智能排序
- 资源领取分页进度与断点续领
- 审核群管理面板、项目搜索、异常面板和健康检查
- 每日 PostgreSQL 备份

## 1. 正式部署

### 准备配置

```bash
cp .env.example .env
```

至少填写：

```env
BOT_TOKEN=
ADMIN_GROUP_ID=
PUBLIC_CHANNEL_ID=
ADMIN_IDS=

POSTGRES_DB=crowdfund
POSTGRES_USER=crowdfund
POSTGRES_PASSWORD=请替换强密码
DATABASE_URL=postgresql+asyncpg://crowdfund:同一密码@postgres:5432/crowdfund

TELEGRAM_API_ID=
TELEGRAM_API_HASH=
FAKA_BOT_USERNAME=
EXPECTED_FAKA_ORDER_BOT=
PAYMENT_AUTO_CONFIRM_ENABLED=true
PAYMENT_CONFIRM_BOT_USERNAME=
PAYMENT_EXPECTED_PRODUCT_KEYWORDS=车位支付链接
```

首次登录 Telethon：

```bash
python -m app.tools_login_telethon
```

然后启动：

```bash
docker compose up -d --build
```

查看日志：

```bash
docker compose logs -f tg-crowdfund-bot
```

## 2. 从 SQLite 迁移现有运营数据

不要删除原来的 `data/bot.db`。先备份：

```bash
cp data/bot.db data/bot_before_postgresql.db
```

启动 PostgreSQL，并执行数据库结构迁移：

```bash
docker compose up -d postgres
docker compose run --rm tg-crowdfund-bot alembic upgrade head
```

然后导入旧数据：

```bash
python scripts/migrate_sqlite_to_postgres.py \
  --sqlite sqlite:///./data/bot.db \
  --postgres postgresql+psycopg://crowdfund:你的密码@127.0.0.1:5432/crowdfund
```

导入脚本会同时回填：

- 当前项目状态历史
- 已支付订单收入流水
- 已完成退款支出流水
- 已完成报销/分润支出流水

核对数据后再切换正式机器人。

## 3. 单实例保护

机器人启动时会获取 PostgreSQL advisory lock。若云端误启动第二个实例，第二个实例会直接退出，避免：

- 同一 Telegram update 被处理两次
- 调度任务重复取消项目
- 重复退款、重复资源通知

生产环境不要设置：

```env
ALLOW_SQLITE_DEV=true
```

## 4. Telegram 命令菜单

用户左侧 `/` 菜单只保留：

```text
/start  打开首页
/orders 打开我的众筹
```

管理员功能全部放在审核群固定的「管理操作中心」按钮面板。旧版本给管理员设置过的专属命令菜单会在启动时清理。

审核群面板包括：

- 待审核投稿
- 待上传资源
- 报销/提现
- 退款
- 客服工单
- 风控记录
- 资金账本
- 异常面板
- 健康检查
- 项目搜索

`/health`、`/search`、`/reply` 和 `/sreply` 仍可由管理员在审核群手动输入，但不会显示在命令菜单。

客服工单现在有三种等价回复方式，且默认不再使用 aiogram 封装投递用户私聊，而是直接调用 Telegram Bot API HTTP 接口：

- 点工单卡片「回复用户」，按提示回复。
- 直接回复管理群里的工单卡片或送达回执，机器人会自动按 `S.001` 路由给用户。
- 发送 `/reply S.001 回复内容` 或 `/sreply S.001 回复内容` 作为兜底。

如果投递失败，机器人会在审核群给出可处理原因，并把失败原因写入工单 `last_error`。用户提交客服后也会看到「🔄 查看小掌柜回复」按钮；管理员回复内容会落库，用户可以主动打开这张小纸条查看回复，不再完全依赖手机推送。

相关配置：

```env
BOT_API_BASE_URL=https://api.telegram.org
SUPPORT_DELIVERY_MODE=direct_http
SUPPORT_DIRECT_API_TIMEOUT_SECONDS=15
SUPPORT_DELIVERY_FALLBACK_TO_AIOGRAM=true
```

如部署了自建 `telegram-bot-api` 服务，可把 `BOT_API_BASE_URL` 改为内网地址，例如 `http://telegram-bot-api:8081`。

## 5. 状态机

项目状态不再由各 handler 直接赋值，全部通过：

```python
transition_project(...)
```

每次变化写入 `project_state_history`，并校验允许的状态路径。管理员项目详情可查看状态历史。

## 6. 统一资金账本

`financial_ledger` 记录：

- 普通拼车收入
- 发起人双车位收入
- 满员后购买收入
- 管理员手动补单
- 用户退款
- 发起人报销
- 发起人分润提现

冷启动暗号和内部测试订单保留业务效果，但账务金额为 0，不计入真实收入。

## 7. 幂等保护

以下动作使用唯一操作键和数据库约束，只允许成功一次：

- 验票
- 管理员手动补单
- 满员通知
- 项目取消
- 资源发布
- 退款确认
- 报销/提现确认

重复点击会得到已处理提示，不会重复变更资金或进度。

## 8. 用户订单体验

待付车票详情只保留：

- `💳 立即支付`
- `🔄 已付款，查询状态`
- `🗑 未付款，取消车票`
- 返回待付列表

付款成功后，用户不需要复制或发送 VP。系统根据购买成功通知自动查单并处理：

- 普通车位显示动态项目、博主、描述、车票类型和验票时间；
- 发起人双车位显示车主卡密、动态项目、预占金额和车主权益；
- 多张匹配车票时，按钮显示 `项目｜博主｜普通车位/发起人双车位/满员后补票`；
- 没有待付车票时，用户直接收到已经锁定付款记录的项目选择页；
- 自动绑定发生技术异常时，用户只看到统一恢复提示并可联系小掌柜，管理员收到完整原因。

历史消息中的旧“提交订单号”按钮只会提示当前使用自动验票，不再进入 VP 输入状态。

## 9. 资源断点续领

系统记录每个用户、每个项目、每种资源的：

- 已发送页数
- 已领取数量
- 是否全部领取
- 最后领取时间

用户可继续上次进度，也可从头重新领取。每页数量由：

```env
RESOURCE_PAGE_SIZE=10
```

控制。

## 10. 热门众筹排序

默认优先级：

1. 距满员差 1–2 人
2. 最近 24 小时新发车
3. 已参与人数较多
4. 已满员仍可补票项目

## 11. 健康检查和异常面板

健康检查显示：

- Bot API
- Telethon
- PostgreSQL
- 频道权限
- 审核群权限
- 调度器
- 单实例锁
- 任务数量
- 最后成功验票
- 最后数据库备份

异常面板汇总：

- 高频验票失败用户
- 超时未上传项目
- 频道消息更新失败
- 资源私发失败
- Telethon 断线
- 调度/数据库任务失败
- 重复按钮操作
- PostgreSQL 备份失败

## 12. 数据备份

每天 03:00 自动运行：

```bash
scripts/backup_postgres.sh
```

备份写入 `backups/`，保留 30 天。`backups/last_backup.txt` 用于健康面板显示最近备份。

## 13. 安全文件

不要上传或提交：

```text
.env
payment_checker.session
data/bot.db
backups/*.sql.gz
```

冷启动完成后关闭：

```env
SEED_MODE_ENABLED=false
```

## v1.6.0.4 客服工单回复回执

管理员回复客服工单后，审核群会显示明确的发送成功/失败回执；成功时原工单卡片同步标记已回复，失败时保留待回复状态并提供重试按钮。


## v1.6.0.7 客服双向桥

客服回复入口升级为统一投递核心：按钮回复、直接回复工单卡片、`/reply S.001 内容`、`/sreply S.001 内容` 都可以把消息投递给用户。失败时会识别用户屏蔽机器人、未启动私聊、账号停用、频率限制、网络/代理异常等原因，并保留工单待重试。


## v1.6.0.8 满员成功频道提醒风格统一

拼车满员后不额外刷屏，只更新频道中的独立拼车面板。


## v1.6.0.9 客服回复换接口

客服回复链路默认从 aiogram 封装方法切换为原生 Telegram Bot API HTTP 接口，直接调用 `sendMessage` / `copyMessage`。如果原生接口异常，可按配置自动退回 aiogram 旧通道；审核群送达回执会显示实际投递通道。

同时新增用户侧主动拉取兜底：用户提交客服小纸条后，会出现「🔄 查看小掌柜回复」按钮。管理员回复内容会写入工单，用户即使没有收到手机推送，也能从这张小纸条里查看回复。

## v1.6.1.0：客服入口外置到独立双向机器人

用户侧所有「联系小掌柜 / 继续联系客服」按钮已统一改为打开独立双向客服机器人，默认：`@jingpinhybot`。

新增配置：

```env
SUPPORT_BOT_USERNAME=@jingpinhybot
SUPPORT_BOT_START_PREFIX=cf
SUPPORT_EXTERNAL_ONLY=true
```

按钮会生成 Telegram deep link，例如：

```text
https://t.me/jingpinhybot?start=cf_error_123
```

旧消息里残留的 `support:start:*` 按钮也会被兼容处理，引导用户打开独立客服机器人，不再进入当前机器人的旧客服工单状态机。


## v1.6.1.1 业务审核与外部客服分层

本版本把“人工咨询”和“业务待办”彻底拆开：

- 用户侧所有「联系小掌柜 / 继续联系客服」入口仍统一打开 `@jingpinhybot`。
- 当前机器人不再生成新的内置客服工单，旧 `ContactSupport` 状态会自动清除并引导用户去外部客服机器人。
- 退款申请、报销申请、提现申请、资源审核、手动补票、异常验票等业务流程不走外部客服机器人，仍发送到 `ADMIN_GROUP_ID` 审核群。
- 审核群面板里的客服入口改为“旧客服工单”，仅用于处理旧版本遗留的 `ContactTicket`。
- 报销/提现确认付款、驳回时增加用户通知异常兜底：业务状态和账本会先完成，若私信用户失败，审核群回执会明确显示失败原因。

配置项：

```env
SUPPORT_EXTERNAL_ONLY=true
```

正式环境默认使用 `SUPPORT_EXTERNAL_ONLY=false`，并开启本机器人内置私聊客服桥；退款/报销/提现通过业务卡片区分，不再靠外置机器人分流。


## v1.6.1.3 内置私聊客服桥

客服入口保留在众筹机器人内部，但不再把人工咨询发到审核群，也不再生成“一条消息一个卡片”的处理方式。用户点「联系小掌柜」后进入持续客服对话态，后续文字、截图、文件、视频或语音会直接同步到 `SUPPORT_ADMIN_ID` 对应管理员的机器人私聊。

管理员在自己的机器人私聊里处理：

- 直接回复某条用户消息：机器人会把回复发回这条消息所属用户，并自动切换当前对话。
- 点「📌 保持这个对话」：后续直接发送内容都会发给当前用户。
- 有另一个用户进来时，管理员回复那位用户的消息即可切换过去。
- 发送成功后只显示简短 `✅ 已发送给用户` 回执，不再刷审核群客服卡片。

业务边界保持清楚：退款、垫付报销、提现、资源审核、手动补票、异常验票等仍然是业务审核单，继续发送到审核群对应业务卡片；只有人工咨询走私聊客服桥。

默认配置：

```env
SUPPORT_ADMIN_ID=0
SUPPORT_PRIVATE_BRIDGE_ENABLED=true
SUPPORT_EXTERNAL_ONLY=false
SUPPORT_DELIVERY_MODE=direct_http
SUPPORT_DELIVERY_FALLBACK_TO_AIOGRAM=true
```

`SUPPORT_ADMIN_ID=0` 时会使用 `ADMIN_IDS` 的第一个管理员。生产环境建议显式设置成真正负责客服的 Telegram 数字 ID，例如 `SUPPORT_ADMIN_ID=123456789`。如果以后临时需要切回外部客服机器人，再把 `SUPPORT_EXTERNAL_ONLY=true`。


## v1.6.1.4 管理员私聊会话中心

客服交互进一步收口到管理员私聊，审核群只保留业务审核。

- 用户点「联系小掌柜」后，在众筹机器人私聊里进入持续客服状态。
- 用户消息直接同步到 `SUPPORT_ADMIN_ID` 的机器人私聊，不再进入审核群客服卡片。
- 管理员回复某条用户消息即可自动切换目标用户并发送。
- 管理员点「📌 保持这个对话」后，后续直接发送文字、图片、文件、视频或语音都会发给当前用户。
- 管理员点「✅ 结束这个对话」后，用户会收到「您的对话已结束」小卡片，并带「去热门众筹瞧瞧」入口。
- 新增 `support_admin_sessions` 表记录管理员当前保持的用户，避免只靠 FSM 或回复消息导致服务重启后丢失会话。
- 退款、报销、提现仍然发送到审核群处理，但业务卡片底部新增「切到用户对话」按钮；管理员点击后，机器人会把该用户的私聊会话切到管理员私聊里。

上线后需要执行：

```bash
alembic upgrade head
```

建议生产配置：

```env
SUPPORT_ADMIN_ID=123456789
SUPPORT_PRIVATE_BRIDGE_ENABLED=true
SUPPORT_EXTERNAL_ONLY=false
```



## Alembic 重叠版本修复（v1.6.3.8）

如果升级时报：

```text
Requested revision 0003_support_admin_sessions overlaps with other requested revisions 0001_postgresql
```

请先停止服务，再运行：

```bash
source venv/bin/activate
python scripts/repair_alembic_overlap.py
python scripts/repair_alembic_overlap.py --apply
alembic upgrade head
alembic current
```

该脚本只清理 `alembic_version` 中重复的低版本记录，不修改拼车、订单、用户或支付数据。

## 频道发布行为

- 新发布拼车：先发送投稿详情/媒体，再发送独立拼车面板和上车按钮。
- 项目进度、满员、取消及补票状态只更新频道拼车面板。
- 满员后不再向频道额外发送完成提醒。
- 旧项目面板缺失时，可在管理员项目详情点击「🧩 生成拼车模板」补发。


## v1.6.4.1 支付用户交互闭环

自动支付确认不再只是后台能力，用户端支付流程同步改为：

1. 用户选择拼车项目，机器人生成对应待付车票。
2. 用户点击「💳 立即支付」完成付款。
3. 系统监听购买成功通知，自动查询 VP、核对 Telegram 用户 ID、金额、商品和支付方式。
4. 唯一匹配时直接锁位，并主动推送「支付成功，已自动上车」。
5. 同一用户存在多张同金额待付票时，机器人直接展示项目按钮，由用户点击确认绑定，不需要重新复制 VP。
6. 没有待付票时，已检测到的付款消息提供「选择要绑定的拼车」恢复入口。
7. 自动识别异常统一通过查询状态或联系小掌柜处理，用户侧不再提供手动 VP 入口。

待付车票按钮调整为：

- `💳 立即支付`
- `🔄 已付款，查询状态`
- `🗑 未付款，取消车票`

取消待付票增加二次确认，并明确提示已付款用户不要取消，避免付款后失去自动匹配对象。


## v1.6.4.6 管理员资源修订与按日资金账本

- 发起人提交资源审核后，普通用户上传/补充/清空入口继续锁定。
- 管理员在资源待审核阶段仍可追加、删除最新一条、清空全部或重新上传；资源发布/交付后才完全只读。
- 管理面板「资金账本」改为北京时间按日期分页，支持前一天、后一天、回到今天和返回管理面板。
- 单日流水超过 20 条时，在当天内部继续分页，保证明细不因 Telegram 消息长度被截断。
