"""
Módulo de encriptación segura para credenciales.

Este módulo implementa encriptación de credenciales usando:
- PBKDF2 para derivación de claves (OWASP 2023 recomendación)
- Salt único por registro
- Fernet (AES-256) para encriptación simétrica

IMPORTANTE: Este módulo mantiene compatibilidad con credenciales legacy
que fueron encriptadas con el sistema anterior (sin salt).

Uso:
    from app.utils.encryption import encrypt_credential, decrypt_credential

    # Encriptar (genera salt automáticamente)
    encrypted, salt = encrypt_credential('mi_contraseña_secreta')

    # Desencriptar
    password = decrypt_credential(encrypted, salt)

    # Compatibilidad legacy (sin salt)
    password = decrypt_credential(encrypted_legacy, salt=None)
"""

import os
import base64
import hashlib
from typing import Tuple, Optional
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
from flask import current_app


# Configuración de PBKDF2 (OWASP 2023)
PBKDF2_ITERATIONS = 480000  # OWASP recomienda 600,000 para SHA-256, pero 480,000 es aceptable
SALT_LENGTH = 32  # 256 bits


def _get_master_key() -> bytes:
    """
    Obtiene la clave maestra de configuración.

    Returns:
        bytes: Clave maestra codificada en UTF-8
    """
    key = current_app.config.get('ENCRYPTION_KEY', '')
    if not key:
        raise ValueError("ENCRYPTION_KEY no está configurada")
    return key.encode('utf-8')


def _derive_key_with_salt(master_key: bytes, salt: bytes) -> bytes:
    """
    Deriva una clave de encriptación usando PBKDF2 con salt.

    Args:
        master_key: Clave maestra
        salt: Salt único para esta derivación

    Returns:
        bytes: Clave derivada de 32 bytes (base64-encoded para Fernet)
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
        backend=default_backend()
    )
    key = kdf.derive(master_key)
    return base64.urlsafe_b64encode(key)


def _derive_key_legacy(master_key: bytes) -> bytes:
    """
    Deriva clave usando el método legacy (SHA-256 sin salt).
    Solo para compatibilidad con datos existentes.

    Args:
        master_key: Clave maestra

    Returns:
        bytes: Clave derivada (base64-encoded para Fernet)
    """
    key_bytes = hashlib.sha256(master_key).digest()
    return base64.urlsafe_b64encode(key_bytes)


def generate_salt() -> bytes:
    """
    Genera un salt criptográficamente seguro.

    Returns:
        bytes: Salt de SALT_LENGTH bytes
    """
    return os.urandom(SALT_LENGTH)


def encrypt_credential(plaintext: str, salt: bytes = None) -> Tuple[str, str]:
    """
    Encripta una credencial con salt único.

    Args:
        plaintext: Texto a encriptar
        salt: Salt a usar (opcional, genera uno nuevo si no se proporciona)

    Returns:
        Tuple[str, str]: (texto_encriptado, salt_base64)

    Ejemplo:
        encrypted, salt = encrypt_credential('mi_password')
        # Guardar ambos en la BD
    """
    master_key = _get_master_key()

    if salt is None:
        salt = generate_salt()
    elif isinstance(salt, str):
        salt = base64.b64decode(salt)

    derived_key = _derive_key_with_salt(master_key, salt)
    cipher = Fernet(derived_key)

    encrypted = cipher.encrypt(plaintext.encode('utf-8'))

    return encrypted.decode('utf-8'), base64.b64encode(salt).decode('utf-8')


def decrypt_credential(ciphertext: str, salt: Optional[str] = None) -> str:
    """
    Desencripta una credencial.

    Si salt es None, usa el método legacy para compatibilidad
    con credenciales antiguas.

    Args:
        ciphertext: Texto encriptado
        salt: Salt en base64 (None para modo legacy)

    Returns:
        str: Texto desencriptado

    Raises:
        InvalidToken: Si la desencriptación falla
    """
    master_key = _get_master_key()

    if salt:
        # Modo nuevo: derivación con salt
        salt_bytes = base64.b64decode(salt)
        derived_key = _derive_key_with_salt(master_key, salt_bytes)
    else:
        # Modo legacy: SHA-256 sin salt
        derived_key = _derive_key_legacy(master_key)

    cipher = Fernet(derived_key)
    return cipher.decrypt(ciphertext.encode('utf-8')).decode('utf-8')


def is_credential_salted(salt: Optional[str]) -> bool:
    """
    Verifica si una credencial usa el nuevo sistema con salt.

    Args:
        salt: Valor del campo salt

    Returns:
        bool: True si usa salt (sistema nuevo)
    """
    return salt is not None and len(salt) > 0


def migrate_credential(old_ciphertext: str) -> Tuple[str, str]:
    """
    Migra una credencial del formato legacy al nuevo formato con salt.

    Args:
        old_ciphertext: Credencial encriptada con sistema legacy

    Returns:
        Tuple[str, str]: (nuevo_ciphertext, nuevo_salt)

    Uso:
        # Desencriptar con legacy, re-encriptar con salt
        plaintext = decrypt_credential(old_ciphertext, salt=None)
        new_encrypted, new_salt = encrypt_credential(plaintext)
    """
    # Desencriptar con método legacy
    plaintext = decrypt_credential(old_ciphertext, salt=None)

    # Re-encriptar con salt
    return encrypt_credential(plaintext)


# ============================================================================
# FUNCIONES DE COMPATIBILIDAD CON CÓDIGO EXISTENTE
# ============================================================================

def obtener_cipher_legacy():
    """
    Obtiene cipher legacy para compatibilidad.
    DEPRECADO: Usar encrypt_credential/decrypt_credential en su lugar.
    """
    master_key = _get_master_key()
    derived_key = _derive_key_legacy(master_key)
    return Fernet(derived_key)


def obtener_cipher_con_salt(salt: str):
    """
    Obtiene cipher con salt específico.

    Args:
        salt: Salt en base64

    Returns:
        Fernet: Cipher configurado
    """
    master_key = _get_master_key()
    salt_bytes = base64.b64decode(salt)
    derived_key = _derive_key_with_salt(master_key, salt_bytes)
    return Fernet(derived_key)
