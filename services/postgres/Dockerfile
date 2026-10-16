FROM postgres:16-alpine

COPY entrypoint.sh /usr/local/bin/citybikes-entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/citybikes-entrypoint.sh && chmod 755 /usr/local/bin/citybikes-entrypoint.sh

EXPOSE 5432

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=5 \
    CMD pg_isready -q -U "$POSTGRES_USER" -d "$POSTGRES_DB"

ENTRYPOINT ["citybikes-entrypoint.sh"]
CMD ["postgres", "-c", "listen_addresses=*", "-c", "hba_file=/tmp/pg_hba.conf"]
