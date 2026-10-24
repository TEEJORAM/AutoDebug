import unittest

from autodebug.redact import REDACTED, clean_text, clean_value


class Redaction(unittest.TestCase):
    def test_secret_names(self):
        for name in ("password", "db_pass", "API_KEY", "accessKey", "auth_header", "session_id", "githubToken", "Cookie"):
            with self.subTest(name=name):
                self.assertEqual(clean_value(name, "'hunter2'"), REDACTED)
        for name in ("author", "points", "total", "i", "keyboard_layout"):
            with self.subTest(name=name):
                self.assertEqual(clean_value(name, "1"), "1")

    def test_secret_shaped_values(self):
        for secret in ("AKIA" + "A" * 16, "sk-" + "a1B2" * 6, "ghp_" + "x" * 36, "eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.abcdefghijklmnop",
                       "-----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY-----"):
            with self.subTest(secret=secret[:10]):
                self.assertNotIn(secret, clean_value("value", f"x {secret} y"))

    def test_length_cap(self):
        text = clean_text("a" * 5000, 100)
        self.assertTrue(text.startswith("a" * 100) and text.endswith("(4900 more characters)"))


if __name__ == "__main__":
    unittest.main()
