# Stage 1: Builder
FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04 AS builder

RUN apt-get update && apt-get install -y \
    python3 python3-pip python3-dev \
    build-essential cmake ninja-build \
    gcc g++ make \
    portaudio19-dev \
    libsndfile1-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# PyAudio is Windows-only in requirements.txt but speech_recognition needs it on Linux too.
# portaudio19-dev is available above so this compiles cleanly.
RUN pip install --no-cache-dir PyAudio

# Stage 2: Runtime
FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

RUN apt-get update && apt-get install -y \
    python3 python3-pip \
    # TLS — edge-tts WebSocket handshake needs up-to-date CA bundle
    ca-certificates \
    # GLib — pygame's bundled SDL2 dlopens libgthread-2.0.so.0 at runtime
    libglib2.0-0 \
    # SDL2 core + mixer (pygame audio playback)
    libsdl2-2.0-0 \
    libsdl2-mixer-2.0-0 \
    # PortAudio — PyAudio + sounddevice mic/speaker on Linux
    libportaudio2 \
    # libsndfile — audio decode fallback
    libsndfile1 \
    # Pillow image codecs (vision.py)
    libjpeg-turbo8 \
    libpng16-16 \
    # PulseAudio client — connects to Windows host PA server for audio I/O
    pulseaudio-utils \
    # ALSA → PulseAudio plugin — routes ALSA calls through PA, eliminates hardware-probe spam
    libasound2-plugins \
    && rm -rf /var/lib/apt/lists/*

# Point ALSA's default device at the PulseAudio TCP server on the Windows host.
# This stops PyAudio from probing non-existent ALSA hardware cards (the wall of
# "cannot find card 0" errors) and makes all ALSA-level audio go through PulseAudio.
RUN printf 'pcm.!default {\n    type pulse\n    server tcp:host.docker.internal:4713\n}\nctl.!default {\n    type pulse\n    server tcp:host.docker.internal:4713\n}\n' > /etc/asound.conf

# Copy pre-built Python packages from builder
COPY --from=builder /usr/local/lib/python3.10/dist-packages /usr/local/lib/python3.10/dist-packages
COPY --from=builder /usr/local/bin /usr/local/bin

WORKDIR /app
COPY . .

RUN mkdir -p /app/models /app/logs /app/memory

ENV PYTHONPATH=/app

CMD ["python3", "-u", "main.py"]
