import httpx
import pytest

from scripts.verify_warp_proxy import TRACE_URL, verify_route
from utils.proxy import get_playwright_proxy, get_proxy_server

STATUS_URL = 'https://agentrouter.example/api/status'


@pytest.mark.parametrize(
	('warp', 'status', 'body', 'content_type', 'passes'),
	[
		('on', 200, '{"success":true,"data":{"system_name":"AgentRouter"}}', 'application/json', True),
		('off', 200, '{"success":true,"data":{"system_name":"AgentRouter"}}', 'application/json', False),
		('on', 200, '<html>Access Verification</html>', 'text/html', False),
		('on', 403, '{"success":false}', 'application/json', False),
		('on', 200, '{"success":false,"data":{}}', 'application/json', False),
		('on', 200, '{"success":true,"data":{}}', 'application/json', False),
		('on', 200, '[]', 'application/json', False),
	],
)
def test_preflight_rejects_direct_exits_and_waf_pages(warp, status, body, content_type, passes):
	def respond(request):
		if str(request.url) == TRACE_URL:
			return httpx.Response(200, text=f'warp={warp}\n')
		assert str(request.url) == STATUS_URL
		return httpx.Response(status, text=body, headers={'content-type': content_type})

	with httpx.Client(transport=httpx.MockTransport(respond)) as client:
		if passes:
			verify_route(client, STATUS_URL)
		else:
			with pytest.raises((ValueError, httpx.HTTPStatusError)):
				verify_route(client, STATUS_URL)


def test_required_proxy_does_not_fall_back_to_direct(monkeypatch):
	monkeypatch.setenv('CHECKIN_PROXY_REQUIRED', 'true')
	monkeypatch.delenv('CHECKIN_PROXY_URL', raising=False)
	with pytest.raises(RuntimeError, match='refusing direct access'):
		get_playwright_proxy()
	assert get_proxy_server(use_proxy=False) is None


def test_browser_and_http_client_accept_the_same_socks_proxy(monkeypatch):
	monkeypatch.setenv('CHECKIN_PROXY_URL', 'socks5://127.0.0.1:40000')
	assert get_playwright_proxy() == {'server': get_proxy_server()}
	# Construction exercises the SOCKS dependency without making network requests.
	with httpx.Client(proxy=get_proxy_server(), http2=True, trust_env=False):
		pass
