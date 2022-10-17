##Miflora-mqtt-daemon  Docker image
#Builds compact image to run as an alternative to installing the modules/service.  

# The build image
FROM python:3.10.7-slim as builder
LABEL stage=builder
RUN apt-get update && apt-get install bluez gcc libglib2.0-dev build-essential -y && apt-get clean
COPY requirements.txt /app/requirements.txt
WORKDIR /app/
RUN pip install --user -r requirements.txt
COPY . /app

# The production image
FROM python:3.10.7-slim as app
RUN apt-get update && apt-get install bluetooth bluez -y && apt-get clean
COPY --from=builder /root/.local /root/.local
COPY --from=builder /app/miflora-mqtt-daemon.py /app/miflora-mqtt-daemon.py
WORKDIR /app/
ENV PATH=/root/.local/bin:$PATH

CMD [ "python3", "./miflora-mqtt-daemon.py", "--config_dir", "/config" ]