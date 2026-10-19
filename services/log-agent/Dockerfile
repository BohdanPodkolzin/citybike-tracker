FROM busybox:1.36.1-musl AS tools

FROM grafana/alloy:v1.19.2

COPY --from=tools /bin/busybox /busybox

COPY config.alloy /etc/alloy/config.alloy

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD ["/busybox", "wget", "-q", "-O", "/dev/null", "http://127.0.0.1:12345/-/ready"]

CMD ["run", "--server.http.listen-addr=127.0.0.1:12345", "--storage.path=/var/lib/alloy/data", "--disable-reporting", "/etc/alloy/config.alloy"]
