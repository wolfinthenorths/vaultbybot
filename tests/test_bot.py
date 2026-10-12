import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import CallbackQuery, Chat, Message, MessageEntity, MessageId, PhotoSize, User

from storage import Database


TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk"
CHAT_ID = -100111
_import_temp = tempfile.TemporaryDirectory()
with mock.patch.dict(os.environ, {"BOT_TOKEN": TOKEN, "SUPPORT_CHAT_ID": str(CHAT_ID),
                                  "DB_PATH": _import_temp.name + "/initial.db"}, clear=True):
    import bot as app
app.database.close()


def tearDownModule():
    _import_temp.cleanup()


class RecordingSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.counter = 500
        self.fail = None

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        yield b""

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if self.fail:
            self.fail(method)
        name = method.__api_method__
        if name == "copyMessage":
            self.counter += 1
            return MessageId(message_id=self.counter)
        if name in {"sendMessage", "sendPhoto", "sendDocument"}:
            self.counter += 1
            result = Message(
                message_id=self.counter, date=datetime.now(timezone.utc),
                chat=Chat(id=method.chat_id, type="private" if method.chat_id > 0 else "supergroup"),
                from_user=User(id=bot.id, is_bot=True, first_name="Pip-Boy"),
                text=getattr(method, "text", None), caption=getattr(method, "caption", None),
                reply_markup=getattr(method, "reply_markup", None))
            return result.as_(bot)
        return True


class BotTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Database(Path(self.temp.name) / "test.db", CHAT_ID)
        self.addCleanup(self.db.close)
        self.session = RecordingSession()
        self.bot = Bot(token=TOKEN, session=self.session)
        self.patchers = [mock.patch.object(app, "database", self.db),
                         mock.patch.object(app, "bot", self.bot)]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        app.recent_templates.clear()
        self.user = User(id=42, is_bot=False, first_name="Фаня", username="fanya")
        self.admin = User(id=99, is_bot=False, first_name="Админ")
        self.bot_user = User(id=self.bot.id, is_bot=True, first_name="Pip-Boy")

    def message(self, message_id=1, chat_id=42, user=None, **kwargs):
        return Message(message_id=message_id, date=datetime.now(timezone.utc),
                       chat=Chat(id=chat_id, type="private" if chat_id > 0 else "supergroup"),
                       from_user=user or self.user, **kwargs).as_(self.bot)

    def card(self, message_id=10, text="Вопрос", user_id=42):
        return self.message(message_id, CHAT_ID, self.bot_user, text=text,
                            reply_markup=app.support_actions_keyboard(user_id))

    def calls(self, method, chat_id=None):
        return [call for call in self.session.calls if call.__api_method__ == method
                and (chat_id is None or getattr(call, "chat_id", None) == chat_id)]

    async def test_text_is_one_support_card_with_formatting(self):
        message = self.message(text="Здравствуйте!", entities=[MessageEntity(type="bold", offset=0, length=12)])
        await app.message_from_user(message)
        incoming = self.calls("sendMessage", CHAT_ID)
        self.assertEqual(len(incoming), 1)
        self.assertIn("Фаня", incoming[0].text)
        self.assertIn("Здравствуйте!", incoming[0].text)
        self.assertGreaterEqual(len(incoming[0].entities), 3)
        self.assertEqual(self.db.get_user_id(501), 42)
        self.assertEqual(len(self.calls("sendMessage", 42)), 0)

    async def test_maximum_text_remains_one_message_and_is_not_truncated(self):
        message = self.message(text="x" * 4096)
        await app.message_from_user(message)
        copies = self.calls("copyMessage", CHAT_ID)
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0].message_id, message.message_id)
        self.assertEqual(len(self.calls("sendMessage", CHAT_ID)), 0)
        self.assertEqual(copies[0].reply_markup.inline_keyboard[0][0].callback_data, "admin:profile:42")

    async def test_short_photo_caption_is_one_card_with_preserved_entities(self):
        message = self.message(photo=[PhotoSize(file_id="p", file_unique_id="u", width=10, height=10)],
                               caption="Привет", caption_entities=[MessageEntity(type="bold", offset=0, length=6)])
        await app.message_from_user(message)
        copies = self.calls("copyMessage", CHAT_ID)
        self.assertEqual(len(copies), 1)
        self.assertIn("Привет", copies[0].caption)
        self.assertGreaterEqual(len(copies[0].caption_entities), 3)
        self.assertFalse(self.calls("sendMessage", CHAT_ID))

    async def test_long_media_caption_is_kept_in_full(self):
        message = self.message(photo=[PhotoSize(file_id="p", file_unique_id="u", width=10, height=10)],
                               caption="x" * 1024)
        await app.message_from_user(message)
        copies = self.calls("copyMessage", CHAT_ID)
        self.assertEqual(len(copies), 1)
        self.assertIsNone(copies[0].caption)
        self.assertFalse(self.calls("sendMessage", CHAT_ID))

    async def test_replayed_update_does_not_duplicate_incoming_or_send_notification(self):
        message = self.message(text="Вопрос")
        await app.message_from_user(message)
        await app.message_from_user(message)
        self.assertEqual(len(self.calls("sendMessage", CHAT_ID)), 1)
        self.assertEqual(len(self.calls("sendMessage", 42)), 0)

    async def test_simultaneous_messages_do_not_send_contact_hint(self):
        await asyncio.gather(app.message_from_user(self.message(1, text="Первый")),
                             app.message_from_user(self.message(2, text="Второй")))
        self.assertEqual(len(self.calls("sendMessage", CHAT_ID)), 2)
        self.assertEqual(len(self.calls("sendMessage", 42)), 0)

    async def test_failed_welcome_is_not_marked_shown(self):
        def fail_private(method):
            if method.__api_method__ in {"sendMessage", "sendPhoto"} and method.chat_id == 42:
                raise TelegramForbiddenError(method, "Forbidden")
        self.session.fail = fail_private
        message = self.message(text="/start")
        with self.assertRaises(TelegramForbiddenError):
            await app.start(message)
        self.assertFalse(self.db.first_reply_sent(42))
        self.session.fail = None
        await app.start(message)
        self.assertTrue(self.db.first_reply_sent(42))
        self.assertEqual(len(self.calls("sendMessage", CHAT_ID)), 0)

    async def test_contact_hint_is_in_first_welcome_only(self):
        await app.start(self.message(text="/start"))
        await app.start(self.message(2, text="/start"))
        welcomes = self.calls("sendPhoto", 42)
        self.assertEqual(len(welcomes), 2)
        self.assertIn(app.CONTACT_HINT, welcomes[0].caption)
        self.assertNotIn(app.CONTACT_HINT, welcomes[1].caption)
        self.assertFalse(self.calls("sendMessage", 42))

    async def test_existing_acknowledgement_is_not_repeated_on_start(self):
        self.db.mark_first_reply_sent(42)
        await app.start(self.message(text="/start"))
        self.assertNotIn(app.CONTACT_HINT, self.calls("sendPhoto", 42)[0].caption)

    async def test_start_hint_state_survives_database_reopen(self):
        await app.start(self.message(text="/start"))
        path = self.db.path
        self.db.close()
        self.db = Database(path, CHAT_ID)
        app.database = self.db
        self.addCleanup(self.db.close)
        await app.start(self.message(2, text="/start"))
        await app.message_from_user(self.message(3, text="Вопрос после обновления"))
        self.assertNotIn(app.CONTACT_HINT, self.calls("sendPhoto", 42)[1].caption)
        self.assertFalse(self.calls("sendMessage", 42))

    async def test_manual_reply_preserves_media_and_has_no_duplicate_success_post(self):
        message = self.message(11, CHAT_ID, self.admin, text="Наш ответ", reply_to_message=self.card())
        await app.handle_support_chat_message(message)
        self.assertEqual(len(self.calls("copyMessage", 42)), 1)
        self.assertFalse(self.calls("sendMessage", CHAT_ID))
        self.assertEqual(self.db.get_user_id(11), 42)
        status = self.calls("editMessageReplyMarkup")[0].reply_markup.inline_keyboard[-1][0].text
        self.assertIn("ответ отправлен", status)

    async def test_status_edit_failure_does_not_repeat_delivered_reply(self):
        def fail_status(method):
            if method.__api_method__ == "editMessageReplyMarkup":
                raise TelegramBadRequest(method, "message to edit not found")
        self.session.fail = fail_status
        message = self.message(11, CHAT_ID, self.admin, text="Ответ", reply_to_message=self.card())
        await app.handle_support_chat_message(message)
        self.assertEqual(len(self.calls("copyMessage", 42)), 1)
        self.assertFalse(self.calls("sendMessage", CHAT_ID))

    async def test_template_double_click_sends_once_and_status_stays_on_card(self):
        callback = CallbackQuery(id="query", from_user=self.admin, chat_instance="instance",
                                 message=self.card(), data="tpl:booking:42").as_(self.bot)
        await asyncio.gather(app.send_template_to_user(callback), app.send_template_to_user(callback))
        self.assertEqual(len(self.calls("sendMessage", 42)), 1)
        self.assertFalse(self.calls("sendMessage", CHAT_ID))

    def test_embedded_user_ids_cannot_override_bot_keyboard_recipient(self):
        message = self.card(text="Текст пользователя\n🆔 ID: 999")
        self.assertEqual(app.find_support_user_id(message), 42)

    def test_human_authored_fake_footer_is_rejected(self):
        message = self.message(12, CHAT_ID, self.admin, text="🆔 ID: 999")
        self.assertIsNone(app.find_support_user_id(message))

    def test_old_footer_is_recovered_and_persisted(self):
        message = self.message(20, CHAT_ID, self.bot_user,
                               text="💬 Сообщение пользователя:\n\n🆔 ID: 999\n\n🆔 ID: 42")
        self.assertEqual(app.find_support_user_id(message), 42)
        self.assertEqual(self.db.get_user_id(20), 42)

    def test_old_author_card_recovers_profile_and_route(self):
        message = self.message(21, CHAT_ID, self.bot_user, text=(
            "📩 Новое сообщение в бота\n\n👤 Пользователь: Фаня\n"
            "🔗 Username: @fanya\n🆔 ID: 42\n\nМожно ответить вручную через Reply"))
        self.assertEqual(app.find_support_user_id(message), 42)
        self.assertIn("@fanya", self.db.get_user_info(42))

    def test_other_chat_cannot_reuse_a_saved_message_id(self):
        self.db.save_message_map(20, 42)
        message = self.message(20, -200, self.bot_user, text="🆔 ID: 999")
        self.assertIsNone(app.find_support_user_id(message))

    async def test_old_human_reply_can_recover_route_via_original_card(self):
        message = self.message(11, CHAT_ID, self.admin, text="Первый ответ", reply_to_message=self.card())
        self.assertEqual(app.find_support_user_id(message), 42)
        self.assertEqual(self.db.get_user_id(11), 42)

    async def test_roles_answer_callback_before_loading_and_paginate_long_list(self):
        def roles():
            self.assertEqual(self.session.calls[0].__api_method__, "answerCallbackQuery")
            return "\n".join(f"✧ Персонаж {index}" for index in range(700))
        message = self.message(photo=[PhotoSize(file_id="p", file_unique_id="u", width=10, height=10)])
        callback = CallbackQuery(id="query", from_user=self.user, chat_instance="instance",
                                 message=message, data="menu_roles:1").as_(self.bot)
        with mock.patch.object(app, "get_taken_roles_text", roles):
            await app.open_roles_menu(callback)
        sent = self.calls("sendMessage", 42)[0]
        self.assertLessEqual(app.utf16_length(sent.text), 4096)
        self.assertIn("Страница 2/", sent.text)
        nav = [button.callback_data for row in sent.reply_markup.inline_keyboard for button in row]
        self.assertIn("menu_roles:0", nav)
        methods = [call.__api_method__ for call in self.session.calls]
        self.assertLess(methods.index("sendMessage"), methods.index("deleteMessage"))

    async def test_failed_menu_replacement_keeps_original_menu(self):
        def fail_send(method):
            if method.__api_method__ in {"sendPhoto", "sendMessage"}:
                raise TelegramBadRequest(method, "send failed")
        self.session.fail = fail_send
        callback = CallbackQuery(id="query", from_user=self.user, chat_instance="instance",
                                 message=self.message(text="Original"), data="menu_main").as_(self.bot)
        with self.assertRaises(TelegramBadRequest):
            await app.edit_photo_menu(callback, "bad-image", "Menu", app.main_menu())
        self.assertFalse(self.calls("deleteMessage"))

    def test_unicode_page_splits_respect_utf16_limit_and_keep_all_text(self):
        text = "🙂" * 3000 + "\n" + "Я" * 4000
        pages = app.split_text(text)
        self.assertEqual("".join(pages), text)
        self.assertTrue(all(app.utf16_length(page) <= 3900 for page in pages))

    def test_whitespace_admin_message_does_not_crash(self):
        self.assertEqual(app.normalize_command("   \n"), "")


if __name__ == "__main__":
    unittest.main()
