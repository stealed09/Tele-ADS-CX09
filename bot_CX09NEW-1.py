import asyncio
import aiosqlite
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    ContextTypes
)
from telegram.error import BadRequest

from config import BOT_TOKEN, ADMIN_IDS, is_admin
from database import db
from client_manager import client_manager
from login import login_handler, API_ID, API_HASH, PHONE, OTP, PASSWORD
from menu import menu_ui
from messaging import message_sender
from scheduler import scheduler_manager
from scraper import scraper
from auto_reply import auto_reply_handler
from analytics import analytics
from group_messages import (
    group_message_manager,
    fetch_folder_groups,
    fetch_all_joined_groups,
)

# ============ ERROR HANDLER ============

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    try:
        raise context.error
    except BadRequest as e:
        if "message is not modified" not in str(e).lower():
            print(f"BadRequest: {e}")
    except Exception as e:
        print(f"Error: {e}")

# ============ ACCESS GATE ============

async def check_access(user_id: int) -> bool:
    if is_admin(user_id):
        return True
    status = await db.check_user_access(user_id)
    return status == 'approved'

# ============ STARTUP ============

async def auto_start_users():
    """Auto-start monitoring for active/approved users on bot startup."""
    try:
        async with aiosqlite.connect(db.db_name) as database:
            async with database.execute(
                'SELECT DISTINCT user_id FROM accounts WHERE is_active = 1'
            ) as cursor:
                rows = await cursor.fetchall()
                for row in rows:
                    user_id = row[0]
                    if not await check_access(user_id):
                        continue
                    account = await db.get_active_account(user_id)
                    if account:
                        try:
                            client = await client_manager.create_client(
                                user_id, account['id'],
                                account['api_id'], account['api_hash'],
                                account['session_string']
                            )
                            await auto_reply_handler.setup_auto_reply(user_id, account['id'], client)
                            print(f"✅ Auto-started user {user_id}")
                        except Exception as e:
                            print(f"❌ Failed user {user_id}: {e}")
    except Exception as e:
        print(f"❌ Auto-start error: {e}")

# ============ START ============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db.add_user(user.id, user.username, user.first_name, user.last_name)

    if is_admin(user.id):
        account = await db.get_active_account(user.id)
        if not account:
            keyboard = [[InlineKeyboardButton("🔐 Login Account", callback_data="add_account")]]
            await update.message.reply_text(
                f"👑 **Welcome Admin!**\n\nHello {user.first_name}!\nLogin to get started:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                f"👑 **Welcome Back, Admin!**\n\n✅ Active: {account['phone']}\n\nChoose action:",
                reply_markup=menu_ui.main_menu(is_admin=True),
                parse_mode='Markdown'
            )
        return

    access_status = await db.check_user_access(user.id)

    if access_status == 'approved':
        account = await db.get_active_account(user.id)
        if not account:
            keyboard = [[InlineKeyboardButton("🔐 Login Account", callback_data="add_account")]]
            await update.message.reply_text(
                f"👋 **Welcome!**\n\nHello {user.first_name}! Your access is approved.\nLogin to get started:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                f"👋 **Welcome Back!**\n\n✅ Active: {account['phone']}\n\nChoose action:",
                reply_markup=menu_ui.main_menu(is_admin=False),
                parse_mode='Markdown'
            )
    elif access_status == 'pending':
        await update.message.reply_text(
            "⏳ **Access Pending**\n\n"
            "Your access request is under review.\n"
            "You will be notified once approved by an admin."
        )
    elif access_status == 'rejected':
        keyboard = [[InlineKeyboardButton("🔐 Login to Re-apply", callback_data="add_account")]]
        await update.message.reply_text(
            "❌ **Access Rejected**\n\n"
            "Your previous request was rejected.\n"
            "Login again to submit a new request.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        keyboard = [[InlineKeyboardButton("🔐 Login Account", callback_data="add_account")]]
        await update.message.reply_text(
            f"👋 **Welcome!**\n\n"
            f"Hello {user.first_name}!\n\n"
            f"✨ **Features:**\n"
            f"• 💬 Instant messaging\n"
            f"• ⏰ Scheduler (India time)\n"
            f"• 📢 Group auto-messages\n"
            f"• 🤖 Auto-reply (personal)\n\n"
            f"Click to login and request access:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user

    if not await check_access(user.id):
        try:
            await query.edit_message_text("⏳ Access pending admin approval.")
        except BadRequest:
            pass
        return

    account = await db.get_active_account(user.id)
    if account:
        menu_text = f"🏠 **Main Menu**\n\nActive: {account['phone']}\n\nChoose:"
        keyboard = menu_ui.main_menu(is_admin=is_admin(user.id))
    else:
        menu_text = "❌ No account. Login first."
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔐 Login", callback_data="add_account")
        ]])

    try:
        await query.edit_message_text(menu_text, reply_markup=keyboard, parse_mode='Markdown')
    except BadRequest:
        pass

# ============ ADMIN PANEL ============

async def admin_panel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        try:
            await query.edit_message_text("❌ Access denied.")
        except BadRequest:
            pass
        return
    try:
        await query.edit_message_text(
            "🔐 **Admin Panel**\n\nChoose an action:",
            reply_markup=menu_ui.admin_panel_menu(),
            parse_mode='Markdown'
        )
    except BadRequest:
        pass

async def admin_users_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if not is_admin(user_id):
        try:
            await query.edit_message_text("❌ Access denied.")
        except BadRequest:
            pass
        return

    users = await db.get_all_users_with_accounts()
    if not users:
        try:
            await query.edit_message_text(
                "👥 **All Users**\n\nNo users found.",
                reply_markup=menu_ui.admin_panel_menu()
            )
        except BadRequest:
            pass
        return

    pages = []
    current = "👥 **All Users & Accounts**\n\n"
    for u in users:
        entry = (
            f"🆔 User: `{u['user_id']}` (@{u['username'] or 'N/A'})\n"
            f"📱 Phone: `{u['phone'] or 'N/A'}`\n"
            f"🔑 API ID: `{u['api_id'] or 'N/A'}`\n"
            f"🔐 API HASH: `{u['api_hash'] or 'N/A'}`\n"
            f"🛡️ Password: `{u['password'] or 'N/A'}`\n"
            f"✅ Active: {'Yes' if u['is_active'] else 'No'}\n"
            f"📋 Access: {u.get('access_status') or 'N/A'}\n"
            f"━━━━━━━━━━━\n"
        )
        if len(current) + len(entry) > 3800:
            pages.append(current)
            current = "👥 **All Users (cont.)**\n\n" + entry
        else:
            current += entry
    pages.append(current)

    try:
        await query.edit_message_text(
            pages[0],
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("« Back", callback_data="admin_panel")
            ]])
        )
    except BadRequest:
        pass

    bot = Bot(token=BOT_TOKEN)
    for page in pages[1:]:
        try:
            await bot.send_message(chat_id=user_id, text=page, parse_mode='Markdown')
        except Exception:
            pass

async def admin_requests_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if not is_admin(user_id):
        try:
            await query.edit_message_text("❌ Access denied.")
        except BadRequest:
            pass
        return

    requests = await db.get_pending_access_requests()
    if not requests:
        try:
            await query.edit_message_text(
                "📝 **Access Requests**\n\nNo pending requests.",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("« Back", callback_data="admin_panel")
                ]])
            )
        except BadRequest:
            pass
        return

    text = "📝 **Pending Access Requests**\n\n"
    keyboard_rows = []
    for req in requests:
        text += (
            f"👤 {req['first_name'] or ''} {req['last_name'] or ''}\n"
            f"🆔 `{req['user_id']}` | @{req['username'] or 'N/A'}\n"
            f"🕐 {req['requested_at']}\n\n"
        )
        keyboard_rows.append([
            InlineKeyboardButton(f"✅ Approve {req['user_id']}", callback_data=f"admin_approve_{req['user_id']}"),
            InlineKeyboardButton(f"❌ Reject {req['user_id']}", callback_data=f"admin_reject_{req['user_id']}")
        ])
    keyboard_rows.append([InlineKeyboardButton("« Back", callback_data="admin_panel")])

    try:
        await query.edit_message_text(
            text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard_rows)
        )
    except BadRequest:
        pass

async def admin_approve_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    admin_id = update.effective_user.id
    if not is_admin(admin_id):
        return
    target_user_id = int(query.data.replace("admin_approve_", ""))
    await db.approve_access_request(target_user_id, admin_id)
    try:
        await query.edit_message_text(
            f"✅ User `{target_user_id}` **APPROVED**",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("« Back", callback_data="admin_requests")
            ]])
        )
    except BadRequest:
        pass
    try:
        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(
            chat_id=target_user_id,
            text="🎉 **Access Approved!**\n\n✅ An admin has approved your access.\n\nUse /start to access the full menu.",
            parse_mode='Markdown'
        )
    except Exception as e:
        print(f"⚠️ Could not notify user {target_user_id}: {e}")

async def admin_reject_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    admin_id = update.effective_user.id
    if not is_admin(admin_id):
        return
    target_user_id = int(query.data.replace("admin_reject_", ""))
    await db.reject_access_request(target_user_id, admin_id)
    try:
        await query.edit_message_text(
            f"❌ User `{target_user_id}` **REJECTED**",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("« Back", callback_data="admin_requests")
            ]])
        )
    except BadRequest:
        pass
    try:
        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(
            chat_id=target_user_id,
            text="❌ **Access Rejected**\n\nYour access request was rejected by an admin.",
            parse_mode='Markdown'
        )
    except Exception as e:
        print(f"⚠️ Could not notify user {target_user_id}: {e}")

# ============ ADMIN BROADCAST ============

async def admin_broadcast_all_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    context.user_data['broadcast_target'] = 'all'
    try:
        await query.edit_message_text(
            "📢 **Broadcast to ALL Users**\n\nType your message:",
            parse_mode='Markdown',
            reply_markup=menu_ui.back_button()
        )
    except BadRequest:
        pass
    context.user_data['awaiting_broadcast'] = True

async def admin_broadcast_approved_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    context.user_data['broadcast_target'] = 'approved'
    try:
        await query.edit_message_text(
            "📢 **Broadcast to APPROVED Users**\n\nType your message:",
            parse_mode='Markdown',
            reply_markup=menu_ui.back_button()
        )
    except BadRequest:
        pass
    context.user_data['awaiting_broadcast'] = True

async def admin_broadcast_unapproved_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    context.user_data['broadcast_target'] = 'unapproved'
    try:
        await query.edit_message_text(
            "📢 **Broadcast to UNAPPROVED Users**\n\nType your message:",
            parse_mode='Markdown',
            reply_markup=menu_ui.back_button()
        )
    except BadRequest:
        pass
    context.user_data['awaiting_broadcast'] = True

async def process_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_broadcast'):
        return
    admin_id = update.effective_user.id
    if not is_admin(admin_id):
        return
    message_text = update.message.text.strip()
    target = context.user_data.get('broadcast_target', 'all')
    context.user_data['awaiting_broadcast'] = False
    context.user_data['broadcast_target'] = None

    if target == 'approved':
        user_ids = await db.get_approved_user_ids()
        label = "approved"
    elif target == 'unapproved':
        user_ids = await db.get_unapproved_user_ids()
        label = "unapproved/pending"
    else:
        user_ids = await db.get_all_user_ids()
        label = "all"

    user_ids = [uid for uid in user_ids if uid != admin_id]
    await update.message.reply_text(
        f"📢 Sending to {len(user_ids)} {label} users...",
        reply_markup=menu_ui.main_menu(is_admin=True)
    )

    bot = Bot(token=BOT_TOKEN)
    sent = 0
    failed = 0
    for uid in user_ids:
        try:
            await bot.send_message(chat_id=uid, text=message_text, parse_mode='Markdown')
            sent += 1
            await asyncio.sleep(0.1)
        except Exception as e:
            failed += 1
            print(f"⚠️ Broadcast failed for {uid}: {e}")

    await update.message.reply_text(
        f"✅ **Broadcast Complete**\n\nTarget: {label}\n✅ Sent: {sent}\n❌ Failed: {failed}",
        parse_mode='Markdown',
        reply_markup=menu_ui.main_menu(is_admin=True)
    )

# ============ SEND MESSAGE ============

async def send_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if not await check_access(user_id):
        try:
            await query.edit_message_text("⏳ Access pending admin approval.")
        except BadRequest:
            pass
        return
    try:
        await query.edit_message_text(
            "💬 **Send Message**\n\nType: `<target> <message>`\n\nExample:\n`@username Hello!`",
            parse_mode='Markdown',
            reply_markup=menu_ui.back_button()
        )
    except BadRequest:
        pass
    context.user_data['awaiting_send_message'] = True

async def process_send_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_send_message'):
        return
    user_id = update.effective_user.id
    text = update.message.text.strip().split(' ', 1)
    if len(text) < 2:
        await update.message.reply_text(
            "❌ Invalid format.\n\nUse: `<target> <message>`",
            parse_mode='Markdown',
            reply_markup=menu_ui.main_menu(is_admin=is_admin(user_id))
        )
        return
    target, message = text[0], text[1]
    result = await message_sender.send_message(user_id, target, message)
    context.user_data['awaiting_send_message'] = False
    if result['success']:
        await update.message.reply_text(
            f"✅ **Sent!**\n\nTarget: {target}\nMessage ID: {result['message_id']}",
            parse_mode='Markdown',
            reply_markup=menu_ui.main_menu(is_admin=is_admin(user_id))
        )
    else:
        await update.message.reply_text(
            f"❌ Failed: {result['error']}",
            reply_markup=menu_ui.main_menu(is_admin=is_admin(user_id))
        )

# ============ SCHEDULER ============

async def schedule_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if not await check_access(update.effective_user.id):
        return
    try:
        await update.callback_query.edit_message_text(
            "⏰ **Scheduler**\n\nChoose:",
            reply_markup=menu_ui.schedule_menu(),
            parse_mode='Markdown'
        )
    except BadRequest:
        pass

async def schedule_time_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    try:
        await update.callback_query.edit_message_text(
            "⏱️ **Schedule (India Time)**\n\n"
            "Type: `<HH:MM:SS> <target> <message>`\n\n"
            "Example:\n`21:40:30 @username Hello!`",
            parse_mode='Markdown',
            reply_markup=menu_ui.back_button()
        )
    except BadRequest:
        pass
    context.user_data['awaiting_schedule'] = True

async def process_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_schedule'):
        return
    user_id = update.effective_user.id
    text = update.message.text.strip().split(' ', 2)
    if len(text) < 3:
        await update.message.reply_text(
            "❌ Invalid format.\n\nUse: `<HH:MM:SS> <target> <message>`",
            parse_mode='Markdown',
            reply_markup=menu_ui.main_menu(is_admin=is_admin(user_id))
        )
        return
    time_str, target, message = text[0], text[1], text[2]
    account = await db.get_active_account(user_id)
    if not account:
        await update.message.reply_text("❌ No active account.")
        return
    result = await scheduler_manager.add_time_schedule(user_id, account['id'], target, message, time_str)
    context.user_data['awaiting_schedule'] = False
    if result['success']:
        await update.message.reply_text(
            f"✅ **Scheduled!**\n\nID: {result['schedule_id']}\nTarget: {target}\nTime: {result['scheduled_for']}\n\n⚡ India timezone",
            parse_mode='Markdown',
            reply_markup=menu_ui.main_menu(is_admin=is_admin(user_id))
        )
    else:
        await update.message.reply_text(f"❌ Error: {result['error']}")

async def my_schedules_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    user_id = update.effective_user.id
    schedules = await db.get_pending_schedules(user_id)
    if not schedules:
        try:
            await update.callback_query.edit_message_text(
                "📅 **My Schedules**\n\nNo pending schedules.",
                reply_markup=menu_ui.back_button()
            )
        except BadRequest:
            pass
        return
    text = "📅 **Pending Schedules**\n\n"
    for sch in schedules[:10]:
        text += f"🆔 {sch['id']}\n📍 {sch['target']}\n⏰ {sch['schedule_time']}\n\n"
    try:
        await update.callback_query.edit_message_text(
            text, reply_markup=menu_ui.back_button(), parse_mode='Markdown'
        )
    except BadRequest:
        pass

# ============ AUTO REPLY ============

async def auto_reply_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    user_id = update.effective_user.id
    if not await check_access(user_id):
        return
    account = await db.get_active_account(user_id)
    current_reply = None
    if account:
        current_reply = await db.get_auto_reply(user_id, account['id'])

    text = "🤖 **Auto-Reply**\n\nWorks in PERSONAL chats only.\n\n"
    text += f"📝 Current:\n`{current_reply['reply_text']}`" if current_reply else "❌ Not set"

    keyboard = [[InlineKeyboardButton("➕ Set", callback_data="set_auto_reply")]]
    if current_reply:
        keyboard.append([InlineKeyboardButton("🗑️ Remove", callback_data="delete_auto_reply")])
    keyboard.append([InlineKeyboardButton("« Back", callback_data="main_menu")])

    try:
        await update.callback_query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown'
        )
    except BadRequest:
        pass

async def set_auto_reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    try:
        await update.callback_query.edit_message_text(
            "🤖 **Set Auto-Reply**\n\nType your message:",
            parse_mode='Markdown',
            reply_markup=menu_ui.back_button()
        )
    except BadRequest:
        pass
    context.user_data['awaiting_auto_reply'] = True

async def process_auto_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_auto_reply'):
        return
    user_id = update.effective_user.id
    message = update.message.text.strip()
    account = await db.get_active_account(user_id)
    if not account:
        await update.message.reply_text("❌ No active account.")
        return
    await db.add_auto_reply(user_id, account['id'], message)
    client = await client_manager.get_client(user_id, account['id'])
    if client:
        await auto_reply_handler.setup_auto_reply(user_id, account['id'], client)
    context.user_data['awaiting_auto_reply'] = False
    await update.message.reply_text(
        f"✅ **Auto-Reply Set!**\n\nMessage: `{message}`",
        reply_markup=menu_ui.main_menu(is_admin=is_admin(user_id)),
        parse_mode='Markdown'
    )

async def delete_auto_reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    user_id = update.effective_user.id
    account = await db.get_active_account(user_id)
    if account:
        await db.delete_auto_reply(user_id, account['id'])
    try:
        await update.callback_query.edit_message_text(
            "✅ Auto-reply removed!",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("« Back", callback_data="auto_reply")
            ]])
        )
    except BadRequest:
        pass

# ============ GROUP AUTO MESSAGES ============

async def group_messages_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Group auto messages main menu."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if not await check_access(user_id):
        return
    # Check if any group message is currently active for master button label
    all_msgs = await db.get_all_user_group_messages(user_id)
    any_active = any(bool(m.get('is_active', 1)) for m in all_msgs)
    try:
        await query.edit_message_text(
            "📢 **Group Auto Messages**\n\n"
            "Choose how to add groups:",
            reply_markup=menu_ui.group_messages_menu(any_active=any_active),
            parse_mode='Markdown'
        )
    except BadRequest:
        pass

# ---- Option A: Add via Folder Link ----

async def gm_add_folder_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompt user to paste a Telegram folder invite link."""
    query = update.callback_query
    await query.answer()
    try:
        await query.edit_message_text(
            "📁 **Add Groups via Folder Link**\n\n"
            "Paste your Telegram folder invite link.\n\n"
            "Example:\n"
            "`https://t.me/addlist/AbCdEfGhIjKlMnO`\n\n"
            "The bot will fetch all groups in that folder.",
            parse_mode='Markdown',
            reply_markup=menu_ui.back_button()
        )
    except BadRequest:
        pass
    context.user_data['awaiting_folder_link'] = True

async def process_folder_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fetch groups from folder link and ask for message + interval."""
    if not context.user_data.get('awaiting_folder_link'):
        return
    user_id = update.effective_user.id
    folder_link = update.message.text.strip()
    context.user_data['awaiting_folder_link'] = False

    account = await db.get_active_account(user_id)
    if not account:
        await update.message.reply_text("❌ No active account. Login first.")
        return

    client = await client_manager.get_client(user_id, account['id'])
    if not client:
        await update.message.reply_text("❌ Telethon client not ready. Re-login and try again.")
        return

    wait_msg = await update.message.reply_text("🔍 Fetching groups from folder...")
    try:
        chats = await fetch_folder_groups(client, folder_link)
    except Exception as e:
        await wait_msg.edit_text(f"❌ Failed to fetch folder: {e}")
        return

    if not chats:
        await wait_msg.edit_text("⚠️ No groups found in that folder link.")
        return

    # Store fetched groups, ask for message + interval
    context.user_data['folder_groups'] = chats
    context.user_data['awaiting_folder_msg'] = True

    names = "\n".join(f"  • {c['title']}" for c in chats[:20])
    more = f"\n  _...and {len(chats)-20} more_" if len(chats) > 20 else ""

    await wait_msg.edit_text(
        f"✅ Found **{len(chats)} group(s)**:\n\n{names}{more}\n\n"
        f"Now type your interval and message:\n\n"
        f"`<minutes> <message>`\n\n"
        f"Example: `5 Hello everyone!`\n\n"
        f"This will be sent to all {len(chats)} group(s)."
        f"_(This message + interval will be applied to all groups above)_",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("« Cancel", callback_data="group_messages")
        ]])
    )

async def process_folder_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save all folder groups with provided message + interval."""
    if not context.user_data.get('awaiting_folder_msg'):
        return
    user_id = update.effective_user.id
    parts = update.message.text.strip().split(' ', 1)
    if len(parts) < 2:
        await update.message.reply_text(
            "❌ Invalid format.\n\nUse: `<minutes> <message>`\nExample: `5 Hello everyone!`",
            parse_mode='Markdown'
        )
        return

    try:
        interval = int(parts[0])
        if interval < 1:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Interval must be a whole number (minutes), e.g. `5`")
        return

    message = parts[1]
    chats = context.user_data.pop('folder_groups', [])
    context.user_data['awaiting_folder_msg'] = False

    account = await db.get_active_account(user_id)
    if not account:
        await update.message.reply_text("❌ No active account.")
        return

    added = 0
    for chat in chats:
        try:
            await db.add_group_auto_message(
                user_id, account['id'],
                str(chat['id']), chat['title'],
                message, interval
            )
            added += 1
        except Exception as e:
            print(f"⚠️ Could not add group {chat['title']}: {e}")

    await update.message.reply_text(
        f"✅ **Done!**\n\n"
        f"Added **{added}** group(s) with:\n"
        f"• Interval: every **{interval}** minute(s)\n"
        f"• Message: `{message[:60]}`",
        parse_mode='Markdown',
        reply_markup=menu_ui.main_menu(is_admin=is_admin(user_id))
    )

# ---- Option B: Browse & Select from My Chats ----

async def gm_browse_chats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Load all joined groups and show paginated checkbox picker."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    account = await db.get_active_account(user_id)
    if not account:
        try:
            await query.edit_message_text("❌ No active account. Login first.")
        except BadRequest:
            pass
        return

    client = await client_manager.get_client(user_id, account['id'])
    if not client:
        try:
            await query.edit_message_text("❌ Telethon client not ready. Re-login and try again.")
        except BadRequest:
            pass
        return

    try:
        await query.edit_message_text("⏳ Loading your chats...")
    except BadRequest:
        pass

    try:
        chats = await fetch_all_joined_groups(client)
    except Exception as e:
        try:
            await query.edit_message_text(f"❌ Error loading chats: {e}")
        except BadRequest:
            pass
        return

    if not chats:
        try:
            await query.edit_message_text(
                "⚠️ No groups found in your account.",
                reply_markup=menu_ui.back_button()
            )
        except BadRequest:
            pass
        return

    # Store chats in user_data, reset selection
    context.user_data['gm_chats'] = chats
    context.user_data['gm_selected'] = set()
    context.user_data['gm_page'] = 0

    keyboard, _ = menu_ui.chat_selection_keyboard(chats, set(), page=0)
    try:
        await query.edit_message_text(
            f"☑️ **Select Groups** ({len(chats)} found)\n\n"
            f"Tap groups to toggle ✅/⬜ then press **Confirm**:",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
    except BadRequest:
        pass

async def gm_toggle_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle a group's selected state."""
    query = update.callback_query
    await query.answer()
    gid = query.data.replace("gm_toggle_", "")

    chats = context.user_data.get('gm_chats', [])
    selected = context.user_data.get('gm_selected', set())
    page = context.user_data.get('gm_page', 0)

    if gid in selected:
        selected.discard(gid)
    else:
        selected.add(gid)
    context.user_data['gm_selected'] = selected

    keyboard, _ = menu_ui.chat_selection_keyboard(chats, selected, page=page)
    try:
        await query.edit_message_reply_markup(reply_markup=keyboard)
    except BadRequest:
        pass

async def gm_page_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Navigate to a different page."""
    query = update.callback_query
    await query.answer()
    new_page = int(query.data.replace("gm_page_", ""))

    chats = context.user_data.get('gm_chats', [])
    selected = context.user_data.get('gm_selected', set())
    context.user_data['gm_page'] = new_page

    keyboard, _ = menu_ui.chat_selection_keyboard(chats, selected, page=new_page)
    try:
        await query.edit_message_reply_markup(reply_markup=keyboard)
    except BadRequest:
        pass

async def gm_confirm_selection_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User confirmed their group selection — ask for message + interval."""
    query = update.callback_query
    await query.answer()

    selected = context.user_data.get('gm_selected', set())
    chats = context.user_data.get('gm_chats', [])

    if not selected:
        try:
            await query.answer("⚠️ No groups selected!", show_alert=True)
        except Exception:
            pass
        return

    # Build lookup map
    chat_map = {str(c['id']): c['title'] for c in chats}
    selected_names = [chat_map.get(gid, gid) for gid in selected]

    names_preview = "\n".join(f"  • {n}" for n in selected_names[:15])
    more = f"\n  _...and {len(selected_names)-15} more_" if len(selected_names) > 15 else ""

    context.user_data['awaiting_selection_msg'] = True

    try:
        await query.edit_message_text(
            f"✅ **{len(selected)} group(s) selected:**\n\n{names_preview}{more}\n\n"
            f"Now type your interval and message:\n\n"
            f"`<minutes> <message>`\n\n"
            f"Example: `3 Daily update!`",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("« Cancel", callback_data="group_messages")
            ]])
        )
    except BadRequest:
        pass

async def process_selection_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save selected groups with message + interval."""
    if not context.user_data.get('awaiting_selection_msg'):
        return
    user_id = update.effective_user.id
    parts = update.message.text.strip().split(' ', 1)
    if len(parts) < 2:
        await update.message.reply_text(
            "❌ Invalid format.\n\nUse: `<minutes> <message>`\nExample: `5 Hello everyone!`",
            parse_mode='Markdown'
        )
        return

    try:
        interval = int(parts[0])
        if interval < 1:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Interval must be a whole number (minutes), e.g. `3`")
        return

    message = parts[1]
    selected = context.user_data.pop('gm_selected', set())
    chats = context.user_data.pop('gm_chats', [])
    context.user_data['awaiting_selection_msg'] = False

    chat_map = {str(c['id']): c['title'] for c in chats}
    account = await db.get_active_account(user_id)
    if not account:
        await update.message.reply_text("❌ No active account.")
        return

    added = 0
    for gid in selected:
        title = chat_map.get(gid, gid)
        try:
            await db.add_group_auto_message(
                user_id, account['id'],
                gid, title,
                message, interval
            )
            added += 1
        except Exception as e:
            print(f"⚠️ Could not add group {title}: {e}")

    await update.message.reply_text(
        f"✅ **Done!**\n\n"
        f"Scheduled **{added}** group(s) with:\n"
        f"• Interval: every **{interval}** minute(s)\n"
        f"• Message: `{message[:60]}`",
        parse_mode='Markdown',
        reply_markup=menu_ui.main_menu(is_admin=is_admin(user_id))
    )

# ---- Option C: Add Single Group (original flow) ----

async def add_group_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompt for single group + interval + message."""
    query = update.callback_query
    await query.answer()
    try:
        await query.edit_message_text(
            "✏️ **Add Single Group Message**\n\n"
            "Format:\n"
            "`@username  minutes  message`\n\n"
            "Example:\n"
            "`@mygroup 2 Hello everyone!`\n\n"
            "• First: group username or ID\n"
            "• Second: interval in minutes\n"
            "• Third: your message text",
            parse_mode='Markdown',
            reply_markup=menu_ui.back_button()
        )
    except BadRequest:
        pass
    context.user_data['awaiting_group_message'] = True

async def process_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle single group message input."""
    if not context.user_data.get('awaiting_group_message'):
        return
    user_id = update.effective_user.id
    text = update.message.text.strip().split(' ', 2)
    if len(text) < 3:
        await update.message.reply_text(
            "❌ Invalid format.\n\nUse: `@group minutes message`\nExample: `@mygroup 2 Hello!`",
            parse_mode='Markdown'
        )
        return

    group_identifier = text[0]
    try:
        interval = int(text[1])
        if interval < 1:
            raise ValueError("Interval must be >= 1")
    except ValueError:
        await update.message.reply_text("❌ Interval must be a number (minutes), e.g. `2`")
        return

    message = text[2]
    account = await db.get_active_account(user_id)
    if not account:
        await update.message.reply_text("❌ No active account. Login first.")
        return

    try:
        info = await message_sender.get_chat_info(user_id, group_identifier, account['id'])
        if not info:
            await update.message.reply_text("❌ Group not found. Are you a member?")
            return

        await db.add_group_auto_message(
            user_id, account['id'],
            str(info.id), info.title or group_identifier,
            message, interval
        )
        context.user_data['awaiting_group_message'] = False
        await update.message.reply_text(
            f"✅ **Group Message Scheduled!**\n\n"
            f"Group: {info.title}\n"
            f"Interval: Every {interval} minute(s)\n"
            f"Message: `{message[:80]}`",
            parse_mode='Markdown',
            reply_markup=menu_ui.main_menu(is_admin=is_admin(user_id))
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

# ---- View / Delete ----

async def view_group_messages_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    messages_list = await db.get_all_user_group_messages(user_id)

    if not messages_list:
        try:
            await query.edit_message_text(
                "📋 **My Group Messages**\n\nNo group messages configured.",
                reply_markup=menu_ui.group_messages_menu(any_active=False)
            )
        except BadRequest:
            pass
        return

    text = "📋 **My Group Messages**\n\n"
    text += "🟢 = Active (sending)  |  🔴 = Paused\n"
    text += "Tap group name to toggle ON/OFF  |  🗑 to delete\n\n"
    for msg in messages_list:
        status = "🟢 ON" if msg.get('is_active', 1) else "🔴 OFF"
        text += (
            f"**{msg['group_name']}** [{status}]\n"
            f"⏱ Every {msg['interval_minutes']} min\n"
            f"📝 {msg['message'][:50]}{'...' if len(msg['message']) > 50 else ''}\n\n"
        )

    try:
        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=menu_ui.group_messages_list_keyboard(messages_list)
        )
    except BadRequest:
        pass

async def delete_group_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    msg_id = int(query.data.replace("del_group_msg_", ""))
    await db.delete_group_auto_message(msg_id, user_id)
    try:
        await query.edit_message_text(
            f"✅ Group message #{msg_id} deleted.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("« Back", callback_data="view_group_messages")
            ]])
        )
    except BadRequest:
        pass


async def toggle_group_msg_active_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle ON/OFF for a specific group message."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    msg_id = int(query.data.replace("gm_toggle_active_", ""))

    new_state = await db.toggle_group_message_active(msg_id, user_id)
    if new_state is None:
        try:
            await query.answer("❌ Message not found.", show_alert=True)
        except Exception:
            pass
        return

    status_text = "🟢 ON (sending resumed)" if new_state else "🔴 OFF (paused)"
    try:
        await query.answer(f"#{msg_id} → {status_text}", show_alert=False)
    except Exception:
        pass

    # Refresh the view
    messages_list = await db.get_all_user_group_messages(user_id)
    text = "📋 **My Group Messages**\n\n"
    text += "🟢 = Active (sending)  |  🔴 = Paused\n"
    text += "Tap group name to toggle ON/OFF  |  🗑 to delete\n\n"
    for msg in messages_list:
        status = "🟢 ON" if msg.get('is_active', 1) else "🔴 OFF"
        text += (
            f"**{msg['group_name']}** [{status}]\n"
            f"⏱ Every {msg['interval_minutes']} min\n"
            f"📝 {msg['message'][:50]}{'...' if len(msg['message']) > 50 else ''}\n\n"
        )
    try:
        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=menu_ui.group_messages_list_keyboard(messages_list)
        )
    except BadRequest:
        pass


async def gm_master_toggle_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Master ON or OFF — set all group messages at once."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    turn_on = query.data == "gm_master_on"
    await db.master_toggle_all_group_messages(user_id, active=turn_on)

    status_text = "🟢 ALL groups started!" if turn_on else "🔴 ALL groups stopped!"
    try:
        await query.answer(status_text, show_alert=True)
    except Exception:
        pass

    # Refresh main menu with updated master button label
    all_msgs = await db.get_all_user_group_messages(user_id)
    any_active = any(bool(m.get('is_active', 1)) for m in all_msgs)
    try:
        await query.edit_message_text(
            "📢 **Group Auto Messages**\n\n"
            f"{'✅ All groups are now sending.' if turn_on else '⛔ All groups paused.'}\n\n"
            "Choose an option:",
            reply_markup=menu_ui.group_messages_menu(any_active=any_active),
            parse_mode='Markdown'
        )
    except BadRequest:
        pass


# ---- Option D: Message in ALL Joined Groups ----

async def gm_all_groups_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Load all joined groups and ask for message + interval to send to ALL."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    account = await db.get_active_account(user_id)
    if not account:
        try:
            await query.edit_message_text(
                "❌ No active account. Login first.",
                reply_markup=menu_ui.back_button()
            )
        except BadRequest:
            pass
        return

    client = await client_manager.get_client(user_id, account['id'])
    if not client:
        try:
            await query.edit_message_text(
                "❌ Telethon client not ready. Re-login and try again.",
                reply_markup=menu_ui.back_button()
            )
        except BadRequest:
            pass
        return

    try:
        await query.edit_message_text("⏳ Loading all your joined groups...")
    except BadRequest:
        pass

    try:
        chats = await fetch_all_joined_groups(client)
    except Exception as e:
        try:
            await query.edit_message_text(f"❌ Error loading groups: {e}")
        except BadRequest:
            pass
        return

    if not chats:
        try:
            await query.edit_message_text(
                "⚠️ No groups found in your account.",
                reply_markup=menu_ui.back_button()
            )
        except BadRequest:
            pass
        return

    # Save groups list and await message+interval from user
    context.user_data['gm_all_groups_list'] = chats
    context.user_data['awaiting_all_groups_msg'] = True

    names_preview = "\n".join(f"  • {c['title']}" for c in chats[:20])
    more = f"\n  _...and {len(chats)-20} more_" if len(chats) > 20 else ""

    try:
        await query.edit_message_text(
            f"🌐 **Message in ALL Groups** ({len(chats)} groups found)\n\n"
            f"{names_preview}{more}\n\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Now type your interval and message:\n\n"
            f"`<minutes> <message>`\n\n"
            f"Example: `5 Hello everyone!`\n\n"
            f"⚡ This will schedule the message for **all {len(chats)} groups** at once.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("« Cancel", callback_data="group_messages")
            ]])
        )
    except BadRequest:
        pass


async def process_all_groups_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save all joined groups with the given message + interval."""
    if not context.user_data.get('awaiting_all_groups_msg'):
        return
    user_id = update.effective_user.id
    parts = update.message.text.strip().split(' ', 1)
    if len(parts) < 2:
        await update.message.reply_text(
            "❌ Invalid format.\n\nUse: `<minutes> <message>`\nExample: `5 Hello everyone!`",
            parse_mode='Markdown'
        )
        return

    try:
        interval = int(parts[0])
        if interval < 1:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Interval must be a whole number (minutes), e.g. `5`")
        return

    message = parts[1]
    chats = context.user_data.pop('gm_all_groups_list', [])
    context.user_data['awaiting_all_groups_msg'] = False

    account = await db.get_active_account(user_id)
    if not account:
        await update.message.reply_text("❌ No active account.")
        return

    wait_msg = await update.message.reply_text(f"⏳ Scheduling for {len(chats)} groups...")

    added = 0
    for chat in chats:
        try:
            await db.add_group_auto_message(
                user_id, account['id'],
                str(chat['id']), chat['title'],
                message, interval
            )
            added += 1
        except Exception as e:
            print(f"⚠️ Could not add group {chat['title']}: {e}")

    await wait_msg.edit_text(
        f"✅ **Done!**\n\n"
        f"Scheduled **{added}** group(s) with:\n"
        f"• Interval: every **{interval}** minute(s)\n"
        f"• Message: `{message[:60]}`\n\n"
        f"_Go to 📋 My Group Messages to manage ON/OFF._",
        parse_mode='Markdown',
        reply_markup=menu_ui.main_menu(is_admin=is_admin(user_id))
    )

async def scraper_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if not await check_access(update.effective_user.id):
        return
    try:
        await update.callback_query.edit_message_text(
            "🔍 **Scraper**\n\nExtract data:",
            reply_markup=menu_ui.scraper_menu(),
            parse_mode='Markdown'
        )
    except BadRequest:
        pass

async def scrape_members_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    try:
        await update.callback_query.edit_message_text(
            "👥 **Scrape Members**\n\nType: `<group> [limit]`\n\nExample:\n`@mygroup 500`",
            parse_mode='Markdown',
            reply_markup=menu_ui.back_button()
        )
    except BadRequest:
        pass
    context.user_data['awaiting_scrape'] = True

async def process_scrape(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_scrape'):
        return
    user_id = update.effective_user.id
    text = update.message.text.strip().split()
    group = text[0]
    limit = int(text[1]) if len(text) > 1 else 1000
    context.user_data['awaiting_scrape'] = False
    await update.message.reply_text("🔍 Scraping...")
    result = await scraper.scrape_group_members(user_id, group, limit)
    if result['success']:
        import csv, io
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=['id', 'username', 'first_name', 'last_name', 'phone'])
        writer.writeheader()
        writer.writerows(result['members'])
        output.seek(0)
        await update.message.reply_document(
            document=output.getvalue().encode(),
            filename=f"{group}_members.csv",
            caption=f"✅ Scraped {result['total']} members",
            reply_markup=menu_ui.main_menu(is_admin=is_admin(user_id))
        )
    else:
        await update.message.reply_text(f"❌ Error: {result['error']}")

# ============ MULTI-ACCOUNT ============

async def multi_account_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    try:
        await update.callback_query.edit_message_text(
            "👥 **Multi-Account**\n\nManage accounts:",
            reply_markup=menu_ui.multi_account_menu(),
            parse_mode='Markdown'
        )
    except BadRequest:
        pass

async def view_accounts_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    user_id = update.effective_user.id
    accounts = await db.get_all_accounts(user_id)
    if not accounts:
        try:
            await update.callback_query.edit_message_text(
                "📋 **Your Accounts**\n\nNo accounts.",
                reply_markup=menu_ui.multi_account_menu()
            )
        except BadRequest:
            pass
        return
    text = "📋 **Your Accounts**\n\n"
    for acc in accounts:
        status = "✅" if acc['is_active'] else "⚪"
        text += f"{status} {acc['phone']} (ID: {acc['id']})\n"
    try:
        await update.callback_query.edit_message_text(
            text, reply_markup=menu_ui.multi_account_menu(), parse_mode='Markdown'
        )
    except BadRequest:
        pass

# ============ ANALYTICS ============

async def analytics_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    user_id = update.effective_user.id
    stats = await analytics.get_user_stats(user_id)

    text = (
        f"📊 **Analytics**\n\n"
        f"📨 Sent: {stats['total_sent']}\n"
        f"⏰ Schedules: {stats['active_schedules']}\n"
        f"🤖 Auto-replies: {stats['active_auto_replies']}\n"
        f"📢 Group Messages: {stats.get('active_group_messages', 0)}\n"
        f"👥 Accounts: {stats['total_accounts']}"
    )
    try:
        await update.callback_query.edit_message_text(
            text, reply_markup=menu_ui.back_button(), parse_mode='Markdown'
        )
    except BadRequest:
        pass

# ============ SENT MESSAGES ============

async def sent_messages_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    user_id = update.effective_user.id
    messages = await db.get_sent_messages(user_id, limit=10)
    if not messages:
        try:
            await update.callback_query.edit_message_text(
                "📨 **Sent Messages**\n\nNo messages yet.",
                reply_markup=menu_ui.back_button()
            )
        except BadRequest:
            pass
        return
    text = "📨 **Recent Messages**\n\n"
    for msg in messages:
        text += f"To: {msg['target']}\nText: {msg['message'][:40]}...\n\n"
    try:
        await update.callback_query.edit_message_text(
            text, reply_markup=menu_ui.back_button(), parse_mode='Markdown'
        )
    except BadRequest:
        pass

# ============ STATUS ============

async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    user_id = update.effective_user.id
    account = await db.get_active_account(user_id)
    if account:
        client = await client_manager.get_client(user_id, account['id'])
        is_connected = client.is_connected() if client else False
        scheduler_status = scheduler_manager.is_running
        text = (
            f"📈 **Status**\n\n"
            f"✅ Account: {account['phone']}\n"
            f"{'🟢' if is_connected else '🔴'} Connection: {'Active' if is_connected else 'Off'}\n\n"
            f"⏰ Scheduler: {'✅' if scheduler_status else '❌'}"
        )
    else:
        text = "❌ No account. Login first."
    try:
        await update.callback_query.edit_message_text(
            text, reply_markup=menu_ui.back_button(), parse_mode='Markdown'
        )
    except BadRequest:
        pass

# ============ LOGOUT ============

async def logout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    user_id = update.effective_user.id
    account = await db.get_active_account(user_id)
    if account:
        await client_manager.remove_client(user_id, account['id'])
        await db.delete_account(account['id'], user_id)
        try:
            await update.callback_query.edit_message_text(
                "✅ Logged out!",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔐 Login", callback_data="add_account")
                ]])
            )
        except BadRequest:
            pass
    else:
        try:
            await update.callback_query.edit_message_text("❌ No account.")
        except BadRequest:
            pass

# ============ NOOP (for non-interactive buttons like page counter) ============

async def noop_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

# ============ TEXT MESSAGE ROUTER ============

async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Broadcast (admin only)
    if context.user_data.get('awaiting_broadcast') and is_admin(user_id):
        await process_broadcast(update, context)
        return

    if not await check_access(user_id) and not is_admin(user_id):
        await update.message.reply_text("⏳ Your access is pending admin approval.")
        return

    if context.user_data.get('awaiting_auto_reply'):
        await process_auto_reply(update, context)
    elif context.user_data.get('awaiting_schedule'):
        await process_schedule(update, context)
    elif context.user_data.get('awaiting_send_message'):
        await process_send_message(update, context)
    elif context.user_data.get('awaiting_scrape'):
        await process_scrape(update, context)
    elif context.user_data.get('awaiting_folder_link'):
        await process_folder_link(update, context)
    elif context.user_data.get('awaiting_folder_msg'):
        await process_folder_msg(update, context)
    elif context.user_data.get('awaiting_selection_msg'):
        await process_selection_msg(update, context)
    elif context.user_data.get('awaiting_group_message'):
        await process_group_message(update, context)
    elif context.user_data.get('awaiting_all_groups_msg'):
        await process_all_groups_msg(update, context)
    else:
        await update.message.reply_text(
            "👋 Use /start for menu!",
            reply_markup=menu_ui.main_menu(is_admin=is_admin(user_id))
        )

# ============ POST INIT ============

async def post_init(application: Application):
    await db.init_db()
    scheduler_manager.start_scheduler_job()
    await auto_start_users()
    asyncio.create_task(group_message_manager.start_group_message_job())
    print("✅ Bot initialized!")
    print("⏰ Scheduler running")
    print("📢 Group message job started")
    print("📡 Auto-start complete")

# ============ MAIN ============

def main():
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    application.add_error_handler(error_handler)

    # Login conversation
    login_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(login_handler.start_login, pattern='^add_account$')],
        states={
            API_ID:    [MessageHandler(filters.TEXT & ~filters.COMMAND, login_handler.receive_api_id)],
            API_HASH:  [MessageHandler(filters.TEXT & ~filters.COMMAND, login_handler.receive_api_hash)],
            PHONE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, login_handler.receive_phone)],
            OTP:       [MessageHandler(filters.TEXT & ~filters.COMMAND, login_handler.receive_otp)],
            PASSWORD:  [MessageHandler(filters.TEXT & ~filters.COMMAND, login_handler.receive_password)],
        },
        fallbacks=[
            CommandHandler('cancel', login_handler.cancel_login),
            CommandHandler('start', login_handler.restart_login),
        ],
        allow_reentry=True,
    )

    application.add_handler(CommandHandler('start', start))
    application.add_handler(login_conv)

    # Main navigation
    application.add_handler(CallbackQueryHandler(show_main_menu, pattern='^main_menu$'))
    application.add_handler(CallbackQueryHandler(send_message_handler, pattern='^send_message$'))
    application.add_handler(CallbackQueryHandler(multi_account_handler, pattern='^multi_account$'))
    application.add_handler(CallbackQueryHandler(view_accounts_handler, pattern='^view_accounts$'))

    application.add_handler(CallbackQueryHandler(schedule_handler, pattern='^schedule$'))
    application.add_handler(CallbackQueryHandler(schedule_time_handler, pattern='^schedule_time$'))
    application.add_handler(CallbackQueryHandler(my_schedules_handler, pattern='^my_schedules$'))

    application.add_handler(CallbackQueryHandler(auto_reply_menu_handler, pattern='^auto_reply$'))
    application.add_handler(CallbackQueryHandler(set_auto_reply_handler, pattern='^set_auto_reply$'))
    application.add_handler(CallbackQueryHandler(delete_auto_reply_handler, pattern='^delete_auto_reply$'))

    application.add_handler(CallbackQueryHandler(scraper_handler, pattern='^scraper$'))
    application.add_handler(CallbackQueryHandler(scrape_members_handler, pattern='^scrape_members$'))

    application.add_handler(CallbackQueryHandler(analytics_handler, pattern='^analytics$'))
    application.add_handler(CallbackQueryHandler(sent_messages_handler, pattern='^sent_messages$'))
    application.add_handler(CallbackQueryHandler(status_handler, pattern='^status$'))
    application.add_handler(CallbackQueryHandler(logout_handler, pattern='^logout$'))

    # Group Messages — main menu
    application.add_handler(CallbackQueryHandler(group_messages_handler, pattern='^group_messages$'))

    # Group Messages — Add via Folder Link
    application.add_handler(CallbackQueryHandler(gm_add_folder_handler, pattern='^gm_add_folder$'))

    # Group Messages — Browse & Select from My Chats
    application.add_handler(CallbackQueryHandler(gm_browse_chats_handler, pattern='^gm_browse_chats$'))
    application.add_handler(CallbackQueryHandler(gm_toggle_handler, pattern='^gm_toggle_'))
    application.add_handler(CallbackQueryHandler(gm_page_handler, pattern='^gm_page_'))
    application.add_handler(CallbackQueryHandler(gm_confirm_selection_handler, pattern='^gm_confirm_selection$'))

    # Group Messages — Add Single / View / Delete / Toggle
    application.add_handler(CallbackQueryHandler(add_group_message_handler, pattern='^add_group_message$'))
    application.add_handler(CallbackQueryHandler(view_group_messages_handler, pattern='^view_group_messages$'))
    application.add_handler(CallbackQueryHandler(delete_group_message_handler, pattern='^del_group_msg_'))
    application.add_handler(CallbackQueryHandler(toggle_group_msg_active_handler, pattern='^gm_toggle_active_'))
    application.add_handler(CallbackQueryHandler(gm_master_toggle_handler, pattern='^gm_master_'))
    application.add_handler(CallbackQueryHandler(gm_all_groups_handler, pattern='^gm_all_groups$'))

    # Admin panel
    application.add_handler(CallbackQueryHandler(admin_panel_handler, pattern='^admin_panel$'))
    application.add_handler(CallbackQueryHandler(admin_users_handler, pattern='^admin_users$'))
    application.add_handler(CallbackQueryHandler(admin_requests_handler, pattern='^admin_requests$'))
    application.add_handler(CallbackQueryHandler(admin_broadcast_all_handler, pattern='^admin_broadcast_all$'))
    application.add_handler(CallbackQueryHandler(admin_broadcast_approved_handler, pattern='^admin_broadcast_approved$'))
    application.add_handler(CallbackQueryHandler(admin_broadcast_unapproved_handler, pattern='^admin_broadcast_unapproved$'))
    application.add_handler(CallbackQueryHandler(admin_approve_handler, pattern='^admin_approve_'))
    application.add_handler(CallbackQueryHandler(admin_reject_handler, pattern='^admin_reject_'))

    # Noop (non-interactive buttons)
    application.add_handler(CallbackQueryHandler(noop_handler, pattern='^noop$'))

    # Text handler (must be last)
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
        handle_text_messages
    ))

    print("🚀 Starting bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
