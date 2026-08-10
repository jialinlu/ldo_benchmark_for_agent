FROM python:3.12.3-slim-bookworm

WORKDIR /app
COPY verify.py expected.json /app/evoldo_tests/
COPY test.sh /tests/test.sh
RUN chmod +x /tests/test.sh
