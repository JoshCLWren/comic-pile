# GCP FastAPI benchmark host

This directory reproduces the tiny Compute Engine host used to benchmark ComicPile's FastAPI backend outside Vercel.

The goal is deliberately narrow: provision a disposable, always-on `e2-micro` close to the production Neon database, install ComicPile reproducibly, and run the same authenticated benchmark against it. This is benchmark infrastructure, not a production deployment.

## What Terraform creates

- one `e2-micro` Compute Engine VM;
- Debian 13 on a 10 GB standard persistent boot disk;
- a dedicated VPC/subnet;
- SSH access only from Google's IAP TCP forwarding range;
- an ephemeral public IP for outbound package/GitHub/Neon access;
- a startup script that creates 2 GB swap, installs `git`, `curl`, build tools, and `uv`, clones ComicPile, installs locked Python dependencies, and installs a systemd unit;
- no public ComicPile port. Uvicorn binds to `127.0.0.1:8000` for benchmarking over SSH.

The default region is `us-east1`, the closest GCP free-tier `e2-micro` region to the production Neon database in AWS `us-east-2`.

## Secrets are intentionally not Terraform variables

Do **not** put `DATABASE_URL`, `SECRET_KEY`, passwords, or API keys in Terraform variables. Terraform persists input values in state, so using sensitive variables would still copy the secret into the state file.

After the VM is created, run the included `configure-env.sh` helper on the VM. It prompts for the Neon URL without echoing it, removes libpq-only `sslmode` / `channel_binding` query parameters that `asyncpg` rejects, writes `/etc/comicpile/benchmark.env` as a root-owned file, and starts the benchmark service.

## Prerequisites

Install and authenticate:

- Terraform >= 1.6
- Google Cloud CLI (`gcloud`)
- Application Default Credentials (`gcloud auth application-default login`)

You need a Google Cloud project with billing enabled. The Terraform config enables the Compute Engine API if necessary.

## Provision

```bash
cd infra/gcp-benchmark
cp terraform.tfvars.example terraform.tfvars
# Set project_id in terraform.tfvars.

terraform init
terraform plan
terraform apply
```

Terraform prints an IAP SSH command. Use it after the startup script has had a few minutes to finish:

```bash
gcloud compute ssh comicpile-benchmark \
  --zone us-east1-b \
  --tunnel-through-iap
```

Check bootstrap status:

```bash
sudo tail -n 100 /var/log/comicpile-bootstrap.log
sudo test -f /var/log/comicpile-bootstrap.done && echo ready
```

## Configure Neon and start ComicPile

From the cloned repository on the VM:

```bash
cd /opt/comic-pile
sudo ./infra/gcp-benchmark/configure-env.sh
```

Paste the Neon connection URL when prompted. The helper does not print it back.

Then verify:

```bash
sudo systemctl status comicpile-benchmark --no-pager
curl -sS http://127.0.0.1:8000/health
free -h
```

The benchmark service intentionally uses:

- `ENVIRONMENT=staging`, so the backend can run without built React artifacts;
- `CACHE_ENABLED=false`, matching the cache-disabled comparison used during the original experiment;
- two Uvicorn workers, which performed better than one under 5-10 request concurrency on `e2-micro` while remaining within 1 GB RAM.

## Run the authenticated benchmark

```bash
cd /opt/comic-pile
./infra/gcp-benchmark/benchmark-auth.sh
```

It prompts for a ComicPile username and password, logs into the local backend, then measures read-only authenticated requests including `roll/bootstrap` sequentially and at concurrency 5 and 10. Login itself updates normal authentication bookkeeping, but the benchmark does not roll, rate, snooze, or otherwise mutate reading state.

## Recreate in another zone or shape

Change Terraform variables and apply again. Useful comparisons include:

```hcl
zone         = "us-east1-b"
machine_type = "e2-micro"
```

The application environment and benchmark procedure remain identical, which is the point: machine/region experiments should change one infrastructure variable rather than repeat the manual setup.

## Destroy

```bash
terraform destroy
```

The boot disk is auto-deleted with the VM. Terraform does not manage Neon or any production data.
