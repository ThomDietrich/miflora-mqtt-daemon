#!/bin/sh
if [ ! -f "/config/config.ini" ]; then
  echo 'Mi-Flora mqtt config.ini does not exists, create default'
  cp /opt/miflora-mqtt-daemon/config.ini.dist /config/config.ini
fi

# Xiaomi Mi Flora Plant Sensor MQTT Client/Daemon
python3 /opt/miflora-mqtt-daemon/miflora-mqtt-daemon.py --config /config
