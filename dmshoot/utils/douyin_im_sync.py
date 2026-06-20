"""抖音历史会话同步 — 基于缓存，不阻塞主线程

缓存层级:
  1. JSON 缓存 (最终结果: 昵称+头像) → 秒级，无网络请求
  2. Protobuf 缓存 (原始 imapi 响应) → 需解析+API补全
  3. Playwright 拉取 (仅首次/重登) → 在子进程中运行，不阻塞 Qt
"""

import json, re, hashlib, time, os, subprocess, sys
from pathlib import Path
from typing import Optional

from dmshoot.utils.console_log import get_logger

logger = get_logger(__name__)

CACHE_DIR = Path("dmshoot/data/cache")


def _cache_key(cookie_str: str) -> str:
    for part in cookie_str.split('; '):
        if part.startswith('sessionid='):
            return hashlib.md5(part.encode()).hexdigest()[:12]
    return hashlib.md5(cookie_str.encode()).hexdigest()[:12]


# ── 缓存读写 ──

def _load_json_cache(key: str) -> Optional[list[dict]]:
    f = CACHE_DIR / f"dy_conv_{key}.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding='utf-8'))
        except:
            pass
    return None


def _save_json_cache(key: str, convs: list[dict]):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"dy_conv_{key}.json").write_text(
        json.dumps(convs, ensure_ascii=False), encoding='utf-8')


def _load_raw_cache(key: str) -> Optional[bytes]:
    f = CACHE_DIR / f"im_init_{key}.bin"
    if f.exists():
        return f.read_bytes()
    return None


def _save_raw_cache(key: str, raw: bytes):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"im_init_{key}.bin").write_bytes(raw)


def clear_douyin_file_cache():
    """仅清除 im_init 和 dy_conv 文件缓存（强制下次重新拉取）"""
    global _cached_messages
    _cached_messages = []
    deleted = 0
    if CACHE_DIR.exists():
        for f in list(CACHE_DIR.glob("dy_conv_*.json")) + list(CACHE_DIR.glob("im_init_*.bin")):
            f.unlink()
            deleted += 1
    logger.success(f"抖音文件缓存已清除: {deleted} 个文件")


def clear_douyin_db_messages():
    """仅清除 DB 中的抖音历史消息（保留会话列表和缓存文件）"""
    try:
        from dmshoot.storage import database
        conn = database._get_conn()
        count = conn.execute("DELETE FROM messages WHERE platform='douyin'").rowcount
        conn.commit()
        logger.success(f"抖音DB消息已清除: {count} 条")
    except Exception as e:
        logger.warning(f"清除DB消息失败: {e}")


def clear_douyin_cache():
    """清除所有抖音 IM 缓存 + DB 历史消息"""
    clear_douyin_file_cache()
    clear_douyin_db_messages()


# ── Playwright 子进程 ──

_PW_SCRIPT = r'''
import asyncio, sys, base64, json, re

async def main():
    from playwright.async_api import async_playwright

    cookies = []
    for part in sys.argv[1].split("; "):
        if "=" in part:
            k, v = part.split("=", 1)
            cookies.append({"name": k.strip(), "value": v, "domain": ".douyin.com", "path": "/"})

    raw_data = None
    user_data = {}     # {uid: {nick, av, sec}}
    msg_history = []   # [{peer_uid, content, timestamp, is_self, msg_index}]

    async def on_response(response):
        nonlocal raw_data
        url = response.url
        # 拦截所有 imapi 响应
        if "imapi.douyin.com" in url:
            try:
                body = await response.body()
                # get_message_by_init 是最大的 payload，包含会话和消息
                if "get_message_by_init" in url:
                    raw_data = body
                sys.stderr.write(f"IMAPI_CAPTURE: url={url[:120]} size={len(body)}\n")
            except:
                pass

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled",
                  "--window-size=400,300", "--window-position=0,0"])
        context = await browser.new_context(viewport={"width": 1280, "height": 720})
        await context.add_cookies(cookies)
        page = await context.new_page()
        page.on("response", on_response)

        # 访问首页（douyin.com/messages/ 不存在，IM 面板在首页加载）
        await page.goto("https://www.douyin.com/", wait_until="domcontentloaded")
        sys.stderr.write(f"Homepage loaded: {page.url[:80]}\n")
        
        # 等 JS 加载 IM 面板，尝试点击消息按钮
        for i in range(10):
            await asyncio.sleep(2)
            if raw_data:
                sys.stderr.write(f"Got im_init data ({len(raw_data)} bytes) at t={(i+1)*2}s\n")
                break
            if i == 2 and not raw_data:
                sys.stderr.write(f"t={(i+1)*2}s: trying to click message button...\n")
                try:
                    # 尝试点击顶部"消息"图标
                    msg_btn = page.locator('[class*="message"], [class*="inbox"], [class*="im-icon"], [data-e2e="message"]').first
                    if await msg_btn.count() > 0:
                        await msg_btn.click()
                        sys.stderr.write("Clicked message button\n")
                except:
                    pass
            if i == 8 and not raw_data:
                sys.stderr.write(f"t={(i+1)*2}s: last try - refreshing page...\n")
                await page.reload()
                await asyncio.sleep(3)
        
        # 再等10秒
        for _ in range(10):
            if raw_data:
                break
            await asyncio.sleep(1)

        # 通过浏览器内 fetch 获取所有 peer 的昵称+头像（浏览器自带 SDK 签名）
        if raw_data:
            peer_uids = set()
            for m in re.finditer(rb'0:1:(\d+):(\d+)', raw_data):
                peer_uids.add(m.group(1).decode())
            # 浏览器内 fetch user info（利用浏览器自带安全 SDK）
            for uid in peer_uids:
                try:
                    result = await page.evaluate(
                        '(async (uid) => {' +
                        '  const url = \"https://www.douyin.com/aweme/v1/web/user/profile/other/?user_id=\" + uid + \"&device_platform=webapp&aid=6383&channel=channel_pc_web&source=channel_pc_web\";' +
                        '  const resp = await fetch(url, {credentials: \"include\", headers: {\"Referer\": \"https://www.douyin.com/user/\" + uid}});' +
                        '  const data = await resp.json();' +
                        '  const u = data.user || {};' +
                        '  const av = u.avatar_larger || u.avatar_medium || u.avatar_thumb || {};' +
                        '  return JSON.stringify({nick: u.nickname || \"\", sec: u.sec_uid || \"\", av: (av.url_list || [])[0] || \"\"});' +
                        '})(\"' + uid + '\")')
                    info = json.loads(result)
                    if info.get('nick'):
                        user_data[uid] = info
                except Exception:
                    pass

            # 消息提取已由 proto_msg_parser.py 完成，不再通过 JS fetch
            # imapi.douyin.com 使用 Protobuf 格式，JS fetch 无法构造
        await browser.close()

    # stdout: protobuf (base64)
    if raw_data:
        sys.stdout.write(base64.b64encode(raw_data).decode())
    else:
        sys.stdout.write("NONE")
    # stderr: JSON (user_data + messages)
    result = {"user_data": user_data, "messages": msg_history}
    sys.stderr.write("PW_RESULT:" + json.dumps(result, ensure_ascii=False))

asyncio.run(main())
'''


def _check_playwright_ready() -> bool:
    """检查 Playwright 和 Chromium 是否可用"""
    try:
        import importlib
        importlib.import_module('playwright')
        import subprocess, sys
        result = subprocess.run(
            [sys.executable, '-c', 'from playwright.sync_api import sync_playwright; p=sync_playwright().start(); p.chromium.launch(headless=True).close(); p.stop()'],
            capture_output=True, timeout=15
        )
        return result.returncode == 0
    except Exception:
        return False


def _fetch_raw_via_subprocess(cookie_str: str) -> tuple[Optional[bytes], dict, list]:
    """在子进程中运行 Playwright，返回 (protobuf_raw, user_data_map, messages_list)"""
    # 先检查 Playwright 可用性
    if not _check_playwright_ready():
        logger.warning("Playwright/Chromium 不可用，跳过浏览器拉取（首次启动需安装: playwright install chromium）")
        return None, {}, []
    
    try:
        logger.info("→ 同步中（Playwright 浏览器拉取，首次约 30s）...")
        result = subprocess.run(
            [sys.executable, '-c', _PW_SCRIPT, cookie_str],
            capture_output=True, text=True, timeout=90,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        output = result.stdout.strip()
        raw = None
        if output and output != 'NONE':
            import base64
            raw = base64.b64decode(output)

        # 解析 stderr 中的完整结果
        user_data = {}
        messages = []
        stderr = result.stderr
        if stderr:
            # 输出 Playwright 的诊断信息
            for line in stderr.split('\n'):
                line = line.strip()
                if line and 'PW_RESULT:' not in line:
                    logger.debug(f"[PW] {line}")
        if stderr and 'PW_RESULT:' in stderr:
            try:
                data_json = stderr.split('PW_RESULT:', 1)[1].strip()
                data = json.loads(data_json)
                user_data = data.get("user_data", {})
                messages = data.get("messages", [])
            except Exception as e:
                logger.warning(f"Playwright stderr 解析失败: {e}")
        return raw, user_data, messages
    except Exception as e:
        logger.warning(f"Playwright 子进程异常: {e}")
    return None, {}, []


# ── 用户信息补全 ──

def _enrich_all(convs: list[dict], cookie_str: str):
    """用抖音用户 API 补全昵称和头像（无需浏览器，直接 HTTP）"""
    import requests
    import urllib3
    urllib3.disable_warnings()

    headers = {
        "Cookie": cookie_str,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.douyin.com/",
    }

    for conv in convs:
        uid = conv['peer_uid']
        if conv.get('nickname') and not conv['nickname'].startswith('\u7528\u6237'):
            continue

        try:
            url = (
                f"https://www.douyin.com/aweme/v1/web/user/profile/other/"
                f"?user_id={uid}&device_platform=webapp&aid=6383"
                f"&channel=channel_pc_web&source=channel_pc_web"
            )
            resp = requests.get(url, headers=headers, timeout=10, verify=False)
            if resp.status_code != 200:
                continue
            data = resp.json()
            user = data.get("user", {})
            nick = user.get("nickname", "")
            av_obj = (user.get("avatar_larger") or user.get("avatar_medium") or
                       user.get("avatar_thumb") or {})
            av_urls = av_obj.get("url_list", [])
            if nick:
                conv['nickname'] = nick
            if av_urls:
                conv['avatar'] = av_urls[0]
        except Exception:
            pass

    # 验证完整性：如果所有昵称仍是占位名，不写缓存
    all_placeholder = all(
        c.get('nickname', '').startswith('\u7528\u6237') for c in convs
    )
    if all_placeholder and len(convs) > 0:
        raise RuntimeError("所有用户昵称仍是占位名，缓存未写入")


# ── Protobuf 解析 ──

_cached_messages: list[dict] = []  # 最新拉取的历史消息


def get_cached_messages() -> list[dict]:
    """获取已解析的历史消息（含真实时间戳）"""
    return _cached_messages


def _parse_protobuf(raw: bytes, my_uid: str) -> list[dict]:
    conv_pattern = re.compile(rb'0:1:(\d+):(\d+)')
    peer_set = {}
    for peer_bytes, _ in conv_pattern.findall(raw):
        peer = peer_bytes.decode()
        if peer not in peer_set:
            peer_set[peer] = True

    # 只靠 API 查昵称，不硬编码
    nick_map = {}

    # sec_uid
    sec_pat = re.compile(rb'MS4wLjAB[A-Za-z0-9_-]{50,}')
    my_sec = ""
    sec_uids = {}
    for peer in peer_set:
        for m in re.finditer(f'0:1:{peer}:{my_uid}'.encode(), raw):
            secs = sec_pat.findall(raw[m.start():m.start()+3000])
            for s in secs:
                d = s.decode()
                if not my_sec: my_sec = d; continue
                if d != my_sec: sec_uids[peer] = d; break
            if peer in sec_uids: break

    return [{'peer_uid': p, 'nickname': nick_map.get(p, f'用户{p}'),
             'sec_uid': sec_uids.get(p, ''), 'avatar': ''} for p in peer_set]


def _parse_and_cache_messages(raw: bytes, my_uid: str):
    """从 protobuf 解析消息并存入全局缓存"""
    global _cached_messages
    try:
        from dmshoot.utils.proto_msg_parser import extract_messages_from_protobuf
        parsed = extract_messages_from_protobuf(raw, my_uid)
        if parsed:
            # 去重合并
            existing_keys = {(m.get('sender_uid',''), m.get('content','')[:60]) for m in _cached_messages}
            for m in parsed:
                key = (m['sender_uid'], m['content'][:60])
                if key not in existing_keys:
                    _cached_messages.append(m)
                    existing_keys.add(key)
            logger.info(f"Protobuf 消息解析: +{len(parsed)}条 (总计{len(_cached_messages)})")
    except Exception as e:
        logger.debug(f"Protobuf 消息解析跳过: {e}")


# ── 主入口 ──

def fetch_conversations_sync(cookie_str: str) -> list[dict]:
    """同步获取历史会话 — 无 asyncio，安全用于 QThread"""
    key = _cache_key(cookie_str)

    # L1: JSON 缓存（完整结果）
    convs = _load_json_cache(key)
    if convs:
        logger.success(f"缓存命中 L1(JSON) → {len(convs)}会话")
        # L1 时也尝试从 L2 Protobuf 提取消息
        raw_l2 = _load_raw_cache(key)
        if raw_l2:
            from dmshoot.utils.douyin_sdk import create_auth
            auth_l2 = create_auth(cookie_str)
            _parse_and_cache_messages(raw_l2, str(auth_l2.get_uid()))
        return convs

    # L2: Protobuf 缓存 → 解析
    raw = _load_raw_cache(key)
    if raw:
        logger.info(f"缓存命中 L2(Protobuf) → 需补全昵称头像")
        from dmshoot.utils.douyin_sdk import create_auth
        auth = create_auth(cookie_str)
        my_uid = str(auth.get_uid())
        convs = _parse_protobuf(raw, my_uid)
        # 解析消息
        _parse_and_cache_messages(raw, my_uid)
        # 尝试补全用户信息
        enriched = False
        try:
            _enrich_all(convs, cookie_str)
            enriched = True
            logger.success(f"L2 昵称补全成功 → {len(convs)}会话")
        except Exception:
            logger.warning("L2 昵称补全失败，将用占位名")
        if enriched:
            _save_json_cache(key, convs)
        return convs

    # L3: 子进程 Playwright（同步获取 protobuf + 用户数据）
    logger.info("缓存未命中，启动 L3(Playwright) 拉取...")
    raw, user_data, _ = _fetch_raw_via_subprocess(cookie_str)
    if not raw:
        logger.warning("L3 未获取到数据 → 首次启动将通过 WS 实时积累消息")
        return []

    _save_raw_cache(key, raw)
    logger.success(f"L3 Protobuf 已缓存 ({len(raw)} bytes)")

    from dmshoot.utils.douyin_sdk import create_auth
    auth = create_auth(cookie_str)
    my_uid = str(auth.get_uid())
    convs = _parse_protobuf(raw, my_uid)

    # 从 protobuf 解析消息（弥补 Playwright JS fetch 失败的情况）
    _parse_and_cache_messages(raw, my_uid)

    # 合并子进程获取的昵称和头像
    if user_data:
        for conv in convs:
            uid = conv['peer_uid']
            if uid in user_data:
                info = user_data[uid]
                if info.get('nick'):
                    conv['nickname'] = info['nick']
                if info.get('av'):
                    conv['avatar'] = info['av']
                if info.get('sec'):
                    conv['sec_uid'] = info['sec']
    else:
        # 回退：尝试 API 补全昵称
        enriched = False
        try:
            _enrich_all(convs, cookie_str)
            enriched = True
        except Exception:
            pass
    # 只在昵称头像完整时才写 JSON 缓存
    has_names = any(
        c.get('nickname') and not c['nickname'].startswith('\u7528\u6237')
        for c in convs
    )
    if has_names:
        _save_json_cache(key, convs)
        logger.success(f"L3 完成 → {len(convs)}会话, 昵称头像已缓存")
    else:
        logger.warning(f"L3 完成 → {len(convs)}会话, 昵称头像缺失, 未缓存")
    return convs
