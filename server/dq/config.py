"""All runtime settings in one place. Every value comes from an environment variable so the same
container runs on a laptop, in Cloud Run, and in tests without code changes."""
import os
import re

# A key pasted into a terminal or Secret Manager on Windows can carry an invisible line break or space.
# HTTP refuses such a header ("Forbidden control character detected in headers"), so every Gemini call
# would fail. Clean the key once, here, before any Gemini client is created.
for _k in ("GOOGLE_API_KEY", "GEMINI_API_KEY"):
    if os.getenv(_k):
        # Gemini keys use only letters, digits, "-" and "_": drop anything else (line breaks, spaces, quotes, a BOM).
        os.environ[_k] = re.sub(r"[^A-Za-z0-9_\-]", "", os.environ[_k])

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


def _retry():
    from google.genai import types  # noqa: PLC0415  (imported here so config stays importable without the SDK)
    return types.HttpRetryOptions(attempts=int(os.getenv("DQ_GEMINI_ATTEMPTS", "4")), initial_delay=2, max_delay=20, exp_base=2,
                                  http_status_codes=[408, 429, 500, 502, 503, 504])


RETRY = _retry()


def gemini_ready() -> tuple[bool, str]:
    """Is live mode usable? Checked before a Gemini run so the app can say what is missing in plain words."""
    if os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("1", "true"):
        return (True, "Vertex AI") if PROJECT else (False, "GOOGLE_GENAI_USE_VERTEXAI is on but GOOGLE_CLOUD_PROJECT is not set.")
    key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or ""
    if not key:
        return False, "No Gemini API key. Put GOOGLE_API_KEY in server/.env (laptop) or the gemini-api-key secret (Cloud Run)."
    if not key.startswith("AIza") or len(key) < 30:
        return False, "The Gemini API key does not look right (AI Studio keys start with AIza and are 39 characters). Copy it again from AI Studio."
    return True, "AI Studio key"


def explain_error(err: str) -> str:
    """Turn a raw Gemini/HTTP error into one plain sentence that says what to do."""
    e = err or ""
    rules = [
        (("Forbidden control character", "header injection"), "The API key has a hidden line break. Paste it again without spaces; DOS now cleans it on start, so restart the server."),
        (("API_KEY_INVALID", "API key not valid", "invalid api key"), "Google refused the API key. Create a new key in AI Studio and update the secret, then redeploy."),
        (("PERMISSION_DENIED", "403"), "The key or project is not allowed to call this model. Check the key's project has the Gemini API enabled."),
        (("NOT_FOUND", "404", "is not found", "not supported for generateContent"), "Gemini does not know this model ID. Set DQ_MODEL_FLASH / DQ_MODEL_LITE / DQ_MODEL_PRO to IDs shown in AI Studio."),
        (("RESOURCE_EXHAUSTED", "429", "quota", "rate limit"), "Gemini rate limit or quota reached even after retries. Wait a minute, run one domain at a time, or enable billing on the key."),
        (("UNAVAILABLE", "503", "overloaded", "DEADLINE", "timed out", "Timeout"), "Gemini was busy and did not answer in time even after retries. Run the agent again."),
        (("INVALID_ARGUMENT", "400"), "Gemini rejected the request format. Check the model ID supports tools and thinking (use a Gemini 3.x Flash model)."),
    ]
    for words, hint in rules:
        if any(w.lower() in e.lower() for w in words):
            return hint
    return "The run stopped with an unexpected error. Open the trace to see the last step, then run it again or in simulation."


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
