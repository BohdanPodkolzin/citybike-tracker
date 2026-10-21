# CityBikes History

Four services and a bastion on five VirtualBox VMs. **Each service is a Docker container built from its own Dockerfile.**

| VM | Private IP | LAN IP | Container(s) | Dockerfile |
|---|---|---|---|---|
| bastion | 10.20.0.54 | 192.168.0.54 | log agent; hardened sshd | `services/log-agent` |
| ui | 10.20.0.53 | **192.168.0.53** | nginx + React build, :80; log agent | `services/ui` (multi-stage) |
| history | 10.20.0.52 | - | gunicorn + poller, API :8002; log agent | `services/history` |
| fetcher | 10.20.0.51 | - | queue worker (no port); log agent | `services/fetcher` |
| db | 10.20.0.50 | - | PostgreSQL :5432 (extensions **pgmq** and **hstore**), Redis :6379, RabbitMQ :5672 (+ web UI :15672), **Loki :3100, Grafana :3000**; log agent | `services/postgres`, `redis`, `rabbitmq`, `loki`, `grafana`, `log-agent` |

Only **ui** (HTTP) and **bastion** (SSH) are in your home network. Everything else lives in an isolated
private network (a VirtualBox internal network) that your LAN cannot see. The VMs still reach the internet
through Vagrant's NAT adapter (images, CityBikes API).

Diagrams: [docs/architecture.md](docs/architecture.md).

## Run

```bash
cp .env.example .env              # set DB_PASSWORD, REDIS_PASSWORD, RABBITMQ_PASSWORD and GRAFANA_PASSWORD
bash scripts/setup-ssh.sh --install   # creates 2 key pairs, writes ssh_config, adds it to ~/.ssh/config
vagrant up                        # db, fetcher, history, ui, bastion
```
Open `http://192.168.0.53` from any device in the LAN.

RAM for the five VMs: db 3 GB, history 1 GB, ui 1 GB, fetcher 0.75 GB, bastion 0.75 GB (about 6.5 GB; change `memory:` in the `VMS` list of the Vagrantfile if your computer is short).
Already running VMs get the new RAM, files and containers with `vagrant reload --provision db` (then the other VMs).

**Updating an installation that already runs** (this version puts the `pgmq` extension into the PostgreSQL image and changes the queue code). The database volume is kept; only the containers are replaced:
```bash
vagrant rsync db      && vagrant provision db      --provision-with app-postgres
vagrant rsync fetcher && vagrant provision fetcher --provision-with app-fetcher
vagrant rsync history && vagrant provision history --provision-with app-history
```
(do `db` first; PostgreSQL is down for a few seconds while its container is replaced).

After you change code or a Dockerfile, update one VM like this (`vagrant provision` alone does **not** copy files):
```bash
vagrant rsync history        # copy the changed files into the VM
vagrant provision history    # rebuild the image, replace the container
```

## SSH: log in to the bastion, then hop from it

```bash
ssh bastion                  # from your computer: the one door into the network
# --- now you are ON the bastion; from here:
ssh ui
ssh fetcher
ssh history
ssh db                       # `exit` brings you back one level
```
Two key pairs, made by `scripts/setup-ssh.sh`:

| key | private half lives | public half is accepted by |
|---|---|---|
| `citybikes_ed25519` (yours) | your computer only | the **bastion** only |
| `citybikes_internal_ed25519` | the bastion only (`~/.ssh/internal_ed25519`) | ui, fetcher, history, db |

So your key opens one door; to reach anything else you must be on the bastion. The bastion has a ready `~/.ssh/config`
(names `ui`, `fetcher`, `history`, `db` → 10.20.0.x, user `vagrant`, its own key), and the same names resolve in `/etc/hosts`.

- Passwords are disabled everywhere; keys only. No agent forwarding.
- The other VMs accept SSH only from the bastion address (`ufw`, port 22 only; Docker's own networking is untouched).
- Direct `ssh vagrant@192.168.0.53` from the LAN is refused; the private VMs have no LAN address at all.
- Tunnel to a private port, e.g. History's API: `ssh -L 8080:10.20.0.52:8002 bastion`, then http://localhost:8080/health.
- `vagrant ssh <vm>` still works from your computer (Vagrant's own NAT channel): keep it as the emergency exit.
- VMs recreated (new host keys)? Delete `.ssh_known_hosts` on your computer and `~/.ssh/known_hosts` on the bastion.
- Changed the keys? `vagrant provision --provision-with ssh-access` replaces them on every VM.

## Logs: everything in one place (Loki + Grafana on the db VM)

```
every VM:  containers (stdout) + systemd journal (sshd, docker, kernel)
              |  log agent (Grafana Alloy, one container per VM, incl. the bastion)
              v  push over the private network
db VM:     Loki (stores 7 days)  <--  Grafana (dashboard "CityBikes logs")
```
- Each line gets labels: `host` (VM), `container`, `level` (for our Python services), and for the journal `unit` (e.g. `ssh.service`).
- The agent remembers where it stopped (volume `citybikes-alloydata`), so a restart neither loses nor repeats lines.
  If Loki is down for a while the agent retries and then drops the lines it could not send; the apps are not affected.
- Loki and Grafana are **not** in your LAN. Open Grafana through the bastion, from your computer:

```bash
ssh -L 3000:10.20.0.50:3000 bastion      # leave it open
# browser: http://localhost:3000    user: admin   password: GRAFANA_PASSWORD from .env
```
The dashboard opens at once (data source and dashboard are part of the Grafana image). Panels: lines and errors per container,
SSH logins per VM, the container log with filters (VM, container, free text), errors and warnings, SSH logins and failures.
The password is read when Grafana is created; to change it later: `ssh db`, then `docker exec grafana grafana cli admin reset-admin-password NEWPASS`.

Queries to try in Grafana → Explore (data source Loki):
```
{source="docker", container="history"}                         # one service
{source="docker"} |~ "(?i)error|traceback"                    # errors of all services
{source="journal", unit="ssh.service"} |~ "Accepted|Failed"   # SSH logins and failures on every VM
{host="bastion"}                                               # everything the bastion logged
```
The usual tools still work too: `docker logs history` on a VM, `journalctl -u ssh` on any VM.

Notes: the agent needs root to read the Docker socket and the journal. It is locked down otherwise (no capabilities, read-only
root filesystem, read-only mounts, no published port). The journal is stored on disk (200 MB cap) on every VM.
The dashboard lists the VMs/containers in two fixed variables; add a new service to them in
`services/grafana/dashboards/citybikes-logs.json` (or just type its name in the free-text filter).

## Internet access: Cloudflare Tunnel (optional)

The UI can be opened from anywhere at `https://citybikes-tracker.pp.ua` without a public IP and without
port forwarding on the router. A `cloudflared` container on the **ui** VM dials **out** to Cloudflare; visitors reach
Cloudflare (HTTPS, certificate by Cloudflare), and Cloudflare passes the request back through that connection to the UI.
Nothing new listens on any VM: History, the databases and the bastion stay private. Only the UI (and its `/api` proxy) is public.

1. Add the domain to Cloudflare (free plan) and set the two Cloudflare name servers at the registrar of `pp.ua`. Wait until
   the domain shows **Active**.
2. Cloudflare dashboard → **Networking → Tunnels** (older menus: Zero Trust → Networks → Tunnels) → **Create a tunnel**,
   type *Cloudflared*, any name. Copy the **token** (the long string after `--token` in the install command). Do not run that command.
3. In the tunnel → **Routes / Public hostnames** → add a **published application**: domain `citybikes-tracker.pp.ua`
   (empty subdomain), Service `HTTP`, URL `10.20.0.53:80` (the ui VM's private address).
4. Put the token in `.env` (`CLOUDFLARE_TUNNEL_TOKEN=...`) and start the connector:
   ```bash
   vagrant rsync ui                                        # copies services/cloudflared to the ui VM
   vagrant provision ui --provision-with app-cloudflared   # builds the image and starts the container
   ```
5. Check: on the ui VM `docker ps` shows `cloudflared` as `healthy`; the tunnel is **Healthy** in the dashboard;
   `https://citybikes-tracker.pp.ua` opens the UI.

The token is a secret: like the passwords it is only in `.env` and in `/etc/citybikes/cloudflared.env` (mode 600) on the ui VM.
If UDP is blocked in your network set `CLOUDFLARE_TUNNEL_PROTOCOL=http2`. To make the site private, put a Cloudflare Access
policy (e.g. one-time PIN to your e-mail) in front of the hostname. Without the token nothing of this is started.

## Check everything at once

```bash
ssh bastion 'bash -s' < scripts/check-all.sh      # from your computer
```
It hops from the bastion to every VM and prints OK / FAIL for: ssh access, every container Up and healthy, the RabbitMQ queue
with the fetcher connected, the backends History really uses, Loki ready and logs from all five VMs.

## Queue and cache: switch in runtime, no rebuild

Two environment variables of the History and Fetcher containers choose the backends. The **same images** run in every combination.

| Variable | Values | What it chooses |
|---|---|---|
| `QUEUE_BACKEND` | `rabbitmq` (default) / `postgres` | how History asks Fetcher for data: a RabbitMQ queue or a table in PostgreSQL |
| `CACHE_BACKEND` | `redis` (default) / `postgres` | where user preferences live: Redis keys with a TTL or a table in PostgreSQL |

```bash
bash scripts/switch-backend.sh                       # show the current values
bash scripts/switch-backend.sh queue=postgres        # recreates fetcher + history (~10 s), no image build
bash scripts/switch-backend.sh cache=postgres
bash scripts/switch-backend.sh queue=rabbitmq cache=redis
# (on the bastion)  ssh history curl -s localhost:8002/api/status   # shows queue_backend / cache_backend that are ACTIVE
```
By hand, without the script: `ssh bastion`, then `ssh history`, then `docker rm -f history` and `docker run ... -e QUEUE_BACKEND=postgres citybikes/history`
(the env file is `/etc/citybikes/history.env`). History and Fetcher must use the **same** queue backend; the script keeps them together.

- **RabbitMQ**: request/reply with *direct reply-to*; every request has a TTL equal to History's timeout, so requests nobody took never pile up; Fetcher acks only after it replied. Web UI: `ssh -L 15672:10.20.0.50:15672 bastion` (on your computer), then http://localhost:15672.
- **PostgreSQL queue = the `pgmq` extension** ([pgmq](https://github.com/pgmq/pgmq), v1.13.0, installed into the `services/postgres` image from `services/postgres/pgmq/`). Two pgmq queues, `fetch_requests` (History → Fetcher) and `fetch_replies` (Fetcher → History):
  History calls `pgmq.send()` and then `pgmq.read_with_poll()` with a *conditional* filter, so it gets only the reply that carries its own id; the Fetcher takes a request with `pgmq.read_with_poll()` (a 30 s visibility timeout: a crashed worker's request is offered again), answers with `pgmq.send()` and removes the request with `pgmq.delete()` in one transaction.
  A request nobody took is withdrawn by History after its timeout, anything older than 60 s is cleaned up, and a request that was handed out more than 3 times is dropped. `CREATE EXTENSION IF NOT EXISTS pgmq` and `pgmq.create(...)` run by themselves when History/Fetcher start in `postgres` mode, so an existing data volume needs no re-init.
  Look inside: `ssh bastion`, `ssh db`, then `docker exec postgres psql -U citybikes_app -d citybikes -c "select * from pgmq.metrics_all()"`.
- **PostgreSQL cache = the `hstore` extension** (a standard PostgreSQL extension, part of the server: there is nothing to install in the image). Table `kv_hstore`, one row per namespace (the part of the key before the first `:`, here `prefs`):
  the column `entries` is an hstore of `key => value` (the preferences as JSON text), the column `expires` is an hstore of `key => expiry time`. `get` is `entries -> key` and only returns a key that has not expired;
  `set` is one `INSERT ... ON CONFLICT` that removes the expired keys (`delete(hstore, keys[])`) and merges the new pair (`||`). `CREATE EXTENSION IF NOT EXISTS hstore` runs by itself when History starts with `CACHE_BACKEND=postgres`.
  Look inside: `docker exec postgres psql -U citybikes_app -d citybikes -c "select namespace, akeys(entries) from kv_hstore"` (the old table `kv_store` of earlier versions is no longer used; `drop table kv_store` is safe).
- Only the settings of the chosen backend are given to a container (in `postgres` queue mode the Fetcher gets the database credentials, in `rabbitmq` mode it gets none).
- `run-container.sh` rebuilds an image only if the code in its folder changed (hash in an image label), so switching a flag never rebuilds.

## How it works

- `provision/docker.sh` installs Docker and **enables it at boot**; log rotation is configured.
- `provision/run-container.sh` builds the image, writes secrets to `/etc/citybikes/<name>.env` (mode 600) and starts the container with `--restart unless-stopped`, so Docker restarts it after a crash **and** after a VM reboot. It waits for the image's `HEALTHCHECK` to go green.
- Secrets are never in an image: they arrive at run time (`--env-file`). Database and Redis data are in named volumes (`citybikes-pgdata`, `citybikes-redisdata`).
- Hardening: pinned base images, multi-stage builds, non-root users, `--cap-drop ALL`, `no-new-privileges`, read-only root filesystem for fetcher/history, `.dockerignore` per service.
- The Vagrantfile has one `VMS` list; a new service = one entry + a Dockerfile.

## Demo for the teachers

One script shows that everything works, with real commands and real output:

```bash
bash scripts/demo.sh              # step by step, Enter between the stages
bash scripts/demo.sh --auto       # without pauses (about 5 minutes; --fast skips the waits for the next poll)
bash scripts/demo.sh --only 1,6,7 # only some stages
```
Run it on your computer after `vagrant up` (needs `curl` and `python3`). Each stage says what it proves, prints the commands and
their output, and ends with ✔ or ✘. At the end there is a summary.

| # | Stage | What you see |
|---|---|---|
| 1 | Network and access | the UI opens from the home network; direct SSH, password login and private ports are refused; `ssh bastion`, then every VM |
| 2 | Whole system check | all containers healthy, the fetcher is connected to the RabbitMQ queue, logs from all five VMs |
| 3 | Data flow | UI → History → queue → Fetcher → API → database → UI; a new snapshot appears |
| 4 | Queue switch | `queue=postgres` without a rebuild (same image ids), data keeps flowing, back to RabbitMQ |
| 5 | Cache switch | preferences saved in Redis, `cache=postgres`, the new store is empty, saved again, back to Redis |
| 6 | Logs in one place | lines per VM from Loki, the fetcher's log, SSH logins from the journal; the Grafana dashboard |
| 7 | Self-healing | `docker kill history`: Docker restarts it by itself (reboot a VM: `vagrant reload db`) |
| 8 | Broker outage | RabbitMQ stopped: the site keeps answering; started again: the fetcher reconnects alone |

Stages 4, 5 and 8 change things on purpose; the script puts the flags and RabbitMQ back, even if you press Ctrl+C.
Also useful on its own: `ssh bastion 'bash -s' < scripts/check-all.sh` (stage 2 only), and Grafana through the tunnel (see "Logs").

## Tests

```bash
bash scripts/tests/run-tests.sh          # needs python3 and bash only, no VMs
```
It runs the unit tests of Fetcher and History (74 tests with a fake queue, database and cache; shown as readable sentences)
and a self-test of `scripts/check-all.sh` and of `scripts/demo.sh` against a fake world (fake ssh, curl, vagrant), for a healthy and a broken system.
`bash scripts/tests/test-check-all.sh --show` and `bash scripts/tests/test-demo.sh --show` print what the check and the whole demo look like.
Tests are not copied into the images (`.dockerignore`).
