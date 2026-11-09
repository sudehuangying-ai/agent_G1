"""Run one real AgentRouter browser login through the verified WARP proxy."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from scripts.probe_warp import BASE_URL, TRACE_URL
from utils.browser import (
	launch_login_context,
	load_browser_login_settings,
	login_with_email_form,
	navigate_login_page,
	prepare_browser_page,
	verify_browser_login,
)
from utils.config import load_accounts_config


class DiagnosticFailure(Exception):
	"""A fixed diagnostic error code that is safe to include in public logs."""


def summarize_login(status: int, payload: object) -> dict:
	data = payload.get('data') if isinstance(payload, dict) else None
	api_success = (
		status == 200
		and isinstance(payload, dict)
		and payload.get('success') is True
		and isinstance(data, dict)
		and bool(data.get('id'))
	)
	checked_in = data.get('checked_in') if api_success else None
	if not isinstance(checked_in, bool):
		checked_in = None
	return {'login_http_status': status, 'login_api_success': api_success, 'checked_in': checked_in}


def evaluate_result(login: dict, profile_matches_login: bool) -> dict:
	passed = login['login_api_success'] and profile_matches_login and login['checked_in'] is not None
	if not login['login_api_success']:
		outcome = 'login_api_rejected'
	elif not profile_matches_login:
		outcome = 'authenticated_profile_not_verified'
	elif login['checked_in'] is None:
		outcome = 'authenticated_but_checkin_result_missing'
	elif login['checked_in']:
		outcome = 'authenticated_and_reward_granted'
	else:
		outcome = 'authenticated_without_new_reward'
	return {'outcome': outcome, 'profile_verified': profile_matches_login, 'probe_passed': passed}


def mask_account_values(account) -> None:
	if os.getenv('GITHUB_ACTIONS') != 'true':
		return
	for value in (account.email, account.password, account.api_user):
		if value:
			escaped = str(value).replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
			print(f'::add-mask::{escaped}', flush=True)


async def run_diagnostic(report: dict) -> None:
	accounts = load_accounts_config()
	if not accounts or len(accounts) != 1 or accounts[0].provider != 'agentrouter':
		raise DiagnosticFailure('expected_exactly_one_agentrouter_account')
	account = accounts[0]
	if (
		not account.has_login_credentials()
		or not isinstance(account.email, str)
		or not isinstance(account.password, str)
	):
		raise DiagnosticFailure('email_password_credentials_required')
	mask_account_values(account)
	if os.getenv('CHECKIN_PROXY_URL') != 'socks5://127.0.0.1:40000':
		raise DiagnosticFailure('expected_local_warp_proxy')
	if os.getenv('DEBUG_MODE', '').lower() != 'false':
		raise DiagnosticFailure('sensitive_debug_output_must_be_disabled')
	settings = load_browser_login_settings('agent_G1', 'agentrouter', persist_profile=False)
	report['stage'] = 'launch_browser'
	context = await launch_login_context(settings, use_proxy=True)
	try:
		page = await context.new_page()
		report['stage'] = 'verify_browser_egress'
		await page.goto(TRACE_URL, wait_until='domcontentloaded', timeout=30_000)
		trace = await page.locator('body').inner_text()
		fields = dict(line.split('=', 1) for line in trace.splitlines() if '=' in line)
		report['browser_route'] = {'ip': fields.get('ip'), 'warp': fields.get('warp')}
		if fields.get('warp') not in {'on', 'plus'} or not fields.get('ip'):
			raise DiagnosticFailure('browser_warp_egress_not_verified')
		report['stage'] = 'navigate_login_page'
		await prepare_browser_page(page)
		await navigate_login_page(
			page, f'{BASE_URL}/login', settings.wait_timeout_ms, provider='agentrouter', account_name='agent_G1'
		)
		report['stage'] = 'submit_real_login'
		async with page.expect_response(
			lambda response: (
				response.request.method == 'POST'
				and urlsplit(response.url).netloc == 'agentrouter.org'
				and urlsplit(response.url).path == '/api/user/login'
			),
			timeout=settings.wait_timeout_ms,
		) as login_response_info:
			await login_with_email_form(
				page,
				account.email,
				account.password,
				settings.wait_timeout_ms,
				provider='agentrouter',
				account_name='agent_G1',
			)
		login_response = await login_response_info.value
		try:
			login_payload = await login_response.json()
		except Exception:
			raise DiagnosticFailure('login_response_was_not_json') from None
		login = summarize_login(login_response.status, login_payload)
		report.update(login)
		if not login['login_api_success']:
			raise DiagnosticFailure('login_api_rejected')
		report['stage'] = 'verify_authenticated_profile'
		profile = await verify_browser_login(page, f'{BASE_URL}/console', settings.wait_timeout_ms)
		profile_matches = bool(profile and str(profile.get('id')) == str(login_payload['data']['id']))
		report.update(evaluate_result(login, profile_matches))
		report['stage'] = 'complete'
	finally:
		await context.close()


def main() -> int:
	project_root = Path(__file__).resolve().parents[1]
	if Path.cwd().resolve() != project_root:
		raise SystemExit('Run this diagnostic from its project root')
	report_dir = (project_root / '.cache' / 'warp-probe').resolve()
	report_path = (report_dir / 'checkin-result.json').resolve()
	if not report_dir.is_relative_to(project_root) or not report_path.is_relative_to(project_root):
		raise SystemExit('Diagnostic output must stay inside the project')
	report_dir.mkdir(parents=True, exist_ok=True)
	report = {
		'time_utc': datetime.now(timezone.utc).isoformat(),
		'target': BASE_URL,
		'account_count': 1,
		'stage': 'validate_configuration',
		'login_api_success': False,
		'profile_verified': False,
		'checked_in': None,
		'probe_passed': False,
	}
	try:
		asyncio.run(run_diagnostic(report))
	except DiagnosticFailure as error:
		report.update(error=str(error), probe_passed=False)
	except Exception as error:
		# Playwright exception messages can contain form values or response data.
		report.update(error_type=type(error).__name__, probe_passed=False)
	report['completed_utc'] = datetime.now(timezone.utc).isoformat()
	report_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
	print(json.dumps(report, indent=2))
	return 0 if report['probe_passed'] else 1


if __name__ == '__main__':
	raise SystemExit(main())
