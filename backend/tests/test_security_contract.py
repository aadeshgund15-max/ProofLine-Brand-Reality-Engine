import dataclasses
import time
import unittest
from uuid import uuid4
from unittest.mock import patch

import jwt
from fastapi import HTTPException
from app.auth import Member, User
from app.routers import library

from app.auth import _decode, hash_password, issue_local_token, verify_password
from app.config import settings


class AuthenticationSecurityTests(unittest.TestCase):
    def test_local_token_is_signed_and_bounded_to_authenticated_audience(self):
        local = dataclasses.replace(settings, auth_mode="local", local_jwt_secret="local-unit-test-secret-32-bytes-minimum")
        with patch("app.auth.settings", local):
            token = issue_local_token(uuid4(), "judge@example.test")
            claims = _decode(token)
        self.assertEqual(claims["aud"], "authenticated")
        self.assertEqual(claims["iss"], "proofline-local")
        self.assertGreater(claims["exp"], claims["iat"])

    def test_local_auth_rejects_expired_unsigned_and_wrong_audience_tokens(self):
        secret = "local-unit-test-secret-32-bytes-minimum"
        local = dataclasses.replace(settings, auth_mode="local", local_jwt_secret=secret)
        now = int(time.time())
        invalid = [
            jwt.encode({"sub": str(uuid4()), "email": "u@example.test", "aud": "authenticated",
                        "iat": now - 20, "exp": now - 10}, secret, algorithm="HS256"),
            jwt.encode({"sub": str(uuid4()), "email": "u@example.test", "aud": "other",
                        "iat": now, "exp": now + 60}, secret, algorithm="HS256"),
            jwt.encode({"sub": str(uuid4()), "email": "u@example.test", "aud": "authenticated",
                        "iat": now, "exp": now + 60}, "", algorithm="none"),
        ]
        with patch("app.auth.settings", local):
            for token in invalid:
                with self.subTest(token=token[-12:]), self.assertRaises(HTTPException) as caught:
                    _decode(token)
                self.assertEqual(caught.exception.status_code, 401)

    def test_supabase_legacy_token_uses_configured_secret_and_audience(self):
        secret = "test-only-supabase-hs256-secret-at-least-32-bytes"
        supabase = dataclasses.replace(settings, auth_mode="supabase", supabase_jwt_secret=secret)
        now = int(time.time())
        token = jwt.encode({"sub": str(uuid4()), "email": "u@example.test", "aud": "authenticated",
                            "iat": now, "exp": now + 600}, secret, algorithm="HS256")
        with patch("app.auth.settings", supabase):
            self.assertEqual(_decode(token)["aud"], "authenticated")
        wrong_audience = jwt.encode({"sub": str(uuid4()), "email": "u@example.test", "aud": "public",
                                     "iat": now, "exp": now + 600}, secret, algorithm="HS256")
        with patch("app.auth.settings", supabase), self.assertRaises(HTTPException) as caught:
            _decode(wrong_audience)
        self.assertEqual(caught.exception.status_code, 401)

    def test_local_password_hash_verifies_without_storing_plaintext(self):
        encoded = hash_password("demonstration-password")
        self.assertTrue(encoded.startswith("scrypt$"))
        self.assertNotIn("demonstration-password", encoded)
        self.assertTrue(verify_password("demonstration-password", encoded))
        self.assertFalse(verify_password("incorrect-password", encoded))


class BrandApprovalPermissionTests(unittest.TestCase):
    def setUp(self):
        self.workspace_id = uuid4()
        self.profile_id = uuid4()
        self.editor = Member(User(uuid4(), "editor@example.test"), self.workspace_id, "editor")

    def test_editor_cannot_create_an_approved_fact(self):
        body = library.FactIn(brand_profile_id=self.profile_id, key="fact", name="Fact", approved_value="Value",
                              value_type="text", status="approved")
        with patch("app.routers.library.q1", return_value={"id": self.profile_id}):
            with self.assertRaises(HTTPException) as caught:
                library.create_fact(body, self.editor, object())
        self.assertEqual(caught.exception.status_code, 403)

    def test_editor_cannot_create_an_approved_rule(self):
        body = library.RuleIn(brand_profile_id=self.profile_id, key="rule", rule_type="prohibited_phrase",
                              description="Rule", patterns=["term"], status="approved")
        with patch("app.routers.library.q1", return_value={"id": self.profile_id}):
            with self.assertRaises(HTTPException) as caught:
                library.create_rule(body, self.editor, object())
        self.assertEqual(caught.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
