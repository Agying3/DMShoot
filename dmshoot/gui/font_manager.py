"""DMShoot GUI 字体管理。

UI 字体在启动时加载，完整版字体按需加载。子集构建是文件操作，GUI
同步时应放到后台线程；QFontDatabase 的热加载必须回到 Qt 主线程。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
import os
import shutil

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication


UI_MODE = "ui-aacute"
SYSTEM_MODE = "system"
FULL_MODE = "full-aacute"
VALID_MODES = (SYSTEM_MODE, UI_MODE, FULL_MODE)


@dataclass(slots=True)
class RebuildResult:
    status: str  # ok | skipped | error
    chars: int = 0
    reason: str = ""


class FontManager:
    """进程内唯一的字体加载器。"""

    _instance: "FontManager | None" = None

    def __init__(self, font_dir: str | Path):
        self.font_dir = Path(font_dir).resolve()
        self._bundled_font_dir = self._resolve_bundled_font_dir()
        self.ui_id = -1
        self.ui_family = ""
        self._ui_path = self.font_dir / "AaCute-UI.ttf"
        self.full_id = -1
        self.full_family = ""
        self.current_mode = UI_MODE
        self.current_family = ""
        self._load_ui_font()

    @classmethod
    def instance(cls, font_dir: str | Path | None = None) -> "FontManager":
        if cls._instance is None:
            if font_dir is None:
                font_dir = cls.resolve_font_dir()
            cls._instance = cls(font_dir)
        return cls._instance

    @classmethod
    def reset_for_tests(cls) -> None:
        """测试用；生产代码不应重置字体单例。"""
        cls._instance = None

    @staticmethod
    def resolve_font_dir() -> Path:
        """返回字体写入目录；打包版始终使用用户可写目录。"""
        if getattr(sys, "frozen", False):
            return FontManager._user_font_dir()
        project_root = Path(__file__).resolve().parents[2]
        return project_root / "tools" / "fonts"

    @staticmethod
    def _user_font_dir() -> Path:
        """返回打包版的用户字体覆盖目录，不在启动时创建。"""
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            base = Path(local_app_data)
        else:
            base = Path.home() / "AppData" / "Local"
        return base / "DMShoot" / "fonts"

    @staticmethod
    def _resolve_bundled_font_dir() -> Path:
        """解析只读的程序内置字体目录。"""
        if getattr(sys, "frozen", False):
            return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "fonts"
        project_root = Path(__file__).resolve().parents[2]
        return project_root / "tools" / "fonts"

    @staticmethod
    def _font_family(font_id: int) -> str:
        if font_id < 0:
            return ""
        families = QFontDatabase.applicationFontFamilies(font_id)
        return families[0] if families else ""

    def _load_ui_font(self) -> str:
        path = self._promote_pending_ui_font()
        if not path.exists():
            bundled = self._bundled_font_dir / "AaCute-UI.ttf"
            if bundled.exists():
                path = bundled
        self._ui_path = path
        if not path.exists():
            print(f"警告: UI 字体不存在，回退系统字体: {path}", file=sys.stderr)
            return ""
        self.ui_id = QFontDatabase.addApplicationFont(str(path))
        self.ui_family = self._font_family(self.ui_id)
        if not self.ui_family:
            print(f"警告: UI 字体加载失败，回退系统字体: {path}", file=sys.stderr)
        return self.ui_family

    def _promote_pending_ui_font(self) -> Path:
        """下次启动时提交上次运行中被 Windows 锁住的字体。"""
        output = self.font_dir / "AaCute-UI.ttf"
        pending = sorted(
            self.font_dir.glob("AaCute-UI.ttf.*.tmp"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        if pending:
            try:
                pending[0].replace(output)
                for stale in pending[1:]:
                    stale.unlink(missing_ok=True)
            except OSError:
                # 只读打包目录仍可直接加载临时字体，不能阻断启动。
                return pending[0]
        return output

    def _ensure_full(self) -> str:
        if self.full_family:
            return self.full_family
        candidates = (
            self.font_dir / "full" / "AaCute-full.ttf",
            self._bundled_font_dir / "full" / "AaCute-full.ttf",
        )
        path = next((candidate for candidate in candidates if candidate.exists()), candidates[0])
        if not path.exists():
            return ""
        self.full_id = QFontDatabase.addApplicationFont(str(path))
        self.full_family = self._font_family(self.full_id)
        return self.full_family

    @staticmethod
    def _system_font() -> QFont:
        font = QFont("Segoe UI")
        font.setStyleHint(QFont.StyleHint.SansSerif)
        return font

    def apply(self, mode: str) -> str:
        """应用全局 UI 字体，返回实际生效的模式。"""
        requested = mode if mode in VALID_MODES else UI_MODE
        family = ""
        actual = requested
        if requested == SYSTEM_MODE:
            font = self._system_font()
        elif requested == FULL_MODE:
            family = self._ensure_full()
            if family:
                font = QFont(family)
            elif self.ui_family:
                actual = UI_MODE
                font = QFont(self.ui_family)
            else:
                actual = SYSTEM_MODE
                font = self._system_font()
        elif self.ui_family:
            family = self.ui_family
            font = QFont(family)
        else:
            actual = SYSTEM_MODE
            font = self._system_font()

        app = QApplication.instance()
        if app is not None:
            app.setFont(font)
        self.current_mode = actual
        self.current_family = family or font.family()
        return actual

    def chat_families(self, mode: str | None = None) -> tuple[str, str]:
        """返回聊天正文和时间应使用的 family。"""
        active_mode = mode or self.current_mode
        if active_mode == FULL_MODE and self.full_family:
            return self.full_family, self.full_family
        return "Microsoft YaHei", "Segoe UI"

    def reload_ui_font(self, temporary_path: str | Path | None = None) -> bool:
        """在 Qt 主线程提交并重新加载刚生成的 UI 子集。

        Windows 下 Qt 会占用已加载的字体文件，因此后台线程只能生成临时
        文件；这里先卸载旧 family，再替换目标文件，避免 ``WinError 5``。
        """
        output = self.font_dir / "AaCute-UI.ttf"
        candidate = Path(temporary_path) if temporary_path else output
        if not candidate.exists():
            return False

        old_id = self.ui_id
        old_family = self.ui_family
        old_path = self._ui_path if self._ui_path.exists() else self._bundled_font_dir / "AaCute-UI.ttf"
        had_output = output.exists()
        backup = output.with_name(f"{output.name}.{os.getpid()}.backup")
        if had_output:
            try:
                shutil.copy2(output, backup)
            except OSError:
                # 没有可靠备份就不卸载当前字体，避免同步失败后无法恢复。
                if candidate != output and candidate.exists():
                    candidate.unlink(missing_ok=True)
                return False
        if old_id >= 0:
            QFontDatabase.removeApplicationFont(old_id)
            self.ui_id = -1
            self.ui_family = ""

        new_id = -1
        keep_candidate = False
        try:
            if candidate.resolve() != output.resolve():
                try:
                    candidate.replace(output)
                except OSError:
                    # 旧字体仍被 Windows 的已创建控件占用：直接加载新临时
                    # 文件即可完成本次运行的热切换，并留待下次启动提交。
                    new_id = QFontDatabase.addApplicationFont(str(candidate))
                    new_family = self._font_family(new_id)
                    if not new_family:
                        raise RuntimeError("Qt 未返回新的 UI 字体 family")
                    self.ui_id = new_id
                    self.ui_family = new_family
                    self._ui_path = candidate
                    self.apply(self.current_mode)
                    keep_candidate = True
                    return True
            new_id = QFontDatabase.addApplicationFont(str(output))
            new_family = self._font_family(new_id)
            if not new_family:
                if new_id >= 0:
                    QFontDatabase.removeApplicationFont(new_id)
                raise RuntimeError("Qt 未返回新的 UI 字体 family")
            self.ui_id = new_id
            self.ui_family = new_family
            self._ui_path = output
            self.apply(self.current_mode)
            return True
        except Exception:
            if new_id >= 0:
                QFontDatabase.removeApplicationFont(new_id)
            if backup and backup.exists():
                backup.replace(output)
                restore_path = output
            else:
                # 首次打包版同步时 output 可能是刚被候选文件占用的坏文件。
                if not had_output and output.exists():
                    output.unlink(missing_ok=True)
                restore_path = old_path
            restored_id = QFontDatabase.addApplicationFont(str(restore_path))
            restored_family = self._font_family(restored_id)
            if restored_family:
                self.ui_id = restored_id
                self.ui_family = restored_family
                self._ui_path = restore_path
                self.current_family = old_family or restored_family
            return False
        finally:
            if candidate != output and candidate.exists() and not keep_candidate:
                candidate.unlink()
            if backup and backup.exists():
                backup.unlink()

    def rebuild_ui_subset(self) -> RebuildResult:
        """同步构建并热加载；只应从 Qt 主线程调用。"""
        from dmshoot.core.font_builder import build_ui_subset

        try:
            result = build_ui_subset(self.font_dir, commit=False)
            if not self.reload_ui_font(result.get("temporary_path")):
                return RebuildResult("error", reason="子集已生成，但 Qt 重新加载失败")
            return RebuildResult("ok", chars=result.get("chars", 0))
        except RuntimeError as exc:
            return RebuildResult("skipped", reason=str(exc))
        except Exception as exc:  # GUI 反馈，不让同步按钮崩溃
            return RebuildResult("error", reason=str(exc))
