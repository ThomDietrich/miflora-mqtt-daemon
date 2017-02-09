#!/usr/bin/env python3

import paho.mqtt.client as mqtt
import time
from miflora.miflora_poller import MiFloraPoller, \
    MI_CONDUCTIVITY, MI_MOISTURE, MI_LIGHT, MI_TEMPERATURE
from configparser import ConfigParser
import json

parameters = [MI_TEMPERATURE,
              MI_LIGHT,
              MI_MOISTURE,
              MI_CONDUCTIVITY]

config = ConfigParser(delimiters=('=', ))
config.read('config.ini')

sleep_time = config['miflora'].getint('sleep', 60)
topic_prefix = config['mqtt'].get('topic_prefix', 'miflora')
miflora_timeout = config['miflora'].getint('timeout', 600)

# The callback for when the client receives a CONNACK response from the server.
def on_connect(client, userdata, flags, rc):
    print("Connected with result code "+str(rc))

# Initialize Flora sensors

flores = {}
for flora in config['sensors'].items():
    print('Adding', flora[0])
    flores[flora[0]] = MiFloraPoller(
        mac=flora[1],
        cache_timeout=miflora_timeout)


client = mqtt.Client()
client.on_connect = on_connect
client.connect(config['mqtt'].get('hostname', 'homeassistant'),
               config['mqtt'].getint('port', 1883),
               config['mqtt'].getint('timeout', 60))
client.loop_start()

while True:

    for flora in flores:
        print('Publishing for', flora)

        data = {}
        for param in parameters:
            data[param] = flores.get(flora).parameter_value(param)

        client.publish("{}/{}".format(
            topic_prefix,
            flora), json.dumps(data))

    print('Sleeping ...')
    time.sleep(sleep_time)
