"""DouyinClient 单元测试

运行: .venv/Scripts/python.exe test_douyin_client.py
策略: 仅 mock douyin SDK 函数，PySide6 用项目真实安装。
"""

import sys, os, unittest
from unittest.mock import MagicMock, PropertyMock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class TestDouyinClient(unittest.TestCase):
    """DouyinClient 接口契约测试"""

    @classmethod
    def setUpClass(cls):
        cls.mock_auth = MagicMock()
        cls.mock_auth.get_uid.return_value = 123456789
        type(cls.mock_auth).ticket = PropertyMock(return_value="mock_ticket_abc")

        # Patch douyin_sdk 模块的函数
        cls._patches = [
            patch('dmshoot.utils.douyin_sdk.create_auth',
                  return_value=cls.mock_auth),
            patch('dmshoot.utils.douyin_sdk.send_message_cached',
                  return_value=True),
            patch('dmshoot.utils.douyin_ws.DouyinWSReceiver',
                  MagicMock()),
            patch('dmshoot.utils.douyin_im_sync.fetch_conversations_sync',
                  return_value=[{'peer_uid': '111', 'nickname': '测试', 'avatar': ''}]),
            patch('dmshoot.utils.douyin_im_sync.get_cached_messages',
                  return_value=[]),
        ]
        for p in cls._patches:
            p.start()

    @classmethod
    def tearDownClass(cls):
        for p in cls._patches:
            p.stop()

    def setUp(self):
        # Reset mock state between tests
        self.mock_auth.get_uid.return_value = 123456789
        from dmshoot.plugins.douyin.douyin_client import DouyinClient
        self.client = DouyinClient("mock_cookie")

    def test_create_auth_and_uid(self):
        self.assertEqual(self.client.uid, "123456789")

    def test_ticket(self):
        self.assertEqual(self.client.ticket, "mock_ticket_abc")
        self.assertTrue(self.client.has_ticket)

    def test_auth_exposed(self):
        self.assertIs(self.client.auth, self.mock_auth)

    def test_connect_ok(self):
        ok, err = self.client.connect()
        self.assertTrue(ok)

    def test_connect_uid_empty(self):
        self.mock_auth.get_uid.return_value = None
        ok, err = self.client.connect()
        self.assertFalse(ok)

    def test_send_message(self):
        ok = self.client.send_message(111, "测试")
        self.assertTrue(ok)

    def test_fetch_history(self):
        convs = self.client.fetch_history()
        self.assertEqual(len(convs), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
