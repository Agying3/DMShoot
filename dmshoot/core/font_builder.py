"""运行时重建 AaCute UI 字体子集。

字体构建本身不依赖 Qt 控件，便于在后台线程执行。字体热加载由
``FontManager`` 在 Qt 主线程完成。
"""

from __future__ import annotations

import pathlib
import sys
import os


_SKIP_PARTS = {
    ".git",
    ".git-rewrite",
    ".pytest_cache",
    "__pycache__",
    "external",
    "node_modules",
    "build",
    "dist",
    "scripts",
    "docs",
    "reports",
    ".workbuddy",
}
_SOURCE_EXTENSIONS = ("*.py", "*.json", "*.ui", "*.qss", "*.txt", "*.md")
# 这份文档会在小红书/快手没有 Web IM 时直接显示在应用内，属于 UI 文案。
# docs/ 其余内容仍然跳过，避免把开发文档和历史报告全部塞进子集。
_EXTRA_SOURCE_FILES = ("docs/XHS_IM_逆向日志.md",)
_UI_FAMILY = "Aa偷吃可爱长大的 UI"
_UI_FULL_NAME = "Aa 偷吃可爱长大的 UI"
_UI_POSTSCRIPT_NAME = "AaCuteUI"


def _runtime_root() -> pathlib.Path:
    """返回源码根或 PyInstaller 解包根目录。"""
    if getattr(sys, "frozen", False):
        return pathlib.Path(getattr(sys, "_MEIPASS", pathlib.Path(sys.executable).parent))
    return pathlib.Path(__file__).resolve().parents[2]


def _resolve_paths(font_dir: str | pathlib.Path):
    """返回 ``(源码根, 完整字体路径)``，兼容开发态和打包态。"""
    font_path = pathlib.Path(font_dir).resolve()
    project_root = pathlib.Path(__file__).resolve().parents[2]
    runtime_root = _runtime_root()

    source_root = project_root if (project_root / "dmshoot").exists() else runtime_root
    full_candidates = (
        font_path / "full" / "AaCute-full.ttf",
        project_root / "tools" / "fonts" / "full" / "AaCute-full.ttf",
        runtime_root / "fonts" / "full" / "AaCute-full.ttf",
    )
    full_path = next((candidate for candidate in full_candidates if candidate.exists()), full_candidates[0])
    return source_root, full_path


def _iter_source_files(src_root: str | pathlib.Path):
    """按稳定顺序枚举扫描范围内的源码文件。"""
    root = pathlib.Path(src_root)
    seen: set[pathlib.Path] = set()
    for source_dir in (root / "dmshoot", root / "prompts"):
        if not source_dir.exists():
            continue
        for extension in _SOURCE_EXTENSIONS:
            for path in sorted(source_dir.rglob(extension)):
                if _SKIP_PARTS.intersection(path.parts):
                    continue
                resolved = path.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                yield path
    for relative_path in _EXTRA_SOURCE_FILES:
        path = root / relative_path
        if not path.is_file():
            continue
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        yield path


def _collect_ui_chars(src_root: str | pathlib.Path, progress_cb=None) -> tuple[set[str], int]:
    """扫描 UI 源码和公开提示词中的汉字，并报告逐文件进度。"""
    chars: set[str] = set()
    files = 0
    source_files = list(_iter_source_files(src_root))
    total = len(source_files)
    for index, path in enumerate(source_files, 1):
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            print(f"skip {path}: {exc}", file=sys.stderr)
            content = ""
        found = {char for char in content if "\u4e00" <= char <= "\u9fff"}
        if found:
            chars.update(found)
            files += 1
        if progress_cb:
            progress_cb(
                0.05 + 0.40 * index / max(1, total),
                f"正在扫描 UI 文案 ({index}/{total})",
            )
    return chars, files


def _build_text(chars: set[str]) -> str:
    """保留可见 ASCII、常用标点以及扫描到的 UI 汉字。"""
    ascii_chars = "".join(chr(code) for code in range(0x20, 0x7F))
    punctuation = "，。！？、；：\"'（）【】《》…—·“”‘’〈〉「」『』〔〕～＠＃＄％＾＆＊"
    return ascii_chars + punctuation + "".join(sorted(chars))


def _rename_family(
    path: str | pathlib.Path,
    family: str = _UI_FAMILY,
    fullname: str = _UI_FULL_NAME,
    psname: str = _UI_POSTSCRIPT_NAME,
) -> None:
    """给 UI 子集改 family，避免和完整版字体在 Qt 中混淆。"""
    from fontTools.ttLib import TTFont

    font = TTFont(str(path))
    try:
        names = font["name"]
        names.setName(family, 1, 3, 1, 0x409)
        names.setName(family, 1, 0, 3, 0x409)
        names.setName(fullname, 4, 3, 1, 0x409)
        names.setName(fullname, 4, 0, 3, 0x409)
        names.setName(psname, 6, 3, 1, 0x409)
        names.setName(psname, 6, 0, 3, 0x409)
        font.save(str(path))
    finally:
        font.close()


def build_ui_subset(
    font_dir: str | pathlib.Path,
    progress_cb=None,
    commit: bool = True,
) -> dict:
    """扫描源码并原子替换 UI 子集，返回构建统计。

    任何异常都会发生在临时文件上，旧的 ``AaCute-UI.ttf`` 不会被覆盖。
    """
    try:
        from fontTools import subset as font_subset
        from fontTools.ttLib import TTFont
    except ImportError as exc:
        raise RuntimeError("缺少依赖 fontTools，请安装 fonttools brotli") from exc

    source_root, full_path = _resolve_paths(font_dir)
    if progress_cb:
        progress_cb(0.02, "正在检查字体资源…")
    if not full_path.exists():
        raise RuntimeError("缺少完整字体 AaCute-full.ttf，无法重建")

    chars, files = _collect_ui_chars(source_root, progress_cb)
    if not chars or not files:
        raise RuntimeError("未找到可扫描的 UI 源码/公开提示词")
    if progress_cb:
        progress_cb(0.48, f"已扫描 {files} 个文件，正在载入完整字体…")

    options = font_subset.Options()
    options.glyph_names = False
    options.notdef_outline = True
    options.recalc_bounds = True
    if progress_cb:
        progress_cb(0.55, "正在载入完整字体…")
    font = font_subset.load_font(str(full_path), options)
    subsetter = font_subset.Subsetter(options=options)
    subsetter.populate(text=_build_text(chars))
    if progress_cb:
        progress_cb(0.65, "正在生成 UI 字体子集…")
    subsetter.subset(font)

    output = pathlib.Path(font_dir).resolve() / "AaCute-UI.ttf"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f"{output.name}.{os.getpid()}.tmp")
    build_succeeded = False
    try:
        if progress_cb:
            progress_cb(0.76, "正在写入 TTF 临时文件…")
        font_subset.save_font(font, str(temporary), options)
        if progress_cb:
            progress_cb(0.82, "正在校正字体名称…")
        _rename_family(temporary)
        if commit:
            temporary.replace(output)
        build_succeeded = True
    finally:
        if temporary.exists() and (commit or not build_succeeded):
            temporary.unlink()

    # WOFF 只服务网页预览，必须从最终 TTF 重新打开后再转换。
    # fontTools.subset.save_font() 会重置 flavor，直接复用上面的 subset
    # 对象会把本应是 WOFF 的文件重新写成普通 TTF。
    result_path = output if commit else temporary
    woff_output = pathlib.Path(font_dir).resolve() / "AaCute-UI.woff"
    woff_temporary = woff_output.with_name(f"{woff_output.name}.{os.getpid()}.tmp")
    woff_font = None
    try:
        if progress_cb:
            progress_cb(0.90, "正在生成 WOFF 预览字体…")
        woff_font = TTFont(str(result_path))
        woff_font.flavor = "woff"
        woff_font.save(str(woff_temporary))
        with woff_temporary.open("rb") as woff_file:
            if woff_file.read(4) != b"wOFF":
                raise RuntimeError("生成的 WOFF 文件头校验失败")
        woff_check = TTFont(str(woff_temporary))
        try:
            if woff_check.flavor != "woff":
                raise RuntimeError("生成的字体未被识别为 WOFF")
        finally:
            woff_check.close()
        # WOFF 不会被 Qt 占用，后台同步时也可以直接更新预览资源。
        woff_temporary.replace(woff_output)
        if progress_cb:
            progress_cb(0.97, "正在校验生成结果…")
    except Exception as exc:
        print(f"WOFF 未生成: {exc}", file=sys.stderr)
    finally:
        if woff_font is not None:
            woff_font.close()
        if woff_temporary.exists():
            woff_temporary.unlink()

    cmap_font = TTFont(str(result_path))
    try:
        cmap = cmap_font.getBestCmap()
    finally:
        cmap_font.close()
    if progress_cb:
        progress_cb(1.0, "字体子集生成完成")
    return {
        "chars": sum(1 for codepoint in cmap if 0x4E00 <= codepoint <= 0x9FFF),
        "total": len(cmap),
        "files": files,
        "path": str(output),
        "woff_path": str(woff_output) if woff_output.exists() else "",
        "temporary_path": str(temporary) if not commit else "",
    }
