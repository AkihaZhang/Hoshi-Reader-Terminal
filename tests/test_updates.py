import unittest
from pathlib import Path
import tempfile
import zipfile

from hoshi_terminal.updates import (
    ReleaseAsset,
    UpdateInfo,
    _version_key,
    extract_pyz_from_package,
    format_update_info,
    package_platform,
    release_asset_for_platform,
)


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
        self.assertIn("hoshi 更新", text)
        self.assertIn("install.sh", text)
        self.assertIn("install.ps1", text)

    def test_release_asset_for_platform_selects_current_package(self) -> None:
        platform_name = package_platform()
        suffix = ".zip" if platform_name == "windows" else ".tar.gz"
        asset_name = f"Hoshi-Reader-Terminal-0.2.0-{platform_name}{suffix}"
        asset = release_asset_for_platform(
            UpdateInfo(
                current_version="0.1.0",
                latest_version="0.2.0",
                release_url="https://example.test/release",
                has_update=True,
                assets=[ReleaseAsset(name=asset_name, download_url="https://example.test/package")],
            )
        )

        self.assertEqual(asset.name, asset_name)

    def test_extract_pyz_from_zip_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package = root / "package.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("Hoshi-Reader-Terminal/hoshi-terminal.pyz", "pyz")

            extracted = extract_pyz_from_package(package, root / "out")

        self.assertEqual(extracted.name, "hoshi-terminal.pyz")


if __name__ == "__main__":
    unittest.main()
