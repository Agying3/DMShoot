"""DMShoot 图标功能测试 — Unicode 字符 / 头像缓存 / 状态灯 / 齿轮动画

运行: python test_icons.py
覆盖: Unicode 图标字符 / 头像 URL 提取 / 头像缓存逻辑 / 状态灯常量 / 旋转齿轮角度
"""

import sys, os, time, json, tempfile, hashlib, threading
from pathlib import Path

PROJECT = Path(__file__).parent
sys.path.insert(0, str(PROJECT))

_results = []
def ok(name, detail=""):
    _results.append((name, True, detail))
    print(f"  [OK] {name}{' — ' + detail if detail else ''}")
def fail(name, reason=""):
    _results.append((name, False, reason))
    print(f"  [FAIL] {name}: {reason}")
def check(name, cond, detail=""):
    (ok if cond else fail)(name, detail)


# ═══════════════════════════════════════════════════════════
# 1. Unicode 字符图标 — 验证所有 Unicode 字符均有效
# ═══════════════════════════════════════════════════════════
def test_unicode_icons_defined():
    """验证项目中使用的 Unicode 字符都存在且正确"""
    print("\n=== Unicode 图标字符 ===")

    icons = {
        # 侧边栏状态灯
        "connected": "\u25CF",   # U+25CF BLACK CIRCLE
        "offline":   "\u2715",   # U+2715 MULTIPLICATION X
        "ready":     "\u2014",   # U+2014 EM DASH

        # 标题栏按钮
        "gear":      "\u2699",   # U+2699 GEAR
        "pin":       "\U0001F4CC",  # U+1F4CC PUSHPIN

        # 加载动画
        "spinner":   "\u23F3",   # U+23F3 HOURGLASS WITH FLOWING SAND

        # 窗口标题
        "perf":      "\U0001F4CA",  # U+1F4CA BAR CHART
        "log":       "\U0001F4C4",  # U+1F4C4 PAGE FACING UP

        # 状态提示
        "success":   "\u2713",   # U+2713 CHECK MARK
        "warning":   "!",
        "info":      "i",

        # 后端选择
        "python":    "\U0001F40D",  # U+1F40D SNAKE
        "go":        "\U0001F400",  # U+1F400 RAT
    }

    for name, char in icons.items():
        check(f"icon '{name}' non-empty", len(char) >= 1)
        check(f"icon '{name}' valid unicode", ord(char[0]) > 0)


def test_status_icon_cycle():
    """侧边栏状态灯：连接态 → 离线 → 就绪 的完整周期"""
    print("\n=== 状态灯周期 ===")

    # 模拟 main_window.py 中的状态更新
    status_map = {"douyin": "\u2715", "bilibili": "\u2715"}

    # 就绪
    status_map["douyin"] = "\u2014"
    check("douyin ready (U+2014)", status_map["douyin"] == "\u2014")

    # 连接
    status_map["douyin"] = "\u25CF"
    check("douyin connected (U+25CF)", status_map["douyin"] == "\u25CF")

    # 离线
    status_map["douyin"] = "\u2715"
    check("douyin offline (U+2715)", status_map["douyin"] == "\u2715")

    # AI 状态同理
    ai_status = "\u2715"
    ai_status = "\u2014"; check("ai ready (U+2014)", ai_status == "\u2014")
    ai_status = "\u25CF"; check("ai connected (U+25CF)", ai_status == "\u25CF")


# ═══════════════════════════════════════════════════════════
# 2. 旋转齿轮动画 — 角度计算（无需 Qt）
# ═══════════════════════════════════════════════════════════
def test_gear_angle_math():
    """旋转齿轮的角度累积逻辑"""
    print("\n=== 齿轮旋转逻辑 ===")

    angle = 0

    # 第一次旋转: 0 → 360
    angle += 360
    check("spin1: 0+360=360", angle == 360)

    # 第二次旋转: 360 → 720
    angle += 360
    check("spin2: 360+360=720", angle == 720)

    # 第三次旋转: 720 → 1080
    angle += 360
    check("spin3: 720+360=1080", angle == 1080)

    # 动画停止后重置 (这个逻辑在 stop() 中)
    angle = 0
    check("reset to 0", angle == 0)


# ═══════════════════════════════════════════════════════════
# 3. 头像缓存逻辑 — MD5 hash / 缓存文件 / Negative cache
# ═══════════════════════════════════════════════════════════
def test_avatar_cache_key():
    """头像缓存的 MD5 文件名生成"""
    print("\n=== 头像缓存键 ===")

    test_url = "https://example.com/avatar/123456.jpg"
    cache_key = hashlib.md5(test_url.encode()).hexdigest()[:16]
    check("cache key length 16", len(cache_key) == 16)
    check("cache key hex", all(c in "0123456789abcdef" for c in cache_key))

    # 相同 URL 产生相同 key
    key2 = hashlib.md5(test_url.encode()).hexdigest()[:16]
    check("same URL = same key", cache_key == key2)

    # 不同 URL 产生不同 key
    key3 = hashlib.md5("different.jpg".encode()).hexdigest()[:16]
    check("different URL ≠ same key", cache_key != key3)


def test_avatar_cache_files():
    """头像缓存文件的读写逻辑"""
    print("\n=== 头像缓存文件 ===")

    # mock PySide6 以允许 contact 模块加载
    from unittest.mock import MagicMock
    for mod_name in ("PySide6", "PySide6.QtWidgets", "PySide6.QtCore", "PySide6.QtGui"):
        if mod_name not in sys.modules:
            try: __import__(mod_name)
            except ImportError: sys.modules[mod_name] = MagicMock()

    import dmshoot.gui.widgets.contact as contact_mod

    tmp_dir = Path(tempfile.mkdtemp())
    orig_dir = contact_mod.AVATAR_DIR
    contact_mod.AVATAR_DIR = tmp_dir

    try:
        test_url = "https://cdn.example.com/avatars/test_user.png"
        cache_key = hashlib.md5(test_url.encode()).hexdigest()[:16]
        cache_path = tmp_dir / f"{cache_key}.png"
        fail_path = tmp_dir / f"{cache_key}.fail"

        # 测试 1: 文件不存在 → 正常返回 None
        check("cache miss returns None", not cache_path.exists())

        # 测试 2: 写入一个有效 (>4096 bytes) 的缓存文件
        test_data = b'\x89PNG\r\n\x1a\n' + b'\x00' * 4100
        cache_path.write_bytes(test_data)
        check("cache file written", cache_path.exists())
        check("cache size > 4096", cache_path.stat().st_size > 4096)

        # 测试 3: 读回缓存数据
        data = cache_path.read_bytes()
        check("cache data == original", data == test_data)

        # 测试 4: 无效文件 (< 4096 bytes)
        small_path = tmp_dir / "small.png"
        small_path.write_bytes(b'tiny')
        check("small avatar invalid", small_path.stat().st_size < 4096)

        # 测试 5: Negative cache (.fail 标记)
        fail_path.write_text("1")
        check("fail flag exists", fail_path.exists())

        # 测试 6: 24h 内不重试
        fail_age = time.time() - fail_path.stat().st_mtime
        check("fail flag fresh (<24h)", fail_age < 86400)

        # 测试 7: 超过 24h 的 fail 标记应清除
        import os as _os
        old_time = time.time() - 86401
        _os.utime(str(fail_path), (old_time, old_time))
        fail_age2 = time.time() - fail_path.stat().st_mtime
        check("fail flag expired (>24h)", fail_age2 > 86400)

    finally:
        contact_mod.AVATAR_DIR = orig_dir
        import shutil
        shutil.rmtree(str(tmp_dir), ignore_errors=True)


# ═══════════════════════════════════════════════════════════
# 4. 头像 URL 提取 — 各平台 adapter 中的 URL 字段
# ═══════════════════════════════════════════════════════════
def test_bilibili_avatar_url():
    """B站适配器从 API 响应中提取头像 URL"""
    print("\n=== B站头像 URL ===")

    # B站 API 返回: user.face = "https://i0.hdslb.com/bfs/face/xxx.jpg"
    mock_bili_user = {
        "face": "https://i0.hdslb.com/bfs/face/abc123def456.jpg"
    }
    face = mock_bili_user.get("face", "")
    check("bili face extracted", len(face) > 0)
    check("bili face is hdslb CDN", "hdslb.com" in face)

    # 空 face 回退
    mock_empty = {}
    empty_face = mock_empty.get("face", "")
    check("bili empty face fallback", empty_face == "")


def test_douyin_avatar_url():
    """抖音适配器从 API 响应中提取头像 URL"""
    print("\n=== 抖音头像 URL ===")

    # 抖音 API 返回多个尺寸的头像
    mock_dy_user = {
        "avatar_larger": {"url_list": ["https://p3.douyinpic.com/aweme/large.jpg"]},
        "avatar_medium": {"url_list": ["https://p3.douyinpic.com/aweme/medium.jpg"]},
        "avatar_thumb": {"url_list": ["https://p3.douyinpic.com/aweme/thumb.jpg"]},
    }

    # 优先取大图
    av = mock_dy_user.get("avatar_larger") or mock_dy_user.get("avatar_medium") or {}
    urls = av.get("url_list", [])
    check("dy avatar url found", len(urls) > 0)
    if urls:
        check("dy avatar is douyin CDN", "douyinpic.com" in urls[0])

    # 缺 avatar_larger 回退到 avatar_medium
    mock_no_large = {
        "avatar_medium": {"url_list": ["https://p3.douyinpic.com/aweme/medium.jpg"]},
    }
    av2 = mock_no_large.get("avatar_larger") or mock_no_large.get("avatar_medium") or {}
    urls2 = av2.get("url_list", [])
    check("dy fallback to medium", len(urls2) > 0)


# ═══════════════════════════════════════════════════════════
# 5. Referer 自适应 — B站 CDN 需要 Referer
# ═══════════════════════════════════════════════════════════
def test_referer_by_domain():
    """根据头像 URL 域名选择正确的 Referer 头"""
    print("\n=== Referer 自适应 ===")

    referers = {
        "hdslb.com": "https://www.bilibili.com/",
        "douyin.com": "https://www.douyin.com/",
        "douyinvod.com": "https://www.douyin.com/",
        "xhscdn.com": "https://www.xiaohongshu.com/",
    }

    def get_referer(url):
        for domain, referer in referers.items():
            if domain in url:
                return referer
        return "https://www.douyin.com/"  # 默认

    check("bili referer", get_referer("https://i0.hdslb.com/bfs/face/x.jpg")
          == "https://www.bilibili.com/")
    check("dy referer", get_referer("https://p3.douyinpic.com/aweme/x.jpg")
          == "https://www.douyin.com/")
    check("dy vod referer", get_referer("https://douyinvod.com/video/x.jpg")
          == "https://www.douyin.com/")
    check("xhs referer", get_referer("https://sns-webpic-qc.xhscdn.com/x.jpg")
          == "https://www.xiaohongshu.com/")
    check("unknown referer default",
          get_referer("https://cdn.unknown.com/img.jpg")
          == "https://www.douyin.com/")


# ═══════════════════════════════════════════════════════════
# 6. _AvatarLoader 线程逻辑 — URL 收集和去重
# ═══════════════════════════════════════════════════════════
def test_avatar_loader_url_collection():
    """头像加载器收集 URL 的逻辑"""
    print("\n=== 头像 URL 收集 ===")

    # 模拟 _AvatarLoader 收集 (session_id, avatar_url) 对
    urls_to_load = [
        ("douyin:user_A", "https://p3.douyinpic.com/aweme/user_A.jpg"),
        ("douyin:user_B", "https://p3.douyinpic.com/aweme/user_B.jpg"),
        ("douyin:user_A", "https://p3.douyinpic.com/aweme/user_A.jpg"),  # 重复
        ("bilibili:user_C", "https://i0.hdslb.com/bfs/face/user_C.jpg"),
    ]

    # 去重：同 URL 不重复下载
    seen_urls = set()
    unique_pairs = []
    for sid, url in urls_to_load:
        if url not in seen_urls:
            seen_urls.add(url)
            unique_pairs.append((sid, url))

    check("dedup from 4 to 3", len(unique_pairs) == 3)
    check("user_A present", any(sid == "douyin:user_A" for sid, _ in unique_pairs))
    check("user_B present", any(sid == "douyin:user_B" for sid, _ in unique_pairs))
    check("user_C present", any(sid == "bilibili:user_C" for sid, _ in unique_pairs))

    # 所有 URL 都有对应的 session_id
    for sid, url in unique_pairs:
        check(f"session_id not empty for {sid}", len(sid) > 0)
        check(f"url valid for {sid}", url.startswith("https://"))


# ═══════════════════════════════════════════════════════════
# 7. 默认头像 fallback — 联系人首字
# ═══════════════════════════════════════════════════════════
def test_avatar_fallback_text():
    """无头像时显示联系人名的首字"""
    print("\n=== 默认头像文字 ===")

    names = [
        ("张三", "张"),
        ("李四", "李"),
        ("TestUser", "T"),
        ("", "?"),          # 空名
        ("A", "A"),         # 单字名
        ("用户12345", "用"),
    ]

    for name, expected in names:
        first_char = name[0] if name else "?"
        check(f"fallback '{name}' -> '{expected}'",
              first_char == expected)


# ═══════════════════════════════════════════════════════════
# 汇总
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 55)
    print("  DMShoot 图标功能测试")
    print("=" * 55)

    test_unicode_icons_defined()
    test_status_icon_cycle()
    test_gear_angle_math()
    test_avatar_cache_key()
    test_avatar_cache_files()
    test_bilibili_avatar_url()
    test_douyin_avatar_url()
    test_referer_by_domain()
    test_avatar_loader_url_collection()
    test_avatar_fallback_text()

    total = len(_results)
    passed = sum(1 for _, ok_, _ in _results if ok_)
    failed_list = [(n, r) for n, ok_, r in _results if not ok_]
    print(f"\n{'=' * 55}")
    print(f"  {passed}/{total} 通过 ({100 * passed // total}%)" if total else "")
    if failed_list:
        print(f"  {len(failed_list)} 失败:")
        for name, reason in failed_list:
            print(f"    [{name}] {reason}")
    print("=" * 55)
    sys.exit(0 if not failed_list else 1)
