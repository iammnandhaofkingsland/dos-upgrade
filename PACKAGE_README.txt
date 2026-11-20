DOS (DigiQuench OS): the complete package, with the new DOS app
================================================================

This folder is the whole project: every file, nothing missing. It is the version tested for the
"DOS App Upgrade" guide: 42 automatic tests, 31 plain-English checks, all 55 agents of all 8 domains
end to end (simulation), and every role walked through every page in a browser.

Not included on purpose: .venv (made by "python dos.py setup"), server/.env (your settings and key;
copy yours in, or let setup copy server/.env.example), caches.

Run it on your laptop (guide, Part A):
    python dos.py setup          once, 3 to 30 minutes
    python dos.py test           42 passed
    python dos.py check all      31 of 31 checks passed
    python dos.py run            open http://localhost:8080 (simulation)
    python dos.py run-live       the same with Gemini (needs GOOGLE_API_KEY in server/.env)

Deploy it to Google Cloud from Cloud Shell (guide, Part A):
    upload this zip, unzip it into ~/dos-complete, then
    cd ~/dos-complete/dos && python3 dos.py setup && python3 dos.py test
    PROJECT_ID=YOUR-PROJECT-ID bash infra/deploy.sh

Sign in: pick a company, pick a role, type the code shown on the role card.
Business Owner 260101 · Operations Manager 260201 · Approver 260301 · Technician 260401 · Auditor 260501

Compare your own project with this package at any time:
    python tools/compare_tree.py <this folder> <your project folder>
