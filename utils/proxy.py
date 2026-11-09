"""代理配置：读取环境变量并供浏览器 / HTTP 客户端使用。"""

from __future__ import annotations

import os


def get_proxy_server(*, use_proxy: bool = True) -> str | None:
	"""按平台配置读取 CHECKIN_PROXY_URL；use_proxy=False 时不返回代理地址。"""
	if not use_proxy:
		return None
	server = os.getenv('CHECKIN_PROXY_URL', '').strip()
	if not server and os.getenv('CHECKIN_PROXY_REQUIRED', '').lower() == 'true':
		raise RuntimeError('CHECKIN_PROXY_REQUIRED=true but CHECKIN_PROXY_URL is missing; refusing direct access')
	return server or None


def get_playwright_proxy(*, use_proxy: bool = True) -> dict[str, str] | None:
	server = get_proxy_server(use_proxy=use_proxy)
	if not server:
		return None
	return {'server': server}
