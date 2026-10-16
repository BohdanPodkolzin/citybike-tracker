FROM redis:7-alpine

COPY redis.conf /etc/redis/redis.conf
COPY entrypoint.sh /usr/local/bin/citybikes-entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/citybikes-entrypoint.sh && chmod 755 /usr/local/bin/citybikes-entrypoint.sh

EXPOSE 6379
VOLUME /data
HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=5 \
    CMD REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli ping | grep -q PONG

USER redis
ENTRYPOINT ["citybikes-entrypoint.sh"]
