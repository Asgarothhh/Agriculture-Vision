FROM alpine:3.20

# Контейнер-хранилище весов моделей.
# При старте копирует seed → shared volume /models (если там ещё пусто).

RUN apk add --no-cache bash coreutils

COPY weights/ /seed/
COPY entrypoint.sh /entrypoint.sh
# Windows CRLF → LF (иначе: exec /entrypoint.sh: no such file or directory)
RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh

VOLUME ["/models"]

ENTRYPOINT ["/entrypoint.sh"]
