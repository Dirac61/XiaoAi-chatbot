# -*- coding: utf-8 -*-
"""
AES 加密/解密工具。
用于安全存储用户的 MCP 环境变量（如 TuShare Token）到 MySQL。
"""
import os
import base64
import hashlib
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 加密密钥（从环境变量读取，默认值仅开发环境用）
_AES_KEY_ENV = os.getenv("MCP_AES_KEY", "xiaoai-mcp-aes-key-2026")


def _derive_key(password: str) -> bytes:
    """从密码派生 32 字节密钥（AES-256）"""
    return hashlib.sha256(password.encode("utf-8")).digest()


def encrypt(plaintext: str) -> str:
    """AES 加密明文字符串，返回 Base64 编码的密文。
    入参：plaintext 待加密的明文（如 JSON 字符串）
    返回：Base64 编码的密文字符串
    """
    if not plaintext:
        return ""
    try:
        from cryptography.fernet import Fernet
        key = _derive_key(_AES_KEY_ENV)
        f = Fernet(base64.urlsafe_b64encode(key))
        encrypted = f.encrypt(plaintext.encode("utf-8"))
        return encrypted.decode("utf-8")
    except ImportError:
        # 依赖未安装时用简单 XOR 兜底（仅开发环境，不可用于生产）
        logger.warning("[MCP][加密] cryptography 库未安装，使用不安全的简单加密兜底")
        return _simple_xor(plaintext)
    except Exception as e:
        logger.error(f"[MCP][加密] AES 加密失败: {e}")
        return ""


def decrypt(ciphertext: str) -> str:
    """AES 解密 Base64 密文，返回明文字符串。
    入参：ciphertext Base64 编码的密文
    返回：明文字符串
    """
    if not ciphertext:
        return ""
    try:
        from cryptography.fernet import Fernet
        key = _derive_key(_AES_KEY_ENV)
        f = Fernet(base64.urlsafe_b64encode(key))
        decrypted = f.decrypt(ciphertext.encode("utf-8"))
        return decrypted.decode("utf-8")
    except ImportError:
        logger.warning("[MCP][解密] cryptography 库未安装，使用不安全的简单解密兜底")
        return _simple_xor(ciphertext)
    except Exception as e:
        logger.error(f"[MCP][解密] AES 解密失败: {e}")
        return ""


def _simple_xor(text: str) -> str:
    """简单 XOR 兜底加密（开发环境用，不可用于生产）"""
    key = _AES_KEY_ENV
    result = []
    for i, ch in enumerate(text):
        result.append(chr(ord(ch) ^ ord(key[i % len(key)])))
    return base64.b64encode("".join(result).encode("utf-8")).decode("utf-8")
