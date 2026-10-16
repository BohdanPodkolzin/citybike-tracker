#!/usr/bin/env bash

set -euo pipefail
: "${CONTAINER_NAME:?}" "${BUILD_DIR:?}" "${ENV_KEYS:?}"

IMAGE="citybikes/${CONTAINER_NAME}:latest"
ENV_FILE="/etc/citybikes/${CONTAINER_NAME}.env"

# The secrets live only here. (umask 077 = mode 600)
# Never written into an image: docker passes them to the container at start (--env-file)
install -d -m 700 /etc/citybikes
(
  umask 077
  : > "${ENV_FILE}"
  for key in ${ENV_KEYS}; do
    printf '%s=%s\n' "${key}" "${!key:?${key} is empty}" >> "${ENV_FILE}"
  done
)

docker build -t "${IMAGE}" "${BUILD_DIR}"

# Replace the old container
docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true

args=(run -d --name "${CONTAINER_NAME}"
      --restart unless-stopped
      --env-file "${ENV_FILE}"
      --security-opt no-new-privileges)
if [ -n "${PUBLISH:-}" ]; then args+=(-p "${PUBLISH}"); fi
if [ -n "${VOLUME:-}" ];  then args+=(-v "${VOLUME}"); fi
if [ -n "${RUN_ARGS:-}" ]; then read -r -a extra <<< "${RUN_ARGS}"; args+=("${extra[@]}"); fi
docker "${args[@]}" "${IMAGE}" >/dev/null

# Wait for the image's HEALTHCHECK to turn green
for _ in $(seq 60); do
  state=$(docker inspect -f '{{.State.Status}}/{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${CONTAINER_NAME}")
  case "${state}" in
    running/healthy) echo "${CONTAINER_NAME} is up and healthy"; exit 0 ;;
    running/starting|running/none) sleep 2 ;;
    *) break ;;
  esac
done
echo "${CONTAINER_NAME} did not become healthy (${state}); last log lines:" >&2
docker logs --tail 40 "${CONTAINER_NAME}" >&2
exit 1
