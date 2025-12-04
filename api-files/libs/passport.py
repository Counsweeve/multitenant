import base64
import hashlib
import json
import logging

import jwt
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes
from Crypto.Util.Padding import pad, unpad
from werkzeug.exceptions import Unauthorized

from configs import dify_config
from libs.rsa import encrypt


class PassportService:
    def __init__(self):
        self.sk = dify_config.SECRET_KEY
        # 优先使用配置文件中指定的静态密钥，否则从 SECRET_KEY 派生
        if hasattr(dify_config, "MAGIC_LINK_ENCRYPTION_KEY") and dify_config.MAGIC_LINK_ENCRYPTION_KEY:
            # 使用配置文件中指定的静态密钥（base64 编码）
            try:
                self.encryption_key = base64.b64decode(dify_config.MAGIC_LINK_ENCRYPTION_KEY)
                # 确保密钥长度是 32 字节（256位）
                if len(self.encryption_key) != 32:
                    raise ValueError(
                        f"Encryption key must be 32 bytes (256 bits), got {len(self.encryption_key)} bytes")
            except Exception as e:
                # 如果解码失败，回退到派生方式
                logger = logging.getLogger(__name__)
                logger.warning(f"Failed to use MAGIC_LINK_ENCRYPTION_KEY, falling back to SECRET_KEY derivation: {e}")
                self.encryption_key = hashlib.sha256(self.sk.encode()).digest()
        else:
            # 从 SECRET_KEY 派生 AES 加密密钥（256位）
            self.encryption_key = hashlib.sha256(self.sk.encode()).digest()

    def issue(self, payload):
        return jwt.encode(payload, self.sk, algorithm="HS256")

    def verify(self, token):
        try:
            return jwt.decode(token, self.sk, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            raise Unauthorized("Token has expired.")
        except jwt.InvalidSignatureError:
            raise Unauthorized("Invalid token signature.")
        except jwt.DecodeError:
            raise Unauthorized("Invalid token.")
        except jwt.PyJWTError:  # Catch-all for other JWT errors
            raise Unauthorized("Invalid token.")
    def _encrypt_payload(self, payload: dict) -> str:
        try:
            payload_json = json.dumps(payload, separators=(',', ':'))

            iv = get_random_bytes(16)

            cipher = AES.new(self.encryption_key, AES.MODE_CBC, iv)

            padded_data = pad(payload_json.encode(), AES.block_size)
            encrypted_data = cipher.encrypt(padded_data)

            combined = iv + encrypted_data

            return base64.b64encode(combined).decode()
        except Exception as e:
            raise ValueError(f"Encryption failed: {str(e)}") from e

    def _decrypt_payload(self, encrypted_payload: str) -> dict:
        try:
            # Base64 解码
            combined = base64.b64decode(encrypted_payload)

            # 提取 IV (前16字节) 和加密数据
            iv = combined[:16]
            encrypted_data_bytes = combined[16:]

            # 创建 AES cipher
            cipher = AES.new(self.encryption_key, AES.MODE_CBC, iv)

            # 解密并去除 padding
            decrypted_data = unpad(cipher.decrypt(encrypted_data_bytes), AES.block_size)

            # 解析 JSON
            payload_json = decrypted_data.decode("utf-8")
            return json.loads(payload_json)
        except Exception as e:
            raise ValueError(f"Decryption failed: {str(e)}") from e

    def issue_encrypted(self, payload: dict) -> str:
        """
        生成加密的 token（对称加密 payload）

        Args:
            payload: JWT payload 字典

        Returns:
            加密后的 JWT token
        """
        # 加密 payload
        encrypted_payload_str = self._encrypt_payload(payload)
        # 将加密后的字符串作为新的 payload
        jwt_payload = {"encrypted": encrypted_payload_str, "sub": "magic_link_encrypted"}
        # 使用 HS256 签名
        return jwt.encode(jwt_payload, self.sk, algorithm="HS256")

    def verify_encrypted(self, token: str) -> dict:
        """
        验证并解密加密的 token

        Args:
            token: 加密的 JWT token

        Returns:
            解密后的原始 payload 字典

        Raises:
            Unauthorized: 如果 token 无效或解密失败
        """
        try:
            # 先验证 JWT 签名
            decoded = jwt.decode(token, self.sk, algorithms=["HS256"])

            # 检查是否是加密的 token
            if "encrypted" in decoded and decoded.get("sub") == "magic_link_encrypted":
                # 解密 payload
                return self._decrypt_payload(decoded["encrypted"])
            else:
                raise Unauthorized("Token is not encrypted or invalid format.")

        except jwt.ExpiredSignatureError:
            raise Unauthorized("Token has expired.")
        except jwt.InvalidSignatureError:
            raise Unauthorized("Invalid token signature.")
        except jwt.DecodeError:
            raise Unauthorized("Invalid token.")
        except ValueError as e:
            # 解密失败
            raise Unauthorized(f"Token decryption failed: {str(e)}")
        except jwt.PyJWTError:  # Catch-all for other JWT errors
            raise Unauthorized("Invalid token.")
