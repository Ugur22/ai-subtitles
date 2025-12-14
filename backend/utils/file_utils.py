"""
File utility functions
"""
import hashlib


def generate_file_hash(file_path: str) -> str:
    """Generate a unique hash for a file based on its content"""
    BUF_SIZE = 65536  # 64kb chunks
    sha256 = hashlib.sha256()

    with open(file_path, 'rb') as f:
        while True:
            data = f.read(BUF_SIZE)
            if not data:
                break
            sha256.update(data)

    return sha256.hexdigest()
