import asyncio
from copy import deepcopy
import importlib.util
import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "custom_components/home_messages"
spec = importlib.util.spec_from_file_location("delivery", ROOT / "delivery.py")
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)
spec = importlib.util.spec_from_file_location("const", ROOT / "const.py")
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)

CFG = {"recipients": {"BB": "+12025550101", "CC": "+12025550102"}, "sipgate_enabled": True}
GROUP_CFG = {**CFG, "recipients": {**CFG["recipients"], "AA": "+12025550103"},
    "groups": {"BB-CC": 42, "AA-BB-CC": 43, "AA-BB": 44}}


def chat(chat_id, aliases):
    return {"id": chat_id, "service": "iMessage", "is_group": True,
            "participants": [GROUP_CFG["recipients"][a] for a in aliases]}


CHATS = {42: chat(42, ["BB", "CC"]), 43: chat(43, ["AA", "BB", "CC"]), 44: chat(44, ["AA", "BB"])}


class Fake:
    def __init__(self, answers, chats=None):
        self.answers = iter(answers)
        self.calls = []
        self.reads = []
        self.chats = deepcopy(CHATS if chats is None else chats)

    async def imessage(self, cfg, phone, text, key):
        self.calls.append(("imessage", phone, text, key))
        return next(self.answers)

    async def sms(self, cfg, phone, text):
        self.calls.append(("sms", phone, text))
        return {"state": "accepted", "transport": "sms"}

    async def imessage_group(self, cfg, chat_id, text, key):
        self.calls.append(("imessage_group", chat_id, text, key))
        return next(self.answers)

    async def group_metadata(self, cfg, chat_id):
        self.reads.append(chat_id)
        return self.chats.get(chat_id)


def manager(answers, records=None, chats=None):
    saved = []
    async def save(value):
        saved.append(deepcopy(value))
    transport = Fake(answers, chats)
    return d.DeliveryManager(transport, save, records), transport, saved


@pytest.mark.parametrize("text", ["123", "True", "[]", "  Grüße 🏠 & \"Test\"\nzweite Zeile  "])
def test_exact_text_preserved(text):
    assert d.prepare(CFG, text, " bb, CC, bb ")["text"] == text


@pytest.mark.parametrize("text,aliases", [("", "BB"), (" ", "BB"), ("-test", "BB"), ("x"*4001,"BB"), ("x\x00", "BB"), (123,"BB"), ("ok", "BB,ZZ"), ("ok", ""), ("ok", "BB,"), ("ok", ["BB"])])
def test_validation(text, aliases):
    with pytest.raises(d.RequestError):
        d.prepare(CFG, text, aliases)


def test_alias_and_phone_deduplication():
    cfg = deepcopy(CFG)
    cfg["recipients"]["CC"] = cfg["recipients"]["BB"]
    p = d.prepare(cfg, "test", "bb,CC,BB")
    assert len(p["targets"]) == 1
    assert p["targets"][0]["initials"] == ["BB", "CC"]
    cfg["recipients"]["CC"] = "wrong"
    assert p["settings"]["recipients"]["CC"] != "wrong"


@pytest.mark.parametrize("status,suffix", sorted(d.SAFE_FALLBACK))
def test_known_pre_send_failures(status, suffix):
    assert d.proxy_result(status, {"status": status, "type": d.PROBLEM_PREFIX+suffix})["state"] == "unavailable"


@pytest.mark.parametrize("status,suffix", [(502,"send-ambiguous"),(504,"send-ambiguous"),(503,"idempotency-completion-failed"),(409,"request-in-progress"),(409,"idempotency-conflict"),(503,"messages-unavailable")])
def test_uncertain_never_falls_back(status, suffix):
    assert d.proxy_result(status, {"status": status, "type": d.PROBLEM_PREFIX+suffix})["state"] == "unknown"


def test_success_and_malformed_success():
    assert d.proxy_result(202, {"state":"accepted","operation_id":"test"})["state"] == "accepted"
    assert d.proxy_result(202, {})["state"] == "unknown"
    assert d.proxy_result(503, {"status":503,"type":"https://wrong/overloaded"})["state"] == "unknown"
    assert d.proxy_result(403, {"status":403,"type":d.PROBLEM_PREFIX+"target-forbidden"})["state"] == "rejected"


@pytest.mark.asyncio
async def test_per_recipient_fallback_persistence_and_replay():
    m, t, saves = manager([{"state":"accepted","transport":"imessage"},{"state":"unavailable","reason":"overloaded"}])
    plan = d.prepare(CFG, "secret test text", "BB,CC")
    key, fresh = await m.reserve(plan, "stable-request-123")
    assert fresh and not t.calls
    r = await m.execute(key, plan)
    assert [x["transport"] for x in r["results"]] == ["imessage", "sms"]
    assert [x[0] for x in t.calls] == ["imessage", "imessage", "sms"]
    assert not t.reads
    assert t.calls[0][3] != t.calls[1][3]
    assert await m.reserve(plan,"stable-request-123") == (key, False)
    with pytest.raises(d.RequestConflict):
        await m.reserve(d.prepare(CFG,"different text","BB,CC"),"stable-request-123")
    assert "secret test text" not in str(saves)
    assert "+12025550101" not in str(saves)
    states = [list(s.values())[0]["results"][-1]["state"] for s in saves]
    assert "imessage_pending" in states and "sms_pending" in states


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["accepted", "unknown", "rejected"])
async def test_no_fallback_after_non_outage(state):
    m,t,_ = manager([{"state":state,"transport":"imessage"}])
    p = d.prepare(CFG,"test","BB")
    key,_ = await m.reserve(p)
    await m.execute(key,p)
    assert len(t.calls) == 1


@pytest.mark.asyncio
async def test_no_fallback_when_disabled():
    cfg = {**CFG, "sipgate_enabled":False}
    m,t,_ = manager([{"state":"unavailable"}])
    p = d.prepare(cfg,"test","BB")
    key,_=await m.reserve(p)
    await m.execute(key,p)
    assert len(t.calls)==1


@pytest.mark.asyncio
async def test_restart_does_not_resubmit():
    m,t,_ = manager([])
    p=d.prepare(CFG,"test","BB")
    key,_ = await m.reserve(p,"stable-request-123")
    restored,t2,_ = manager([],deepcopy(m.records))
    await restored.recover()
    assert restored.result(key)["results"][0]["state"]=="unknown"
    assert await restored.reserve(p,"stable-request-123") == (key,False)
    assert not t.calls and not t2.calls


def test_settings_preserve_secrets_and_validate_mapping():
    base={"proxy_url":"http://localhost:8765","proxy_api_key":"secret-proxy","sipgate_enabled":True,
        "sipgate_token_id":"secret-id","sipgate_token_secret":"secret-sg","sipgate_sms_id":"s0","recipients":"BB=+12025550101"}
    n=c.normalize_settings(base)
    updated=c.normalize_settings({"proxy_api_key":"","sipgate_token_secret":"", "recipients":"CC=+12025550102"},n)
    assert updated["proxy_api_key"]=="secret-proxy"
    assert updated["sipgate_token_secret"]=="secret-sg"
    assert updated["recipients"]=={"CC":"+12025550102"}
    for bad in ("bb=+12025550101\nBB=+12025550102", "BB=abc", "", "BB=+1"):
        with pytest.raises(c.SettingsValidationError):
            c.normalize_settings({**base,"recipients":bad})


@pytest.mark.asyncio
async def test_save_failure_prevents_dispatch():
    calls=0
    async def failing_save(value):
        nonlocal calls
        calls+=1
        if calls > 1:
            raise OSError("disk full")
    t=Fake([{"state":"accepted"}])
    m=d.DeliveryManager(t,failing_save)
    p=d.prepare(CFG,"test","BB")
    key,_=await m.reserve(p)
    with pytest.raises(OSError):await m.execute(key,p)
    assert not t.calls


@pytest.mark.asyncio
async def test_failed_sms_intent_save_prevents_fallback():
    calls=0
    async def failing_save(value):
        nonlocal calls
        calls+=1
        if calls==3:raise OSError("disk full")
    t=Fake([{"state":"unavailable","reason":"connection_failed"}])
    m=d.DeliveryManager(t,failing_save)
    p=d.prepare(CFG,"test","BB")
    key,_=await m.reserve(p)
    result=await m.execute(key,p)
    assert len(t.calls)==1
    assert result["results"][0]["state"]=="unknown"


@pytest.mark.parametrize("initials,expected", [
    ("BB,CC", [("single", "BB", ["BB"]), ("single", "CC", ["CC"])]),
    ("BB-CC", [("group", "BB-CC", ["BB", "CC"])]),
    ("BB-CC,AA", [("single", "AA", ["AA"]), ("group", "BB-CC", ["BB", "CC"])]),
    ("BB-CC-AA", [("group", "AA-BB-CC", ["AA", "BB", "CC"])]),
])
def test_comma_destinations_and_hyphen_groups(initials, expected):
    plan = d.prepare(GROUP_CFG, "Hello", initials)
    preview = d.dry_run_result(plan)
    assert preview["dry_run"] is True
    assert [(r["target_type"], r["target"], r["initials"]) for r in preview["results"]] == expected
    assert preview["recipients"] == [r[2] for r in expected]
    assert all(r["state"] == "dry_run" for r in preview["results"])
    assert "chat_id" not in str(preview) and "+1202" not in str(preview)


def test_group_reordering_and_duplicates_are_canonical():
    first = d.prepare(GROUP_CFG, "test", "bb - cc, CC-BB, bb-cc")
    assert first == d.prepare(GROUP_CFG, "test", "CC-BB")
    assert first["targets"] == [{"chat_id": 42, "initials": ["BB", "CC"],
                                 "phones": ["+12025550101", "+12025550102"]}]


@pytest.mark.parametrize("initials", ["BB-", "-BB", "BB--CC", "BB-BB", "BB-CC-ZZ", "BB/CC", "BB CC", "BB-CC,", "AA-CC"])
def test_invalid_or_unconfigured_groups(initials):
    with pytest.raises(d.RequestError):
        d.prepare(GROUP_CFG, "test", initials)


@pytest.mark.parametrize("chat_id", [None, True, False, 0, -1, "42", 42.0, 2**63])
def test_group_chat_id_is_positive_integer(chat_id):
    with pytest.raises(d.RequestError):
        d.prepare({**GROUP_CFG, "groups": {"BB-CC": chat_id}}, "test", "BB-CC,AA")


def test_legacy_hyphen_alias_is_never_reinterpreted_as_group():
    cfg = deepcopy(GROUP_CFG)
    cfg["recipients"]["BB-CC"] = "+12025550104"
    for initials in ("BB-CC", "BB", "AA"):
        with pytest.raises(d.RequestError, match="hyphen"):
            d.prepare(cfg, "test", initials)


def test_duplicate_group_member_phone_and_reused_chat_id_rejected():
    cfg = deepcopy(GROUP_CFG)
    cfg["recipients"]["CC"] = cfg["recipients"]["BB"]
    with pytest.raises(d.RequestError, match="distinct phone"):
        d.prepare(cfg, "test", "BB-CC,AA")
    cfg = deepcopy(GROUP_CFG)
    cfg["groups"]["AA-BB"] = 42
    with pytest.raises(d.RequestError, match="share a chat"):
        d.prepare(cfg, "test", "BB-CC,AA-BB")


@pytest.mark.asyncio
async def test_single_legacy_fingerprint_and_results_replay_without_network():
    plan = d.prepare(CFG, "existing text", "CC,BB")
    old_targets = [{"phone": "+12025550101", "initials": ["BB"]},
                   {"phone": "+12025550102", "initials": ["CC"]}]
    assert plan["targets"] == old_targets
    key = hashlib.sha256(b"legacy-request-123").hexdigest()
    fingerprint = hashlib.sha256(json.dumps({"text": "existing text", "targets": old_targets}, sort_keys=True).encode()).hexdigest()
    old = {key: {"request_id": "legacy-request-123", "fingerprint": fingerprint, "complete": True,
                 "results": [{"initials": ["BB"], "state": "accepted", "transport": "imessage"},
                             {"initials": ["CC"], "state": "accepted", "transport": "sms"}]}}
    m, t, saved = manager([], deepcopy(old))
    assert await m.reserve(plan, "legacy-request-123") == (key, False)
    assert [r["target_type"] for r in m.result(key)["results"]] == ["single", "single"]
    assert [r["target"] for r in m.result(key)["results"]] == ["BB", "CC"]
    assert m.records == old and not saved and not t.calls and not t.reads


@pytest.mark.asyncio
async def test_group_replay_and_member_mapping_conflict():
    m, t, saves = manager([{"state": "accepted", "transport": "imessage"}])
    plan = d.prepare(GROUP_CFG, "private text", "CC-BB")
    key, fresh = await m.reserve(plan, "group-request-123")
    assert fresh and not t.reads and not t.calls
    result = await m.execute(key, plan)
    assert t.reads == [42]
    assert result["results"] == [{"initials": ["BB", "CC"], "target_type": "group", "target": "BB-CC",
                                  "state": "accepted", "transport": "imessage"}]
    assert await m.reserve(d.prepare(GROUP_CFG, "private text", "BB-CC"), "group-request-123") == (key, False)
    assert t.reads == [42] and len(t.calls) == 1
    cfg = deepcopy(GROUP_CFG)
    cfg["recipients"]["BB"] = "+12025550105"
    with pytest.raises(d.RequestConflict):
        await m.reserve(d.prepare(cfg, "private text", "BB-CC"), "group-request-123")
    cfg = deepcopy(GROUP_CFG)
    cfg["groups"]["BB-CC"] = 99
    with pytest.raises(d.RequestConflict):
        await m.reserve(d.prepare(cfg, "private text", "BB-CC"), "group-request-123")
    assert t.reads == [42]
    assert "private text" not in str(saves) and "+1202" not in str(saves) and "chat_id" not in str(saves)


@pytest.mark.asyncio
async def test_concurrent_group_reservations_are_local_and_reserve_once():
    m, t, saves = manager([])
    plan = d.prepare(GROUP_CFG, "test", "BB-CC")
    results = await asyncio.gather(m.reserve(plan, "group-request-123"), m.reserve(plan, "group-request-123"))
    assert sorted(fresh for _, fresh in results) == [False, True]
    assert not t.reads and len(saves) == 1


@pytest.mark.asyncio
async def test_all_groups_verified_before_any_mixed_target_sent():
    chats = deepcopy(CHATS)
    chats[42]["participants"].append("+12025550109")
    m, t, saves = manager([], chats=chats)
    plan = d.prepare(GROUP_CFG, "test", "BB,AA-BB,BB-CC")
    key, _ = await m.reserve(plan, "group-request-123")
    result = await m.execute(key, plan)
    assert result["complete"] and all(r["state"] == "rejected" for r in result["results"])
    assert all(r["reason"] == "group_chat_verification_failed" for r in result["results"])
    assert t.reads == [44, 42] and not t.calls and len(saves) == 2


@pytest.mark.parametrize("changes", [
    {"id": 99}, {"id": True}, {"is_group": False}, {"is_group": 1}, {"service": "SMS"},
    {"participants": None}, {"participants": ["+12025550101"]},
    {"participants": ["+12025550101", "+12025550102", "+12025550109"]},
    {"participants": ["+12025550101", "+12025550102", "+12025550101"]},
    {"participants": ["+12025550101", "person@example.com"]},
    {"participants": ["+12025550101", 492222222222]},
])
@pytest.mark.asyncio
async def test_group_metadata_fails_closed_without_sending(changes):
    m, t, saves = manager([], chats={42: {**CHATS[42], **changes}})
    plan = d.prepare(GROUP_CFG, "test", "BB-CC,AA")
    key, _ = await m.reserve(plan, "group-request-123")
    result = await m.execute(key, plan)
    assert result["complete"] and all(r["state"] == "rejected" for r in result["results"])
    assert len(saves) == 2 and not t.calls


@pytest.mark.asyncio
async def test_group_membership_is_read_after_waiting_for_send_lock():
    m, t, _ = manager([])
    plan = d.prepare(GROUP_CFG, "test", "BB-CC,AA")
    key, _ = await m.reserve(plan, "group-request-123")
    await m.send_lock.acquire()
    task = asyncio.create_task(m.execute(key, plan))
    await asyncio.sleep(0)
    assert not t.reads
    t.chats[42]["participants"].append("+12025550109")
    m.send_lock.release()
    result = await task
    assert result["complete"] and all(r["state"] == "rejected" for r in result["results"])
    assert not t.calls and t.reads == [42]
    assert await m.reserve(plan, "group-request-123") == (key, False)
    assert t.reads == [42]


def test_group_metadata_normalizes_phone_format_and_member_order():
    target = d.prepare(GROUP_CFG, "test", "BB-CC")["targets"][0]
    d.validate_group_metadata(target, {**CHATS[42], "participants": ["+1 (202) 555-0102", " +1.202.5550101 "]})


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["unavailable", "unknown", "rejected", "accepted"])
async def test_group_never_uses_sms_or_individual_fanout(state):
    m, t, _ = manager([{"state": state, "transport": "imessage", "reason": "connection_failed"}])
    plan = d.prepare(GROUP_CFG, "test", "BB-CC")
    key, _ = await m.reserve(plan)
    result = await m.execute(key, plan)
    assert [call[0] for call in t.calls] == ["imessage_group"]
    assert t.calls[0][1] == 42 and result["results"][0]["state"] == state
    assert "fallback_reason" not in result["results"][0]


@pytest.mark.asyncio
async def test_single_and_group_transport_paths_are_independent():
    m, t, _ = manager([{"state": "unavailable", "transport": "imessage"},
                       {"state": "unavailable", "transport": "imessage"}])
    plan = d.prepare(GROUP_CFG, "test", "BB-CC,AA")
    key, _ = await m.reserve(plan)
    result = await m.execute(key, plan)
    assert [call[0] for call in t.calls] == ["imessage", "sms", "imessage_group"]
    assert [r["transport"] for r in result["results"]] == ["sms", "imessage"]


@pytest.mark.asyncio
async def test_restart_of_reserved_group_never_reads_or_resubmits():
    m, t, _ = manager([])
    plan = d.prepare(GROUP_CFG, "test", "BB-CC")
    key, _ = await m.reserve(plan, "group-request-123")
    restored, t2, _ = manager([], deepcopy(m.records))
    await restored.recover()
    assert await restored.reserve(plan, "group-request-123") == (key, False)
    result = restored.result(key)["results"][0]
    assert result["target_type"] == "group" and result["state"] == "unknown"
    assert not t2.calls and not t2.reads
