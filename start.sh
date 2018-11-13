#!/bin/sh
if [! -f "/opt/miflora-mqtt-daemon/config/config.ini"]; then
  echo 'Mi-Flora mqtt config does not exists, create default.'
  mv /tmp/config.ini.dist /opt/miflora-mqtt-daemon/config/config.ini
fi

# Xiaomi Mi Flora Plant Sensor MQTT Client/Daemon
python3 /opt/miflora-mqtt-daemon/miflora-mqtt-daemon.py --config /opt/miflora-config
