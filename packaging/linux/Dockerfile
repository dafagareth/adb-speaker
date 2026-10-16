FROM ubuntu:22.04 AS builder
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends make python3 python3-pip python3-dev binutils adb pulseaudio-utils ca-certificates && rm -rf /var/lib/apt/lists/*
RUN python3 -m pip install --no-cache-dir pyinstaller==6.16.0 setuptools==80.9.0 pyinstaller-hooks-contrib==2025.9
WORKDIR /src
COPY . .
RUN python3 -m pip install --no-deps --no-build-isolation -e .
RUN make test check-receiver
RUN python3 packaging/linux/build.py
FROM scratch AS artifact
COPY --from=builder /src/dist/*.tar.gz /
COPY --from=builder /src/dist/SHA256SUMS /
