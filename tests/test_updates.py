import unittest

from hoshi_terminal.updates import UpdateInfo, _version_key, format_update_info


class UpdateTests(unittest.TestCase):
    def test_version_key_compares_semver(self) -> None:
        self.assertGreater(_version_key("0.1.10"), _version_key("0.1.4"))
        self.assertEqual(_version_key("v0.1.4"), (0, 1, 4))

    def test_format_update_info_includes_one_click_install_commands(self) -> None:
        text = format_update_info(
            UpdateInfo(
                current_version="0.1.3",
                latest_version="0.1.4",
                release_url="https://example.test/release",
                has_update=True,
            )
        )

        self.assertIn("发现新版本", text)
        self.assertIn("install.sh", text)
        self.assertIn("install.ps1", text)


if __name__ == "__main__":
    unittest.main()
