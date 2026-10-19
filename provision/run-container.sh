#!/usr/bin/env bash

set -euo pipefail
: "${CONTAINER_NAME:?}" "${BUILD_DIR:?}"
ENV_KEYS="${ENV_KEYS:-}"      # may be empty (Loki needs no variables)

IMAGE="citybikes/${CONTAINER_NAME}:latest"
ENV_FILE="/etc/citybikes/${CONTAINER_NAME}.env"

# The secrets live only here, readable by root alone (umask 077 = mode 600). They are
# never written into an image: docker passes them to the container at start (--env-file).
install -d -m 700 /etc/citybikes
(
  umask 077
  : > "${ENV_FILE}"
  for key in ${ENV_KEYS}; do
    printf '%s=%s\n' "${key}" "${!key:?${key} is empty}" >> "${ENV_FILE}"
  done
)

# Build only when the code changed. The hash of the build folder is stored in an image label, so
# changing a setting (a backend flag, a password) just recreates the container: no rebuild.
src_hash=$(cd "${BUILD_DIR}" && find . -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -d' ' -f1)
built_hash=$(docker image inspect -f '{{index .Config.Labels "citybikes.src"}}' "${IMAGE}" 2>/dev/null || true)
if [ "${built_hash}" = "${src_hash}" ]; then
  echo "${IMAGE}: code unchanged, no rebuild"
else
  docker build --label "citybikes.src=${src_hash}" -t "${IMAGE}" "${BUILD_DIR}"
fi

# Replace the old container; named volumes (the database files) are kept.
docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true

args=(run -d --name "${CONTAINER_NAME}"
      # self-healing: Docker restarts the container if it crashes, and again after a VM reboot
      --restart unless-stopped
      --env-file "${ENV_FILE}"
      --security-opt no-new-privileges)
for port in ${PUBLISH:-}; do args+=(-p "${port}"); done
if [ -n "${CONTAINER_HOSTNAME:-}" ]; then args+=(--hostname "${CONTAINER_HOSTNAME}"); fi
if [ -n "${VOLUME:-}" ];  then args+=(-v "${VOLUME}"); fi
if [ -n "${RUN_ARGS:-}" ]; then read -r -a extra <<< "${RUN_ARGS}"; args+=("${extra[@]}"); fi
docker "${args[@]}" "${IMAGE}" >/dev/null

# Wait for the image's HEALTHCHECK to turn green; show the logs if it never does.
for _ in $(seq 90); do
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