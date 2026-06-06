import json
import logging
from datetime import datetime
from pathlib import Path

# =========================================================
# SESSION
# =========================================================

SESSION_ID = datetime.now().strftime("%H%M%S")

# =========================================================
# SYSTEM NAME MAP — update here to add custom names
# =========================================================

SYSTEM_NAMES = {
    "tool": "TOOL",
    "executor": "EXECUTOR",
    "llm": "LLM",
    "stt": "STT",
    "tts": "TTS",
    "main": "MAIN",
    "memory": "MEMORY",
    "web": "WEB",
}


def get_system_name(key: str) -> str:
    return SYSTEM_NAMES.get(key, key.upper())


# =========================================================
# LOG DIRECTORIES
# =========================================================

BASE_LOG_DIR = Path.home() / "FRIDAY" / "logs"

CONVO_LOG_DIR = BASE_LOG_DIR / "conversations"
ERROR_LOG_DIR = BASE_LOG_DIR / "errors"

CONVO_LOG_DIR.mkdir(parents=True, exist_ok=True)
ERROR_LOG_DIR.mkdir(parents=True, exist_ok=True)

# =========================================================
# LOG FILES
# =========================================================

DATE = datetime.now().strftime("%Y-%m-%d")

CONVO_LOG_FILE = CONVO_LOG_DIR / f"friday_{DATE}.log"
ERROR_LOG_FILE = ERROR_LOG_DIR / f"errors_{DATE}.log"

# =========================================================
# LOGGER
# =========================================================

logger = logging.getLogger("FRIDAY")
logger.setLevel(logging.INFO)

formatter = logging.Formatter(
    f"%(asctime)s | {SESSION_ID} | %(levelname)s | %(message)s"
)

# =========================================================
# HANDLERS
# =========================================================

convo_handler = logging.FileHandler(CONVO_LOG_FILE)
convo_handler.setFormatter(formatter)

error_handler = logging.FileHandler(ERROR_LOG_FILE)
error_handler.setLevel(logging.ERROR)
error_handler.setFormatter(formatter)

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)

logger.addHandler(convo_handler)
logger.addHandler(error_handler)
logger.addHandler(console_handler)

# =========================================================
# LOG HELPERS
# =========================================================


def log_user(text: str):
    logger.info(f"[USER] {text}")


def log_response(response):
    if isinstance(response, (dict, list)):
        response = json.dumps(response, indent=2, ensure_ascii=False)
    logger.info(f"[FRIDAY] {response}")


def log_tool(system: str, name: str, args: dict):
    label = get_system_name(system)
    logger.info(f"[{label}] TOOL CALL: {name} → {json.dumps(args, ensure_ascii=False)}")


def log_result(system: str, result):
    label = get_system_name(system)
    result = str(result)
    if len(result) > 500:
        result = result[:500] + "..."
    logger.info(f"[{label}] RESULT: {result}")


def log_error(error: str):
    logger.error(f"[ERROR] {error}")


def log_system(system: str, msg: str):
    label = get_system_name(system)
    logger.info(f"[{label}] {msg}")
