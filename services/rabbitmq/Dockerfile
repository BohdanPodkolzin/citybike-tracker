FROM rabbitmq:3.13-management-alpine

COPY rabbitmq.conf /etc/rabbitmq/conf.d/20-citybikes.conf

EXPOSE 5672 15672
VOLUME /var/lib/rabbitmq
HEALTHCHECK --interval=15s --timeout=10s --start-period=60s --retries=5 \
    CMD rabbitmq-diagnostics -q ping
