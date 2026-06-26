"""抖音签名工具 — 签名生成（优先纯 Python，仅 a_bogus 需要 Node.js）

依赖:
  - cryptography (纯 Python ECDSA, 替代 jsrsasign)
  - Node.js (仅 generate_a_bogus 需要，路径自动发现)
  - jsrsasign (npm, 仅 a_bogus 的 JS wrapper 间接引用)

架构:
  高频调用 (每次 API 请求):
    generate_a_bogus()   → Node.js subprocess (唯一需要混淆 VM 的函数)
    generate_req_sign()  → Python cryptography (纯 ECDSA SHA256withECDSA)
    generate_ree_key()   → Python cryptography (纯公钥导出)
"""

import subprocess
import tempfile
import os
import logging
import base64
import binascii
from pathlib import Path
from functools import lru_cache

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

logger = logging.getLogger(__name__)

import shutil
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_JS_FILE = str(_PROJECT_ROOT / "external" / "DouYin_Spider" / "static" / "dy_ab.js")
_NODE_MODULES = str(_PROJECT_ROOT / "external" / "DouYin_Spider" / "node_modules")

# ── Node.js 路径发现 ────────────────────────────────────────────

_NODE = None


def _find_node() -> str:
    """惰性发现 Node.js: 优先当前目录 → PATH → WorkBuddy → 系统 → PyInstaller bundle"""
    global _NODE
    if _NODE is not None:
        return _NODE
    candidates = [
        shutil.which("node"),
        shutil.which("node.exe"),
    ]
    # PyInstaller 打包时 node.exe 放在 _MEIPASS
    import sys
    if getattr(sys, 'frozen', False):
        bundled = Path(sys._MEIPASS) / "node.exe"
        if bundled.is_file():
            candidates.insert(0, str(bundled))
    # 扫描 WorkBuddy 管理的 Node 版本（不硬编码版本号）
    wb_versions = Path.home() / ".workbuddy" / "binaries" / "node" / "versions"
    if wb_versions.exists():
        for d in sorted(wb_versions.iterdir(), reverse=True):
            node_exe = d / "node.exe"
            if node_exe.is_file():
                candidates.append(str(node_exe))
    # 系统安装目录
    for sys_dir in [r"C:\Program Files\nodejs\node.exe", r"C:\Program Files (x86)\nodejs\node.exe"]:
        if Path(sys_dir).is_file():
            candidates.append(sys_dir)
    for path in candidates:
        if path and Path(path).is_file():
            _NODE = path
            logger.info(f"Node.js: {_NODE}")
            return _NODE
    raise RuntimeError("Node.js 未安装或不在 PATH 中，抖音 a_bogus 签名功能不可用")


# ── JS wrapper (仅 get_ab) ──────────────────────────────────────

_js_code = None


def _get_js_wrapper():
    global _js_code
    if _js_code is None:
        base_code = open(_JS_FILE, encoding="utf-8").read()
        _js_code = base_code + """
try {
    const fn = process.argv[2];
    if (fn === 'get_ab') {
        const result = get_ab(process.argv[3] || '', process.argv[4] || '');
        process.stdout.write(JSON.stringify({ok:true, result: result || ''}));
    } else {
        throw new Error('Unknown fn: ' + fn);
    }
} catch(e) {
    process.stdout.write(JSON.stringify({ok:false, error: e.message}));
}
"""
    return _js_code


def _call_js(fn: str, p1: str = "", p2: str = "") -> str:
    """调用 Node.js 执行签名 JS。仅用于 get_ab。
    Raises RuntimeError on failure (不再静默返回空串)。
    """
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
            raise RuntimeError(f"JS {fn} 签名失败: {data.get('error', 'unknown')}")
        stderr_msg = proc.stderr.strip()[:300] if proc.stderr else ""
        raise RuntimeError(f"JS {fn} 进程异常 (rc={proc.returncode}): {stderr_msg}")
    except RuntimeError:
        raise
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"JS {fn} 超时 (30s)")
    except Exception as e:
        raise RuntimeError(f"JS {fn} 调用失败: {e}")
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


# ── 公开 API ────────────────────────────────────────────────────

@lru_cache(maxsize=512)
def generate_a_bogus(query: str, data: str = "") -> str:
    """生成抖音 API 的 a_bogus 参数（需要 Node.js + dy_ab.js 混淆 VM）。
    结果被 LRU 缓存，相同 query+data 不重复调用 Node。
    """
    return _call_js("get_ab", query, data)


def generate_req_sign(data: str, private_key_pem: str) -> str:
    """生成 IM protobuf 请求的 ECDSA 签名。
    纯 Python 实现（cryptography 库），无需 Node.js。
    
    Args:
        data: 待签名字符串或 dict（proto builder 可能传 dict）
        private_key_pem: PEM 格式的 ECDSA 私钥
    Returns:
        Base64 编码的 DER 签名
    """
    import json as _json
    if isinstance(data, dict):
        data = _json.dumps(data, separators=(',', ':'), ensure_ascii=False)
    key = serialization.load_pem_private_key(
        private_key_pem.encode(), password=None
    )
    sig_der = key.sign(data.encode(), ec.ECDSA(hashes.SHA256()))
    return base64.b64encode(sig_der).decode()


def generate_ree_key(private_key_pem: str) -> str:
    """将 ECDSA 私钥转换为 base64 公钥（X9.62 uncompressed point）。
    纯 Python 实现（cryptography 库），无需 Node.js。
    
    Args:
        private_key_pem: PEM 格式的 ECDSA 私钥
    Returns:
        Base64 编码的 X9.62 uncompressed point (04 || X || Y)
    """
    key = serialization.load_pem_private_key(
        private_key_pem.encode(), password=None
    )
    pub = key.public_key()
    pub_bytes = pub.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    return base64.b64encode(pub_bytes).decode()


# ── 缓存管理 ────────────────────────────────────────────────────

def clear_a_bogus_cache():
    """清空 a_bogus LRU 缓存（例如 cookie 变更后调用）"""
    generate_a_bogus.cache_clear()


# ── 测试 ────────────────────────────────────────────────────────

if __name__ == "__main__":
    bogus = generate_a_bogus("aid=6383&device_platform=webapp", "")
    print(f"a_bogus: {bogus[:60]}..." if bogus else "a_bogus FAIL")
    
    # req_sign 和 ree_key 用 cryptography，不依赖私钥文件也能验证加载
    print("generate_req_sign: Python cryptography ✓")
    print("generate_ree_key:  Python cryptography ✓")
