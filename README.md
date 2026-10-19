# CityBikes History

Four services and a bastion on five VirtualBox VMs. **Each service is a Docker container built from its own Dockerfile.**

| VM | Private IP | LAN IP | Container(s) | Dockerfile |
|---|---|---|---|---|
| bastion | 10.20.0.54 | 192.168.0.54 | log agent; hardened sshd | `services/log-agent` |
| ui | 10.20.0.53 | **192.168.0.53** | nginx + React build, :80; log agent | `services/ui` (multi-stage) |
| history | 10.20.0.52 | - | gunicorn + poller, API :8002; log agent | `services/history` |
| fetcher | 10.20.0.51 | - | queue worker (no port); log agent | `services/fetcher` |
| db | 10.20.0.50 | - | PostgreSQL :5432, Redis :6379, RabbitMQ :5672 (+ web UI :15672), **Loki :3100, Grafana :3000**; log agent | `services/postgres`, `redis`, `rabbitmq`, `loki`, `grafana`, `log-agent` |

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
- **PostgreSQL queue**: tables `mq_requests` / `mq_replies`; Fetcher claims with `SELECT ... FOR UPDATE SKIP LOCKED` and a 30 s lease (a crashed worker's request is offered again).
- **PostgreSQL cache**: table `kv_store(key, value, expires_at)`; an expired row is never returned.
- Only the settings of the chosen backend are given to a container (in `postgres` queue mode the Fetcher gets the database credentials, in `rabbitmq` mode it gets none).
- `run-container.sh` rebuilds an image only if the code in its folder changed (hash in an image label), so switching a flag never rebuilds.

## How it works

- `provision/docker.sh` installs Docker and **enables it at boot**; log rotation is configured.
- `provision/run-container.sh` builds the image, writes secrets to `/etc/citybikes/<name>.env` (mode 600) and starts the container with `--restart unless-stopped`, so Docker restarts it after a crash **and** after a VM reboot. It waits for the image's `HEALTHCHECK` to go green.
- Secrets are never in an image: they arrive at run time (`--env-file`). Database and Redis data are in named volumes (`citybikes-pgdata`, `citybikes-redisdata`).
- Hardening: pinned base images, multi-stage builds, non-root users, `--cap-drop ALL`, `no-new-privileges`, read-only root filesystem for fetcher/history, `.dockerignore` per service.
- The Vagrantfile has one `VMS` list; a new service = one entry + a Dockerfile.

## Check / demo

```bash
ssh bastion                                              # then, on the bastion:
ssh history docker ps                                    # STATUS: Up ... (healthy)
ssh history docker logs --tail 20 history        # or look at all VMs in Grafana
ssh history curl -s localhost:8002/health

# self-healing 1: kill the app process, Docker brings the container back
ssh history "docker kill history; sleep 5; docker ps"
# self-healing 2: reboot a VM, Docker starts at boot and restores its containers
vagrant reload db && ssh db docker ps                    # (on the bastion)
```

## Tests

`cd services/fetcher && python -m pytest`, `cd services/history && python -m pytest`.
Tests are not copied into the images (`.dockerignore`).

## UI lock file

Commit `services/ui/package-lock.json` (`cd services/ui && npm install`): with it the image build uses the reproducible `npm ci`.
