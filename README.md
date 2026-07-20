# v1.6.3.6 频道媒体简洁版

- 公开频道只展示发起众筹时提交的媒体，以及四行摘要：`🚗 新车发车！ / 项目 / 博主 / 描述`。
- 频道不展示价格、拼车进度、满员/取消状态，也不挂上车按钮。
- 完整拼车详情和上车按钮发布到该频道帖的关联评论区。
- 项目进度、满员、取消、补票等状态只同步更新评论区详情卡和按钮。
- 图片与视频优先合并为媒体组，文件单独组成文件媒体组，减少频道占屏。
- 评论区未正确关联时自动撤回本次频道媒体并告警，项目保持待审核，避免发布残缺内容。
- 每日汇总发布成功后自动删除上一日汇总，拼车满员后不再新增独立频道提醒。

上线前请执行：

```bash
alembic upgrade head
```

频道必须绑定一个讨论组，机器人需要加入该讨论组并拥有读取消息、发送消息权限。`PUBLIC_DISCUSSION_GROUP_ID=0` 时自动识别关联讨论组，也可以直接填写讨论组 ID。

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
PUBLIC_DISCUSSION_GROUP_ID=0
ADMIN_IDS=

POSTGRES_DB=crowdfund
POSTGRES_USER=crowdfund
POSTGRES_PASSWORD=请替换强密码
DATABASE_URL=postgresql+asyncpg://crowdfund:同一密码@postgres:5432/crowdfund

TELEGRAM_API_ID=
TELEGRAM_API_HASH=
FAKA_BOT_USERNAME=
EXPECTED_FAKA_ORDER_BOT=
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

待付车票详情显示：

- 绝对过期时间
- 剩余分钟
- 支付按钮
- 我已支付，去验票
- 取消车票
- 返回列表

验票页显示：

- 提交订单号
- 刷新车票状态
- 返回待付车票

验票失败联系客服时，会自动附带来源页面、项目、车票、当前状态和最近错误。

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

该旧版独立提醒逻辑已取消。拼车满员后只更新评论区详情，不再新增频道消息，也不修改频道媒体摘要。


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
