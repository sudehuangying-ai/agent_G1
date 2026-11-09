"""Require a working WARP exit and a real AgentRouter JSON response before login."""

from __future__ import annotations

import time

import httpx

from utils.config import AppConfig
from utils.proxy import get_proxy_server

TRACE_URL = 'https://www.cloudflare.com/cdn-cgi/trace'


def verify_route(client: httpx.Client, status_url: str) -> None:
	trace = client.get(TRACE_URL)
	trace.raise_for_status()
	fields = dict(line.split('=', 1) for line in trace.text.splitlines() if '=' in line)
	if fields.get('warp') not in {'on', 'plus'}:
		raise ValueError('The proxy is not using WARP')

	response = client.get(status_url)
	response.raise_for_status()
	if 'application/json' not in response.headers.get('content-type', '').lower():
		raise ValueError('AgentRouter returned a non-JSON response')
	payload = response.json()
	if not isinstance(payload, dict) or payload.get('success') is not True or not isinstance(payload.get('data'), dict):
		raise ValueError('AgentRouter returned an invalid status response')
	if 'system_name' not in payload['data']:
		raise ValueError('AgentRouter status response is missing system information')


def main() -> int:
	proxy = get_proxy_server()
	if not proxy:
		print('[WARP] Proxy address is missing; refusing direct access')
		return 1
	provider = AppConfig.load_from_env().providers['agentrouter']
	if not provider.use_proxy:
		print('[WARP] AgentRouter use_proxy must be true; refusing direct access')
		return 1
	status_url = f'{provider.domain.rstrip("/")}/api/status'
	with httpx.Client(proxy=proxy, trust_env=False, http2=True, timeout=8.0) as client:
		for attempt in range(12):
			try:
				verify_route(client, status_url)
				print('[WARP] Verified warp=on and AgentRouter /api/status JSON through the HTTP client')
				return 0
			except (httpx.HTTPError, ValueError) as error:
				print(f'[WARP] Readiness attempt {attempt + 1}/12 failed: {type(error).__name__}')
				if attempt < 11:
					time.sleep(2)
	print('[WARP] Exit or AgentRouter verification failed; refusing direct access')
	return 1


if __name__ == '__main__':
	raise SystemExit(main())
