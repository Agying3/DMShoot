"""应用图标资源和 PyInstaller 路径回归测试。"""

from pathlib import Path

from PySide6.QtGui import QIcon


PROJECT = Path(__file__).resolve().parents[1]


def test_application_icon_path_points_to_bundled_image():
    from dmshoot.gui.app_icon import application_icon_path

    assert application_icon_path() == PROJECT / "resources" / "大咸鱼.jpeg"
    assert application_icon_path().is_file()


def test_application_icon_loads(qapp):
    from dmshoot.gui.app_icon import application_icon

    icon = application_icon()
    assert isinstance(icon, QIcon)
    assert not icon.isNull()


def test_markdown_document_view_shows_application_icon(qapp, qtbot, tmp_path):
    from dmshoot.gui.widgets.chat_view import ChatView

    document = tmp_path / "XHS_IM_逆向日志.md"
    document.write_text("# IM 逆向日志\n\n字体覆盖检查", encoding="utf-8")
    view = ChatView()
    qtbot.addWidget(view)
    view.show()

    view.show_markdown(str(document), "小红书 IM 逆向日志")

    assert view.title_label.text() == "小红书 IM 逆向日志"
    assert view.title_icon.isVisible()
    assert view.title_icon.pixmap() is not None
    assert not view.title_icon.pixmap().isNull()
