"""📚 Mini App step 1: Telegram's launch data, the page and its API, the testers' menu button and /app, the
measurements in /stats, and deletion."""

import hashlib
import hmac
import json
import re
import time
from unittest.mock import AsyncMock, patch
from urllib.parse import urlencode

from fastapi.testclient import TestClient
from telegram import MenuButtonWebApp
from telegram.error import BadRequest
from telegram.ext import ExtBot

import config
import main
from modules import admin, miniapp, privacy, stats, student, webapp
from modules.activity import utc_today
from modules.math.shared import record_answer
from modules.ui import miniapp as miniapp_ui
from modules.ui import router
from tests.test_ui import STUDENT, TelegramMocks, button_update, run, text_update

TOKEN = config.TOKEN
TESTER = 4242
ADMIN = 901


def init_data(user_id=STUDENT, auth_date=None, token=TOKEN, language="en", extra=None, **user):
    """Launch data signed the way Telegram signs it."""
    profile = {"id": user_id, "first_name": "Sara", "last_name": "Ahmadi", "username": "sara_a", "language_code": language,
               "photo_url": "https://t.me/i/userpic/320/sara.jpg", **user}
    fields = {"auth_date": str(int(auth_date if auth_date is not None else time.time())), "query_id": "AAH1",
              "user": json.dumps(profile, separators=(",", ":"), ensure_ascii=False), **(extra or {})}
    check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


class LaunchDataTests(TelegramMocks):
    def check(self, data, now=None):
        return miniapp.check_init_data(data, TOKEN, 3600, now=now)

    def test_genuine_data_gives_only_the_user_id_language_and_start_parameter(self):
        result = self.check(init_data(language="fa", extra={"start_param": "insta"}))
        self.assertEqual(result, {"user_id": STUDENT, "language_code": "fa", "start_param": "insta"})

    def test_tampered_wrong_token_or_malformed_data_is_refused(self):
        genuine = init_data()
        self.assertIsNotNone(self.check(genuine))
        tampered = genuine.replace(f"%22id%22%3A{STUDENT}", "%22id%22%3A777")
        self.assertNotEqual(tampered, genuine)
        self.assertIsNone(self.check(tampered), "another user id")
        self.assertIsNone(self.check(init_data(token="999:OTHER_BOT")), "signed for another bot")
        self.assertIsNone(self.check(genuine.replace("hash=", "hash=0")), "a wrong hash")
        self.assertIsNone(self.check(re.sub(r"&?hash=[0-9a-f]+", "", genuine)), "no hash")
        self.assertIsNone(self.check(genuine + "&auth_date=1"), "a field twice")
        self.assertIsNone(self.check(""), "nothing")
        self.assertIsNone(self.check("x" * 9000), "too long")
        self.assertIsNone(self.check("%%%"), "not a query string")

    def test_old_or_future_data_is_refused(self):
        now = time.time()
        self.assertIsNotNone(self.check(init_data(auth_date=now - 3500), now=now))
        self.assertIsNone(self.check(init_data(auth_date=now - 3700), now=now), "older than an hour")
        self.assertIsNone(self.check(init_data(auth_date=now + 600), now=now), "from the future")

    def test_the_signature_is_built_as_telegram_documents_it(self):
        """secret = HMAC-SHA256(key="WebAppData", message=bot token); hash = HMAC-SHA256(key=secret, message=check string)."""
        fields = {"auth_date": "1700000000", "user": '{"id":1}'}
        secret = hmac.new(b"WebAppData", b"123:ABC", hashlib.sha256).digest()
        digest = hmac.new(secret, b"auth_date=1700000000\nuser={\"id\":1}", hashlib.sha256).hexdigest()
        data = urlencode(dict(fields, hash=digest))
        self.assertEqual(miniapp.check_init_data(data, "123:ABC", 10 ** 9, now=1700000001)["user_id"], 1)
        swapped = hmac.new(hmac.new(b"123:ABC", b"WebAppData", hashlib.sha256).digest(),
                           b"auth_date=1700000000\nuser={\"id\":1}", hashlib.sha256).hexdigest()
        self.assertIsNone(miniapp.check_init_data(urlencode(dict(fields, hash=swapped)), "123:ABC", 10 ** 9, now=1700000001))


class WebTests(TelegramMocks):
    def setUp(self):
        super().setUp()
        self.client = TestClient(main.api)  # no startup: the routes only

    def get(self, path, data=None):
        headers = {"Authorization": f"tma {data}"} if data is not None else {}
        return self.client.get(path, headers=headers)

    def test_the_page_has_strict_headers_and_both_languages(self):
        response = self.get("/app")
        self.assertEqual(response.status_code, 200)
        policy = response.headers["content-security-policy"]
        self.assertIn("default-src 'none'", policy)
        self.assertIn("script-src 'self'", policy)
        self.assertIn("frame-ancestors 'self' https://web.telegram.org", policy)
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        texts = json.loads(re.search(r'<script type="application/json" id="texts">(.*?)</script>', response.text, re.S).group(1))
        self.assertEqual(texts["fa"]["app.retry"], "دوباره امتحان کن")
        self.assertEqual(set(texts["en"]), set(texts["fa"]))
        for path, kind in (("/app/app.js", "javascript"), ("/app/app.css", "text/css")):
            asset = self.get(path)
            self.assertEqual(asset.status_code, 200)
            self.assertIn(kind, asset.headers["content-type"])

    def test_nothing_comes_from_other_hosts_and_the_page_is_small(self):
        page = self.get("/app").text
        script, styles = self.get("/app/app.js").text, self.get("/app/app.css").text
        for name, text in (("index.html", page), ("app.js", script), ("app.css", styles)):
            self.assertIsNone(re.search(r"(src|href)\s*=\s*[\"']?(https?:)?//", text), name)
            self.assertNotIn("@import", text, name)
            self.assertNotIn("telegram.org/js", text, name)
        self.assertLess(len(page.encode()) + len(script.encode()) + len(styles.encode()), 15 * 1024)

    def test_the_api_needs_genuine_launch_data(self):
        for data in (None, "", "user=x", init_data(token="999:OTHER"), init_data(auth_date=time.time() - 7200)):
            self.assertEqual(self.get("/api/me/progress", data).status_code, 401, data)
            self.assertEqual(self.client.post("/api/miniapp/ping", json={}, headers={"Authorization": f"tma {data}"}).status_code, 401)
        self.assertEqual(self.client.get("/api/me/progress", headers={"Authorization": f"Bearer {init_data()}"}).status_code, 401)

    def test_progress_in_the_students_language(self):
        record_answer(STUDENT, "high_school", "algebra", "easy", "first_try")
        data = self.get("/api/me/progress", init_data(language="en")).json()
        self.assertEqual((data["lang"], data["dir"], data["title"]), ("en", "ltr", "📊 My progress"))
        self.assertIsNone(data["empty"])
        (section,) = data["sections"]
        self.assertEqual(section["level"], "🎓 Grades 10–11")
        self.assertEqual(section["topics"][0], {"name": "Equations with brackets", "percent": 18, "detail": "18% · ✅ 1 · ❌ 0"})
        self.assertEqual(section["topics"][1]["detail"], "Not started yet")
        self.assertEqual(data["suggest"], "💡 Suggested next: Quadratic equations")
        # The language chosen in the bot wins over Telegram's.
        student.set_language(STUDENT, "fa")
        data = self.get("/api/me/progress", init_data(language="en")).json()
        self.assertEqual((data["lang"], data["dir"]), ("fa", "rtl"))
        self.assertEqual(data["sections"][0]["topics"][0]["detail"], "۱۸٪ · ✅ ۱ · ❌ ۰")

    def test_a_new_student_sees_the_empty_text(self):
        data = self.get("/api/me/progress", init_data(user_id=31337)).json()
        self.assertIn("haven't practised yet", data["empty"])

    def test_ping_stores_only_the_measurements(self):
        response = self.client.post("/api/miniapp/ping", headers={"Authorization": f"tma {init_data(language='fa')}"}, json={
            "platform": "android", "bridge": True, "dns_ms": 12.6, "connect_ms": 80, "ttfb_ms": 340, "dom_ms": 420,
            "total_ms": 910, "api_ms": 230, "first_name": "Sara", "notes": "anything else"})
        self.assertEqual(response.status_code, 200)
        (row,) = miniapp._FALLBACK.values()
        self.assertEqual(row, {"platform": "android", "bridge": True, "dns_ms": 12, "connect_ms": 80, "ttfb_ms": 340,
                               "dom_ms": 420, "total_ms": 910, "api_ms": 230, "opened": True, "day": utc_today()})
        stored = json.dumps(list(miniapp._FALLBACK.values()), default=str)
        for private in ("Sara", "Ahmadi", "sara_a", "userpic"):
            self.assertNotIn(private, stored)

    def test_ping_refuses_junk(self):
        headers = {"Authorization": f"tma {init_data()}"}
        self.assertEqual(self.client.post("/api/miniapp/ping", headers=headers, content=b"not json").status_code, 400)
        self.assertEqual(self.client.post("/api/miniapp/ping", headers=headers, json=[1, 2]).status_code, 400)
        self.assertEqual(self.client.post("/api/miniapp/ping", headers=headers, content=b"{" + b" " * 5000 + b"}").status_code, 413)
        self.client.post("/api/miniapp/ping", headers=headers, json={"platform": "<script>", "total_ms": 10 ** 9})
        (row,) = miniapp._FALLBACK.values()
        self.assertEqual((row["platform"], row["total_ms"]), ("other", miniapp.MAX_TIMING_MS))


class TesterTests(TelegramMocks):
    def setUp(self):
        super().setUp()
        for patcher in (
            patch.multiple(config, ADMIN_USER_IDS=frozenset({ADMIN}), MINIAPP_TESTER_IDS=frozenset({TESTER}),
                           MINIAPP_URL="https://darsai.example/app"),
            patch.object(admin, "ADMIN_USER_IDS", frozenset({ADMIN})),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.set_menu = self._patch(ExtBot, "set_chat_menu_button", True)

    def test_the_menu_button_is_set_for_testers_only(self):
        student.set_language(TESTER, "fa")
        done = run_async(miniapp_ui.setup_menu_buttons(main.telegram_app.bot))
        self.assertEqual(done, [ADMIN, TESTER])
        calls = {call.kwargs["chat_id"]: call.kwargs["menu_button"] for call in self.set_menu.call_args_list}
        self.assertEqual(set(calls), {ADMIN, TESTER})
        self.assertIsInstance(calls[TESTER], MenuButtonWebApp)
        self.assertEqual((calls[TESTER].text, calls[TESTER].web_app.url), ("📚 DarsAI", "https://darsai.example/app"))

    def test_a_tester_who_never_started_the_bot_is_only_logged(self):
        self.set_menu.side_effect = BadRequest("Chat not found")
        with self.assertLogs("modules.ui.miniapp", "WARNING"):
            self.assertEqual(run_async(miniapp_ui.setup_menu_buttons(main.telegram_app.bot)), [])

    def test_off_without_an_https_address(self):
        for url, logs in (("", False), ("http://darsai.example/app", True)):
            with patch.object(config, "MINIAPP_URL", url):
                if logs:
                    with self.assertLogs("modules.ui.miniapp", "WARNING"):
                        run_async(miniapp_ui.setup_menu_buttons(main.telegram_app.bot))
                else:
                    run_async(miniapp_ui.setup_menu_buttons(main.telegram_app.bot))
        self.set_menu.assert_not_called()

    def test_app_command_for_testers(self):
        run(miniapp_ui.app_command, text_update("/app", user_id=TESTER))
        call = self.reply_text.call_args
        self.assertTrue(call.args[0].startswith("📚 The DarsAI app (test)"))
        buttons = [b for row in self.markup(call).inline_keyboard for b in row]
        self.assertEqual(buttons[0].web_app.url, "https://darsai.example/app")
        self.assertEqual(buttons[1].callback_data, f"d1:{TESTER}:app:x")
        self.set_menu.assert_called_once()

    def test_app_command_ignores_everyone_else(self):
        with self.assertLogs("modules.ui.miniapp", "INFO"):
            run(miniapp_ui.app_command, text_update("/app", user_id=STUDENT))
            run(miniapp_ui.app_command, text_update("/app", user_id=TESTER, chat_type="supergroup"))
        self.reply_text.assert_not_called()
        self.set_menu.assert_not_called()

    def test_app_command_when_the_app_is_off(self):
        with patch.object(config, "MINIAPP_URL", ""):
            run(miniapp_ui.app_command, text_update("/app", user_id=TESTER, language_code="fa"))
        self.assertEqual(self.reply_text.call_args.args[0], "📚 برنامه الان در دسترس نیست.")

    def test_it_did_not_open(self):
        run(router.callback_router, button_update(f"d1:{TESTER}:app:x", user_id=TESTER))
        self.assertEqual(self.answer.call_args.args[0], "🙏 Thanks, noted.")
        (row,) = miniapp._FALLBACK.values()
        self.assertFalse(row["opened"])

    def test_stats_line_leaves_admins_out(self):
        miniapp.record_open(TESTER, {"total_ms": 1000})
        miniapp.record_open(TESTER, {"total_ms": 2000})
        miniapp.record_open(STUDENT, {"total_ms": 600})
        miniapp.record_failure(STUDENT)
        miniapp.record_open(ADMIN, {"total_ms": 50})
        text = stats.format_stats(stats.collect_stats(utc_today(), admins={ADMIN}))
        self.assertIn("📱 Mini App test, today: 3 opens by 2 testers, median load 1,000 ms, ❌ didn't open 1\n"
                      "Last 7 days: 3 opens by 2 testers, median load 1,000 ms, ❌ didn't open 1", text)

    def test_delete_my_data_removes_the_measurements(self):
        miniapp.record_open(TESTER, {"total_ms": 1000})
        miniapp.record_failure(TESTER)
        miniapp.record_open(STUDENT, {"total_ms": 600})
        privacy.delete_student(TESTER)
        self.assertEqual([key[0] for key in miniapp._FALLBACK], [STUDENT])


def run_async(coroutine):
    import asyncio
    return asyncio.run(coroutine)
