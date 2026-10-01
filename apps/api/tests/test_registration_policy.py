import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.modules.auth.controller import register
from app.modules.auth.schemas import RegisterRequest


class RegistrationPolicyTest(unittest.TestCase):
    def test_registration_can_be_disabled_for_single_account_deployment(self):
        with patch("app.modules.auth.controller.get_settings", return_value=SimpleNamespace(allow_registration=False)):
            with self.assertRaises(HTTPException) as error:
                register(RegisterRequest(username="another-user", password="password123"), db=None)
        self.assertEqual(error.exception.status_code, 403)
