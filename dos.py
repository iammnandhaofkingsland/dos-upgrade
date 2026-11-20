"""DOS task runner. Works the same on Windows, macOS, Linux and Google Cloud Shell.

Run every task from the repository root with:   python dos.py <task>
(On macOS, Linux and Cloud Shell, use python3 if "python" is not found.)

Tasks
  setup              create the private Python environment (.venv) and install everything
  test               run the 33 automatic tests (simulation mode: no key, no internet, no cost)
  check <stage>      plain-English PASS/FAIL for one build stage:
                     foundation, config, data, tools, agents, safety, server, plant, all
  faults             inject every machine fault 10 times; report detection time and diagnosis
  run                start DOS on http://localhost:8080 in simulation mode (stop with Ctrl+C)
  run-live           start DOS with real Gemini (needs GOOGLE_API_KEY in server/.env)
  seed [url] [pwd]   fill a running DOS with a day of demo activity (default http://localhost:8080)
  adk-web            open Google's ADK developer screen with the voice agents (uses server/.env)
  eval               run the ADK evaluation of the LoanProcess agent (uses server/.env)
  doctor             check that Python, the environment and the settings file are in order
"""
import os
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
SERVER = ROOT / "server"
VENV = ROOT / ".venv"
WINDOWS = os.name == "nt"
VPY = VENV / ("Scripts/python.exe" if WINDOWS else "bin/python")
VBIN = VENV / ("Scripts" if WINDOWS else "bin")


def say(msg: str) -> None:
    print(f"[dos] {msg}", flush=True)


def load_env_file() -> dict:
    """Read server/.env (KEY=VALUE lines; # comments) without printing any value."""
    env = {}
    path = SERVER / ".env"
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.split(" #")[0].strip().strip('"').strip("'")
        env[key.strip()] = value
    return env


def child_env(mode: str | None = None, use_env_file: bool = False) -> dict:
    env = dict(os.environ)
    if use_env_file:
        env.update(load_env_file())
    if mode:
        env["DQ_MODEL_MODE"] = mode
    env["PYTHONPATH"] = str(SERVER)
    env["PYTHONUTF8"] = "1"            # Windows: read and print every file as UTF-8
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def need_venv() -> None:
    if not VPY.exists():
        sys.exit("[dos] The Python environment does not exist yet. Run:  python dos.py setup")


def run(cmd: list, cwd: pathlib.Path = ROOT, env: dict | None = None) -> int:
    say("running: " + " ".join(str(c) for c in cmd))
    try:
        return subprocess.call([str(c) for c in cmd], cwd=str(cwd), env=env)
    except KeyboardInterrupt:
        say("stopped.")
        return 0


def task_setup(_args):
    if sys.version_info < (3, 11):
        sys.exit(f"[dos] Python {sys.version.split()[0]} is too old. Install Python 3.12 or newer (guide, Step 6).")
    if not VPY.exists():
        say("creating the private Python environment in .venv ...")
        if run([sys.executable, "-m", "venv", str(VENV)]) != 0:
            sys.exit("[dos] Could not create .venv.")
    say("installing packages (3 to 8 minutes the first time) ...")
    code = run([VPY, "-m", "pip", "install", "--upgrade", "pip"])
    code = code or run([VPY, "-m", "pip", "install", "-r", SERVER / "requirements-dev.txt"])
    if code:
        sys.exit("[dos] Installation failed. Read the last red lines above; see the guide's troubleshooting chapter.")
    env_file = SERVER / ".env"
    if not env_file.exists():
        shutil.copy(SERVER / ".env.example", env_file)
        say("created server/.env from .env.example (simulation mode).")
    say("setup complete. Next:  python dos.py test")
    return 0


def task_test(_args):
    need_venv()
    return run([VPY, "-m", "pytest", "-q"], cwd=SERVER, env=child_env("mock"))


def task_check(args):
    need_venv()
    stage = args[0] if args else "all"
    return run([VPY, ROOT / "tools" / "check_step.py", stage], cwd=SERVER, env=child_env("mock"))


def task_faults(_args):
    need_venv()
    return run([VPY, ROOT / "tools" / "fault_matrix.py"], cwd=SERVER, env=child_env("mock"))


def task_run(_args):
    need_venv()
    env = child_env(use_env_file=True)
    env["DQ_MODEL_MODE"] = "mock"
    say("DOS is starting in SIMULATION mode. Open http://localhost:8080 . Stop with Ctrl+C.")
    return run([VPY, "-m", "uvicorn", "main:app", "--port", "8080"], cwd=SERVER, env=env)


def task_run_live(_args):
    need_venv()
    env = child_env(use_env_file=True)
    if not env.get("GOOGLE_API_KEY"):
        sys.exit("[dos] GOOGLE_API_KEY is empty in server/.env. Add your Gemini key there first (guide, Step 61).")
    env["DQ_MODEL_MODE"] = "live"
    say("DOS is starting in LIVE mode (real Gemini). Open http://localhost:8080 . Stop with Ctrl+C.")
    return run([VPY, "-m", "uvicorn", "main:app", "--port", "8080"], cwd=SERVER, env=env)


def task_seed(args):
    need_venv()
    url = args[0] if args else "http://localhost:8080"
    extra = args[1:2]
    return run([VPY, ROOT / "tools" / "seed_demo.py", url, *extra], env=child_env(use_env_file=True))


def task_adk_web(_args):
    need_venv()
    env = child_env(use_env_file=True)
    env.setdefault("DQ_TENANT", "kaveri")
    adk = VBIN / ("adk.exe" if WINDOWS else "adk")
    return run([adk, "web", "adk_agents"], cwd=SERVER, env=env)


def task_eval(_args):
    need_venv()
    adk = VBIN / ("adk.exe" if WINDOWS else "adk")
    return run([adk, "eval", "adk_agents/loanprocess", "evals/loanprocess.evalset.json",
                "--config_file_path=evals/eval_config.json", "--print_detailed_results"],
               cwd=SERVER, env=child_env(use_env_file=True))


def task_doctor(_args):
    ok = True
    say(f"Python running this script: {sys.version.split()[0]} at {sys.executable}")
    if sys.version_info < (3, 11):
        ok = False; say("PROBLEM: Python 3.12 or newer is needed.")
    say(f"Operating system: {'Windows' if WINDOWS else sys.platform}")
    say(f"Repository folder: {ROOT}")
    if WINDOWS and len(str(ROOT)) > 40:
        say("WARNING: the folder path is long. Use a short folder such as C:\\dos to avoid Windows path-length errors.")
    say("Private environment (.venv): " + ("present" if VPY.exists() else "MISSING - run: python dos.py setup"))
    ok = ok and VPY.exists()
    env = load_env_file()
    say("Settings file server/.env: " + ("present" if env else "MISSING - run: python dos.py setup"))
    if env:
        say(f"  DQ_MODEL_MODE={env.get('DQ_MODEL_MODE', '(not set)')}  DQ_AUTH_MODE={env.get('DQ_AUTH_MODE', '(not set)')}  "
            f"DQ_PLANT_LOOP={env.get('DQ_PLANT_LOOP', '(not set)')}")
        say("  GOOGLE_API_KEY is " + ("set (value hidden)" if env.get("GOOGLE_API_KEY") else "empty (fine until Step 61)"))
    git = shutil.which("git")
    say("Git: " + (git or "NOT FOUND - install Git (guide, Step 5)"))
    say("RESULT: " + ("all good" if ok else "fix the PROBLEM lines above"))
    return 0 if ok else 1


TASKS = {"setup": task_setup, "test": task_test, "check": task_check, "faults": task_faults, "run": task_run,
         "run-live": task_run_live, "seed": task_seed, "adk-web": task_adk_web, "eval": task_eval, "doctor": task_doctor}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in TASKS:
        print(__doc__)
        sys.exit(0 if len(sys.argv) < 2 else 2)
    sys.exit(TASKS[sys.argv[1]](sys.argv[2:]) or 0)
