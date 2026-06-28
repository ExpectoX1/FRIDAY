import json
import logging
import os
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
logger.propagate = False

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

logger.addHandler(convo_handler)
logger.addHandler(error_handler)

DEBUG_CONSOLE = os.getenv("FRIDAY_DEBUG", "0") == "1"
STATUS_CONSOLE = os.getenv("FRIDAY_STATUS", "1") == "1"

if DEBUG_CONSOLE:
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

# =========================================================
# LOG HELPERS
# =========================================================


def log_user(text: str):
    logger.info(f"[USER] {text}")


def log_response(response):
    if isinstance(response, (dict, list)):
        # default=str so any non-serializable payload logs instead of crashing.
        response = json.dumps(response, indent=2, ensure_ascii=False, default=str)
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


def status(label: str, msg: str = ""):
    """Small user-facing terminal status.

    Full structured logs still go to ~/FRIDAY/logs. By default the terminal only
    gets these concise progress lines; set FRIDAY_DEBUG=1 for the full log firehose.
    """
    if not STATUS_CONSOLE:
        return
    text = f"{label}: {msg}" if msg else label
    print(text, flush=True)
