"""Validated, durable message routing. No HA imports; transport is injectable."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
import re
import uuid

import aiohttp

PROBLEM_PREFIX = "https://github.com/mglaeser/imessage-proxy/problems/"
SAFE_FALLBACK = {
    (503, "key-store-unavailable"), (503, "overloaded"),
    (503, "allowlist-unavailable"), (503, "audit-unavailable"),
    (503, "idempotency-unavailable"), (429, "send-rate-limited"),
    (429, "rate-limited"), (504, "dependency-timeout"),
}
ALIAS = re.compile(r"[A-Z][A-Z0-9_]{0,15}")
PHONE = re.compile(r"\+[1-9][0-9]{6,14}")


class RequestError(ValueError):
    """Safe public validation error."""


class RequestConflict(RequestError):
    """An id was reused with different message content or recipients."""


def prepare(settings, text, initials):
    """Validate all recipients before any transport action; snapshot settings."""
    if not isinstance(text, str) or not text.strip() or len(text) > 4000:
        raise RequestError("text must contain 1–4000 characters")
    if text.startswith("-") or any((ord(c) < 32 and c not in "\t\r\n") or 127 <= ord(c) <= 159 for c in text):
        raise RequestError("text contains characters unsupported by the proxy")
    if not isinstance(initials, str) or len(initials) > 256:
        raise RequestError("initials must be a comma-separated string")
    mapping = settings.get("recipients", {})
    if not isinstance(mapping, dict) or any(not isinstance(a, str) or not ALIAS.fullmatch(a) for a in mapping):
        # Previously '-' was allowed in aliases. Never silently reinterpret an
        # existing alias such as BB-CC as a group after the syntax upgrade.
        raise RequestError("recipient aliases must not contain hyphens or invalid characters")
    groups = settings.get("groups", {})
    if not isinstance(groups, dict):
        raise RequestError("group configuration must be a mapping")
    singles, group_targets = {}, {}
    for part in dict.fromkeys(part.strip().upper() for part in initials.split(",")):
        aliases = [a.strip() for a in part.split("-")]
        if any(not ALIAS.fullmatch(a) for a in aliases):
            raise RequestError("initials contains an empty or invalid alias")
        if len(aliases) != len(set(aliases)):
            raise RequestError("a group must contain distinct aliases")
        if any(a not in mapping for a in aliases):
            raise RequestError("unknown initials; no message sent")
        phones = [mapping[a] for a in aliases]
        if any(not isinstance(p, str) or not PHONE.fullmatch(p) for p in phones):
            raise RequestError("recipient configuration contains an invalid phone number")
        if len(aliases) == 1:
            bucket = singles.setdefault(phones[0], [])
            if aliases[0] not in bucket:
                bucket.append(aliases[0])
            continue
        if len(phones) != len(set(phones)):
            raise RequestError("group members must have distinct phone numbers")
        aliases.sort()
        group_key = "-".join(aliases)
        chat_id = groups.get(group_key)
        if type(chat_id) is not int or not 0 < chat_id <= 2**63 - 1:
            raise RequestError("requested group has no valid configured chat ID; no message sent")
        group_targets[group_key] = {"chat_id": chat_id, "initials": aliases, "phones": sorted(phones)}
    if len({t["chat_id"] for t in group_targets.values()}) != len(group_targets):
        raise RequestError("different groups must not share a chat ID")
    # Preserve the exact single-target structure/order used by existing ledger
    # fingerprints. Group member addresses are hashed but never persisted.
    return {"settings": deepcopy(settings), "text": text,
            "targets": [{"phone": p, "initials": a} for p, a in sorted(singles.items())]
                       + [group_targets[k] for k in sorted(group_targets)]}


def target_metadata(target):
    """Public routing identity, without phone numbers or native chat IDs."""
    is_group = "chat_id" in target
    return {"initials": list(target["initials"]), "target_type": "group" if is_group else "single",
            "target": ("-" if is_group else ",").join(sorted(target["initials"]))}


def dry_run_result(plan):
    """Identical local-only preview for the HA service and webhook."""
    return {"dry_run": True, "recipients": [list(t["initials"]) for t in plan["targets"]],
            "results": [{**target_metadata(t), "state": "dry_run"} for t in plan["targets"]]}


def validate_group_metadata(target, chat):
    """Fail closed unless the existing iMessage chat has exactly these members."""
    if (not isinstance(chat, dict) or type(chat.get("id")) is not int
        or chat["id"] != target["chat_id"] or chat.get("is_group") is not True
        or not isinstance(chat.get("service"), str) or chat["service"].casefold() != "imessage"
        or not isinstance(chat.get("participants"), list)):
        raise RequestError("group chat metadata could not be verified; no message sent")
    participants = []
    for member in chat["participants"]:
        if not isinstance(member, str):
            raise RequestError("group chat participants could not be verified; no message sent")
        phone = re.sub(r"[\s().-]", "", member)
        if not PHONE.fullmatch(phone):
            raise RequestError("group chat participants must be configured phone numbers; no message sent")
        participants.append(phone)
    if len(participants) != len(set(participants)) or sorted(participants) != target["phones"]:
        raise RequestError("group chat participants do not match the configured members; no message sent")


def proxy_result(status, body):
    """Only known, pre-send failures permit automatic SMS fallback."""
    if status == 202 and isinstance(body, dict) and body.get("state") == "accepted" and body.get("operation_id"):
        return {"state": "accepted", "transport": "imessage"}
    suffix = ""
    if isinstance(body, dict) and body.get("status") == status:
        typ = body.get("type", "")
        if isinstance(typ, str) and typ.startswith(PROBLEM_PREFIX):
            suffix = typ[len(PROBLEM_PREFIX):]
    if (status, suffix) in SAFE_FALLBACK:
        return {"state": "unavailable", "transport": "imessage", "reason": suffix}
    # Configuration and authorization failures must not bypass the proxy allowlist.
    if status in (400, 401, 403, 404, 413, 415, 431):
        return {"state": "rejected", "transport": "imessage", "reason": "proxy_configuration_or_permission", "http_status": status}
    return {"state": "unknown", "transport": "imessage", "reason": "proxy_outcome_uncertain", "http_status": status}


class Transport:
    def __init__(self, session):
        self.session = session

    async def imessage(self, cfg, phone, text, key):
        return await self._imessage(cfg, {"recipient": phone}, text, key)

    async def imessage_group(self, cfg, chat_id, text, key):
        return await self._imessage(cfg, {"chat_id": chat_id}, text, key)

    async def _imessage(self, cfg, destination, text, key):
        try:
            async with self.session.post(
                cfg["proxy_url"].rstrip("/") + "/api/messages",
                headers={"Authorization": "Bearer " + cfg["proxy_api_key"], "Idempotency-Key": key},
                json={**destination, "text": text, "service": "imessage"},
                timeout=aiohttp.ClientTimeout(total=190, connect=5), allow_redirects=False,
            ) as response:
                try:
                    body = await response.json(content_type=None)
                except (ValueError, aiohttp.ClientError):
                    body = None
                return proxy_result(response.status, body)
        except (aiohttp.ClientConnectorError, aiohttp.ConnectionTimeoutError):
            return {"state": "unavailable", "transport": "imessage", "reason": "connection_failed"}
        except (aiohttp.ClientError, TimeoutError):
            return {"state": "unknown", "transport": "imessage", "reason": "connection_lost_after_possible_submission"}

    async def group_metadata(self, cfg, chat_id):
        """Read chat metadata only, never history or messages."""
        try:
            async with self.session.get(
                cfg["proxy_url"].rstrip("/") + "/api/chats/" + str(chat_id),
                headers={"Authorization": "Bearer " + cfg["proxy_api_key"]},
                timeout=aiohttp.ClientTimeout(total=35, connect=5), allow_redirects=False,
            ) as response:
                if response.status != 200:
                    raise RequestError("group chat metadata is unavailable or forbidden; no message sent")
                return await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise RequestError("group chat metadata could not be read; no message sent") from err

    async def sms(self, cfg, phone, text):
        try:
            async with self.session.post(
                "https://api.sipgate.com/v2/sessions/sms",
                auth=aiohttp.BasicAuth(cfg["sipgate_token_id"], cfg["sipgate_token_secret"]),
                json={"smsId": cfg["sipgate_sms_id"], "recipient": phone, "message": text},
                timeout=aiohttp.ClientTimeout(total=30, connect=5), allow_redirects=False,
            ) as response:
                if response.status == 204:
                    return {"state": "accepted", "transport": "sms"}
                return {"state": "rejected" if 400 <= response.status < 500 else "unknown",
                        "transport": "sms", "reason": "sipgate_did_not_confirm", "http_status": response.status}
        except (aiohttp.ClientConnectorError, aiohttp.ConnectionTimeoutError):
            return {"state": "failed", "transport": "sms", "reason": "connection_failed"}
        except (aiohttp.ClientError, TimeoutError):
            return {"state": "unknown", "transport": "sms", "reason": "connection_lost_after_possible_submission"}

    async def check(self, cfg):
        """Read-only credential/connectivity checks; never sends a message."""
        result = {}
        try:
            async with self.session.get(cfg["proxy_url"].rstrip("/") + "/api/status",
                headers={"Authorization": "Bearer " + cfg["proxy_api_key"]},
                timeout=aiohttp.ClientTimeout(total=35, connect=5), allow_redirects=False) as r:
                try:
                    body = await r.json(content_type=None)
                except (ValueError, aiohttp.ClientError):
                    body = {}
                result["proxy"] = {"http_status": r.status, "authenticated": r.status == 200,
                    "status": body.get("status", "unknown") if isinstance(body, dict) else "unknown"}
        except (aiohttp.ClientError, TimeoutError):
            result["proxy"] = {"authenticated": False, "status": "unreachable"}
        result["sipgate"] = {"enabled": bool(cfg.get("sipgate_enabled")),
            "configured": all(cfg.get(k) for k in ("sipgate_token_id", "sipgate_token_secret", "sipgate_sms_id"))}
        return result


class DeliveryManager:
    """Persist before dispatch; uncertain sends are never retried automatically."""
    def __init__(self, transport, save, records=None, notify=None):
        self.transport, self.save, self.notify = transport, save, notify
        self.records = records or {}
        self.lock = asyncio.Lock()
        self.send_lock = asyncio.Lock()

    async def recover(self):
        for record in self.records.values():
            if not record.get("complete"):
                for result in record["results"]:
                    if result["state"] in ("queued", "imessage_pending", "sms_pending"):
                        result.update(state="unknown", reason="ha_restarted_during_request")
                record["complete"] = True
        await self.save(self.records)

    async def reserve(self, plan, request_id=None):
        request_id = request_id or uuid.uuid4().hex
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_.~-]{8,80}", request_id):
            raise RequestError("request_id must be 8–80 letters, digits, dots, underscores, tildes or hyphens")
        record_key = hashlib.sha256(request_id.encode()).hexdigest()
        fingerprint = hashlib.sha256(json.dumps({"text": plan["text"], "targets": plan["targets"]}, sort_keys=True).encode()).hexdigest()
        async with self.lock:
            if record_key in self.records:
                if self.records[record_key]["fingerprint"] != fingerprint:
                    raise RequestConflict("request_id already belongs to different content")
                return record_key, False
            if sum(not r.get("complete") for r in self.records.values()) >= 25:
                raise RequestError("message queue is full")
            # Retain the latest 1000 request IDs. Phone numbers and text are never stored.
            while len(self.records) >= 1000:
                oldest = next((k for k, v in self.records.items() if v.get("complete")), None)
                if oldest is None:
                    raise RequestError("message ledger is full")
                self.records.pop(oldest)
            self.records[record_key] = {"request_id": request_id, "fingerprint": fingerprint, "complete": False,
                "results": [{**target_metadata(t), "state": "queued"} for t in plan["targets"]]}
            await self.save(self.records)
        return record_key, True

    def result(self, key):
        result = {k: deepcopy(v) for k, v in self.records[key].items() if k != "fingerprint"}
        for item in result["results"]:
            # Old ledgers only contain individual destinations, including aliases
            # sharing one phone. Do not change stored fingerprints on migration.
            item.setdefault("target_type", "single")
            item.setdefault("target", ",".join(sorted(item["initials"])))
        return result

    async def execute(self, key, plan):
        async with self.send_lock:
            record = self.records[key]
            cfg = plan["settings"]
            # Check every group after waiting for earlier sends, before any POST
            # in this request. A mixed request must not partially send on a known
            # membership/configuration mismatch. Single-only plans make no GET.
            try:
                for target in plan["targets"]:
                    if "chat_id" in target:
                        chat = await self.transport.group_metadata(cfg, target["chat_id"])
                        validate_group_metadata(target, chat)
            except Exception:
                for result in record["results"]:
                    result.update(state="rejected", reason="group_chat_verification_failed")
                record["complete"] = True
                await self.save(self.records)
                if self.notify:
                    await self.notify(self.result(key))
                return self.result(key)
            for index, target in enumerate(plan["targets"]):
                result = record["results"][index]
                result["state"] = "imessage_pending"
                await self.save(self.records)
                try:
                    is_group = "chat_id" in target
                    method = self.transport.imessage_group if is_group else self.transport.imessage
                    destination = target["chat_id"] if is_group else target["phone"]
                    sent = await method(cfg, destination, plan["text"], "ha-" + key + "-" + str(index))
                    if not is_group and sent["state"] == "unavailable" and cfg.get("sipgate_enabled"):
                        result.update(state="sms_pending", fallback_reason=sent.get("reason"))
                        await self.save(self.records)
                        sent = await self.transport.sms(cfg, target["phone"], plan["text"])
                    result.update(sent)
                except Exception:
                    # An unexpected transport error may occur after submission.
                    result.update(state="unknown", reason="unexpected_send_error")
                await self.save(self.records)
            record["complete"] = True
            await self.save(self.records)
            if self.notify:
                await self.notify(self.result(key))
            return self.result(key)
