"""平台连接验证器 — 用 Cookie 实际登录验证"""

import httpx


async def verify_douyin(cookie: str) -> tuple[bool, str]:
    """验证抖音 Cookie 是否有效，返回 (成功, 昵称)"""
    headers = {
        "Cookie": cookie,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://creator.douyin.com/",
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # 请求创作者中心 API 验证登录态
            resp = await client.get(
                "https://creator.douyin.com/creator-micro/home",
                headers=headers,
                follow_redirects=False,
            )
            # 如果返回200且没有被重定向到登录页，说明 Cookie 有效
            if resp.status_code == 200 and "login" not in resp.url.path.lower():
                # 尝试提取昵称
                try:
                    data = await client.get(
                        "https://creator.douyin.com/web/api/media/user/info/",
                        headers=headers,
                    )
                    if data.status_code == 200:
                        j = data.json()
                        if j.get("user", {}).get("nickname"):
                            return True, j["user"]["nickname"]
                except Exception:
                    pass
                return True, "已连接"
            return False, "Cookie已失效"
    except Exception as e:
        return False, str(e)


async def verify_bilibili(sessdata: str, bili_jct: str,
                         buvid3: str = "", buvid4: str = "",
                         dedeuserid: str = "", ac_time_value: str = ""
                         ) -> tuple[bool, str]:
    """验证B站 Cookie 是否有效"""
    try:
        from bilibili_api import user, sync
        credential = __import__("bilibili_api", fromlist=["Credential"]).Credential(
            sessdata=sessdata,
            bili_jct=bili_jct,
            buvid3=buvid3,
            buvid4=buvid4,
            dedeuserid=dedeuserid,
            ac_time_value=ac_time_value,
        )
        info = sync(user.get_self_info(credential))
        name = info.get("name", "已连接") if isinstance(info, dict) else "已连接"
        return True, name
    except Exception as e:
        return False, str(e)
