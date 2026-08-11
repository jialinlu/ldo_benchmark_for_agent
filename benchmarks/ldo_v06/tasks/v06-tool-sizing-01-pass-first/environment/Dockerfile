FROM ghcr.io/arcadia-1/circuit-bench-sky130-ngspice@sha256:bd5c425675eb99fc1a2c3bca10b63a871c457613767e2c6984d6c207b3160500
WORKDIR /app
COPY starter/ /app/
RUN git init -q && git add . && git -c user.email=evoldo-bench@users.noreply.github.com -c user.name=benchmark commit -qm starter
