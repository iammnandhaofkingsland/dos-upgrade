#!/usr/bin/env bash
# One-time Google Cloud setup. Usage: PROJECT_ID=my-project bash infra/bootstrap.sh
# Safe to re-run: every step is idempotent or tolerates "already exists".
set -euo pipefail
: "${PROJECT_ID:?Set PROJECT_ID}"
REGION="${REGION:-asia-south1}"          # Mumbai: closest to Indian users
SA="dq-runtime"
SA_EMAIL="${SA}@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud config set project "$PROJECT_ID"

echo "1/6 Enabling APIs (takes a minute the first time)"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  firestore.googleapis.com secretmanager.googleapis.com aiplatform.googleapis.com \
  cloudtrace.googleapis.com logging.googleapis.com monitoring.googleapis.com generativelanguage.googleapis.com

echo "2/6 Creating the Firestore database (Native mode)"
gcloud firestore databases create --location="$REGION" --type=firestore-native 2>/dev/null || echo "   Firestore database already exists"

echo "3/6 Creating the runtime service account"
gcloud iam service-accounts create "$SA" --display-name="DOS platform runtime" 2>/dev/null || echo "   service account already exists"

echo "4/6 Granting least-privilege roles"
for ROLE in roles/datastore.user roles/secretmanager.secretAccessor roles/cloudtrace.agent roles/logging.logWriter roles/monitoring.metricWriter roles/aiplatform.user; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${SA_EMAIL}" --role="$ROLE" --condition=None --quiet >/dev/null
done

# Source deploys build with Cloud Build, which in new projects runs as the Compute Engine default service account.
# It needs the Cloud Run Builder role, or "gcloud run deploy --source" fails with a storage or build permission error.
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/run.builder" --condition=None --quiet >/dev/null 2>&1 || echo "   (could not grant Cloud Run Builder to the build account; see the guide if the deploy fails)"

echo "5/6 Creating secrets (you will be asked to paste values; nothing is echoed)"
create_secret () {
  local NAME="$1" PROMPT="$2"
  if gcloud secrets describe "$NAME" >/dev/null 2>&1; then echo "   secret $NAME already exists"; return; fi
  read -r -s -p "   $PROMPT: " VALUE; echo
  printf '%s' "$VALUE" | gcloud secrets create "$NAME" --replication-policy=automatic --data-file=-
}
create_secret gemini-api-key "Paste your Gemini API key from Google AI Studio"
create_secret dq-console-key "Choose a console access key (any long random string; used only by scripts in header mode)"
if ! gcloud secrets describe dq-session-secret >/dev/null 2>&1; then  # signs the sign-in tokens; nobody needs to know it
  openssl rand -hex 32 | tr -d "\n" | gcloud secrets create dq-session-secret --replication-policy=automatic --data-file=-
  echo "   secret dq-session-secret created (random)"
fi

echo "6/6 Done. Next: bash infra/deploy.sh"
echo "    Also set a budget alert now: Billing > Budgets & alerts > Create budget (for example Rs 2,000 with alerts at 50%, 90%, 100%)."
