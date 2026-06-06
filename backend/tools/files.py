from pathlib import Path


def read_file(path: str) -> str:
    try:
        file_path = Path(path).expanduser()
        if not file_path.exists():
            return f"File not found: {path}"
        return file_path.read_text()
    except Exception as e:
        return f"Error reading file: {e}"


def write_file(path: str, content: str) -> str:
    try:
        file_path = Path(path).expanduser()
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)
        return f"Successfully wrote to {path}"
    except Exception as e:
        return f"Error writing file: {e}"
