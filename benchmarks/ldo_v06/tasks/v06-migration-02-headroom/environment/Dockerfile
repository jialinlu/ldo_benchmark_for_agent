FROM python:3.12-slim
WORKDIR /app
COPY starter/ /app/
RUN git init -q && git add . && git -c user.email=evoldo-bench@users.noreply.github.com -c user.name=benchmark commit -qm starter
