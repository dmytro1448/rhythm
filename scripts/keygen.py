"""Генерує STATE_KEY для шифрування стану."""

from cryptography.fernet import Fernet

print(Fernet.generate_key().decode())
