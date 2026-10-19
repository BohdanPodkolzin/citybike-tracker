FROM busybox:1.36.1-musl AS tools

FROM grafana/loki:3.7.8

COPY --from=tools /bin/busybox /busybox

COPY loki.yaml /etc/loki/loki.yaml

EXPOSE 3100

VOLUME /loki

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=6 \
    CMD ["/busybox", "wget", "-q", "-O", "/dev/null", "http://127.0.0.1:3100/ready"]

CMD ["-config.file=/etc/loki/loki.yaml"]
