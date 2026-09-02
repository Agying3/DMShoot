"""字体构建、打包覆盖和设置页同步线程回归测试。"""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("fontTools")

PROJECT = Path(__file__).resolve().parents[1]


def _copy_bundled_fonts(root: Path) -> Path:
    bundled = root / "bundle" / "fonts"
    bundled.mkdir(parents=True)
    (bundled / "full").mkdir()
    shutil.copy2(PROJECT / "tools" / "fonts" / "AaCute-UI.ttf", bundled / "AaCute-UI.ttf")
    shutil.copy2(
        PROJECT / "tools" / "fonts" / "full" / "AaCute-full.ttf",
        bundled / "full" / "AaCute-full.ttf",
    )
    return bundled


def test_builder_emits_real_woff(tmp_path):
    from fontTools.ttLib import TTFont

    from dmshoot.core.font_builder import build_ui_subset

    font_dir = tmp_path / "fonts"
    (font_dir / "full").mkdir(parents=True)
    shutil.copy2(
        PROJECT / "tools" / "fonts" / "full" / "AaCute-full.ttf",
        font_dir / "full" / "AaCute-full.ttf",
    )

    result = build_ui_subset(font_dir, commit=True)
    ttf_path = Path(result["path"])
    woff_path = Path(result["woff_path"])

    assert ttf_path.exists()
    assert woff_path.exists()
    assert woff_path.read_bytes()[:4] == b"wOFF"

    ttf = TTFont(str(ttf_path))
    woff = TTFont(str(woff_path))
    try:
        assert ttf.getBestCmap()
        assert woff.flavor == "woff"
        assert woff["name"].getDebugName(1) == "Aa偷吃可爱长大的 UI"
    finally:
        ttf.close()
        woff.close()


@pytest.mark.gui
def test_frozen_font_dir_uses_user_override_and_survives_restart(tmp_path, monkeypatch, qapp):
    from dmshoot.gui.font_manager import FontManager

    bundled = _copy_bundled_fonts(tmp_path)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundled.parent), raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))

    user_dir = FontManager.resolve_font_dir()
    assert user_dir == (tmp_path / "localappdata" / "DMShoot" / "fonts").resolve()
    user_dir.mkdir(parents=True)
    user_font = user_dir / "AaCute-UI.ttf"
    shutil.copy2(bundled / "AaCute-UI.ttf", user_font)

    manager = FontManager(user_dir)
    try:
        assert manager._ui_path == user_font.resolve()
        assert manager.ui_family
        assert manager._bundled_font_dir == bundled.resolve()
    finally:
        if manager.ui_id >= 0:
            from PySide6.QtGui import QFontDatabase

            QFontDatabase.removeApplicationFont(manager.ui_id)


@pytest.mark.gui
def test_reload_failure_restores_bundled_font(tmp_path, monkeypatch, qapp):
    from dmshoot.gui.font_manager import FontManager

    bundled = _copy_bundled_fonts(tmp_path)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundled.parent), raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))

    user_dir = FontManager.resolve_font_dir()
    manager = FontManager(user_dir)
    old_path = manager._ui_path
    bad_candidate = tmp_path / "AaCute-UI.ttf.bad.tmp"
    bad_candidate.write_bytes(b"not-a-font")

    try:
        assert not manager.reload_ui_font(bad_candidate)
        assert manager.ui_family
        assert manager._ui_path == old_path
        assert old_path.exists()
        assert not (user_dir / "AaCute-UI.ttf").exists()
    finally:
        if manager.ui_id >= 0:
            from PySide6.QtGui import QFontDatabase

            QFontDatabase.removeApplicationFont(manager.ui_id)


@pytest.mark.gui
def test_settings_waits_for_font_worker_before_closing(qapp, qtbot, temp_db, tmp_path, monkeypatch):
    from dmshoot.core import font_builder
    from dmshoot.gui.settings_dialog import SettingsDialog
    from dmshoot.storage.models import AppConfig

    class FakeFontManager:
        font_dir = tmp_path / "fonts"
        ui_family = "Aa UI"
        current_mode = "ui-aacute"

        def apply(self, mode):
            self.current_mode = mode
            return mode

        def reload_ui_font(self, _temporary_path):
            return True

    def slow_build(_font_dir, commit=False):
        assert commit is False
        time.sleep(0.15)
        return {"temporary_path": "", "chars": 2, "total": 3}

    monkeypatch.setattr(font_builder, "build_ui_subset", slow_build)
    dialog = SettingsDialog(AppConfig(), font_manager=FakeFontManager())
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._on_sync_font()

    qtbot.waitUntil(
        lambda: dialog._sync_worker is not None and dialog._sync_worker.isRunning(),
        timeout=2000,
    )
    dialog.reject()
    assert dialog.isVisible()

    qtbot.waitUntil(lambda: dialog._sync_worker is None, timeout=5000)
    qtbot.waitUntil(lambda: not dialog.isVisible(), timeout=2000)
