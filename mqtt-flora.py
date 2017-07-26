#!/usr/bin/env python3

import sys
import json
import os.path
from time import sleep, localtime, strftime
from configparser import ConfigParser
from miflora.miflora_poller import MiFloraPoller, MI_BATTERY, MI_CONDUCTIVITY, MI_LIGHT, MI_MOISTURE, MI_TEMPERATURE
import paho.mqtt.client as mqtt
import sdnotify

parameters = [MI_BATTERY, MI_CONDUCTIVITY, MI_LIGHT, MI_MOISTURE, MI_TEMPERATURE]

# Intro
print('Xiaomi Mi Flora Plant Sensor MQTT Client/Daemon')
print('Source: https://github.com/ThomDietrich/miflora-mqtt-daemon')
print()

# Systemd Service Notifications - https://github.com/bb4242/sdnotify
sd_notifier = sdnotify.SystemdNotifier()

# Eclipse Paho callbacks - http://www.eclipse.org/paho/clients/python/docs/#callbacks
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print('Connected.\n')
        sd_notifier.notify('STATUS=MQTT connection established')
    else:
        print('Connection error with result code {} - {}'.format(str(rc), mqtt.connack_string(rc)), file=sys.stderr)
        #kill main thread
        os._exit(1)

def on_publish(client, userdata, mid):
    print('Data successfully published!')

# Load configuration file
config = ConfigParser(delimiters=('=', ))
config.optionxform = str
config.read([os.path.join(sys.path[0], 'config.ini'), os.path.join(sys.path[0], 'config.local.ini')])

reporting_mode = config['General'].get('reporting_method', 'mqtt-json')
daemon_enabled = config['Daemon'].getboolean('enabled', True)
topic_prefix = config['MQTT'].get('topic_prefix', 'miflora')
sleep_period = config['Daemon'].getint('period', 300)
#miflora_cache_timeout = config['MiFlora'].getint('cache_timeout', 600)
miflora_cache_timeout = sleep_period - 1

# Check configuration
if not reporting_mode in ['mqtt-json', 'json']:
    print('Error. Configuration parameter reporting_mode set to an invalid value.', file=sys.stderr)
    sd_notifier.notify('STATUS=Configuration parameter reporting_mode set to an invalid value')
    sys.exit(1)
if not config['Sensors']:
    print('Error. Please add at least one sensor to the configuration file "config.ini".', file=sys.stderr)
    print('Scan for available Miflora sensors with "sudo hcitool lescan".', file=sys.stderr)
    sd_notifier.notify('STATUS=No sensors found in configuration file "config.ini"')
    sys.exit(1)
sd_notifier.notify('STATUS=Configuration accepted')

# MQTT connection
if reporting_mode == 'mqtt-json':
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
        sd_notifier.notify('STATUS=Please check your MQTT connection settings in the configuration file "config.ini"')
        sys.exit(1)
    else:
        mqtt_client.loop_start()
        sleep(1) # some slack to establish the connection

sd_notifier.notify('READY=1')

# Initialize Mi Flora sensors
flores = dict()
for [name, mac] in config['Sensors'].items():
    sd_notifier.notify('STATUS=Attempting initial connection to MiFlora sensor "{}" ({})'.format(name, mac))
    print('Adding sensor to device list and testing connection...')
    print('Name:         "{}"'.format(name))
    flora_poller = MiFloraPoller(mac=mac, cache_timeout=miflora_cache_timeout, retries=9)
    flora_poller.fill_cache()
    try:
        flora_poller.parameter_value(MI_LIGHT)
    except IOError:
        print('Error. Initial connection to MiFlora sensor "{}" ({}) failed. Please check your setup and the MAC address.'.format(name, mac), file=sys.stderr)
        sd_notifier.notify('STATUS=Initial connection to MiFlora sensor "{}" ({}) failed'.format(name, mac))
        sys.exit(1)
    else:
        print('Device name:  "{}"'.format(flora_poller.name()))
        print('MAC address:  {}'.format(flora_poller._mac))
        print('Firmware:     {}'.format(flora_poller.firmware_version()))
        flores[name] = flora_poller
    print()

sd_notifier.notify('STATUS=Initialization complete, starting MQTT publish loop')

# Sensor data retrieval and publication
while True:
    for [flora_name, flora_poller] in flores.items():
        data = dict()
        for param in parameters:
            data[param] = flora_poller.parameter_value(param)
        timestamp = strftime('%Y-%m-%d %H:%M:%S', localtime())

        if reporting_mode == 'mqtt-json':
            print('[{}] Attempting to publishing to MQTT topic "{}/{}" ...\nData: {}'.format(timestamp, topic_prefix, flora_name, json.dumps(data)))
            mqtt_client.publish('{}/{}'.format(topic_prefix, flora_name), json.dumps(data))
            sleep(0.5) # some slack for the publish roundtrip and callback function
            print()
        elif reporting_mode == 'json':
            data['timestamp'] = timestamp
            data['name'] = flora_name
            data['mac'] = flora_poller._mac
            data['firmware'] = flora_poller.firmware_version()
            print('Data:', json.dumps(data))
        else:
            raise NameError('Unexpected reporting_mode.')

    sd_notifier.notify('STATUS={} - Status messages for all sensors published'.format(strftime('%Y-%m-%d %H:%M:%S', localtime())))

    if daemon_enabled:
        print('Sleeping ({} seconds) ...'.format(sleep_period))
        sleep(sleep_period)
        print()
    else:
        sd_notifier.notify('STATUS=Execution finished in non-daemon-mode')
        if reporting_mode == 'mqtt-json':
            mqtt_client.disconnect()
        break

