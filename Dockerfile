FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxcb-render0 \
    libxcb-render-util0 \
    libxcb-util1 \
    libxcb-xinerama0 \
    libxcb-xinput0 \
    libxcb-xkb1 \
    libegl1 \
    libgl1 \
    libglu1-mesa \
    libxcb-shape0 \
    libxcb-xfixes0 \
    libxcb-image0 \
    libxcb-keysyms1 \
    libxcb-icccm4 \
    libxcb-cursor0 \
    libxcb-shm0 \
    libxcb-randr0 \
    libxkbcommon0 \
    libxkbcommon-x11-0 \
    libxrender1 \
    libxext6 \
    libdbus-1-3 \
    libglib2.0-0 \
    libfontconfig1 \
    libfreetype6 \
    libsm6 \
    libice6 \
    fontconfig \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Optional but often helpful for Qt in containers
ENV QT_X11_NO_MITSHM=1
ENV QT_QPA_PLATFORM=xcb

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

VOLUME ["/app/data", "/app/backups", "/app/logs"]

CMD ["python", "-m", "inventory_manager"]
