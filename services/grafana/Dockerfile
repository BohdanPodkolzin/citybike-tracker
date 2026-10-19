FROM grafana/grafana-oss:12.4.3

COPY provisioning /etc/grafana/provisioning

COPY dashboards /etc/grafana/dashboards

EXPOSE 3000

VOLUME /var/lib/grafana

HEALTHCHECK --interval=10s --timeout=5s --start-period=40s --retries=12 \
    CMD wget -q -O /dev/null http://127.0.0.1:3000/api/health || exit 1
