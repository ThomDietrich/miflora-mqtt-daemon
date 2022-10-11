# The build image
FROM python:3.8.0-slim as builder
RUN apt-get update && apt-get install gcc libglib2.0-dev build-essential -y && apt-get clean
COPY requirements.txt /app/requirements.txt
WORKDIR app
RUN pip install --user -r requirements.txt
COPY . /app

# The production image
FROM python:3.8.0-slim as app
COPY --from=builder /root/.local /root/.local
COPY --from=builder /app/miflora-mqtt-daemon.py /app/miflora-mqtt-daemon.py
WORKDIR app
ENV PATH=/root/.local/bin:$PATH

CMD [ "python3", "./miflora-mqtt-daemon.py", "--config_dir", "/config" ]