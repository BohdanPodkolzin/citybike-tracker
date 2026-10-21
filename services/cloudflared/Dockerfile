FROM busybox:1.36.1-musl AS tools

FROM cloudflare/cloudflared:2026.7.0

COPY --from=tools /bin/busybox /busybox

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=4 \
    CMD ["/busybox", "wget", "-q", "-O", "/dev/null", "http://127.0.0.1:20241/ready"]


ENTRYPOINT ["cloudflared", "--no-autoupdate"]
CMD ["tunnel", "--metrics", "127.0.0.1:20241", "run"]
