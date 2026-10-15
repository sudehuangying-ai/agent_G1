from checkin import get_user_info


class FakeResponse:
	def __init__(self, data):
		self.status_code = 200
		self._data = data

	def json(self):
		return self._data


class FakeClient:
	def __init__(self, data):
		self._data = data

	def get(self, url, headers, timeout):
		return FakeResponse(self._data)


def test_get_user_info_extracts_response_group():
	client = FakeClient(
		{
			'success': True,
			'data': {
				'quota': 337901096,
				'used_quota': 612098904,
				'group': 'core',
			},
		}
	)

	user_info = get_user_info(client, {}, 'https://example.com/api/user/self')

	assert user_info['success'] is True
	assert user_info['group'] == 'core'
