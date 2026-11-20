#!/usr/bin/env bash
# Build from source and deploy to Cloud Run. Usage: PROJECT_ID=my-project bash infra/deploy.sh
set -euo pipefail
: "${PROJECT_ID:?Set PROJECT_ID}"
REGION="${REGION:-asia-south1}"
SERVICE="${SERVICE:-dos-platform}"
SA_EMAIL="dq-runtime@${PROJECT_ID}.iam.gserviceaccount.com"

# Gate: never deploy code that fails the offline tests.
PY="python3"; [ -x .venv/bin/python ] && PY="../.venv/bin/python"
if [ "${SKIP_TESTS:-0}" = "1" ]; then
  echo "SKIP_TESTS=1: skipping the test gate (only if the tests already passed on your laptop)."
else
  ( cd server && DQ_MODEL_MODE=mock PYTHONUTF8=1 $PY -m pytest -q )
fi

gcloud run deploy "$SERVICE" \
  --project "$PROJECT_ID" --region "$REGION" --source server \
  --service-account "$SA_EMAIL" \
  --allow-unauthenticated \
  --min-instances 1 --max-instances 1 \
  --cpu 1 --memory 1Gi --no-cpu-throttling \
  --timeout 300 --concurrency 40 \
  --set-env-vars "DQ_MODEL_MODE=${DQ_MODEL_MODE:-live},DQ_STORE=${DQ_STORE:-memory},DQ_TENANT=${DQ_TENANT:-demo},DQ_AUTH_MODE=token,DQ_DEMO_LOGINS=${DQ_DEMO_LOGINS:-1},DQ_PLANT_LOOP=1,GOOGLE_CLOUD_PROJECT=${PROJECT_ID}" \
  --set-secrets "GOOGLE_API_KEY=gemini-api-key:latest,DQ_API_KEY=dq-console-key:latest,DQ_SESSION_SECRET=dq-session-secret:latest" \
  --labels "app=dos,env=demo"

URL=$(gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --format='value(status.url)')
echo "Deployed: $URL"
echo "Smoke test:"
curl -fsS "$URL/healthz" && echo
echo "Open $URL in a browser and sign in (reviewer quick access is on while DQ_DEMO_LOGINS=1)."
# Why these flags:
#  --min-instances 1      no cold start in front of the jury
#  DQ_STORE=memory       the tested default for the event; set DQ_STORE=firestore to keep data across restarts (test it first)
#  --max-instances 1      run sessions and the live plant simulator live in memory, so all requests must reach one instance
#  --no-cpu-throttling    agent runs and the plant loop (one tick every 2 s) run in the background; CPU must stay allocated
#  --allow-unauthenticated the sign-in page is public; every other /api call needs a signed session token
