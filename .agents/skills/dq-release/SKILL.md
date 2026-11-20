---
name: dq-release
description: Tests, deploys and verifies DOS on Google Cloud Run. Use when the user asks to deploy, release, ship, redeploy or roll back the platform.
---
# Release to Cloud Run

## Before you deploy
1. `make test` must pass.
2. `git status` must be clean. Commit first.
3. Confirm `PROJECT_ID` with the user. Never guess a project.

## Deploy
```
PROJECT_ID=<project> bash infra/deploy.sh
```
The script runs the tests again, builds from source with Cloud Build, and deploys one instance.

## Verify (do all four)
1. `curl -fsS <url>/healthz` returns `"status":"ok"` and `"agents":38`.
2. Open the console, activate and deploy LoanProcess, run its demo request, approve the waiver.
3. Open Cloud Trace in the Google Cloud console and confirm a new trace exists for the run.
4. `gcloud run services logs read dq-platform --region asia-south1 --limit 50` shows no errors.

## Roll back the platform
```
gcloud run revisions list --service dq-platform --region asia-south1
gcloud run services update-traffic dq-platform --region asia-south1 --to-revisions <previous-revision>=100
```
Rolling back the platform is different from rolling back one agent version, which is done in the console.
