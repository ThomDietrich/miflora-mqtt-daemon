#!/usr/bin/env python3

import sys
import re
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

if False:
    print('Sorry, this script requires a python3 runtime environemt.', file=sys.stderr)

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
    #print('Data successfully published.')
    pass

# Load configuration file
config = ConfigParser(delimiters=('=', ))
config.optionxform = str
config.read([os.path.join(sys.path[0], 'config.ini'), os.path.join(sys.path[0], 'config.local.ini')])

reporting_mode = config['General'].get('reporting_method', 'mqtt-json')
daemon_enabled = config['Daemon'].getboolean('enabled', True)
base_topic = config['MQTT'].get('base_topic', 'homie' if reporting_mode == 'mqtt-homie' else 'miflora')
device_id = config['MQTT'].get('homie_device_id', 'miflora-mqtt-daemon')
sleep_period = config['Daemon'].getint('period', 300)
#miflora_cache_timeout = config['MiFlora'].getint('cache_timeout', 600)
miflora_cache_timeout = sleep_period - 1

# Check configuration
if not reporting_mode in ['mqtt-json', 'mqtt-homie', 'json']:
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
if reporting_mode in ['mqtt-json', 'mqtt-homie']:
    print('Connecting to MQTT broker ...')
    mqtt_client = mqtt.Client()
    mqtt_client.on_connect = on_connect
    mqtt_client.on_publish = on_publish
    if reporting_mode == 'mqtt-json':
        mqtt_client.will_set('{}/$announce'.format(base_topic), payload='{}', retain=True)
    elif reporting_mode == 'mqtt-homie':
        mqtt_client.will_set('{}/{}/$online'.format(base_topic, device_id), payload='false', retain=True)
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
        sleep(1.0) # some slack to establish the connection

sd_notifier.notify('READY=1')

# Initialize Mi Flora sensors
flores = dict()
for [name, mac] in config['Sensors'].items():
    location = ''
    if '@' in name:
        name, location = name.split("@")
    if not re.match("C4:7C:8D:[0-9A-F]{2}:[0-9A-F]{2}:[0-9A-F]{2}", mac):
        print('Error. The MAC address "{}" seems to be in the wrong format. Please check your configuration.'.format(mac), file=sys.stderr)
        sd_notifier.notify('STATUS=The MAC address "{}" seems to be in the wrong format. Please check your configuration.'.format(mac))
        sys.exit(1)
    flora = dict()
    print('Adding sensor to device list and testing connection ...')
    print('Name:         "{}"'.format(name))
    sd_notifier.notify('STATUS=Attempting initial connection to Mi Flora sensor "{}" ({})'.format(name, mac))
    flora_poller = MiFloraPoller(mac=mac, cache_timeout=miflora_cache_timeout, retries=9)
    flora['poller'] = flora_poller
    flora['mac'] = flora_poller._mac
    flora['refresh'] = sleep_period
    flora['location'] = location
    try:
        flora_poller.fill_cache()
        flora_poller.parameter_value(MI_LIGHT)
        flora['firmware'] = flora_poller.firmware_version()
    except IOError:
        print('Error. Initial connection to Mi Flora sensor "{}" ({}) failed. Please check your setup and the MAC address.'.format(name, mac), file=sys.stderr)
        sd_notifier.notify('STATUS=Initial connection to Mi Flora sensor "{}" ({}) failed'.format(name, mac))
        continue
    else:
        print('Device name:  "{}"'.format(flora_poller.name()))
        print('MAC address:  {}'.format(flora_poller._mac))
        print('Firmware:     {}'.format(flora_poller.firmware_version()))
        print()
    flores[name] = flora

# Discovery Announcement
if reporting_mode == 'mqtt-json':
    print('Announcing Mi Flora devices to MQTT broker for auto-discovery ...')
    flores_info = dict()
    for [flora_name, flora] in flores.items():
        flora_info = {key: value for key, value in flora.items() if key not in ['poller']}
        flora_info['topic'] = '{}/{}'.format(base_topic, flora_name)
        flores_info[flora_name] = flora_info
    mqtt_client.publish('{}/$announce'.format(base_topic), json.dumps(flores_info), retain=True)
    sleep(0.5) # some slack for the publish roundtrip and callback function
    print()
elif reporting_mode == 'mqtt-homie':
    print('Announcing Mi Flora devices to MQTT broker for auto-discovery ...')
    mqtt_client.publish('{}/{}/$homie'.format(base_topic, device_id), '2.1.0-alpha', 1, True)
    mqtt_client.publish('{}/{}/$online'.format(base_topic, device_id), 'true', 1, True)
    mqtt_client.publish('{}/{}/$name'.format(base_topic, device_id), device_id, 1, True)
    mqtt_client.publish('{}/{}/$fw/version'.format(base_topic, device_id), flora['firmware'], 1, True)

    nodes_list = ','.join([flora_name for [flora_name, flora] in flores.items()])
    mqtt_client.publish('{}/{}/$nodes'.format(base_topic, device_id), nodes_list, 1, True)

    for [flora_name, flora] in flores.items():
        mqtt_client.publish('{}/{}/{}/$type'.format(base_topic, device_id, flora_name), 'miflora', 1, True)
        mqtt_client.publish('{}/{}/{}/$properties'.format(base_topic, device_id, flora_name), 'battery,conductivity,light,moisture,temperature', 1, True)
        mqtt_client.publish('{}/{}/{}/battery/$settable'.format(base_topic, device_id, flora_name), 'false', 1, True)
        mqtt_client.publish('{}/{}/{}/battery/$unit'.format(base_topic, device_id, flora_name), 'percent', 1, True)
        mqtt_client.publish('{}/{}/{}/battery/$datatype'.format(base_topic, device_id, flora_name), 'int', 1, True)
        mqtt_client.publish('{}/{}/{}/battery/$range'.format(base_topic, device_id, flora_name), '0:100', 1, True)
        mqtt_client.publish('{}/{}/{}/conductivity/$settable'.format(base_topic, device_id, flora_name), 'false', 1, True)
        mqtt_client.publish('{}/{}/{}/conductivity/$unit'.format(base_topic, device_id, flora_name), 'µS/cm', 1, True)
        mqtt_client.publish('{}/{}/{}/conductivity/$datatype'.format(base_topic, device_id, flora_name), 'int', 1, True)
        mqtt_client.publish('{}/{}/{}/conductivity/$range'.format(base_topic, device_id, flora_name), '0:*', 1, True)
        mqtt_client.publish('{}/{}/{}/light/$settable'.format(base_topic, device_id, flora_name), 'false', 1, True)
        mqtt_client.publish('{}/{}/{}/light/$unit'.format(base_topic, device_id, flora_name), 'lux', 1, True)
        mqtt_client.publish('{}/{}/{}/light/$datatype'.format(base_topic, device_id, flora_name), 'int', 1, True)
        mqtt_client.publish('{}/{}/{}/light/$range'.format(base_topic, device_id, flora_name), '0:50000', 1, True)
        mqtt_client.publish('{}/{}/{}/moisture/$settable'.format(base_topic, device_id, flora_name), 'false', 1, True)
        mqtt_client.publish('{}/{}/{}/moisture/$unit'.format(base_topic, device_id, flora_name), 'percent', 1, True)
        mqtt_client.publish('{}/{}/{}/moisture/$datatype'.format(base_topic, device_id, flora_name), 'int', 1, True)
        mqtt_client.publish('{}/{}/{}/moisture/$range'.format(base_topic, device_id, flora_name), '0:100', 1, True)
        mqtt_client.publish('{}/{}/{}/temperature/$settable'.format(base_topic, device_id, flora_name), 'false', 1, True)
        mqtt_client.publish('{}/{}/{}/temperature/$unit'.format(base_topic, device_id, flora_name), '°C', 1, True)
        mqtt_client.publish('{}/{}/{}/temperature/$datatype'.format(base_topic, device_id, flora_name), 'float', 1, True)
        mqtt_client.publish('{}/{}/{}/temperature/$range'.format(base_topic, device_id, flora_name), '*', 1, True)
    sleep(0.5) # some slack for the publish roundtrip and callback function
    print()

sd_notifier.notify('STATUS=Initialization complete, starting MQTT publish loop')

# Sensor data retrieval and publication
while True:
    for [flora_name, flora] in flores.items():
        data = dict()
        retries = 3
        while retries > 0 and not flora['poller']._cache:
            try:
                flora['poller'].fill_cache()
                flora['poller'].parameter_value(MI_LIGHT)
            except IOError:
                print('Failed to retrieve data from Mi Flora Sensor "{}" ({}). Retrying ...'.format(flora_name, flora['mac']), file=sys.stderr)
                sd_notifier.notify('STATUS=Failed to retrieve data from Mi Flora Sensor "{}" ({}). Retrying ...'.format(flora_name, flora['mac']))
                retries = retries - 1
        if not flora['poller']._cache:
            continue
        for param in parameters:
            data[param] = flora['poller'].parameter_value(param)

        timestamp = strftime('%Y-%m-%d %H:%M:%S', localtime())

        if reporting_mode == 'mqtt-json':
            print('[{}] Attempting to publishing to MQTT topic "{}/{}" ...\nData: {}'.format(timestamp, base_topic, flora_name, json.dumps(data)))
            mqtt_client.publish('{}/{}'.format(base_topic, flora_name), json.dumps(data))
            sleep(0.5) # some slack for the publish roundtrip and callback function
            print()
        elif reporting_mode == 'mqtt-homie':
            print('[{}] Attempting to publishing data for Mi Flora "{}" ...\nData: {}'.format(timestamp, flora_name, str(data)))
            for [param, value] in data.items():
                mqtt_client.publish('{}/{}/{}/{}'.format(base_topic, device_id, flora_name, param), value, 1, False)
            sleep(0.5) # some slack for the publish roundtrip and callback function
            print()
        elif reporting_mode == 'json':
            data['timestamp'] = timestamp
            data['name'] = flora_name
            data['mac'] = flora['mac']
            data['firmware'] = flora['firmware']
            print('Data:', json.dumps(data))
        else:
            raise NameError('Unexpected reporting_mode.')

    sd_notifier.notify('STATUS={} - Status messages for all sensors published'.format(strftime('%Y-%m-%d %H:%M:%S', localtime())))

    if daemon_enabled:
        print('Sleeping ({} seconds) ...'.format(sleep_period))
        sleep(sleep_period)
        print()
    else:
        print('Execution finished in non-daemon-mode.')
        sd_notifier.notify('STATUS=Execution finished in non-daemon-mode')
        if reporting_mode == 'mqtt-json':
            mqtt_client.disconnect()
        break

