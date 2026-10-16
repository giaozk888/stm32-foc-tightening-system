# Compilation only: no USB, serial, host networking, SSH keys, or flashing tools.
FROM ubuntu:24.04
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    ca-certificates cmake ninja-build gcc g++ python3 clang-format-18 \
    gcc-arm-none-eabi libnewlib-arm-none-eabi libstdc++-arm-none-eabi-newlib \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY . /src
RUN groupadd --gid 10001 builder && useradd --uid 10001 --gid 10001 --no-create-home builder \
    && mkdir /out && chown builder:builder /out
USER builder
ENV PYTHONDONTWRITEBYTECODE=1
ENTRYPOINT ["python3", "/src/tools/docker_build.py"]
CMD ["--slot", "both", "--preset", "RouterTransferReadOnly"]
