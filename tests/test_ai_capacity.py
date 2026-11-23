"""AI capacity (Phase 1 step 8): the history budget, the shared HTTP client, call slots, "too many requests", the
question-length cap, the backup provider, the deadline and "typing…". The provider is an httpx.MockTransport:
nothing leaves the machine."""

import asyncio
import inspect
import logging
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from telegram.error import TimedOut

import config
import main
import run_local
from modules import ai
from modules.i18n import t
from modules.ui import privacy as privacy_ui
from modules.ui import tools

from tests.test_ui import STUDENT, TelegramMocks, button_update, run, text_update

MAIN_URL = "https://main.test/v1/chat/completions"
BACKUP_URL = "https://backup.test/v1/chat/completions"
QUESTION = [{"role": "user", "content": "What is 2 + 2?"}]


def fake_provider_config(provider=None, model=None):
    """The main provider (no arguments) at main.test, any other at backup.test. No keys needed."""
    if provider is None:
        return "groq", MAIN_URL, model or "main-model", {}
    return provider, BACKUP_URL, model, {}


def ok(content="An answer.", prompt_tokens=42):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": prompt_tokens}})


def refused(status, headers=None, code=""):
    return httpx.Response(status, headers=headers or {}, json={"error": {"message": "refused", "code": code}})


def hangs(seconds=5.0):
    async def reply(request):
        await asyncio.sleep(seconds)
        return ok("Too late.")
    return reply


class _Records(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)


def screen_for(lang):
    return SimpleNamespace(lang=lang, private=True, t=lambda key, **params: t(lang, key, **params))


class CapacityTestCase(unittest.TestCase):
    """Fake providers behind the shared client, a clean state, and everything modules.ai logs."""

    def setUp(self):
        ai._MEMORY_FALLBACK.clear()
        ai._USAGE_FALLBACK.clear()
        ai.busy_events.reset()
        self.replies = {"main.test": [], "backup.test": []}
        self.calls = {"main.test": 0, "backup.test": 0}
        for patcher in (
            patch.object(ai, "provider_config", side_effect=fake_provider_config),
            patch.multiple(config, AI_FALLBACK_PROVIDER="", AI_FALLBACK_MODEL="", AI_MAX_CONCURRENT_CALLS=4,
                           AI_QUEUE_WAIT_SECONDS=20, AI_DEADLINE_SECONDS=45, AI_RETRY_MAX_WAIT_SECONDS=5,
                           AI_HISTORY_TOKEN_BUDGET=1500, AI_MAX_QUESTION_CHARS=1500, AI_BUSY_ALERT_THRESHOLD=10,
                           AI_BUSY_ALERT_WINDOW_MINUTES=10),
            patch.object(ai.logger, "propagate", False),  # keep the console quiet
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.log = _Records()
        ai.logger.addHandler(self.log)
        self.addCleanup(ai.logger.removeHandler, self.log)
        self.addCleanup(ai.logger.setLevel, ai.logger.level)
        ai.logger.setLevel(logging.DEBUG)

    async def _handler(self, request):
        host = request.url.host
        self.calls[host] += 1
        reply = self.replies[host].pop(0)
        return reply if isinstance(reply, httpx.Response) else await reply(request)

    def run_with_client(self, make_coroutine):
        """make_coroutine() inside one event loop, with the shared client open on the fake providers."""
        async def scenario():
            await ai.open_http_client(transport=httpx.MockTransport(self._handler))
            try:
                return await make_coroutine()
            finally:
                await ai.close_http_client()
        return asyncio.run(scenario())

    def ask(self, prompt="What is 2 + 2?", user_id=2, **kwargs):
        return self.run_with_client(lambda: ai.ask_ai_with_memory(1, user_id, "math", prompt, "system", **kwargs))

    def logged(self, level):
        return [record.getMessage() for record in self.log.records if record.levelno == level]

    def used(self):
        return sum(ai._USAGE_FALLBACK.values())


# ------------------------------------------------------------
# 1. The history budget
# ------------------------------------------------------------

def pairs(count, question, answer):
    history = []
    for number in range(count):
        history += [{"role": "user", "content": f"{question}"}, {"role": "assistant", "content": f"{answer}"}]
    return history


class HistoryBudgetTests(unittest.TestCase):
    def setUp(self):
        ai._MEMORY_FALLBACK.clear()
        ai._USAGE_FALLBACK.clear()

    def test_the_estimate_errs_on_the_safe_side(self):
        self.assertEqual(ai.estimate_tokens(""), 4, "each message costs its place in the chat format")
        self.assertEqual(ai.estimate_tokens("abc"), 5, "English letters: a third each")
        self.assertEqual(ai.estimate_tokens("سلام"), 6, "Persian letters: half each")
        self.assertEqual(ai.estimate_tokens("2025"), 8, "digits: one each")
        self.assertEqual(ai.estimate_tokens("x² − 5"), 8, "math symbols: one each")
        self.assertEqual(ai.estimate_tokens("می‌شه"), 7, "the half-space: one")
        self.assertEqual(ai.estimate_tokens("۱۲"), 6, "Persian digits: one each")
        self.assertGreater(ai.estimate_tokens("ب" * 300), ai.estimate_tokens("a" * 300), "Persian costs more per character")

    def test_the_newest_whole_pairs_that_fit(self):
        english = pairs(8, "a" * 60, "b" * 600)  # 24 + 204 = 228 tokens a pair
        self.assertEqual(ai.fit_history(english, 500), english[-4:], "two pairs fit 500")
        persian = pairs(8, "ب" * 60, "پ" * 600)  # 34 + 304 = 338 tokens a pair
        self.assertEqual(ai.fit_history(persian, 500), persian[-2:], "the same length in Persian: one pair")
        self.assertEqual(ai.fit_history(english, 100_000), english, "a big budget keeps everything it was given")

    def test_a_pair_that_does_not_fit_ends_the_history(self):
        history = pairs(3, "short", "short") + pairs(1, "a" * 60, "b" * 3000)
        self.assertEqual(ai.fit_history(history, 500), [], "no gap: older pairs aren't sent after a newer one is left out")

    def test_half_pairs_and_a_zero_budget(self):
        history = [{"role": "assistant", "content": "orphan"}] + pairs(1, "q", "a") + [{"role": "user", "content": "unanswered"}]
        self.assertEqual(ai.fit_history(history, 1500), pairs(1, "q", "a"))
        self.assertEqual(ai.fit_history(pairs(2, "q", "a"), 0), [])

    def test_the_tutor_gets_only_what_fits(self):
        for number in range(10):
            ai.save_exchange(1, 2, "math", f"question {number} " + "a" * 60, "b" * 600)
        provider = AsyncMock(return_value="An answer.")
        with patch.object(ai, "call_ai_provider", provider), patch.object(config, "AI_HISTORY_TOKEN_BUDGET", 500):
            asyncio.run(ai.ask_ai_with_memory(1, 2, "math", "new question", "system"))
        messages = provider.call_args.args[0]
        self.assertEqual([m["role"] for m in messages], ["system", "user", "assistant", "user", "assistant", "user"])
        self.assertTrue(messages[1]["content"].startswith("question 8 "), "the newest two pairs, oldest first")
        with patch.object(ai, "call_ai_provider", provider), patch.object(config, "AI_HISTORY_TOKEN_BUDGET", 100_000):
            asyncio.run(ai.ask_ai_with_memory(1, 2, "math", "another", "system"))
        self.assertEqual(len(provider.call_args.args[0]), 1 + config.AI_MAX_HISTORY_MESSAGES + 1,
                         "AI_MAX_HISTORY_MESSAGES still caps it")


# ------------------------------------------------------------
# 2. One shared HTTP client
# ------------------------------------------------------------

class SharedClientTests(CapacityTestCase):
    def test_one_client_for_every_call_until_it_is_closed(self):
        self.replies["main.test"] = [ok("one"), ok("two")]

        async def scenario():
            await ai.open_http_client(transport=httpx.MockTransport(self._handler))
            client = ai._http_client
            await ai.open_http_client()  # a second open keeps the same pool
            self.assertIs(ai._http_client, client)
            answers = [await ai.call_ai_provider(QUESTION), await ai.call_ai_provider(QUESTION)]
            self.assertIs(ai._http_client, client)
            await ai.close_http_client()
            return client, answers

        client, answers = asyncio.run(scenario())
        self.assertEqual(answers, ["one", "two"])
        self.assertEqual(self.calls["main.test"], 2, "both went through the shared client's transport")
        self.assertIsNone(ai._http_client)
        self.assertTrue(client.is_closed)
        self.assertEqual((client.timeout.connect, client.timeout.read), (ai.CONNECT_TIMEOUT_SECONDS, ai.ANSWER_TIMEOUT_SECONDS))

    def test_startup_opens_it_and_shutdown_closes_it(self):
        for source in (inspect.getsource(main.lifespan), inspect.getsource(run_local.main)):
            self.assertIn("await open_http_client()", source)
            self.assertIn("await close_http_client()", source)

    def test_the_provider_count_is_logged_next_to_the_estimate(self):
        self.replies["main.test"] = [ok(prompt_tokens=17)]
        self.run_with_client(lambda: ai.call_ai_provider(QUESTION))
        self.assertIn(f"AI answer from groq (main-model): 17 prompt tokens counted by the provider, "
                      f"{ai.estimate_tokens(QUESTION[0]['content'])} estimated.", self.logged(logging.INFO))


# ------------------------------------------------------------
# 3. Call slots
# ------------------------------------------------------------

class CallSlotTests(CapacityTestCase):
    def setUp(self):
        super().setUp()
        self.running = self.most = 0

    async def slow_answer(self, *args, **kwargs):
        self.running += 1
        self.most = max(self.most, self.running)
        await asyncio.sleep(self.seconds)
        self.running -= 1
        return "An answer."

    def ask_many(self, count):
        async def scenario():
            return await asyncio.gather(
                *(ai.ask_ai_with_memory(1, 100 + n, "math", "question", "system") for n in range(count)),
                return_exceptions=True,
            )
        with patch.object(ai, "call_ai_provider", side_effect=self.slow_answer):
            return asyncio.run(scenario())

    def test_at_most_the_setting_at_once_and_the_rest_wait(self):
        self.seconds = 0.05
        with patch.object(config, "AI_MAX_CONCURRENT_CALLS", 2):
            results = self.ask_many(5)
        self.assertEqual(results, ["An answer."] * 5)
        self.assertEqual(self.most, 2)

    def test_a_question_that_finds_no_free_slot_hears_the_tutor_is_busy(self):
        self.seconds = 1.0
        with patch.multiple(config, AI_MAX_CONCURRENT_CALLS=1, AI_QUEUE_WAIT_SECONDS=0.2):
            started = time.monotonic()
            results = self.ask_many(2)
        self.assertEqual(results[0], "An answer.")
        self.assertIsInstance(results[1], ai.AIBusy)
        self.assertEqual(self.used(), 1, "the busy question's daily message was given back")
        self.assertIn("AI capacity: all 1 AI call slots stayed taken for 0 s (1 in the last 10 min)", self.logged(logging.WARNING))
        self.assertEqual(self.logged(logging.ERROR), [])
        self.assertLess(time.monotonic() - started, 2.0)


# ------------------------------------------------------------
# 4. "Too many requests"
# ------------------------------------------------------------

class RateLimitTests(CapacityTestCase):
    def test_a_short_wait_is_retried_once(self):
        self.replies["main.test"] = [refused(429, {"retry-after": "0.05"}), ok("After the wait.")]
        self.assertEqual(self.ask(), "After the wait.")
        self.assertEqual(self.calls["main.test"], 2)
        self.assertEqual(self.logged(logging.WARNING), ["AI capacity: groq rate limit (429, retry in 0.05 s) (1 in the last 10 min)"])
        self.assertEqual(self.logged(logging.ERROR), [])

    def test_groq_reset_headers_say_how_long_to_wait(self):
        tokens_soon = {"x-ratelimit-remaining-tokens": "0", "x-ratelimit-reset-tokens": "0.05s",
                       "x-ratelimit-remaining-requests": "250", "x-ratelimit-reset-requests": "2m59.56s"}
        self.replies["main.test"] = [refused(429, tokens_soon), ok("After the wait.")]
        self.assertEqual(self.ask(), "After the wait.")
        requests_later = dict(tokens_soon, **{"x-ratelimit-remaining-requests": "0"})
        self.replies["main.test"] = [refused(429, requests_later)]
        with self.assertRaises(ai.AIBusy):
            self.ask()
        self.assertEqual(self.calls["main.test"], 3, "a wait of 3 minutes isn't retried")

    def test_a_long_wait_tells_the_student_the_tutor_is_busy_and_gives_the_message_back(self):
        self.replies["main.test"] = [refused(429, {"retry-after": "30"})]
        with self.assertRaises(ai.AIBusy) as caught:
            self.ask()
        self.assertEqual(self.calls["main.test"], 1)
        self.assertEqual(self.used(), 0)
        self.assertEqual(tools.ai_error_text(screen_for("en"), caught.exception), t("en", "ai.busy"))
        self.assertEqual(tools.ai_error_text(screen_for("fa"), caught.exception), t("fa", "ai.busy"))
        self.assertIn("very busy", ai.ai_error_message(caught.exception))
        self.assertEqual(self.logged(logging.ERROR), [], "a 429 is a WARNING, never an alert on its own")
        self.assertIn("Told a student the tutor is busy: groq rate limit (429, retry in 30 s)", self.logged(logging.INFO))

    def test_a_second_refusal_is_not_retried(self):
        self.replies["main.test"] = [refused(429, {"retry-after": "0.05"}), refused(429, {"retry-after": "0.05"})]
        with self.assertRaises(ai.AIBusy):
            self.ask()
        self.assertEqual(self.calls["main.test"], 2)
        self.assertEqual(len(self.logged(logging.WARNING)), 2)

    def test_many_refusals_in_a_short_time_are_one_alert(self):
        with patch.object(config, "AI_BUSY_ALERT_THRESHOLD", 3):
            for number in range(5):
                self.replies["main.test"] = [refused(429, {"retry-after": "60"})]
                with self.assertRaises(ai.AIBusy):
                    self.ask(user_id=100 + number)
        errors = self.logged(logging.ERROR)
        self.assertEqual(len(errors), 1)
        self.assertTrue(errors[0].startswith("AI capacity: 3 refusals in the last 10 min (last: groq rate limit"))

    def test_wait_durations(self):
        cases = {"7": 7.0, "0.5": 0.5, "7.66s": 7.66, "2m59.56s": 179.56, "1h2m": 3720.0, "300ms": 0.3,
                 "": None, "soon": None, "Wed, 21 Oct 2026 07:28:00 GMT": None, "5x": None}
        for value, expected in cases.items():
            with self.subTest(value=value):
                result = ai._seconds(value)
                if expected is None:
                    self.assertIsNone(result)
                else:
                    self.assertAlmostEqual(result, expected)


# ------------------------------------------------------------
# 5. The question-length cap
# ------------------------------------------------------------

class QuestionLengthTests(CapacityTestCase):
    def test_a_long_question_is_refused_before_it_counts(self):
        provider = AsyncMock(return_value="An answer.")
        with patch.object(ai, "call_ai_provider", provider):
            with self.assertRaises(ai.AIQuestionTooLong) as caught:
                asyncio.run(ai.ask_ai_with_memory(1, 2, "math", "x" * 1501, "system"))
            provider.assert_not_called()
            self.assertEqual(self.used(), 0)
            self.assertEqual(asyncio.run(ai.ask_ai_with_memory(1, 2, "math", "x" * 1500, "system")), "An answer.")
        error = caught.exception
        self.assertEqual(tools.ai_error_text(screen_for("en"), error),
                         "✂️ That question is too long (1501 characters). Please shorten it to at most 1500 characters.")
        self.assertIn("۱۵۰۱", tools.ai_error_text(screen_for("fa"), error))
        self.assertIn("۱۵۰۰", tools.ai_error_text(screen_for("fa"), error))
        self.assertIn("too long (1501 characters)", ai.ai_error_message(error))
        self.assertEqual(self.log.records, [], "the student's input, not a failure: nothing logged")


class QuestionLengthButtonTests(TelegramMocks):
    def test_the_tutor_screen_asks_for_a_shorter_question(self):
        provider = AsyncMock(return_value="An answer.")
        with patch.object(ai, "call_ai_provider", provider):
            from modules.ui import router, typed
            run(router.callback_router, button_update(f"d1:{STUDENT}:tutor"))
            run(typed.private_text, text_update("why?" * 500))
        provider.assert_not_called()
        self.assertTrue(self.reply_text.call_args.args[0].startswith("✂️ That question is too long (2000 characters)."))
        self.assertEqual(sum(ai._USAGE_FALLBACK.values()), 0)


# ------------------------------------------------------------
# 6. The backup provider, and 7. the deadline
# ------------------------------------------------------------

class BackupTests(CapacityTestCase):
    def setUp(self):
        super().setUp()
        patcher = patch.multiple(config, AI_FALLBACK_PROVIDER="openrouter", AI_FALLBACK_MODEL="backup-model")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_off_when_not_set(self):
        self.replies["main.test"] = [refused(503)]
        with patch.object(config, "AI_FALLBACK_PROVIDER", ""):
            with self.assertRaises(ai.AIProviderError):
                self.ask()
        self.assertEqual(self.calls["backup.test"], 0)
        self.assertEqual(self.used(), 0)

    def test_the_backup_answers_after_a_refusal_an_outage_or_a_bad_key(self):
        cases = {
            "429": (refused(429, {"retry-after": "30"}), logging.WARNING),
            "503": (refused(503), logging.WARNING),
            "401": (refused(401), logging.ERROR),  # a broken key still needs fixing: an alert
            "gone": (refused(404, code="model_decommissioned"), logging.ERROR),
        }
        for number, (name, (reply, level)) in enumerate(cases.items()):
            with self.subTest(main=name):
                self.log.records.clear()
                self.replies["main.test"] = [reply]
                self.replies["backup.test"] = [ok("From the backup.")]
                self.assertEqual(self.ask(user_id=100 + number), "From the backup.")
                self.assertTrue(any("so the backup (openrouter) answered" in message for message in self.logged(level)))
        self.assertEqual(self.calls, {"main.test": 4, "backup.test": 4})

    def test_the_backup_answers_after_a_timeout_within_the_deadline(self):
        self.replies["main.test"] = [hangs()]
        self.replies["backup.test"] = [ok("From the backup.")]
        with patch.multiple(ai, BACKUP_RESERVE_SECONDS=0.4, MIN_CALL_SECONDS=0.05):
            started = time.monotonic()
            answer = self.run_with_client(
                lambda: ai.call_ai_provider(QUESTION, deadline=asyncio.get_running_loop().time() + 1.0))
        self.assertEqual(answer, "From the backup.")
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertTrue(any("didn't answer within" in message for message in self.logged(logging.WARNING)))

    def test_no_backup_after_a_bad_request(self):
        self.replies["main.test"] = [refused(400)]
        with self.assertRaises(ai.AIProviderError) as caught:
            self.ask()
        self.assertNotIsInstance(caught.exception, ai.AIBusy)
        self.assertEqual(self.calls["backup.test"], 0, "the backup would refuse the same request")

    def test_when_both_fail_the_student_hears_about_the_main_one(self):
        self.replies["main.test"] = [refused(429, {"retry-after": "30"})]
        self.replies["backup.test"] = [refused(503)]
        with self.assertRaises(ai.AIBusy):
            self.ask()
        self.assertEqual(self.used(), 0)
        self.assertTrue(any(m.startswith("The backup AI (openrouter) failed too: AI provider error 503")
                            for m in self.logged(logging.WARNING)))
        self.assertEqual(self.logged(logging.ERROR), [])

    def test_a_broken_backup_setting_is_an_alert(self):
        self.replies["main.test"] = [refused(503)]
        self.replies["backup.test"] = [refused(404, code="model_not_found")]
        with self.assertRaises(ai.AIProviderError):
            self.ask()
        self.assertTrue(any("AI_FALLBACK_MODEL 'backup-model' is no longer available from openrouter" in m
                            for m in self.logged(logging.ERROR)))

    def test_the_deadline_covers_the_whole_question(self):
        self.replies["main.test"] = [hangs()]
        with patch.object(config, "AI_FALLBACK_PROVIDER", ""), patch.object(config, "AI_DEADLINE_SECONDS", 0.5):
            started = time.monotonic()
            with self.assertRaises(ai.AIProviderError) as caught:
                self.ask()
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertIn("didn't answer within", str(caught.exception))
        self.assertEqual(self.used(), 0)

    def test_the_setting_check(self):
        keys = {"groq": "k1", "openrouter": "k2", "openai": ""}
        main_ai = ("groq", "qwen/qwen3.8-27b")
        self.assertEqual(config.fallback_problem("openrouter", "some/model", keys, main_ai), "")
        self.assertEqual(config.fallback_problem("groq", "another-model", keys, main_ai), "", "Groq with another model")
        self.assertIn("isn't one of", config.fallback_problem("claude", "x", keys, main_ai))
        self.assertEqual(config.fallback_problem("openrouter", "", keys, main_ai), "has no AI_FALLBACK_MODEL")
        self.assertEqual(config.fallback_problem("openai", "gpt", keys, main_ai), "has no OPENAI_API_KEY")
        self.assertIn("same provider and model", config.fallback_problem("groq", "qwen/qwen3.8-27b", keys, main_ai))


# ------------------------------------------------------------
# "typing…" while the student waits
# ------------------------------------------------------------

class TypingTests(CapacityTestCase):
    def test_typing_is_repeated_until_the_answer_is_there(self):
        typing = AsyncMock()

        async def slow_answer(*args, **kwargs):
            await asyncio.sleep(0.23)
            return "An answer."

        async def scenario():
            answer = await ai.ask_ai_with_memory(1, 2, "math", "question", "system", typing=typing)
            sent = typing.call_count
            await asyncio.sleep(0.15)
            return answer, sent

        with patch.object(ai, "TYPING_REPEAT_SECONDS", 0.05), patch.object(ai, "call_ai_provider", side_effect=slow_answer):
            answer, sent = asyncio.run(scenario())
        self.assertEqual(answer, "An answer.")
        self.assertGreaterEqual(sent, 4)
        self.assertEqual(typing.call_count, sent, "stopped with the answer")

    def test_a_failing_typing_call_changes_nothing(self):
        typing = AsyncMock(side_effect=TimedOut())
        with patch.object(ai, "call_ai_provider", AsyncMock(return_value="An answer.")):
            self.assertEqual(asyncio.run(ai.ask_ai_with_memory(1, 2, "math", "q", "system", typing=typing)), "An answer.")


# ------------------------------------------------------------
# The privacy policy names a backup of another company
# ------------------------------------------------------------

class BackupInPolicyTests(unittest.TestCase):
    def test_named_only_when_it_is_another_company(self):
        for provider, model, named in (("openrouter", "some/model", True), ("groq", "another-model", False), ("", "", False)):
            with patch.multiple(config, AI_PROVIDER="groq", AI_FALLBACK_PROVIDER=provider, AI_FALLBACK_MODEL=model):
                for lang in ("en", "fa"):
                    with self.subTest(backup=provider, lang=lang):
                        text = privacy_ui.policy_text(screen_for(lang))
                        line = t(lang, "privacy.backup_ai", ai="Groq", backup="OpenRouter")
                        self.assertEqual(line in text, named)
                        self.assertEqual("OpenRouter" in text, named)


if __name__ == "__main__":
    unittest.main()
