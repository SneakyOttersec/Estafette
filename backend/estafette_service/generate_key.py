"""Print a Fernet key suitable for TOKEN_ENCRYPTION_KEY."""

from cryptography.fernet import Fernet

if __name__ == "__main__":
    print(Fernet.generate_key().decode("ascii"))
