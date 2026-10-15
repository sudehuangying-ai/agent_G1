from checkin import format_check_in_notification


def test_format_check_in_notification_includes_group():
	detail = {
		'name': '测试账号',
		'group': 'core',
		'before_quota': 1.0,
		'before_used': 0.2,
		'after_quota': 1.5,
		'after_used': 0.2,
		'check_in_reward': 0.5,
		'usage_increase': 0,
		'balance_change': 0.5,
	}

	notification = format_check_in_notification(detail)

	assert notification.startswith('[CHECK-IN] 测试账号（分组: core）')
