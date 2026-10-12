"""Home automation messages: iMessage first, Sipgate only on definite outage."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field
import json
import logging
from pathlib import Path

from aiohttp import web
from homeassistant.components import persistent_notification, webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store

from ._schema import schema as vol
from .const import DOMAIN
from .delivery import DeliveryManager, GroupNotConfigured, RequestConflict, RequestError, Transport, dry_run_result, prepare

_LOGGER = logging.getLogger(__name__)
SIGNAL = DOMAIN + "_delivery"


@dataclass
class Runtime:
    manager: DeliveryManager
    entry: ConfigEntry
    tasks: set = field(default_factory=set)
    last: dict = field(default_factory=dict)
    active: int = 0
    closing: bool = False

    @property
    def settings(self):
        return {**self.entry.data, **self.entry.options}


async def async_report_preflight_rejection(rt: Runtime, error: RequestError) -> None:
    """Expose a rejected attempt without reserving an ID or exposing raw inputs."""
    code = "request_id_conflict" if isinstance(error, RequestConflict) else "request_validation_failed"
    result = {"initials": [], "target": "request", "state": "rejected", "reason": code}
    if isinstance(error, GroupNotConfigured):
        code = "group_not_configured"
        result.update(initials=error.group.split("-"), target_type="group",
                      target=error.group, reason=code)
    # An explicit rejected result prevents callers from treating an empty list
    # as all accepted. This is status only, never an idempotency-ledger record.
    await rt.manager.notify({
        "complete": True, "phase": "preflight",
        "error": {"code": code, "message": str(error)},
        "results": [result],
    })


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    def runtime():
        entries = hass.config_entries.async_entries(DOMAIN)
        for entry in entries:
            if getattr(entry, "runtime_data", None) and not entry.runtime_data.closing:
                return entry.runtime_data
        raise HomeAssistantError("Home Messages is not configured")

    async def send(call: ServiceCall):
        rt = runtime()
        rt.active += 1
        try:
            plan = prepare(rt.settings, call.data["text"], call.data["initials"])
            if call.data.get("dry_run", False):
                return dry_run_result(plan)
            key, fresh = await rt.manager.reserve(plan, call.data.get("request_id"))
            if fresh:
                return await rt.manager.execute(key, plan)
            return rt.manager.result(key)
        except RequestError as err:
            if not call.data.get("dry_run", False):
                await async_report_preflight_rejection(rt, err)
            raise HomeAssistantError(str(err)) from err
        finally:
            rt.active -= 1

    async def check(call: ServiceCall):
        rt = runtime()
        return await rt.manager.transport.check(rt.settings)

    hass.services.async_register(DOMAIN, "send", send, schema=vol.Schema({
        vol.Required("text"): str, vol.Required("initials"): str,
        vol.Optional("request_id"): str, vol.Optional("dry_run", default=False): bool,
    }), supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, "test_connection", check,
        schema=vol.Schema({}), supports_response=SupportsResponse.ONLY)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.requests", private=True, atomic_writes=True)

    def check_existing_ledger():
        # Store would rename corrupt JSON and return None. Do not mistake that for
        # first installation and lose the evidence that an SMS may already exist.
        path = Path(store.path)
        if path.exists():
            saved = json.loads(path.read_text())
            if not isinstance(saved, dict) or not isinstance(saved.get("data"), dict):
                raise ValueError("Invalid Home Messages ledger; refusing to send")

    await hass.async_add_executor_job(check_existing_ledger)
    records = await store.async_load() or {}
    transport = Transport(async_get_clientsession(hass))
    persistence_lock = asyncio.Lock()

    async def save_confirmed(value):
        # Store logs write errors instead of raising. Verify the committed snapshot
        # before permitting a send, especially an SMS that has no idempotency API.
        if hass.is_stopping:
            raise OSError("HA is stopping; no new message may be submitted")
        async with persistence_lock:
            snapshot = deepcopy(value)
            await store.async_save(snapshot)

            def verify():
                stored = json.loads(Path(store.path).read_text())
                if stored.get("data") != snapshot:
                    raise OSError("Message ledger write was not confirmed")

            await hass.async_add_executor_job(verify)
        if hass.is_stopping:
            raise OSError("HA stopped during ledger persistence")

    rt = Runtime(DeliveryManager(transport, save_confirmed, records), entry)
    entry.runtime_data = rt

    async def changed(result):
        rt.last = result
        async_dispatcher_send(hass, SIGNAL)
        if result.get("phase") == "preflight":
            persistent_notification.async_create(hass,
                "Request rejected before dispatch: " + result["error"]["message"],
                title="Check message delivery", notification_id=DOMAIN + "_delivery")
            return
        failures = [r for r in result["results"] if r["state"] != "accepted"]
        if result.get("complete") and failures:
            summary = "; ".join(r["target"] + ": " + r["state"] + " (" + r.get("reason", "unconfirmed") + ")" for r in failures)
            persistent_notification.async_create(hass,
                f"Request {result['request_id']}: {summary}. No automatic retry was performed.",
                title="Check message delivery", notification_id=DOMAIN + "_delivery")

    rt.manager.notify = changed
    await rt.manager.recover()
    if records:
        rt.last = rt.manager.result(next(reversed(records)))

    async def run(key, plan):
        try:
            await rt.manager.execute(key, plan)
        except Exception:
            _LOGGER.error("Message processing stopped; check Home Messages status before retrying")
            persistent_notification.async_create(hass,
                "Processing stopped unexpectedly. The outcome may be uncertain; inspect Home Messages before retrying.",
                title="Check message delivery", notification_id=DOMAIN + "_delivery")

    async def handle(hass, webhook_id, request):
        if rt.closing:
            return web.json_response({"error": "integration is unloading"}, status=503)
        rt.active += 1
        is_preview = False
        try:
            if request.content_length and request.content_length > 65536:
                return web.json_response({"error": "request too large"}, status=413)
            if request.content_type == "application/json":
                data = await request.json()
            elif request.content_type in ("application/x-www-form-urlencoded", "multipart/form-data"):
                form = await request.post()
                if any(len(form.getall(k)) != 1 for k in form):
                    raise RequestError("duplicate form fields are not accepted")
                data = dict(form)
            else:
                return web.json_response({"error": "use form data or JSON"}, status=415)
            if not isinstance(data, dict) or set(data) - {"text", "initials", "request_id", "dry_run"}:
                raise RequestError("unsupported request fields")
            dry_run = data.get("dry_run", False)
            if dry_run not in (False, True, "true", "false"):
                raise RequestError("dry_run must be true or false")
            is_preview = dry_run in (True, "true")
            plan = prepare(rt.settings, data.get("text"), data.get("initials"))
            if is_preview:
                return web.json_response(dry_run_result(plan))
            key, fresh = await rt.manager.reserve(plan, data.get("request_id"))
            if fresh:
                await changed(rt.manager.result(key))
                task = hass.async_create_task(run(key, plan), "Home Messages delivery")
                rt.tasks.add(task)
                task.add_done_callback(rt.tasks.discard)
            result = rt.manager.result(key)
            return web.json_response(result, status=200 if result["complete"] else 202)
        except RequestConflict as err:
            await async_report_preflight_rejection(rt, err)
            return web.json_response({"error": str(err)}, status=409)
        except RequestError as err:
            if not is_preview:
                await async_report_preflight_rejection(rt, err)
            return web.json_response({"error": "invalid text, initials, or request ID; nothing sent"}, status=400)
        except ValueError:
            # JSON decoder errors may contain the submitted body; do not expose it.
            await async_report_preflight_rejection(rt, RequestError("invalid JSON payload; no message sent"))
            return web.json_response({"error": "invalid text, initials, or request ID; nothing sent"}, status=400)
        except OSError:
            return web.json_response({"error": "message ledger unavailable; no dispatch started"}, status=503)
        finally:
            rt.active -= 1

    webhook.async_register(hass, DOMAIN, "Home Messages", entry.data["webhook_id"], handle,
        local_only=True, allowed_methods=["POST"])
    await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    rt = entry.runtime_data
    # Prevent configuration reload from cutting across a send or enabling duplicates.
    if rt.active or rt.tasks or rt.manager.send_lock.locked():
        return False
    rt.closing = True
    if not await hass.config_entries.async_unload_platforms(entry, [Platform.SENSOR]):
        rt.closing = False
        return False
    webhook.async_unregister(hass, entry.data["webhook_id"])
    del entry.runtime_data
    return True
