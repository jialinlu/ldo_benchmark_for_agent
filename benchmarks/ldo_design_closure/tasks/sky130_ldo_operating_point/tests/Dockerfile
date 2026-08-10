FROM python:3.12.3-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends ngspice && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY evoldo_bench /app/evoldo_tests/evoldo_bench
COPY track /app/evoldo_tests/track
COPY verify.py /app/evoldo_tests/verify.py
COPY test.sh /tests/test.sh
RUN chmod +x /tests/test.sh
ENV EVOLDO_CLOSURE_TASK_ID=sky130_ldo_operating_point
