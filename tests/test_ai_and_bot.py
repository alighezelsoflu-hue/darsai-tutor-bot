import asyncio
import re
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

import config
import main
from config import WEBHOOK_SECRET_TOKEN
from modules import ai
from modules.common import split_message
from modules.math.math import MATH_MEMORY_TOPICS


GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
ROOT = Path(__file__).resolve().parent.parent


class ProviderTests(unittest.TestCase):
    def setUp(self):
        ai._MEMORY_FALLBACK.clear()
        ai._USAGE_FALLBACK.clear()
        patcher = patch.object(ai, "provider_config", return_value=("groq", GROQ_URL, "llama-3.1-8b-instant", {}))
        patcher.start()
        self.addCleanup(patcher.stop)

    def respond(self, status, body):
        response = httpx.Response(status, json=body, request=httpx.Request("POST", GROQ_URL))
        patcher = patch.object(httpx.AsyncClient, "post", AsyncMock(return_value=response))
        patcher.start()
        self.addCleanup(patcher.stop)

    def answer(self, content):
        self.respond(200, {"choices": [{"message": {"content": content}}]})

    def test_default_model_is_the_same_everywhere(self):
        self.assertEqual(config.AI_MODEL, "qwen/qwen3.8-27b")
        example = re.search(r"^AI_MODEL=(.*)$", (ROOT / ".env.example").read_text(encoding="utf-8"), re.M)
        self.assertEqual(example.group(1).strip(), config.DEFAULT_AI_MODEL)
        self.assertIn(f"AI_MODEL={config.DEFAULT_AI_MODEL}", (ROOT / "README.md").read_text(encoding="utf-8"))
        self.assertIn(config.DEFAULT_AI_MODEL, (ROOT / "CLAUDE.md").read_text(encoding="utf-8"))

    def test_strip_reasoning(self):
        cases = {
            "<think>Let me see.</think>\n\nx = 6": "x = 6",
            "<THINK>a</THINK>One <think>b\nc</think>two": "One two",
            "the template opened it</think>Answer": "Answer",
            "Answer first <think>then the model kept thinking until max_tokens": "Answer first",
            "<think>only thinking, cut off": "",
            "No tags at all": "No tags at all",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(ai.strip_reasoning(text), expected)

    def test_reasoning_is_removed_before_sending_and_saving(self):
        self.answer("<think>The student wants...</think>\n\nSubtract 5 from both sides.")
        answer = asyncio.run(ai.ask_ai_with_memory(1, 2, "math", "2x + 5 = 17?", "system"))
        self.assertEqual(answer, "Subtract 5 from both sides.")
        self.assertEqual(ai.load_history(1, 2, "math")[-1]["content"], answer)

    def test_an_answer_that_is_only_reasoning_counts_as_failed(self):
        self.answer("<think>Hmm, let me think about this very carefully")
        with self.assertRaises(ai.AIProviderError):
            asyncio.run(ai.ask_ai_with_memory(1, 2, "math", "question", "system"))
        self.assertEqual(sum(ai._USAGE_FALLBACK.values()), 0, "the daily message is given back")
        self.assertEqual(ai.load_history(1, 2, "math"), [])

    def test_a_removed_model_is_logged_clearly(self):
        for code in ("model_not_found", "model_decommissioned"):
            with self.subTest(code=code):
                self.respond(404, {"error": {"message": "The model does not exist", "type": "invalid_request_error", "code": code}})
                with self.assertRaises(ai.AIModelUnavailable) as caught:
                    asyncio.run(ai.call_ai_provider([{"role": "user", "content": "hi"}]))
                with self.assertLogs("modules.ai", "ERROR") as logs:
                    student_text = ai.ai_error_message(caught.exception)
                self.assertIn("AI_MODEL 'llama-3.1-8b-instant' is no longer available from groq", logs.output[0])
                self.assertNotIn("AI_MODEL", student_text)

    def test_other_provider_errors_stay_general(self):
        self.respond(429, {"error": {"message": "Rate limit reached", "code": "rate_limit_exceeded"}})
        with self.assertRaises(ai.AIProviderError) as caught:
            asyncio.run(ai.call_ai_provider([{"role": "user", "content": "hi"}]))
        self.assertNotIsInstance(caught.exception, ai.AIModelUnavailable)


class AIMemoryTests(unittest.TestCase):
    def setUp(self):
        ai._MEMORY_FALLBACK.clear()
        ai._USAGE_FALLBACK.clear()

    def test_math_topics_keep_their_own_memory(self):
        for topic in ("linear_equations", "precalculus", "algebra", "calculus"):
            self.assertEqual(ai.normalize_topic(topic), topic)
        self.assertEqual(ai.normalize_topic("bad topic!"), "general")

    def test_clear_history_by_topic(self):
        ai.save_exchange(1, 2, "general", "hi", "hello")
        ai.save_exchange(1, 2, "quadratics", "q", "a")
        ai.save_exchange(1, 2, "linear_equations", "q", "a")
        self.assertEqual(ai.clear_history(1, 2, MATH_MEMORY_TOPICS), 4)
        self.assertEqual(len(ai.load_history(1, 2, "general")), 2)
        self.assertEqual(ai.clear_history(1, 2, all_topics=True), 2)

    def test_daily_limit(self):
        days = [ai.reserve_ai_message(7) for _ in range(3)]
        with self.assertRaises(ai.AILimitReached):
            ai.reserve_ai_message(7)
        ai.release_ai_message(7, days[0])
        ai.reserve_ai_message(7)
        ai.reserve_ai_message(8)  # other users are not affected

    def test_ask_counts_usage_and_saves_memory(self):
        with patch.object(ai, "call_ai_provider", AsyncMock(return_value="answer")):
            answer = asyncio.run(ai.ask_ai_with_memory(1, 2, "algebra", "question", "system"))
        self.assertEqual(answer, "answer")
        self.assertEqual(ai.load_history(1, 2, "algebra")[-1], {"role": "assistant", "content": "answer"})
        self.assertEqual(sum(ai._USAGE_FALLBACK.values()), 1)

    def test_failed_ask_gives_the_message_back(self):
        failing = AsyncMock(side_effect=ai.AIProviderError("down"))
        with patch.object(ai, "call_ai_provider", failing):
            with self.assertRaises(ai.AIProviderError):
                asyncio.run(ai.ask_ai_with_memory(1, 2, "general", "question", "system"))
        self.assertEqual(sum(ai._USAGE_FALLBACK.values()), 0)
        self.assertEqual(ai.load_history(1, 2, "general"), [])

    def test_error_messages_do_not_leak_details(self):
        text = ai.ai_error_message(ai.AIProviderError("GROQ_API_KEY is missing"))
        self.assertNotIn("GROQ", text)
        self.assertIn("limit", ai.ai_error_message(ai.AILimitReached()))


class SplitMessageTests(unittest.TestCase):
    def test_long_text_is_split_under_the_limit(self):
        text = "\n".join(f"line {i} " + "word " * 30 for i in range(200))
        chunks = split_message(text)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 4000 for chunk in chunks))
        self.assertEqual(" ".join(" ".join(chunks).split()), " ".join(text.split()))

    def test_short_and_empty_text(self):
        self.assertEqual(split_message("hello"), ["hello"])
        self.assertEqual(split_message("   "), [])


class WebhookTests(unittest.TestCase):
    UPDATE = {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "date": 0,
            "chat": {"id": 1, "type": "private"},
            "from": {"id": 1, "is_bot": False, "first_name": "Test"},
            "text": "/start",
        },
    }

    def setUp(self):
        self.client = TestClient(main.api)  # no context manager: startup (real Telegram calls) is skipped

    def tearDown(self):
        while not main.telegram_app.update_queue.empty():
            main.telegram_app.update_queue.get_nowait()

    def test_root_does_not_reveal_the_webhook_path(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(main.WEBHOOK_PATH, response.text)

    def test_rejects_requests_without_the_secret(self):
        for headers in ({}, {main.SECRET_HEADER: "wrong"}):
            response = self.client.post(f"/{main.WEBHOOK_PATH}", json=self.UPDATE, headers=headers)
            self.assertEqual(response.status_code, 403)
        self.assertTrue(main.telegram_app.update_queue.empty())

    def test_accepts_and_queues_telegram_updates(self):
        response = self.client.post(
            f"/{main.WEBHOOK_PATH}", json=self.UPDATE, headers={main.SECRET_HEADER: WEBHOOK_SECRET_TOKEN}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(main.telegram_app.update_queue.qsize(), 1)

    def test_rejects_invalid_json(self):
        response = self.client.post(
            f"/{main.WEBHOOK_PATH}", content=b"not json", headers={main.SECRET_HEADER: WEBHOOK_SECRET_TOKEN}
        )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
