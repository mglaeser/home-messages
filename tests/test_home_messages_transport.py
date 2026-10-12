import importlib.util
from pathlib import Path
from types import SimpleNamespace

import aiohttp
import pytest

spec = importlib.util.spec_from_file_location("delivery", Path(__file__).resolve().parents[1]/"custom_components/home_messages/delivery.py")
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)

class Response:
    def __init__(self, status=202, body=None, error=None):
        self.status,self.body,self.error=status,body,error
    async def __aenter__(self):
        if self.error: raise self.error
        return self
    async def __aexit__(self,*args): return False
    async def json(self,**kwargs): return self.body

class Session:
    def __init__(self,response):self.response=response;self.calls=[]
    def post(self,url,**kwargs):
        self.calls.append((url,kwargs));return self.response
    def get(self,url,**kwargs):
        self.calls.append((url,kwargs));return self.response

CFG={"proxy_url":"http://proxy:8765", "proxy_api_key":"secret", "sipgate_token_id":"tokenid", "sipgate_token_secret":"tokensecret", "sipgate_sms_id":"s0", "sipgate_enabled":True}

@pytest.mark.asyncio
async def test_exact_proxy_request_and_no_redirects():
    s=Session(Response(body={"state":"accepted","operation_id":"op"}))
    result=await d.Transport(s).imessage(CFG,"+12025550101",'  123 & "x"\n🏠  ',"key-12345678")
    assert result["state"]=="accepted"
    url,kwargs=s.calls[0]
    assert url=="http://proxy:8765/api/messages"
    assert kwargs["headers"]=={"Authorization":"Bearer secret","Idempotency-Key":"key-12345678"}
    assert kwargs["json"]=={"recipient":"+12025550101","text":'  123 & "x"\n🏠  ',"service":"imessage"}
    assert kwargs["allow_redirects"] is False
    assert kwargs["timeout"].total > 180

@pytest.mark.asyncio
async def test_sipgate_contract():
    s=Session(Response(status=204))
    result=await d.Transport(s).sms(CFG,"+12025550101","Hello")
    assert result=={"state":"accepted","transport":"sms"}
    url,kwargs=s.calls[0]
    assert url=="https://api.sipgate.com/v2/sessions/sms"
    assert kwargs["auth"]==aiohttp.BasicAuth("tokenid","tokensecret")
    assert kwargs["json"]=={"smsId":"s0","recipient":"+12025550101","message":"Hello"}
    assert kwargs["allow_redirects"] is False

@pytest.mark.asyncio
@pytest.mark.parametrize("error,expected",[(TimeoutError(),"unknown"),(aiohttp.ServerDisconnectedError(),"unknown"),(aiohttp.ConnectionTimeoutError(),"unavailable"),(aiohttp.ClientConnectorError(SimpleNamespace(host="x",port=1,ssl=False),ConnectionRefusedError()),"unavailable")])
async def test_connect_failure_vs_ambiguous_timeout(error,expected):
    s=Session(Response(error=error))
    result=await d.Transport(s).imessage(CFG,"+12025550101","test","key-12345678")
    assert result["state"]==expected
    assert len(s.calls)==1

@pytest.mark.asyncio
async def test_check_is_get_only():
    s=Session(Response(status=200,body={"status":"ok"}))
    result=await d.Transport(s).check(CFG)
    assert result["proxy"]["authenticated"] is True
    assert s.calls[0][0].endswith("/api/status")
    assert "json" not in s.calls[0][1]


@pytest.mark.asyncio
async def test_group_request_uses_existing_chat_id_and_imessage_only():
    s = Session(Response(body={"state": "accepted", "operation_id": "op"}))
    result = await d.Transport(s).imessage_group(CFG, 42, "Group text", "group-key-123")
    assert result == {"state": "accepted", "transport": "imessage"}
    url, kwargs = s.calls[0]
    assert url == "http://proxy:8765/api/messages"
    assert kwargs["json"] == {"chat_id": 42, "text": "Group text", "service": "imessage"}
    assert kwargs["headers"]["Idempotency-Key"] == "group-key-123"
    assert kwargs["allow_redirects"] is False


@pytest.mark.asyncio
async def test_group_metadata_reads_chat_only_with_authentication():
    body = {"id": 42, "is_group": True, "service": "iMessage", "participants": ["+12025550101", "+12025550102"]}
    s = Session(Response(status=200, body=body))
    assert await d.Transport(s).group_metadata(CFG, 42) == body
    url, kwargs = s.calls[0]
    assert url == "http://proxy:8765/api/chats/42"
    assert kwargs["headers"] == {"Authorization": "Bearer secret"}
    assert kwargs["allow_redirects"] is False and "json" not in kwargs
    assert kwargs["timeout"].total == 35


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [202, 301, 401, 403, 404, 409, 429, 500, 503])
async def test_group_metadata_http_failure_stops_request(status):
    s = Session(Response(status=status, body={}))
    with pytest.raises(d.RequestError):
        await d.Transport(s).group_metadata(CFG, 42)
    assert len(s.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [TimeoutError(), aiohttp.ServerDisconnectedError(), ValueError("bad json")])
async def test_group_metadata_read_failure_stops_request(error):
    s = Session(Response(error=error))
    with pytest.raises(d.RequestError):
        await d.Transport(s).group_metadata(CFG, 42)
    assert len(s.calls) == 1
