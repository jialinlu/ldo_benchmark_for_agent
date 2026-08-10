FROM python:3.12.3-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends ngspice ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY starter/ /app/
CMD ["bash"]
