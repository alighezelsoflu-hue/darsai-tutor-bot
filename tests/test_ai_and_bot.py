import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import main
from config import WEBHOOK_SECRET_TOKEN
from modules import ai
from modules.common import split_message
from modules.math.math import MATH_MEMORY_TOPICS


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
