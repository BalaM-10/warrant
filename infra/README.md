# Infra

- `scripts/deploy_cloud_run.sh`: deploys the keyless hosted demo to Google Cloud Run from this folder.
- `render.yaml`: the Render blueprint, for the same image. It needs the code on GitHub.
- `scripts/preflight.py`: run it before every recording and before you submit.
- `scripts/record_model_reads.py` and `scripts/record_instruction_reads.py`: record real model reads into `data/`.

The image is the `Dockerfile` in the repo root.
- `scripts/live_purchase.py`: makes one real sandbox purchase (`--mode normal`, `overstep` or `unrecorded`) and saves the signed receipt.
- `scripts/export_recorded.py`: saves your real disputes to `data/recorded_disputes.json` with personal fields removed.
