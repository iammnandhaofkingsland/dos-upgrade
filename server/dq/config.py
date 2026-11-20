"""All runtime settings in one place. Every value comes from an environment variable so the same
container runs on a laptop, in Cloud Run, and in tests without code changes."""
import os

# Model aliases used in the catalog -> real Gemini model IDs.
# Change a model for all 38 agents by changing one environment variable, not 38 specs.
MODEL_ALIASES = {
    "flash": os.getenv("DQ_MODEL_FLASH", "gemini-3.8-flash"),
    "lite": os.getenv("DQ_MODEL_LITE", "gemini-3.5-flash-lite"),
    "pro": os.getenv("DQ_MODEL_PRO", "gemini-4-argon"),
}
IMAGE_MODEL = os.getenv("DQ_MODEL_IMAGE", "gemini-nano-banana-2.1")
LIVE_MODEL = os.getenv("DQ_MODEL_LIVE", "gemini-3.8-live")
# Embeddings for meaning-based repair-history search (opt-in with DQ_EMBED_SEARCH=1, live mode only).
# gemini-embedding-001 is the long-standing ID; if the AI Studio model picker shows Gemini Embedding 2, put its ID here.
EMBED_MODEL = os.getenv("DQ_MODEL_EMBED", "gemini-embedding-001")
EMBED_SEARCH = os.getenv("DQ_EMBED_SEARCH", "0") == "1"

# live = call Gemini. mock = scripted offline model for rehearsal and tests (never present it as real output).
MODEL_MODE = os.getenv("DQ_MODEL_MODE", "live").lower()
# memory = in-process dict (laptop, tests). firestore = Cloud Firestore (deployed).
STORE = os.getenv("DQ_STORE", "memory").lower()
TENANT = os.getenv("DQ_TENANT", "demo")  # the client used when a request names none
# Shared secret that the console sends in the X-DQ-Key header. Empty = auth off (local only).
API_KEY = os.getenv("DQ_API_KEY", "")
ALLOW_ORIGINS = [o for o in os.getenv("DQ_ALLOW_ORIGINS", "*").split(",") if o]
USD_INR = float(os.getenv("DQ_USD_INR", "88"))
# Limits (step budgets, evaluation pass mark, spend caps) are client settings: see dq/clients.py (layer 2).
PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "")


def resolve_model(alias: str) -> str:
    return MODEL_ALIASES.get(alias, alias)

# ---------------------------------------------------------------- sign-in
# token  = users sign in; every request carries a signed session token (default, use this when deployed)
# headers = X-DQ-Client and X-DQ-Role headers are trusted (only for automated tests and local scripts)
AUTH_MODE = os.getenv("DQ_AUTH_MODE", "token")
# Signs session tokens. Set it from Secret Manager when deployed; a random value is used otherwise
# (then everyone must sign in again after a restart).
SESSION_SECRET = os.getenv("DQ_SESSION_SECRET") or __import__("secrets").token_hex(32)
SESSION_HOURS = int(os.getenv("DQ_SESSION_HOURS", "12"))
# Show one-click reviewer logins (demo users and their password) on the sign-in page. Turn off for real clients.
DEMO_LOGINS = os.getenv("DQ_DEMO_LOGINS", "1") == "1"
# Run the live plant simulation loop (turned off in tests, which advance the plant step by step).
PLANT_LOOP = os.getenv("DQ_PLANT_LOOP", "1") == "1"
