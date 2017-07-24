#!/usr/bin/env python3

import sys
import json
import os.path
from time import sleep, localtime, strftime
from configparser import ConfigParser
from miflora.miflora_poller import MiFloraPoller, MI_BATTERY, MI_CONDUCTIVITY, MI_LIGHT, MI_MOISTURE, MI_TEMPERATURE
import paho.mqtt.client as mqtt

parameters = [MI_BATTERY, MI_CONDUCTIVITY, MI_LIGHT, MI_MOISTURE, MI_TEMPERATURE]

print('Xiaomi Mi Flora Plant Sensor MQTT Client/Daemon')
print('Source: https://github.com/janwh/miflora-mqtt-daemon')
print()

# Load configuration file
config = ConfigParser(delimiters=('=', ))
config.optionxform = str
config.read(os.path.join(sys.path[0], 'config.ini'))
daemon_enabled = config['Daemon'].getboolean('enabled', True)
sleep_period = config['Daemon'].getint('period', 60)
topic_prefix = config['MQTT'].get('topic_prefix', 'miflora')
miflora_cache_timeout = config['MiFlora'].getint('cache_timeout', 600)
if not config['Sensors']:
    print('Error. Please add at least one sensor to the configuration file "config.ini".', file=sys.stderr)
    print('Scan for available Miflora sensors with "hcitool lescan".', file=sys.stderr)
    sys.exit(1)

# Initialize Mi Flora sensors
flores = {}
for flora in config['Sensors'].items():
    print('Adding device from config to Mi Flora device list ...')
    print('Name:         "{}"'.format(flora[0]))
    flores[flora[0]] = MiFloraPoller(mac=flora[1], cache_timeout=miflora_cache_timeout)
    print('Device name:  "{}"'.format(flores[flora[0]].name()))
    print('MAC address:  {}'.format(flora[1]))
    print('Firmware:     {}'.format(flores[flora[0]].firmware_version()))
    print()

# Callbacks http://www.eclipse.org/paho/clients/python/docs/#callbacks
def on_connect(client, userdata, flags, rc):
    if rc != 0:
        print('Connected with result code {}: {}'.format(str(rc), mqtt.connack_string(rc)), file=sys.stderr)
        sys.exit(1)
def on_publish(client, userdata, mid):
    print('Data successfully published!')

# MQTT connection
print('Connecting to MQTT broker ...')
mqtt_client = mqtt.Client()
mqtt_client.on_connect = on_connect
mqtt_client.on_publish = on_publish
if config['MQTT'].get('username'):
    mqtt_client.username_pw_set(config['MQTT'].get('username'), config['MQTT'].get('password', None))
try:
    mqtt_client.connect(config['MQTT'].get('hostname', 'localhost'),
                        port=config['MQTT'].getint('port', 1883),
                        keepalive=config['MQTT'].getint('keepalive', 60))
except:
    print('Error. Please check your MQTT connection settings in the configuration file "config.ini".', file=sys.stderr)
    sys.exit(1)
else:
    print('Connected.\n')
    mqtt_client.loop_start()

# Sensor data retrieval and publishing
while True:
    for flora in flores:
        data = {}
        for param in parameters:
            data[param] = flores.get(flora).parameter_value(param)
        print(strftime('[%Y-%m-%d %H:%M:%S]', localtime()), end=' ')
        print('Attempting to publishing to MQTT topic "{}/{}" ...\nData: {}'.format(topic_prefix, flora, json.dumps(data)))
        mqtt_client.publish('{}/{}'.format(topic_prefix, flora), json.dumps(data))
        sleep(0.5) # some slack for the publish roundtrip and callback function
        print()
    if not daemon_enabled:
        break
    print('Sleeping ({} seconds) ...'.format(sleep_period))
    sleep(sleep_period)
    print()

mqtt_client.disconnect()

