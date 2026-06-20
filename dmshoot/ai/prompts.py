"""提示词管理 — 从 prompts/ 文件夹加载 .txt 文件"""

from pathlib import Path


def load_prompts() -> dict[str, str]:
    """扫描 prompts/ 目录，返回 {名称: 内容}（角色提示词）"""
    prompts_dir = Path(__file__).parent.parent.parent / "prompts"
    if not prompts_dir.exists():
        return {}
    return _load_from_dir(prompts_dir)


def load_behavior_prompts() -> dict[str, str]:
    """扫描 prompts/行为/ 目录，返回 {名称: 内容}（行为提示词）"""
    prompts_dir = Path(__file__).parent.parent.parent / "prompts" / "行为"
    if not prompts_dir.exists():
        return {}
    return _load_from_dir(prompts_dir)


def _load_from_dir(directory: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for f in sorted(directory.glob("*.txt")):
        name = f.stem
        if "_" in name and name.split("_")[0].isdigit():
            name = name.split("_", 1)[1]
        try:
            content = f.read_text(encoding="utf-8").strip()
        except UnicodeDecodeError:
            content = f.read_text(encoding="gbk", errors="ignore").strip()
        if content:
            result[name] = content
    return result


def save_prompt(name: str, content: str):
    """保存提示词到文件"""
    if ".." in name or "/" in name or "\\" in name:
        raise ValueError(f"非法文件名: {name}")
    prompts_dir = Path(__file__).parent.parent.parent / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    path = prompts_dir / f"{name}.txt"
    path.write_text(content, encoding="utf-8")


def delete_prompt(name: str):
    """删除提示词文件"""
    # 防路径穿越：只允许字母数字中文下划线连字符
    if ".." in name or "/" in name or "\\" in name:
        raise ValueError(f"非法文件名: {name}")
    path = Path(__file__).parent.parent.parent / "prompts" / f"{name}.txt"
    if path.exists():
        path.unlink()


# 模块级变量，供外部 import 使用
PROMPTS: dict[str, str] = {}
try:
    PROMPTS = load_prompts()
except Exception:
    pass
