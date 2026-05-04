from telegram import InlineKeyboardButton, InlineKeyboardMarkup


class MenuUI:

    @staticmethod
    def main_menu(is_admin=False):
        """Main menu"""
        keyboard = [
            [
                InlineKeyboardButton("💬 Send Message", callback_data="send_message"),
                InlineKeyboardButton("🤖 Auto Reply", callback_data="auto_reply")
            ],
            [
                InlineKeyboardButton("⏰ Schedule", callback_data="schedule"),
                InlineKeyboardButton("📅 My Schedules", callback_data="my_schedules")
            ],
            [
                InlineKeyboardButton("👥 Multi-Account", callback_data="multi_account"),
                InlineKeyboardButton("📊 Analytics", callback_data="analytics")
            ],
            [
                InlineKeyboardButton("🔍 Scraper", callback_data="scraper"),
                InlineKeyboardButton("📢 Group Messages", callback_data="group_messages")
            ],
            [
                InlineKeyboardButton("📨 Sent Messages", callback_data="sent_messages"),
                InlineKeyboardButton("📈 Status", callback_data="status")
            ],
        ]

        if is_admin:
            keyboard.append([
                InlineKeyboardButton("🔐 Admin Panel", callback_data="admin_panel")
            ])

        keyboard.append([
            InlineKeyboardButton("🚪 Logout", callback_data="logout")
        ])

        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def admin_panel_menu():
        """Admin panel menu"""
        keyboard = [
            [
                InlineKeyboardButton("👥 All Users & Accounts", callback_data="admin_users"),
                InlineKeyboardButton("📝 Access Requests", callback_data="admin_requests")
            ],
            [
                InlineKeyboardButton("📢 Broadcast (All)", callback_data="admin_broadcast_all"),
                InlineKeyboardButton("📢 Broadcast (Approved)", callback_data="admin_broadcast_approved"),
            ],
            [
                InlineKeyboardButton("📢 Broadcast (Unapproved)", callback_data="admin_broadcast_unapproved"),
            ],
            [
                InlineKeyboardButton("« Back", callback_data="main_menu")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def group_messages_menu():
        """Group auto messages main menu"""
        keyboard = [
            [InlineKeyboardButton("🌐 Message in ALL Groups", callback_data="gm_all_groups")],
            [InlineKeyboardButton("📁 Add via Folder Link", callback_data="gm_add_folder")],
            [InlineKeyboardButton("☑️ Select from My Chats", callback_data="gm_browse_chats")],
            [InlineKeyboardButton("✏️ Add Single Group", callback_data="add_group_message")],
            [InlineKeyboardButton("📋 My Group Messages", callback_data="view_group_messages")],
            [InlineKeyboardButton("« Back", callback_data="main_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def group_messages_list_keyboard(messages_list: list) -> "InlineKeyboardMarkup":
        """
        Build view keyboard with ON/OFF toggle + delete for each group message.
        Shows ALL messages (active + paused).
        """
        keyboard_rows = []
        # Master toggle row — always at top
        any_active = any(bool(m.get('is_active', 1)) for m in messages_list)
        if any_active:
            keyboard_rows.append([
                InlineKeyboardButton("🔴 STOP ALL (Master OFF)", callback_data="gm_master_off")
            ])
        else:
            keyboard_rows.append([
                InlineKeyboardButton("🟢 START ALL (Master ON)", callback_data="gm_master_on")
            ])

        for msg in messages_list:
            is_active = bool(msg.get('is_active', 1))
            status_icon = "🟢" if is_active else "🔴"
            name_short = msg['group_name'][:20]
            toggle_label = f"{status_icon} {name_short}"
            keyboard_rows.append([
                InlineKeyboardButton(
                    toggle_label,
                    callback_data=f"gm_toggle_active_{msg['id']}"
                ),
                InlineKeyboardButton(
                    "🗑",
                    callback_data=f"del_group_msg_{msg['id']}"
                )
            ])
        keyboard_rows.append([InlineKeyboardButton("« Back", callback_data="group_messages")])
        return InlineKeyboardMarkup(keyboard_rows)

    @staticmethod
    def multi_account_menu():
        """Multi-account menu"""
        keyboard = [
            [
                InlineKeyboardButton("➕ Add Account", callback_data="add_account"),
                InlineKeyboardButton("📋 View Accounts", callback_data="view_accounts")
            ],
            [InlineKeyboardButton("🔄 Switch Account", callback_data="switch_account")],
            [InlineKeyboardButton("« Back", callback_data="main_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def scraper_menu():
        """Scraper menu"""
        keyboard = [
            [InlineKeyboardButton("👥 Scrape Members", callback_data="scrape_members")],
            [InlineKeyboardButton("« Back", callback_data="main_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def schedule_menu():
        """Schedule menu"""
        keyboard = [
            [InlineKeyboardButton("⏱️ Schedule Time (HH:MM:SS)", callback_data="schedule_time")],
            [InlineKeyboardButton("« Back", callback_data="main_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def auto_reply_menu():
        """Auto-reply menu"""
        keyboard = [
            [InlineKeyboardButton("➕ Set Message", callback_data="set_auto_reply")],
            [InlineKeyboardButton("🗑️ Remove", callback_data="delete_auto_reply")],
            [InlineKeyboardButton("« Back", callback_data="main_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def back_button():
        """Back to main menu button"""
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("« Back to Menu", callback_data="main_menu")
        ]])

    @staticmethod
    def chat_selection_keyboard(chats: list, selected_ids: set, page: int = 0, page_size: int = 8):
        """
        Build a paginated inline keyboard for selecting groups.
        chats: list of dicts with 'id', 'title'
        selected_ids: set of group id strings currently selected
        Returns (keyboard markup, total_pages)
        """
        total = len(chats)
        total_pages = max(1, (total + page_size - 1) // page_size)
        start = page * page_size
        end = min(start + page_size, total)
        page_chats = chats[start:end]

        rows = []
        for chat in page_chats:
            gid = str(chat['id'])
            tick = "✅ " if gid in selected_ids else "⬜ "
            label = (chat['title'][:28] + "…") if len(chat['title']) > 30 else chat['title']
            rows.append([
                InlineKeyboardButton(
                    f"{tick}{label}",
                    callback_data=f"gm_toggle_{gid}"
                )
            ])

        # Pagination row
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("◀ Prev", callback_data=f"gm_page_{page - 1}"))
        nav.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton("Next ▶", callback_data=f"gm_page_{page + 1}"))
        if nav:
            rows.append(nav)

        # Action row
        rows.append([
            InlineKeyboardButton(
                f"✅ Confirm ({len(selected_ids)} selected)",
                callback_data="gm_confirm_selection"
            )
        ])
        rows.append([InlineKeyboardButton("« Cancel", callback_data="group_messages")])

        return InlineKeyboardMarkup(rows), total_pages


menu_ui = MenuUI()
