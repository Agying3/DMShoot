"""抖音签名工具 — 通过 Node.js subprocess 调用 dy_ab.js 生成签名

依赖:
  - Node.js (C:\\Users\\Administrator\\.workbuddy\\binaries\\node\\versions\\22.12.0\\node.exe)
  - jsrsasign (npm install jsrsasign, 已装在 H:\\DMShoot\\external\\DouYin_Spider\\node_modules)
"""

import subprocess
import tempfile
import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 路径配置 — 基于项目根目录，不依赖用户名/盘符
import shutil
_PROJECT_ROOT = Path(__file__).parent.parent.parent  # dmshoot/utils → H:\DMShoot
_JS_FILE = str(_PROJECT_ROOT / "external" / "DouYin_Spider" / "static" / "dy_ab.js")
_NODE_MODULES = str(_PROJECT_ROOT / "external" / "DouYin_Spider" / "node_modules")

# 缓存 Node.js 路径
_NODE = None


def _find_node() -> str:
    """惰性查找 Node.js，兼容 GUI 环境 PATH 与终端不同的问题"""
    global _NODE
    if _NODE is not None:
        return _NODE
    candidates = [
        shutil.which("node"),
        shutil.which("node.exe"),
        str(Path.home() / ".workbuddy" / "binaries" / "node" / "versions" / "22.22.2" / "node.exe"),
        str(Path.home() / ".workbuddy" / "binaries" / "node" / "versions" / "22.12.0" / "node.exe"),
    ]
    for path in candidates:
        if path and Path(path).is_file():
            _NODE = path
            logger.info(f"Node.js 路径: {_NODE}")
            return _NODE
    raise RuntimeError("Node.js 未安装或不在 PATH 中，抖音签名功能不可用")

# 缓存编译后的 JS wrapper
_js_code = None


def _get_js_wrapper():
    """返回已拼接好 dy_ab.js + 命令行调用逻辑的代码"""
    global _js_code
    if _js_code is None:
        base = open(_JS_FILE, encoding="utf-8").read()
        _js_code = base + """
try {
    const fn = process.argv[2];
    let result;
    if (fn === 'get_ab') result = get_ab(process.argv[3] || '', process.argv[4] || '');
    else if (fn === 'get_req_sign') result = get_req_sign(process.argv[3] || '', process.argv[4] || '');
    else if (fn === 'get_ree_key') result = get_ree_key(process.argv[3] || '');
    else throw new Error('Unknown fn: ' + fn);
    process.stdout.write(JSON.stringify({ok:true, result: result || ''}));
} catch(e) {
    process.stdout.write(JSON.stringify({ok:false, error: e.message}));
}
"""
    return _js_code


def _call_js(fn: str, p1: str = "", p2: str = "") -> str:
    """调用 JS 函数，返回结果字符串。失败返回空字符串。"""
    import json
    code = _get_js_wrapper()
    with tempfile.NamedTemporaryFile(suffix=".js", mode="w", encoding="utf-8", delete=False) as f:
        f.write(code)
        tmp = f.name
    try:
        env = {
            **os.environ,
            "NODE_OPTIONS": "",
            "NODE_PATH": _NODE_MODULES,
        }
        proc = subprocess.run(
            [_find_node(), tmp, fn, str(p1), str(p2)],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(Path(_NODE_MODULES).parent),
            timeout=30,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout.strip())
            if data.get("ok"):
                return str(data["result"])
            logger.debug(f"JS {fn} error: {data.get('error')}")
        return ""
    except Exception as e:
        logger.error(f"JS {fn} 调用失败: {e}")
        return ""
    finally:
        try:
            os.unlink(tmp)
        except:
            pass


def generate_a_bogus(query: str, data: str = "") -> str:
    """生成抖音 API 的 a_bogus 参数"""
    return _call_js("get_ab", query, data)


def generate_req_sign(data: str, private_key: str) -> str:
    """生成 IM protobuf 请求的 ECDSA 签名"""
    return _call_js("get_req_sign", data, private_key)


def generate_ree_key(private_key: str) -> str:
    """将 ECDSA 私钥转换为 base64 公钥"""
    return _call_js("get_ree_key", private_key)


# 测试
if __name__ == "__main__":
    bogus = generate_a_bogus("aid=6383&device_platform=webapp", "")
    print(f"a_bogus: {bogus[:60]}...")
    print("OK" if bogus else "FAIL")
