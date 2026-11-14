"""Delivering alerts to the owner of a portfolio, right away.

Two kinds of channel, each portfolio can have several:

* ``{"type": "bale" | "telegram", "token": ..., "chat_id": ...}`` — a messenger bot. Bale
  (tapi.bale.ai) speaks the Telegram Bot API, and works inside Iran without a tunnel. Urgent alerts
  carry buttons («خارج می‌شوم» / «نصف را می‌فروشم» / «نگه می‌دارم»); the press comes back through
  ``getUpdates`` (:func:`poll_answers`) and is stored on the alert.
* ``{"type": "apprise", "url": ...}`` — any of the 100+ services Apprise supports: ntfy (phone push
  with sound, self-hostable), Pushover, e-mail (mailto://), Discord, Slack, Gotify, SMS gateways...

The page itself also shows every alert within seconds (it polls the API) and raises a browser
notification while it is open.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

log = logging.getLogger(__name__)

BOT_HOSTS = {"bale": "https://tapi.bale.ai", "telegram": "https://api.telegram.org"}
ANSWERS = {"exit": "خارج می‌شوم", "reduce": "نصف را می‌فروشم", "hold": "نگه می‌دارم"}
SEVERITY_FA = {1: "اطلاع", 2: "هشدار", 3: "فوری"}
SEVERITY_ICON = {1: "ℹ️", 2: "⚠️", 3: "🚨"}


@dataclass(frozen=True)
class Message:
    alert_id: int
    severity: int
    title: str
    body: str
    ask_exit: bool
    link: str | None = None


def masked(channel: dict[str, Any]) -> dict[str, Any]:
    """A channel as the API shows it: never the token or the full URL."""
    out = {"type": channel.get("type"), "label": channel.get("label")}
    if channel.get("type") in BOT_HOSTS:
        tok = str(channel.get("token") or "")
        out["token"] = (tok[:4] + "…" + tok[-3:]) if len(tok) > 8 else "…"
        out["chat_id"] = channel.get("chat_id")
    else:
        url = str(channel.get("url") or "")
        out["url"] = url.split("://", 1)[0] + "://…" if "://" in url else "…"
    return out


def validate(channel: dict[str, Any]) -> str | None:
    """Why the channel cannot work, or None."""
    t = channel.get("type")
    if t in BOT_HOSTS:
        if not channel.get("token") or not channel.get("chat_id"):
            return "token و chat_id لازم است"
        return None
    if t == "apprise":
        import apprise

        if not apprise.Apprise().add(str(channel.get("url") or "")):
            return "آدرس Apprise نامعتبر است"
        return None
    return "نوع کانال باید bale، telegram یا apprise باشد"


def _text(m: Message) -> str:
    head = f"{SEVERITY_ICON.get(m.severity, '')} [{SEVERITY_FA.get(m.severity, '')}] {m.title}"
    tail = f"\n{m.link}" if m.link else ""
    return f"{head}\n\n{m.body}{tail}"


def _keyboard(alert_id: int) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": label, "callback_data": f"a:{alert_id}:{key}"}]
            for key, label in ANSWERS.items()
        ]
    }


async def _send_bot(client: httpx.AsyncClient, ch: dict[str, Any], m: Message) -> None:
    host = BOT_HOSTS[str(ch["type"])]
    payload: dict[str, Any] = {"chat_id": ch["chat_id"], "text": _text(m)}
    if m.ask_exit:
        payload["reply_markup"] = _keyboard(m.alert_id)
    r = await client.post(f"{host}/bot{ch['token']}/sendMessage", json=payload)
    r.raise_for_status()
    if not (r.json() or {}).get("ok", False):
        raise RuntimeError(str(r.json())[:200])


async def _send_apprise(ch: dict[str, Any], m: Message) -> None:
    import apprise

    a = apprise.Apprise()
    if not a.add(str(ch["url"])):
        raise ValueError("invalid apprise url")
    kind = {1: apprise.NotifyType.INFO, 2: apprise.NotifyType.WARNING}.get(
        m.severity, apprise.NotifyType.FAILURE
    )
    body = m.body + (f"\n{m.link}" if m.link else "")
    if m.ask_exit:
        body += "\n\nپاسخ را در صفحهٔ پرتفوی یا پیام‌رسان بده: خروج / نصف / نگه‌داری."
    ok = await a.async_notify(body=body, title=m.title, notify_type=kind)
    if not ok:
        raise RuntimeError("apprise delivery failed")


async def deliver(
    channels: list[dict[str, Any]], m: Message, client: httpx.AsyncClient | None = None
) -> list[dict[str, Any]]:
    """Send to every channel at once; one failing channel never blocks the others. Returns one
    ``{"type", "ok", "error"?}`` per channel (stored on the alert)."""
    own = client is None
    client = client or httpx.AsyncClient(timeout=15)

    async def one(ch: dict[str, Any]) -> dict[str, Any]:
        try:
            if ch.get("type") in BOT_HOSTS:
                await _send_bot(client, ch, m)
            elif ch.get("type") == "apprise":
                await _send_apprise(ch, m)
            else:
                return {"type": ch.get("type"), "ok": False, "error": "unknown channel"}
            return {"type": ch.get("type"), "ok": True}
        except Exception as exc:
            log.warning("alert %s via %s failed: %s", m.alert_id, ch.get("type"), exc)
            return {"type": ch.get("type"), "ok": False, "error": str(exc)[:200]}

    try:
        return list(await asyncio.gather(*(one(c) for c in channels)))
    finally:
        if own:
            await client.aclose()


def parse_callback(data: str) -> tuple[int, str] | None:
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != "a" or parts[2] not in ANSWERS:
        return None
    try:
        return int(parts[1]), parts[2]
    except ValueError:
        return None


async def poll_answers(
    client: httpx.AsyncClient,
    bots: list[dict[str, Any]],
    offsets: dict[str, int],
    on_answer: Callable[[int, str, str], bool],
) -> int:
    """One ``getUpdates`` round per distinct bot. ``on_answer(alert_id, answer, chat_id)`` stores
    the press (and returns False when the chat does not own that alert). A ``/start`` message is
    answered with the chat id, so the owner can paste it into the portfolio settings."""
    n = 0
    seen: set[tuple[str, str]] = set()
    for ch in bots:
        sig = (str(ch["type"]), str(ch["token"]))
        if sig in seen:
            continue
        seen.add(sig)
        host = BOT_HOSTS[sig[0]]
        base = f"{host}/bot{sig[1]}"
        key = f"{sig[0]}:{sig[1][:12]}"
        try:
            r = await client.get(
                f"{base}/getUpdates", params={"offset": offsets.get(key, 0), "timeout": 0}
            )
            updates = (r.json() or {}).get("result") or []
        except Exception as exc:
            log.debug("getUpdates failed: %s", exc)
            continue
        for u in updates:
            offsets[key] = int(u["update_id"]) + 1
            cb = u.get("callback_query")
            if cb:
                parsed = parse_callback(str(cb.get("data") or ""))
                chat = str(((cb.get("message") or {}).get("chat") or {}).get("id", ""))
                ok = parsed is not None and on_answer(parsed[0], parsed[1], chat)
                text = f"ثبت شد: {ANSWERS[parsed[1]]}" if ok and parsed else "این هشدار پیدا نشد"
                try:
                    await client.post(
                        f"{base}/answerCallbackQuery",
                        json={"callback_query_id": cb.get("id"), "text": text},
                    )
                    if ok and chat:
                        await client.post(
                            f"{base}/sendMessage", json={"chat_id": chat, "text": text}
                        )
                except Exception:
                    pass
                n += int(ok)
                continue
            msg = u.get("message") or {}
            if str(msg.get("text") or "").startswith("/start"):
                start_chat = (msg.get("chat") or {}).get("id")
                with contextlib.suppress(Exception):
                    await client.post(
                        f"{base}/sendMessage",
                        json={
                            "chat_id": start_chat,
                            "text": f"شناسهٔ این گفت‌وگو: {start_chat}\n"
                            "آن را در تنظیمات پرتفوی وارد کن.",
                        },
                    )
    return n
