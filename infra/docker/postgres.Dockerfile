# PostgreSQL 17 (Alpine, unchanged from M1-M8) with the pgvector extension compiled in (M9).
# Staying on the Alpine image keeps the existing data volume and its en_US.utf8 (musl)
# collation unchanged; the Debian-based pgvector image would change libc collation rules
# under existing text indexes.
FROM postgres:17-alpine
ARG PGVECTOR_VERSION=0.8.6
# with_llvm=no: no JIT bitcode (avoids pinning clang/llvm to the server's build).
# OPTFLAGS="": portable build, no -march=native.
RUN apk add --no-cache --virtual .pgvector-build git build-base \
    && git clone --branch "v${PGVECTOR_VERSION}" --depth 1 \
        https://github.com/pgvector/pgvector.git /tmp/pgvector \
    && make -C /tmp/pgvector with_llvm=no OPTFLAGS="" \
    && make -C /tmp/pgvector with_llvm=no install \
    && rm -rf /tmp/pgvector \
    && apk del .pgvector-build
