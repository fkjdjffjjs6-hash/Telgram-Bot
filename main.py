"""
🤖 بوت إدارة حسابات + رد تلقائي
كل شيء من تيليجرام - ما يطلبش والو في Terminal
"""

from telethon import TelegramClient, events
from telethon.tl.types import User
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError
import asyncio
import json
import os
import re
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading


# ==========================================================
# ⚙️ الإعدادات
# ==========================================================
API_ID = int(os.environ.get("API_ID", "39481672"))
API_HASH = os.environ.get("API_HASH", "870948ec58b2cdc783b6c981a9af0d16").strip()
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8786766793:AAF53vCdoURQIeDDLNS8ZXA67Y_I4xGWJKQ").strip()
PORT = int(os.environ.get("PORT", "8080"))

# التحقق الصارم
if not API_ID:
    print("❌ API_ID غير معيّن")
    exit(1)
if not API_HASH:
    print("❌ API_HASH غير معيّن")
    exit(1)
if not BOT_TOKEN:
    print("❌ BOT_TOKEN غير معيّن")
    exit(1)

# نتأكد من صيغة التوكن
if ':' not in BOT_TOKEN:
    print(f"❌ BOT_TOKEN غلط: يجب أن يكون مثل 123456:ABC-DEF...")
    print(f"   القيمة الحالية: {BOT_TOKEN[:20]}...")
    exit(1)

print("=" * 50)
print(f"🔑 API_ID: {API_ID}")
print(f"🔑 API_HASH: {API_HASH[:8]}...")
print(f"🤖 BOT_TOKEN: {BOT_TOKEN[:20]}...")
print("=" * 50)

ACCOUNTS_FILE = 'accounts.json'
accounts = {}
user_states = {}
clients = {}
pending_clients = {}


# ==========================================================
# 💾 حفظ/تحميل
# ==========================================================
def load_json(file, default=None):
    if default is None:
        default = {}
    if os.path.exists(file):
        try:
            with open(file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return default
    return default


def save_json(file, data):
    with open(file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def default_account_config():
    return {
        "is_busy": True,
        "reply_message": "أنا مشغول حالياً، سأرد عليك في أقرب وقت 🙏",
        "reply_delay": 2,
        "cooldown_minutes": 30,
        "exclude_list": [],
        "replied_users": {},
        "scheduled_msgs": {}
    }


# ==========================================================
# 🤖 البوت - مع StringSession لتجنب مشكلة Terminal
# ==========================================================
BOT_SESSION_FILE = 'bot_session'

if os.path.exists(BOT_SESSION_FILE + '.session'):
    bot_client = TelegramClient(BOT_SESSION_FILE, API_ID, API_HASH)
else:
    bot_client = TelegramClient(BOT_SESSION_FILE, API_ID, API_HASH)


# ==========================================================
# 🛠️ مساعدات
# ==========================================================
def is_real_user(sender):
    if not sender:
        return False
    if isinstance(sender, User):
        if getattr(sender, 'bot', False):
            return False
        if getattr(sender, 'deleted', False):
            return False
        return True
    return False


def should_reply(cfg, sender_id):
    key = str(sender_id)
    if key not in cfg["replied_users"]:
        return True
    last_str = cfg["replied_users"][key].get("date")
    if not last_str:
        return True
    try:
        last = datetime.strptime(last_str, "%Y-%m-%d %H:%M:%S")
    except:
        return True
    return (datetime.now() - last) >= timedelta(minutes=cfg["cooldown_minutes"])


def time_remaining(cfg, sender_id):
    key = str(sender_id)
    if key not in cfg["replied_users"]:
        return None
    last_str = cfg["replied_users"][key].get("date")
    if not last_str:
        return None
    try:
        last = datetime.strptime(last_str, "%Y-%m-%d %H:%M:%S")
    except:
        return None
    nxt = last + timedelta(minutes=cfg["cooldown_minutes"])
    rem = nxt - datetime.now()
    return str(rem).split('.')[0] if rem.total_seconds() > 0 else None


def parse_duration(s):
    m = re.match(r'^(\d+)([smh])$', s.strip())
    if not m:
        return None
    n = int(m.group(1))
    u = m.group(2)
    return n if u == 's' else (n * 60 if u == 'm' else n * 3600)


def get_active_account(user_id):
    state = user_states.get(user_id, {})
    active = state.get("active_account")
    if active and active in accounts:
        return active
    return list(accounts.keys())[0] if accounts else None


def get_acc(event):
    aid = get_active_account(event.sender_id)
    if not aid:
        return None, None
    return aid, accounts.get(aid)


# ==========================================================
# 📨 معالج الرد التلقائي
# ==========================================================
def make_handler(account_id):
    async def handler(event):
        if not event.is_private or event.out:
            return
        sender = await event.get_sender()
        if not is_real_user(sender):
            return

        acc = accounts.get(account_id)
        if not acc:
            return

        cfg = acc["config"]
        sid = event.sender_id

        if not cfg["is_busy"]:
            return
        if sid in cfg["exclude_list"]:
            return
        if not should_reply(cfg, sid):
            return

        name = sender.first_name or "Unknown"
        cfg["replied_users"][str(sid)] = {
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "name": name
        }
        save_json(ACCOUNTS_FILE, accounts)

        await asyncio.sleep(cfg["reply_delay"])

        try:
            await event.reply(cfg["reply_message"])
            print(f"[{account_id}] ✅ ردينا على {name}")
        except Exception as e:
            print(f"[{account_id}] ❌ {e}")
    return handler


# ==========================================================
# ⏰ الجدولة
# ==========================================================
async def scheduler_loop(account_id):
    while True:
        try:
            acc = accounts.get(account_id)
            client = clients.get(account_id)
            if not acc or not client or not client.is_connected():
                await asyncio.sleep(10)
                continue

            cfg = acc["config"]
            now = datetime.now()
            to_remove = []

            for mid, info in list(cfg["scheduled_msgs"].items()):
                send_time = datetime.strptime(info["send_at"], "%Y-%m-%d %H:%M:%S")
                if now >= send_time:
                    try:
                        target = info["target"]
                        if target.startswith('@'):
                            entity = await client.get_entity(target)
                        elif target.lstrip('-').isdigit():
                            entity = await client.get_entity(int(target))
                        else:
                            entity = await client.get_entity(target)
                        await client.send_message(entity, info["message"])
                        print(f"[{account_id}] 📤 → {target}")
                        to_remove.append(mid)
                    except Exception as e:
                        print(f"[{account_id}] ❌ {e}")
                        to_remove.append(mid)

            if to_remove:
                for mid in to_remove:
                    cfg["scheduled_msgs"].pop(mid, None)
                save_json(ACCOUNTS_FILE, accounts)
        except Exception as e:
            print(f"❌ sched [{account_id}]: {e}")
        await asyncio.sleep(10)


# ==========================================================
# 🔐 تسجيل حساب جديد
# ==========================================================
async def start_add_account(user_id, phone):
    phone = phone.strip()
    if not phone.startswith('+'):
        phone = '+' + phone

    if user_id in pending_clients:
        try:
            await pending_clients[user_id].disconnect()
        except:
            pass
        del pending_clients[user_id]

    client = TelegramClient(StringSession(), API_ID, API_HASH)
    try:
        await client.connect()
    except Exception as e:
        return False, f"❌ فشل الاتصال: {e}"

    try:
        sent = await client.send_code_request(phone)
        pending_clients[user_id] = client
        user_states[user_id] = {
            "step": "waiting_code",
            "phone": phone
        }
        return True, (
            f"📱 **تم إرسال الكود**\n\n"
            f"• الرقم: `{phone}`\n\n"
            f"أرسل الكود الآن 👇\n"
            f"`/cancel` للإلغاء"
        )
    except Exception as e:
        try:
            await client.disconnect()
        except:
            pass
        return False, f"❌ فشل إرسال الكود: {e}"


async def submit_code(user_id, code):
    if user_id not in pending_clients:
        return False, "❌ لا توجد جلسة"
    client = pending_clients[user_id]
    state = user_states.get(user_id, {})
    phone = state.get("phone")

    try:
        await client.sign_in(phone=phone, code=code)
        return await finalize_account(user_id, client)
    except SessionPasswordNeededError:
        user_states[user_id]["step"] = "waiting_password"
        return True, (
            "🔐 **الحساب محمي بـ 2FA**\n\n"
            "أرسل كلمة السر الآن 👇\n"
            "`/cancel` للإلغاء"
        )
    except Exception as e:
        return False, f"❌ كود خاطئ: {e}"


async def submit_password(user_id, password):
    if user_id not in pending_clients:
        return False, "❌ لا توجد جلسة"
    client = pending_clients[user_id]
    try:
        await client.sign_in(password=password)
        return await finalize_account(user_id, client)
    except Exception as e:
        return False, f"❌ كلمة سر خاطئة: {e}"


async def finalize_account(user_id, client):
    try:
        me = await client.get_me()
        account_id = str(me.id)

        if account_id in accounts:
            await client.disconnect()
            return False, f"⚠️ الحساب موجود: **{me.first_name}**"

        session_str = client.session.save()

        accounts[account_id] = {
            "name": me.first_name or "Unknown",
            "username": me.username or "",
            "phone": me.phone or "",
            "session": session_str,
            "config": default_account_config(),
            "added_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        save_json(ACCOUNTS_FILE, accounts)

        client.add_event_handler(make_handler(account_id), events.NewMessage(incoming=True))
        clients[account_id] = client
        asyncio.create_task(scheduler_loop(account_id))

        user_states.pop(user_id, None)
        pending_clients.pop(user_id, None)

        return True, (
            f"✅ **تم إضافة الحساب!**\n\n"
            f"• الاسم: **{me.first_name}**\n"
            f"• اليوزر: @{me.username or 'لا يوجد'}\n"
            f"• ID: `{account_id}`\n\n"
            f"🎯 الحساب نشط الآن"
        )
    except Exception as e:
        return False, f"❌ خطأ: {e}"


# ==========================================================
# 🎮 أوامر البوت
# ==========================================================

@bot_client.on(events.NewMessage(pattern=r'^/start$|^/help$'))
async def bot_help(event):
    await event.reply(
        "🤖 **بوت إدارة الحسابات**\n\n"
        "**📋 الحسابات:**\n"
        "• `/accounts` — عرض\n"
        "• `/addaccount` — إضافة\n"
        "• `/removeaccount ID` — حذف\n"
        "• `/use ID` — تنشيط\n\n"
        "**⚙️ التحكم:**\n"
        "• `/busy` `/free` `/status`\n"
        "• `/setmsg النص` `/getmsg`\n"
        "• `/cooldown 30` `/delay 3`\n"
        "• `/stats` `/reset`\n\n"
        "**📤 الجدولة:**\n"
        "• `/send @user النص | 5m`\n"
        "• `/schedule @user HH:MM النص`\n"
        "• `/listscheduled` `/cancelall`\n\n"
        "**🚫 الاستثناءات:**\n"
        "• `/exclude ID` `/unexclude ID` `/exlist`\n\n"
        "`/cancel` للإلغاء"
    )


@bot_client.on(events.NewMessage(pattern=r'^/accounts$'))
async def cmd_accounts(event):
    if not accounts:
        await event.reply("📭 **لا توجد حسابات**\n\nأضف: `/addaccount`")
        return
    active = get_active_account(event.sender_id)
    text = f"📋 **الحسابات ({len(accounts)}):**\n\n"
    for aid, acc in accounts.items():
        mark = "🟢" if aid == active else "⚪"
        st = "مشغول" if acc["config"]["is_busy"] else "متاح"
        text += (
            f"{mark} **{acc['name']}**\n"
            f"  • ID: `{aid}`\n"
            f"  • @{acc['username'] or 'لا يوجد'}\n"
            f"  • الحالة: {st}\n"
            f"  • المردود عليهم: {len(acc['config']['replied_users'])}\n\n"
        )
    if active:
        text += f"\n👤 **النشط:** `{active}`"
    await event.reply(text)


@bot_client.on(events.NewMessage(pattern=r'^/addaccount$'))
async def cmd_add_account(event):
    user_states[event.sender_id] = {"step": "waiting_phone"}
    await event.reply(
        "📱 **إضافة حساب جديد**\n\n"
        "أرسل رقم الهاتف مع رمز الدولة:\n"
        "مثال: `+213551670735`\n\n"
        "`/cancel` للإلغاء"
    )


@bot_client.on(events.NewMessage(pattern=r'^/cancel$'))
async def cmd_cancel(event):
    uid = event.sender_id
    if uid in pending_clients:
        try:
            await pending_clients[uid].disconnect()
        except:
            pass
        del pending_clients[uid]
    user_states.pop(uid, None)
    await event.reply("❌ تم الإلغاء")


@bot_client.on(events.NewMessage(pattern=r'^/removeaccount (\d+)$'))
async def cmd_remove_account(event):
    aid = event.pattern_match.group(1)
    if aid not in accounts:
        await event.reply("❌ الحساب غير موجود")
        return
    if aid in clients:
        try:
            await clients[aid].disconnect()
        except:
            pass
        del clients[aid]
    name = accounts[aid]["name"]
    del accounts[aid]
    save_json(ACCOUNTS_FILE, accounts)
    await event.reply(f"✅ تم حذف: **{name}**")


@bot_client.on(events.NewMessage(pattern=r'^/use (\d+)$'))
async def cmd_use(event):
    aid = event.pattern_match.group(1)
    if aid not in accounts:
        await event.reply("❌ الحساب غير موجود")
        return
    if event.sender_id not in user_states:
        user_states[event.sender_id] = {}
    user_states[event.sender_id]["active_account"] = aid
    await event.reply(f"✅ النشط: **{accounts[aid]['name']}**")


@bot_client.on(events.NewMessage(pattern=r'^/busy$'))
async def cmd_busy(event):
    aid, acc = get_acc(event)
    if not acc:
        await event.reply("❌ لا يوجد حساب")
        return
    acc["config"]["is_busy"] = True
    save_json(ACCOUNTS_FILE, accounts)
    await event.reply(f"🔴 الرد مفعّل — {acc['name']}")


@bot_client.on(events.NewMessage(pattern=r'^/free$'))
async def cmd_free(event):
    aid, acc = get_acc(event)
    if not acc:
        await event.reply("❌ لا يوجد حساب")
        return
    acc["config"]["is_busy"] = False
    save_json(ACCOUNTS_FILE, accounts)
    await event.reply(f"🟢 الرد متوقف — {acc['name']}")


@bot_client.on(events.NewMessage(pattern=r'^/status$'))
async def cmd_status(event):
    aid, acc = get_acc(event)
    if not acc:
        await event.reply("❌ لا يوجد حساب")
        return
    cfg = acc["config"]
    st = "🔴 مشغول" if cfg["is_busy"] else "🟢 متاح"
    await event.reply(
        f"📊 **الحالة**\n\n"
        f"👤 {acc['name']} (`{aid}`)\n"
        f"• الوضع: {st}\n"
        f"• نص الرد: `{cfg['reply_message']}`\n"
        f"• التأخير: {cfg['reply_delay']}s\n"
        f"• الانتظار: {cfg['cooldown_minutes']}m\n"
        f"• 👥 المردود: {len(cfg['replied_users'])}\n"
        f"• 🚫 المستثنون: {len(cfg['exclude_list'])}\n"
        f"• 📤 المجدولة: {len(cfg['scheduled_msgs'])}"
    )


@bot_client.on(events.NewMessage(pattern=r'^/setmsg ([\s\S]+)$'))
async def cmd_setmsg(event):
    aid, acc = get_acc(event)
    if not acc:
        await event.reply("❌ لا يوجد حساب")
        return
    msg = event.pattern_match.group(1).strip()
    if not msg:
        await event.reply("❌ النص فارغ")
        return
    acc["config"]["reply_message"] = msg
    save_json(ACCOUNTS_FILE, accounts)
    preview = msg if len(msg) < 300 else msg[:300] + "..."
    await event.reply(
        f"✅ **تم التغيير**\n\n━━━━━━━━━━━━━━━\n{preview}\n━━━━━━━━━━━━━━━\n"
        f"📏 {len(msg)} حرف"
    )


@bot_client.on(events.NewMessage(pattern=r'^/getmsg$'))
async def cmd_getmsg(event):
    aid, acc = get_acc(event)
    if not acc:
        await event.reply("❌ لا يوجد حساب")
        return
    await event.reply(f"📝\n\n━━━━━━━━━━━━━━━\n{acc['config']['reply_message']}\n━━━━━━━━━━━━━━━")


@bot_client.on(events.NewMessage(pattern=r'^/cooldown (\d+)$'))
async def cmd_cooldown(event):
    aid, acc = get_acc(event)
    if not acc:
        await event.reply("❌ لا يوجد حساب")
        return
    m = int(event.pattern_match.group(1))
    acc["config"]["cooldown_minutes"] = m
    save_json(ACCOUNTS_FILE, accounts)
    await event.reply(f"⏰ الانتظار: {m} دقيقة")


@bot_client.on(events.NewMessage(pattern=r'^/delay (\d+)$'))
async def cmd_delay(event):
    aid, acc = get_acc(event)
    if not acc:
        await event.reply("❌ لا يوجد حساب")
        return
    s = int(event.pattern_match.group(1))
    acc["config"]["reply_delay"] = s
    save_json(ACCOUNTS_FILE, accounts)
    await event.reply(f"⏱️ التأخير: {s} ثانية")


@bot_client.on(events.NewMessage(pattern=r'^/reset$'))
async def cmd_reset(event):
    aid, acc = get_acc(event)
    if not acc:
        await event.reply("❌ لا يوجد حساب")
        return
    acc["config"]["replied_users"] = {}
    save_json(ACCOUNTS_FILE, accounts)
    await event.reply("🔄 تم حذف السجل")


@bot_client.on(events.NewMessage(pattern=r'^/stats$'))
async def cmd_stats(event):
    aid, acc = get_acc(event)
    if not acc:
        await event.reply("❌ لا يوجد حساب")
        return
    replied = acc["config"]["replied_users"]
    if not replied:
        await event.reply("📭 لا يوجد أحد")
        return
    text = f"📊 **المردود ({len(replied)}):**\n\n"
    for uid, info in list(replied.items())[-10:]:
        rem = time_remaining(acc["config"], int(uid))
        text += f"• {info['name']} (`{uid}`){' ⏳ ' + rem if rem else ' ✅'}\n"
    await event.reply(text)


@bot_client.on(events.NewMessage(pattern=r'^/exclude (\d+)$'))
async def cmd_exclude(event):
    aid, acc = get_acc(event)
    if not acc:
        await event.reply("❌ لا يوجد حساب")
        return
    uid = int(event.pattern_match.group(1))
    if uid not in acc["config"]["exclude_list"]:
        acc["config"]["exclude_list"].append(uid)
        save_json(ACCOUNTS_FILE, accounts)
        await event.reply(f"✅ تم منع `{uid}`")
    else:
        await event.reply("⚠️ موجود")


@bot_client.on(events.NewMessage(pattern=r'^/unexclude (\d+)$'))
async def cmd_unexclude(event):
    aid, acc = get_acc(event)
    if not acc:
        await event.reply("❌ لا يوجد حساب")
        return
    uid = int(event.pattern_match.group(1))
    if uid in acc["config"]["exclude_list"]:
        acc["config"]["exclude_list"].remove(uid)
        save_json(ACCOUNTS_FILE, accounts)
        await event.reply("✅ تم إلغاء المنع")


@bot_client.on(events.NewMessage(pattern=r'^/exlist$'))
async def cmd_exlist(event):
    aid, acc = get_acc(event)
    if not acc:
        await event.reply("❌ لا يوجد حساب")
        return
    if not acc["config"]["exclude_list"]:
        await event.reply("📭 فارغة")
        return
    text = "🚫 **المستثنون:**\n\n"
    for uid in acc["config"]["exclude_list"]:
        text += f"• `{uid}`\n"
    await event.reply(text)


@bot_client.on(events.NewMessage(pattern=r'^/send ([\s\S]+)$'))
async def cmd_send(event):
    aid, acc = get_acc(event)
    if not acc:
        await event.reply("❌ لا يوجد حساب")
        return
    content = event.pattern_match.group(1)
    if '|' in content:
        first, dur = content.rsplit('|', 1)
        sec = parse_duration(dur.strip())
        if sec is None:
            await event.reply("❌ `30s`, `5m`, `2h`")
            return
        send_time = datetime.now() + timedelta(seconds=sec)
    else:
        first = content
        send_time = datetime.now() + timedelta(seconds=30)

    parts = first.strip().split(' ', 1)
    if len(parts) < 2:
        await event.reply("❌ `/send @user النص | 5m`")
        return

    target, text = parts[0], parts[1].strip()
    mid = str(int(datetime.now().timestamp() * 1000))
    acc["config"]["scheduled_msgs"][mid] = {
        "target": target, "message": text,
        "send_at": send_time.strftime("%Y-%m-%d %H:%M:%S"),
        "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    save_json(ACCOUNTS_FILE, accounts)
    preview = text if len(text) < 100 else text[:100] + "..."
    await event.reply(
        f"✅ **تم الجدولة**\n\n"
        f"• ID: `{mid}`\n• إلى: `{target}`\n"
        f"• النص: {preview}\n"
        f"• الوقت: `{send_time.strftime('%Y-%m-%d %H:%M:%S')}`"
    )


@bot_client.on(events.NewMessage(pattern=r'^/schedule ([\s\S]+)$'))
async def cmd_schedule(event):
    aid, acc = get_acc(event)
    if not acc:
        await event.reply("❌ لا يوجد حساب")
        return
    content = event.pattern_match.group(1)
    m1 = re.match(r'^(\S+)\s+(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\s+([\s\S]+)$', content)
    m2 = re.match(r'^(\S+)\s+(\d{1,2}:\d{2})\s+([\s\S]+)$', content)
    if m1:
        target, tstr, text = m1.group(1), m1.group(2), m1.group(3).strip()
        try:
            send_time = datetime.strptime(tstr, "%Y-%m-%d %H:%M")
        except:
            await event.reply("❌ تاريخ خاطئ")
            return
    elif m2:
        target, tstr, text = m2.group(1), m2.group(2), m2.group(3).strip()
        try:
            today = datetime.now().date()
            t = datetime.strptime(tstr, "%H:%M").time()
            send_time = datetime.combine(today, t)
            if send_time <= datetime.now():
                send_time += timedelta(days=1)
        except:
            await event.reply("❌ وقت خاطئ")
            return
    else:
        await event.reply("❌ `/schedule @user HH:MM النص`")
        return
    mid = str(int(datetime.now().timestamp() * 1000))
    acc["config"]["scheduled_msgs"][mid] = {
        "target": target, "message": text,
        "send_at": send_time.strftime("%Y-%m-%d %H:%M:%S"),
        "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    save_json(ACCOUNTS_FILE, accounts)
    await event.reply(
        f"✅ **تم الجدولة**\n\n• ID: `{mid}`\n• إلى: `{target}`\n"
        f"• الوقت: `{send_time.strftime('%Y-%m-%d %H:%M:%S')}`"
    )


@bot_client.on(events.NewMessage(pattern=r'^/listscheduled$'))
async def cmd_listsched(event):
    aid, acc = get_acc(event)
    if not acc:
        await event.reply("❌ لا يوجد حساب")
        return
    sched = acc["config"]["scheduled_msgs"]
    if not sched:
        await event.reply("📭 لا توجد")
        return
    text = f"📤 **المجدولة ({len(sched)}):**\n\n"
    for mid, info in list(sched.items())[:20]:
        preview = info['message'][:40] + ('...' if len(info['message']) > 40 else '')
        text += f"🆔 `{mid}`\n  → `{info['target']}`\n  `{info['send_at']}`\n  {preview}\n\n"
    await event.reply(text)


@bot_client.on(events.NewMessage(pattern=r'^/cancelscheduled (\S+)$'))
async def cmd_cancelsched(event):
    aid, acc = get_acc(event)
    if not acc:
        await event.reply("❌ لا يوجد حساب")
        return
    mid = event.pattern_match.group(1)
    if mid in acc["config"]["scheduled_msgs"]:
        acc["config"]["scheduled_msgs"].pop(mid)
        save_json(ACCOUNTS_FILE, accounts)
        await event.reply("✅ تم الإلغاء")
    else:
        await event.reply("❌ لم أجدها")


@bot_client.on(events.NewMessage(pattern=r'^/cancelall$'))
async def cmd_cancelall(event):
    aid, acc = get_acc(event)
    if not acc:
        await event.reply("❌ لا يوجد حساب")
        return
    c = len(acc["config"]["scheduled_msgs"])
    acc["config"]["scheduled_msgs"] = {}
    save_json(ACCOUNTS_FILE, accounts)
    await event.reply(f"✅ تم إلغاء {c} رسالة")


# ==========================================================
# 📥 معالج التسجيل (رقم → كود → كلمة السر)
# ==========================================================
@bot_client.on(events.NewMessage())
async def state_handler(event):
    if not event.is_private:
        return
    uid = event.sender_id
    state = user_states.get(uid)
    if not state:
        return
    text = event.text.strip() if event.text else ""
    if text.startswith('/'):
        return

    step = state.get("step")

    if step == "waiting_phone":
        if not re.match(r'^\+?\d{7,15}$', text.replace(' ', '')):
            await event.reply("❌ رقم غير صالح. مثال: `+213551670735`")
            return
        msg = await event.reply("⏳ جاري إرسال الكود...")
        ok, reply = await start_add_account(uid, text)
        await msg.edit(reply)

    elif step == "waiting_code":
        msg = await event.reply("⏳ جاري التحقق...")
        ok, reply = await submit_code(uid, text)
        await msg.edit(reply)

    elif step == "waiting_password":
        msg = await event.reply("⏳ جاري التحقق...")
        try:
            await event.delete()
        except:
            pass
        ok, reply = await submit_password(uid, text)
        await msg.edit(reply)


# ==========================================================
# 🔄 تحميل الحسابات
# ==========================================================
async def load_accounts():
    global accounts
    data = load_json(ACCOUNTS_FILE, {})

    # ⭐ إصلاح: إذا الملف فيه list، نحوّلها لـ dict
    if isinstance(data, list):
        print("⚠️ الملف القديم كان list، جاري التصليح...")
        accounts = {}
        save_json(ACCOUNTS_FILE, accounts)
    elif isinstance(data, dict):
        accounts = data
    else:
        accounts = {}

    if not accounts:
        print("📭 لا توجد حسابات")
        return

    for aid, acc in list(accounts.items()):
        try:
            client = TelegramClient(StringSession(acc["session"]), API_ID, API_HASH)
            await client.connect()
            if not await client.is_user_authorized():
                print(f"❌ [{aid}] جلسة منتهية")
                await client.disconnect()
                continue
            client.add_event_handler(make_handler(aid), events.NewMessage(incoming=True))
            clients[aid] = client
            asyncio.create_task(scheduler_loop(aid))
            print(f"✅ تحميل: {acc['name']} ({aid})")
        except Exception as e:
            print(f"❌ فشل [{aid}]: {e}")


# ==========================================================
# 🌐 Web Server
# ==========================================================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(b"<html><body><h1>Bot is running</h1></body></html>")
    def log_message(self, *args):
        pass


def run_web_server():
    try:
        server = HTTPServer(('0.0.0.0', PORT), HealthHandler)
        print(f"🌐 Web Server على {PORT}")
        server.serve_forever()
    except Exception as e:
        print(f"Web error: {e}")


# ==========================================================
# 🚀 التشغيل
# ==========================================================
async def main():
    print("=" * 50)
    print("🚀 بدء البوت...")
    print("=" * 50)

    # ⭐ هذي أهم خطوة: start مع bot_token (لا يطلب والو)
    try:
        await bot_client.start(bot_token=BOT_TOKEN)
    except Exception as e:
        print(f"❌ فشل تسجيل الدخول: {e}")
        print("تأكد من BOT_TOKEN")
        return

    bot_me = await bot_client.get_me()
    print(f"✅ بوت التحكم: @{bot_me.username}")

    await load_accounts()

    threading.Thread(target=run_web_server, daemon=True).start()

    print("=" * 50)
    print(f"📋 الحسابات: {len(accounts)}")
    print("✅ البوت شغال! افتح تيليجرام")
    print("=" * 50)

    await bot_client.run_until_disconnected()


if __name__ == '__main__':
    with bot_client:
        bot_client.loop.run_until_complete(main())
