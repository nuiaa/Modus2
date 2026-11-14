import unittest
from unittest.mock import Mock
import requests
from ai_client import AIClientError, fetch_models, probe_connection, send_chat


def response(data, status=200):
    return Mock(status_code=status, json=Mock(return_value=data))


class ClientTests(unittest.TestCase):
    turns = [{"role": "user", "content": "My ticker is SPY"},
             {"role": "assistant", "content": "Understood"},
             {"role": "user", "content": "Which ticker?"}]

    def test_gemini_history_and_parts(self):
        s = Mock()
        s.post.return_value = response({"candidates": [{"content": {"parts": [{"text": "hidden", "thought": True}, {"text": "SPY"}, {"text": "answer"}]}}]})
        ok, text, _ = send_chat("secret", "gemini", "a", self.turns, "system", s)
        self.assertTrue(ok)
        self.assertEqual(text, "SPY\nanswer")
        call = s.post.call_args
        self.assertNotIn("secret", call.args[0])
        self.assertEqual([t["role"] for t in call.kwargs["json"]["contents"]], ["user", "model", "user"])
        self.assertEqual(call.kwargs["headers"]["x-goog-api-key"], "secret")

    def test_openai_skips_reasoning_and_collects_text(self):
        s = Mock()
        s.post.return_value = response({"output": [{"type": "reasoning"}, {"type": "message", "content": [{"type": "output_text", "text": "SPY"}]}]})
        self.assertTrue(send_chat("secret", "openai", "a", self.turns, "system", s)[0])
        self.assertEqual(s.post.call_args.kwargs["json"]["input"], self.turns)

    def test_anthropic_contract_and_limit(self):
        s = Mock()
        s.post.return_value = response({"content": [{"type": "text", "text": "SPY"}], "stop_reason": "max_tokens"})
        ok, text, _ = send_chat("secret", "anthropic", "a", self.turns, "system", s)
        self.assertTrue(ok)
        self.assertIn("tamamlanamadı", text)
        self.assertEqual(s.post.call_args.kwargs["headers"]["anthropic-version"], "2026-10-21")
        self.assertEqual(s.post.call_args.kwargs["headers"]["x-api-key"], "secret")
        self.assertNotIn("Authorization", s.post.call_args.kwargs["headers"])
        self.assertEqual(s.post.call_args.kwargs["json"]["messages"], self.turns)

    def test_empty_openrouter_is_not_success(self):
        s = Mock()
        s.post.return_value = response({"choices": [{"message": {"content": None}}]})
        self.assertFalse(send_chat("secret", "openrouter", "a", self.turns, "system", s)[0])

    def test_errors_never_expose_provider_body_or_exception(self):
        s = Mock()
        s.post.return_value = response({"error": {"message": "secret"}}, 401)
        result = send_chat("secret", "openai", "a", self.turns, "system", s)
        self.assertFalse(result[0])
        self.assertNotIn("secret", result[1])
        s.post.side_effect = requests.ConnectionError("secret")
        self.assertNotIn("secret", send_chat("secret", "openai", "a", self.turns, "system", s)[1])

    def test_gemini_paginated_discovery(self):
        s = Mock()
        s.get.side_effect = [response({"models": [{"name": "models/gemini-3-pro", "supportedGenerationMethods": ["generateContent"]}], "nextPageToken": "next"}), response({"models": [{"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]}, {"name": "models/embed", "supportedGenerationMethods": ["embedContent"]}]})]
        self.assertEqual([m["id"] for m in fetch_models("secret", "gemini", s)], ["gemini-3-pro", "gemini-2.5-flash"])
        self.assertEqual(s.get.call_args.kwargs["params"]["pageToken"], "next")

    def test_failed_discovery_has_no_invented_fallback(self):
        s = Mock()
        s.get.return_value = response({}, 403)
        with self.assertRaises(AIClientError):
            fetch_models("secret", "gemini", s)

    def test_gemini_zero_quota_is_not_reported_as_waiting(self):
        s = Mock()
        s.post.return_value = response({"error": {"message": "key=secret", "details": [
            {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [
                {"quotaId": "GenerateRequestsPerDay", "quotaValue": "0"}]}]}}, 429)
        ok, message, _ = send_chat("secret", "gemini", "gemini-3-pro", self.turns, "system", s)
        self.assertFalse(ok)
        self.assertIn("kota 0", message)
        self.assertNotIn("secret", message)

    def test_gemini_invalid_key_400_is_reported_as_bad_key(self):
        s = Mock()
        s.post.return_value = response({"error": {"code": 400, "message": "key=secret", "details": [
            {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "API_KEY_INVALID"}]}}, 400)
        ok, message, _ = send_chat("secret", "gemini", "gemini-3-pro", self.turns, "system", s)
        self.assertFalse(ok)
        self.assertEqual(message, "HTTP 401: API anahtarı geçersiz.")
        # probe_connection stops on 401 instead of trying more models.

    def test_gemini_probe_tries_flash_after_pro_quota_failure(self):
        calls = []
        def fake_sender(key, provider, model, messages, system):
            calls.append(model)
            return (False, "HTTP 429: Proje/model kotası sınırlandı.", model) if "pro" in model else (True, "Merhaba", model)
        models = [{"id": "gemini-3-pro"}, {"id": "gemini-3-flash"}, {"id": "gemini-3-flash-lite"}]
        ok, _, _, model = probe_connection("secret", "gemini", models, sender=fake_sender)
        self.assertTrue(ok)
        self.assertEqual(model, "gemini-3-flash")
        self.assertEqual(calls, ["gemini-3-pro", "gemini-3-flash"])

    def test_explicit_provider_rejects_unknown(self):
        s = Mock()
        self.assertFalse(send_chat("secret", "unknown", "a", self.turns, "system", s)[0])
        s.post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
