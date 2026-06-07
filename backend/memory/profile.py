import json
from pathlib import Path
from logger import log_system

PROFILE_PATH = Path.home() / "FRIDAY" / "memory" / "profile.json"
PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)

DEFAULT_PROFILE = {
    "name": "Siddharth",
    "location": "Bengaluru, India",
    "projects": {
        "FRIDAY": {"status": "active", "stack": ["Python", "Ollama"]},
        "cocode": {"status": "completed", "stack": ["React", "FastAPI"]},
    },
    "interests": ["FC Barcelona", "football", "AI", "local models"],
    "preferences": {
        "editor": "Cursor",
        "languages": ["Python", "TypeScript"],
    },
    "relationships": {},
    "schedule": {},
    "last_updated": "",
}


def get_profile() -> dict:
    if not PROFILE_PATH.exists():
        save_profile(DEFAULT_PROFILE)
        return DEFAULT_PROFILE
    with open(PROFILE_PATH, "r") as f:
        return json.load(f)


def save_profile(profile: dict):
    with open(PROFILE_PATH, "w") as f:
        json.dump(profile, f, indent=2)


def get_profile_prompt() -> str:
    profile = get_profile()
    return f"""User profile:
- Name: {profile.get('name')}
- Current home city: {profile.get('location')} (this is a LIVES_IN fact, not a preference)
- Projects: {', '.join(profile.get('projects', {}).keys())}
- Interests: {', '.join(profile.get('interests', []))}
- Preferred languages: {', '.join(profile.get('preferences', {}).get('languages', []))}"""
