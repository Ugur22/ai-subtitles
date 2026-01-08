"""
API key encryption service using AES-256-GCM.

Encryption key is stored in Supabase Vault for security.
"""
import os
from typing import Optional
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from services.supabase_service import SupabaseService


# Cache encryption key in memory for performance
_encryption_key_cache: Optional[bytes] = None


async def get_encryption_key() -> bytes:
    """
    Get encryption key from Supabase Vault.

    Caches key in memory after first retrieval for performance.

    Returns:
        32-byte encryption key for AES-256-GCM

    Raises:
        Exception: If key not found in vault or invalid format
    """
    global _encryption_key_cache

    if _encryption_key_cache is not None:
        return _encryption_key_cache

    try:
        client = SupabaseService.get_client()

        # Read secret from Supabase Vault via public wrapper function
        response = client.rpc("get_vault_secret", {"secret_name_input": "api_key_encryption"}).execute()

        if not response.data or len(response.data) == 0 or response.data[0].get("secret") is None:
            raise Exception("Encryption key not found in Supabase Vault")

        # Convert hex string to bytes
        key_hex = response.data[0]["secret"]
        key_bytes = bytes.fromhex(key_hex)

        if len(key_bytes) != 32:
            raise Exception(f"Invalid encryption key length: {len(key_bytes)} bytes (expected 32)")

        # Cache for future use
        _encryption_key_cache = key_bytes

        print("[Encryption] Loaded encryption key from Supabase Vault")

        return key_bytes

    except Exception as e:
        print(f"[Encryption] Failed to get encryption key: {e}")
        raise Exception(f"Failed to get encryption key from vault: {str(e)}")


def encrypt_api_key(key: str, encryption_key: bytes) -> str:
    """
    Encrypt API key with AES-256-GCM.

    Format: nonce (12 bytes) + ciphertext + auth tag
    Returns hex-encoded string.

    Args:
        key: Plain text API key to encrypt
        encryption_key: 32-byte encryption key from vault

    Returns:
        Hex-encoded encrypted data (nonce + ciphertext)

    Raises:
        Exception: If encryption fails
    """
    try:
        aesgcm = AESGCM(encryption_key)

        # Generate random nonce (12 bytes for GCM)
        nonce = os.urandom(12)

        # Encrypt (includes authentication tag)
        ciphertext = aesgcm.encrypt(nonce, key.encode('utf-8'), None)

        # Combine nonce + ciphertext and encode as hex
        encrypted_data = nonce + ciphertext

        return encrypted_data.hex()

    except Exception as e:
        print(f"[Encryption] Failed to encrypt API key: {e}")
        raise Exception(f"Encryption failed: {str(e)}")


def decrypt_api_key(encrypted: str, encryption_key: bytes) -> str:
    """
    Decrypt API key encrypted with AES-256-GCM.

    Args:
        encrypted: Hex-encoded encrypted data (nonce + ciphertext)
        encryption_key: 32-byte encryption key from vault

    Returns:
        Decrypted plain text API key

    Raises:
        Exception: If decryption fails or authentication fails
    """
    try:
        # Decode from hex
        data = bytes.fromhex(encrypted)

        # Split nonce and ciphertext
        nonce = data[:12]
        ciphertext = data[12:]

        # Decrypt and verify authentication tag
        aesgcm = AESGCM(encryption_key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)

        return plaintext.decode('utf-8')

    except Exception as e:
        print(f"[Encryption] Failed to decrypt API key: {e}")
        raise Exception(f"Decryption failed: {str(e)}")


def get_key_suffix(api_key: str, length: int = 4) -> str:
    """
    Get last N characters of API key for display.

    Args:
        api_key: Plain text API key
        length: Number of characters to return (default 4)

    Returns:
        Last N characters of key
    """
    if len(api_key) <= length:
        return api_key

    return api_key[-length:]


def clear_encryption_key_cache() -> None:
    """
    Clear cached encryption key from memory.

    Useful for key rotation - forces reload from vault on next use.
    """
    global _encryption_key_cache
    _encryption_key_cache = None
    print("[Encryption] Cleared encryption key cache")
