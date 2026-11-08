# Deploy the hosted demo

The hosted demo needs no keys. One container serves the console and the API. The console shows the real disputes recorded from our own sandbox run (`data/recorded_disputes.json`), and item and instruction reads come from the recordings in `data/`. Without a model key,
an instruction that was never recorded is read by the fixed pattern reader, and the screen says so.

Do not put your NVIDIA or PayPal keys on the hosted demo. It is public, and anyone could use up your quota
or act on your sandbox account. The live PayPal run happens on your own machine.

## Google Cloud Run (no GitHub needed)

Cloud Run deploys straight from this folder, scales to zero when idle and wakes in a few seconds. The free
tier covers a demo like this by a wide margin, but the project needs billing turned on.

1. Install the gcloud CLI and sign in with `gcloud auth login`.
2. From the repo root, run `bash infra/scripts/deploy_cloud_run.sh YOUR_PROJECT_ID`.
3. Open the URL it prints, add `/health` to check it returns `{"ok":true}`, then open the main page.
4. Put the URL in the README and the Devpost form.

To keep costs capped, set a small budget alert on the project. The script limits the service to 2 instances.

## Render

`infra/render.yaml` is a Render blueprint for the same image. Render deploys from a Git repository, so it
needs the code on GitHub first. A private repo works. Free Render services sleep after 15 minutes without a
visit and take about a minute to wake, so keep one awake with a free monitor that requests `/health`.

## Test the image locally

    docker build -t warrant .
    docker run -p 8000:8000 warrant      # then open http://localhost:8000

The rules say the project must stay free to test until judging ends on 2026-12-15, so leave the hosted demo
up and the repo public until after the winners are announced.

Status: the image hasn't been built yet. The files were checked by running the server from a copy laid out the same way as the image.
