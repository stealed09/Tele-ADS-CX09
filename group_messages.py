"""
group_messages.py — Group Auto Message Manager
================================================
Features:
  1. Add via Folder Link  — paste a t.me/addlist/... link; bot fetches all
                            groups in that folder and lets user confirm.
  2. Select from My Chats — browse a paginated, checkboxed list of all groups
                            the logged-in account is a member of, tick any
                            subset, then set message + interval once for all.
  3. Add Single Group     — original flow (group id/username + interval + msg).
  4. View / Delete active group messages.

The background job polls every 60 s and fires messages at their individual
interval_minutes cadences exactly as before.
"""

import asyncio
import re
from datetime import datetime, timedelta

from database import db
from client_manager import client_manager


# ---------------------------------------------------------------------------
# Helper: resolve folder link → list of group entities
# ---------------------------------------------------------------------------

async def fetch_folder_groups(client, folder_link: str) -> list:
    """
    Accept a Telegram folder invite link (t.me/addlist/XXXX) and return
    a list of dicts: [{'id': int, 'title': str}, ...]
    Only groups/supergroups/channels are included (not private chats).
    """
    from telethon.tl.functions.chatlists import CheckChatlistInviteRequest
    from telethon.tl.types import ChatlistInviteAlready, ChatlistInvite

    # Extract slug from link
    match = re.search(r'addlist/([A-Za-z0-9_-]+)', folder_link)
    if not match:
        raise ValueError("Invalid folder link. Expected format: t.me/addlist/XXXX")
    slug = match.group(1)

    result = await client(CheckChatlistInviteRequest(slug=slug))

    chats = []
    # result.chats contains the peer list
    for chat in result.chats:
        # Filter to groups/channels only
        chat_type = type(chat).__name__
        if chat_type in ('Chat', 'Channel'):
            title = getattr(chat, 'title', str(chat.id))
            chats.append({'id': chat.id, 'title': title})

    return chats


# ---------------------------------------------------------------------------
# Helper: list all groups the account is already in
# ---------------------------------------------------------------------------

async def fetch_all_joined_groups(client) -> list:
    """Return groups where the logged-in user can actually send messages.
    Skips channels/groups where send_messages permission is restricted.
    """
    from telethon.tl.types import Channel, Chat, ChatBannedRights

    dialogs = await client.get_dialogs()
    groups = []
    for dialog in dialogs:
        entity = dialog.entity
        if not isinstance(entity, (Channel, Chat)):
            continue

        title = getattr(entity, 'title', str(entity.id))

        # --- Channel / Supergroup checks ---
        if isinstance(entity, Channel):
            # Broadcast channels — only admins can post, skip
            if getattr(entity, 'broadcast', False):
                continue

            # Check if user's own send_messages right is restricted
            banned: ChatBannedRights = getattr(entity, 'banned_rights', None)
            if banned and getattr(banned, 'send_messages', False):
                continue

            # Check default_banned_rights — if everyone is banned from sending
            default_banned: ChatBannedRights = getattr(entity, 'default_banned_rights', None)
            if default_banned and getattr(default_banned, 'send_messages', False):
                # Only skip if user is not admin
                if not getattr(entity, 'admin_rights', None):
                    continue

        groups.append({'id': entity.id, 'title': title})

    return groups


# ---------------------------------------------------------------------------
# Background job
# ---------------------------------------------------------------------------

class GroupMessageManager:
    def __init__(self):
        self.is_running = False

    async def check_and_send_group_messages(self):
        """Check all active group messages and send those that are due."""
        try:
            active_messages = await db.get_all_active_group_messages()

            for msg_config in active_messages:
                try:
                    if msg_config['last_sent']:
                        last_sent = datetime.fromisoformat(msg_config['last_sent'])
                        interval = int(msg_config['interval_minutes'])
                        next_send = last_sent + timedelta(minutes=interval)
                        if datetime.now() < next_send:
                            continue

                    client = await client_manager.get_client(
                        msg_config['user_id'],
                        msg_config['account_id']
                    )
                    if not client:
                        continue

                    await client.send_message(
                        int(msg_config['group_id']),
                        msg_config['message']
                    )
                    await db.update_group_message_last_sent(msg_config['id'])

                    print(
                        f"✅ Group msg sent → '{msg_config['group_name']}' "
                        f"(every {msg_config['interval_minutes']} min)"
                    )

                except Exception as e:
                    print(f"❌ Group msg error for {msg_config.get('group_name')}: {e}")

        except Exception as e:
            print(f"❌ Group message check error: {e}")

    async def start_group_message_job(self):
        """Background loop — checks every 60 seconds."""
        self.is_running = True
        print("✅ Group auto-message job started (60 s poll, per-group intervals)")
        while self.is_running:
            await self.check_and_send_group_messages()
            await asyncio.sleep(60)


group_message_manager = GroupMessageManager()
