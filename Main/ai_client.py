"""Provider adapters; no UI dependencies or mutable application state."""
import requests


class AIClientError(RuntimeError):
    pass


PROVIDERS = {"gemini": "Gemini", "openrouter": "OpenRouter", "openai": "OpenAI", "anthropic": "Claude"}


def _headers(key, provider):
    if provider not in PROVIDERS:
        raise AIClientError("Desteklenmeyen API sağlayıcısı.")
    key = str(key or "").strip().strip("\"'").strip()
    if not key:
        raise AIClientError("API anahtarı gerekli.")
    headers = {"Content-Type": "application/json"}
    if provider == "gemini":
        headers["x-goog-api-key"] = key
    elif provider == "anthropic":
        # API keys go in x-api-key; Bearer is only for OAuth access tokens.
        headers["x-api-key"] = key
    else:
        headers["Authorization"] = "Bearer " + key
    if provider == "anthropic":
        headers["anthropic-version"] = "2026-10-21"
    return headers


def _request(session, method, url, headers, **kwargs):
    try:
        response = getattr(session, method)(url, headers=headers, timeout=(10, 90), **kwargs)
    except requests.Timeout:
        raise AIClientError("İstek zaman aşımına uğradı. Tekrar deneyin.") from None
    except requests.RequestException:
        raise AIClientError("API bağlantısı kurulamadı. Ağ bağlantısını kontrol edin.") from None
    status = response.status_code
    if not 200 <= status < 300:
        errors = {400: "İstek veya model parametreleri desteklenmiyor.", 401: "API anahtarı geçersiz.",
                  402: "API bakiyesi yetersiz.", 403: "Bu anahtarın modele erişim izni yok.",
                  404: "Model veya API uç noktası bulunamadı. Model listesini yenileyin.",
                  429: "Proje veya model kotası sınırlandı."}
        message = errors.get(status, "API hizmeti isteği tamamlayamadı.")
        if status == 429 and "generativelanguage.googleapis.com" in url:
            message = _gemini_quota_hint(response)
        if status == 400 and "generativelanguage.googleapis.com" in url and _gemini_key_invalid(response):
            status, message = 401, errors[401]  # Google reports a bad key as 400.
        raise AIClientError(f"HTTP {status}: " + message)
    try:
        data = response.json()
    except (ValueError, TypeError):
        raise AIClientError("API geçerli JSON döndürmedi.") from None
    if not isinstance(data, dict) or data.get("error"):
        raise AIClientError("API hata yanıtı döndürdü.")
    return data


def _gemini_key_invalid(response):
    try:
        details = (response.json().get("error") or {}).get("details") or []
    except (ValueError, TypeError, AttributeError):
        return False
    return any(isinstance(d, dict) and d.get("reason") == "API_KEY_INVALID" for d in details)


def _gemini_quota_hint(response):
    """Summarize only documented quota fields; never echo provider error text or keys."""
    try:
        error = response.json().get("error") or {}
        details = error.get("details") or []
    except (ValueError, TypeError, AttributeError):
        details = []
    quotas, retry = [], None
    for detail in details:
        if not isinstance(detail, dict):
            continue
        kind = detail.get("@type", "")
        if kind.endswith("QuotaFailure"):
            quotas.extend(v for v in detail.get("violations", []) if isinstance(v, dict))
        elif kind.endswith("RetryInfo"):
            retry = detail.get("retryDelay")
    if any(str(v.get("quotaValue", "")).strip() == "0" for v in quotas):
        return "Bu proje/model için bildirilen kota 0. AI Studio'da proje, model ve faturalandırma durumunu kontrol edin."
    quota_ids = " ".join(str(v.get("quotaId", "")) for v in quotas).lower()
    if "perday" in quota_ids:
        return "Günlük proje/model kotası dolmuş. AI Studio kota ekranını kontrol edin."
    if "perminute" in quota_ids:
        return "Dakikalık proje/model kotası dolmuş. Kısa süre sonra tekrar deneyin."
    if isinstance(retry, str) and retry.endswith("s") and len(retry) < 12:
        return f"Geçici kota sınırı. Google tekrar deneme süresi: {retry}."
    return "Proje/model kotası sınırlandı. AI Studio kota ekranında bu anahtarın projesini ve modeli kontrol edin."


def fetch_models(api_key, provider, session=None):
    """Return live model metadata, or raise AIClientError. Never invent models."""
    headers = _headers(api_key, provider)
    own_session = session is None
    session = session or requests.Session()
    urls = {"gemini": "https://generativelanguage.googleapis.com/v1beta/models",
            "openrouter": "https://openrouter.ai/api/v1/models",
            "openai": "https://api.openai.com/v1/models",
            "anthropic": "https://api.anthropic.com/v1/models"}
    result, seen, cursors = [], set(), set()
    params = {"pageSize": 1000} if provider == "gemini" else {"limit": 100} if provider == "anthropic" else {}
    try:
        for _ in range(100):
            data = _request(session, "get", urls[provider], headers, params=params)
            models = data.get("models" if provider == "gemini" else "data", [])
            if not isinstance(models, list):
                raise AIClientError("API model listesi biçimi geçersiz.")
            for item in models:
                if not isinstance(item, dict):
                    continue
                model_id = item.get("name", "").removeprefix("models/") if provider == "gemini" else item.get("id", "")
                if not model_id or model_id in seen:
                    continue
                if provider == "gemini" and "generateContent" not in item.get("supportedGenerationMethods", []):
                    continue
                if provider == "gemini" and (not model_id.startswith("gemini-") or
                                             any(x in model_id.lower() for x in ("image", "audio", "tts", "embedding", "live"))):
                    continue
                if provider == "openrouter":
                    architecture = item.get("architecture") or {}
                    if "text" not in architecture.get("output_modalities", ["text"]):
                        continue
                if provider == "openai":
                    # The model-list endpoint lacks endpoint capability metadata.
                    # Exclude known non-chat families, but preserve future text IDs.
                    lower = model_id.lower()
                    if any(x in lower for x in ("embedding", "whisper", "tts", "image", "dall-e", "realtime", "transcribe", "audio", "moderation", "sora")):
                        continue
                    if not (lower.startswith(("gpt-", "chatgpt-")) or
                            (lower.startswith("o") and len(lower) > 1 and lower[1].isdigit())):
                        continue
                if provider == "anthropic" and not model_id.startswith("claude-"):
                    continue
                seen.add(model_id)
                name = item.get("displayName") or item.get("display_name") or item.get("name") or model_id
                result.append({"id": model_id, "name": name, "desc": "API kataloğu; kullanım erişim ve kotaya bağlıdır."})
            cursor = data.get("nextPageToken") if provider == "gemini" else data.get("last_id") if provider == "anthropic" and data.get("has_more") else None
            if not cursor:
                break
            if cursor in cursors:
                raise AIClientError("API model sayfalaması tekrarlanıyor.")
            cursors.add(cursor)
            params["pageToken" if provider == "gemini" else "after_id"] = cursor
        else:
            raise AIClientError("API model sayfalama sınırı aşıldı.")
        if not result:
            raise AIClientError("Uyumlu metin modeli bulunamadı.")
        if provider == "gemini":
            result.sort(key=lambda m: ("pro" in m["id"], "flash-lite" not in m["id"], m["id"]), reverse=True)
        return result
    finally:
        if own_session:
            session.close()


def probe_connection(api_key, provider, models, saved_model=None, sender=None):
    """Try distinct Gemini model families when one model has no generation quota."""
    sender = sender or send_chat
    ids = [m.get("id") for m in models if isinstance(m, dict) and m.get("id")]
    candidates = [saved_model] if saved_model in ids else []
    if provider == "gemini":
        for family in ("pro", "flash", "flash-lite"):
            match = next((model for model in ids if model not in candidates and
                          ("flash-lite" in model if family == "flash-lite" else
                           "flash" in model and "lite" not in model if family == "flash" else
                           "pro" in model)), None)
            if match:
                candidates.append(match)
    candidates.extend(model for model in ids if model not in candidates)
    last_error, last_tag, last_model = "Uygun modelle bağlantı kurulamadı.", provider, ""
    quota_errors, attempted = [], []
    for model in candidates[:4 if provider == "gemini" else 3]:
        attempted.append(model)
        ok, reply, tag = sender(api_key, provider, model,
                                 [{"role": "user", "content": "Merhaba. Tek sözcükle yanıt ver."}],
                                 "Türkçe kısa yanıt ver.")
        if ok:
            return True, reply, tag, model
        last_error, last_tag, last_model = reply, tag, model
        if reply.startswith("HTTP 429"):
            quota_errors.append(reply)
            if provider == "gemini":
                continue
        if reply.startswith(("HTTP 401", "HTTP 402", "API bağlantısı", "İstek zaman")):
            break
    if quota_errors and len(quota_errors) == len(attempted):
        last_error = ("Denenen Gemini modelleri kotaya takıldı: " + ", ".join(attempted)
                      + ". " + quota_errors[-1])
    return False, last_error, last_tag, last_model


def send_chat(api_key, provider, model_id, messages, system_prompt, session=None):
    """Send canonical user/assistant history; return (ok, text, provider/model tag)."""
    tag = f"{PROVIDERS.get(provider, provider)} ({model_id})"
    own_session = session is None
    session = session or requests.Session()
    try:
        headers = _headers(api_key, provider)
        if not isinstance(model_id, str) or not model_id.strip() or any(c in model_id for c in "?#\\") or ".." in model_id:
            raise AIClientError("Geçerli bir model seçin.")
        turns = [{"role": m["role"], "content": str(m["content"])} for m in messages
                 if isinstance(m, dict) and m.get("role") in ("user", "assistant") and m.get("content")]
        if not turns or turns[-1]["role"] != "user":
            raise AIClientError("Sohbet bir kullanıcı mesajıyla bitmelidir.")
        if provider == "gemini":
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id.removeprefix('models/')}:generateContent"
            payload = {"systemInstruction": {"parts": [{"text": system_prompt}]},
                       "contents": [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]} for m in turns],
                       "generationConfig": {"maxOutputTokens": 4096}}
        elif provider == "openai":
            url = "https://api.openai.com/v1/responses"
            payload = {"model": model_id, "instructions": system_prompt, "input": turns, "max_output_tokens": 4096, "store": False}
        elif provider == "anthropic":
            url = "https://api.anthropic.com/v1/messages"
            payload = {"model": model_id, "system": system_prompt, "messages": turns, "max_tokens": 4096}
        else:
            url = "https://openrouter.ai/api/v1/chat/completions"
            payload = {"model": model_id, "messages": [{"role": "system", "content": system_prompt}] + turns, "max_tokens": 4096}
        data = _request(session, "post", url, headers, json=payload)
        truncated = False
        if provider == "gemini":
            candidates = data.get("candidates") or []
            candidate = candidates[0] if candidates else {}
            parts = (candidate.get("content") or {}).get("parts") or []
            text = "\n".join(p["text"] for p in parts if isinstance(p.get("text"), str) and not p.get("thought"))
            truncated = candidate.get("finishReason") == "MAX_TOKENS"
            if data.get("promptFeedback", {}).get("blockReason") or candidate.get("finishReason") in ("SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT"):
                raise AIClientError("Sağlayıcı güvenlik filtresi yanıtı engelledi.")
        elif provider == "openai":
            text = "\n".join(part["text"] for item in data.get("output", []) if item.get("type") == "message"
                             for part in item.get("content", []) if part.get("type") == "output_text" and isinstance(part.get("text"), str))
            truncated = data.get("status") == "incomplete"
            if data.get("status") in ("failed", "cancelled"):
                raise AIClientError("Sağlayıcı yanıtı tamamlayamadı.")
        elif provider == "anthropic":
            text = "\n".join(p["text"] for p in data.get("content", []) if p.get("type") == "text" and isinstance(p.get("text"), str))
            truncated = data.get("stop_reason") == "max_tokens"
        else:
            choices = data.get("choices") or []
            choice = choices[0] if choices else {}
            text = (choice.get("message") or {}).get("content")
            truncated = choice.get("finish_reason") == "length"
        if not isinstance(text, str) or not text.strip():
            raise AIClientError("API boş metin döndürdü; model erişimini ve çıktı sınırını kontrol edin.")
        if truncated:
            text += "\n\n[Yanıt çıktı sınırı nedeniyle tamamlanamadı.]"
        return True, text.strip(), tag
    except AIClientError as exc:
        return False, str(exc), tag
    except (KeyError, TypeError, ValueError, AttributeError, IndexError):
        return False, "API yanıt biçimi beklenenden farklı.", tag
    finally:
        if own_session:
            session.close()
