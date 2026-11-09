"""Compare unauthenticated AgentRouter responses on direct and WARP routes."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = 'https://agentrouter.org'
TRACE_URL = 'https://www.cloudflare.com/cdn-cgi/trace'
WARP_PROXY = 'socks5h://127.0.0.1:40000'
USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36'
WAF_MARKERS = re.compile(
	r'aliyun_waf_|aliyunCaptcha|Access Verification|slide to verify|request has been blocked', re.I
)


def fetch(url: str, proxy: str) -> dict:
	# Explicit proxy arguments override the runner's ambient proxy environment.
	command = [
		'curl',
		'-q',
		'--silent',
		'--show-error',
		'--include',
		'--suppress-connect-headers',
		'--connect-timeout',
		'8',
		'--max-time',
		'15',
		'--max-filesize',
		'262144',
		'--user-agent',
		USER_AGENT,
		f'--proxy={proxy}',
		f'--noproxy={"" if proxy else "*"}',
		url,
	]
	try:
		process = subprocess.run(
			command, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=20
		)
	except (OSError, subprocess.TimeoutExpired) as error:
		return {'status': 0, 'body': '', 'headers': {}, 'error': type(error).__name__}
	if process.returncode:
		return {'status': 0, 'body': '', 'headers': {}, 'error': f'curl_exit_{process.returncode}'}
	header_text, separator, body = process.stdout.partition('\n\n')
	match = re.match(r'HTTP/\S+ (\d{3})', header_text)
	if not separator or not match:
		return {'status': 0, 'body': '', 'headers': {}, 'error': 'invalid_http_response'}
	headers = {}
	for line in header_text.splitlines()[1:]:
		name, colon, value = line.partition(':')
		if colon:
			headers[name.lower()] = value.strip()
	return {'status': int(match.group(1)), 'body': body, 'headers': headers}


def classify(path: str, response: dict) -> dict:
	body = response['body']
	headers = response['headers']
	result = {
		'path': path,
		'http_status': response['status'],
		'content_type': headers.get('content-type', ''),
		'classification': 'unexpected_response',
	}
	if response.get('error'):
		result.update(classification='network_error', error=response['error'])
	elif WAF_MARKERS.search(body):
		result['classification'] = 'waf_challenge'
	elif path == '/api/status' and response['status'] == 200:
		try:
			payload = json.loads(body)
		except (ValueError, TypeError):
			payload = None
		if isinstance(payload, dict) and payload.get('success') is True and isinstance(payload.get('data'), dict):
			if 'system_name' in payload['data'] and 'application/json' in result['content_type'].lower():
				result['classification'] = 'application_response'
	elif path == '/login' and response['status'] == 200:
		if re.search(r'<title>\s*Agent\s*Router\s*</title>', body, re.I) and '<script' in body:
			result['classification'] = 'application_response'
	request_id = headers.get('request-id') or headers.get('x-oneapi-request-id')
	if not request_id:
		match = re.search(r'(?:TraceID:|Your Request ID is:)\s*([a-zA-Z0-9_-]+)', body)
		request_id = match.group(1) if match else None
	if request_id:
		result['request_id'] = request_id
	# Cookie values, registration credentials, and raw page bodies stay out of reports.
	return result


def observe_route(proxy: str) -> dict:
	response = fetch(TRACE_URL, proxy)
	fields = dict(line.split('=', 1) for line in response['body'].splitlines() if '=' in line)
	return {
		'ip': fields.get('ip') if response['status'] == 200 else None,
		'warp': fields.get('warp') if response['status'] == 200 else None,
		'error': response.get('error'),
	}


def observe_site(proxy: str) -> list[dict]:
	return [classify(path, fetch(BASE_URL + path, proxy)) for path in ('/login', '/api/status')]


def compare(direct: dict, warp_rounds: list[dict]) -> dict:
	route_verified = (
		bool(direct['route'].get('ip'))
		and direct['route'].get('warp') == 'off'
		and all(
			round_['route'].get('warp') in {'on', 'plus'}
			and round_['route'].get('ip')
			and round_['route']['ip'] != direct['route']['ip']
			for round_ in warp_rounds
		)
	)
	public_pages_passed = bool(warp_rounds) and all(
		{response['path'] for response in round_['responses']} == {'/login', '/api/status'}
		and all(response['classification'] == 'application_response' for response in round_['responses'])
		for round_ in warp_rounds
	)
	success = len(warp_rounds) == 2 and route_verified and public_pages_passed
	baseline_challenged = any(item['classification'] == 'waf_challenge' for item in direct['responses'])
	if not success:
		comparison = 'warp_route_or_public_pages_not_verified'
	elif baseline_challenged:
		comparison = 'direct_challenged_warp_public_pages_passed'
	elif all(item['classification'] == 'application_response' for item in direct['responses']):
		comparison = 'both_routes_passed_block_not_reproduced'
	else:
		comparison = 'warp_public_pages_passed_baseline_inconclusive'
	return {
		'comparison': comparison,
		'warp_route_verified': route_verified,
		'public_pages_passed': public_pages_passed,
		'probe_passed': success,
		'authenticated_checkin_tested': False,
	}


def main() -> int:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument('phase', choices=('direct', 'warp'))
	args = parser.parse_args()
	project_root = Path(__file__).resolve().parents[1]
	if Path.cwd().resolve() != project_root:
		parser.error('Run this script from its project root')
	report_dir = (project_root / '.cache' / 'warp-probe').resolve()
	if not report_dir.is_relative_to(project_root):
		parser.error('Report directory must remain inside the project')
	report_dir.mkdir(parents=True, exist_ok=True)
	for filename in ('direct.json', 'result.json'):
		if not (report_dir / filename).resolve().is_relative_to(project_root):
			parser.error('Report files must remain inside the project')
	if args.phase == 'direct':
		result = {
			'time_utc': datetime.now(timezone.utc).isoformat(),
			'route': observe_route(''),
			'responses': observe_site(''),
		}
		(report_dir / 'direct.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
		print(json.dumps(result, indent=2))
		return 0
	direct = json.loads((report_dir / 'direct.json').read_text(encoding='utf-8'))
	for attempt in range(6):
		route = observe_route(WARP_PROXY)
		if route.get('warp') in {'on', 'plus'}:
			break
		if attempt < 5:
			time.sleep(5)
	rounds = []
	for attempt in range(2):
		if attempt:
			time.sleep(15)
			route = observe_route(WARP_PROXY)
		rounds.append(
			{'time_utc': datetime.now(timezone.utc).isoformat(), 'route': route, 'responses': observe_site(WARP_PROXY)}
		)
	result = {**compare(direct, rounds), 'direct': direct, 'warp_rounds': rounds}
	(report_dir / 'result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
	print(json.dumps(result, indent=2))
	return 0 if result['probe_passed'] else 1


if __name__ == '__main__':
	raise SystemExit(main())
