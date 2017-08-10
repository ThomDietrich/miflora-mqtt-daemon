#!/usr/bin/env python3

import sys
import re
import json
import os.path
from time import sleep, localtime, strftime
from colorama import init as colorama_init
from colorama import Fore, Back, Style
from configparser import ConfigParser
from unidecode import unidecode
from miflora.miflora_poller import MiFloraPoller, MI_BATTERY, MI_CONDUCTIVITY, MI_LIGHT, MI_MOISTURE, MI_TEMPERATURE
import paho.mqtt.client as mqtt
import sdnotify

parameters = {MI_BATTERY: dict(pretty='Sensor Battery Level', typeformat='%d', unit='%'),
              MI_CONDUCTIVITY: dict(pretty='Soil Conductivity/Fertility', typeformat='%d', unit='µS/cm'),
              MI_LIGHT: dict(pretty='Sunlight Intensity', typeformat='%d', unit='lux'),
              MI_MOISTURE: dict(pretty='Soil Moisture', typeformat='%d', unit='%'),
              MI_TEMPERATURE: dict(pretty='Air Temperature', typeformat='%.1f', unit='°C')}

# Intro
colorama_init()
print(Fore.GREEN + Style.BRIGHT)
print('Xiaomi Mi Flora Plant Sensor MQTT Client/Daemon')
print('Source: https://github.com/ThomDietrich/miflora-mqtt-daemon')
print(Style.RESET_ALL)

if False:
    print('Sorry, this script requires a python3 runtime environemt.', file=sys.stderr)

# Systemd Service Notifications - https://github.com/bb4242/sdnotify
sd_notifier = sdnotify.SystemdNotifier()

def print_line(text, error = False, warning=False, sd_notify=False, console=True):
    timestamp = strftime('%Y-%m-%d %H:%M:%S', localtime())
    if console:
        if error:
            print(Fore.RED + Style.BRIGHT + '[{}] '.format(timestamp) + Style.RESET_ALL + '{}'.format(text) + Style.RESET_ALL, file=sys.stderr)
        elif warning:
            print(Fore.YELLOW + '[{}] '.format(timestamp) + Style.RESET_ALL + '{}'.format(text) + Style.RESET_ALL)
        else:
            print(Fore.GREEN + '[{}] '.format(timestamp) + Style.RESET_ALL + '{}'.format(text) + Style.RESET_ALL)

    timestamp_sd = strftime('%b %d %H:%M:%S', localtime())
    if sd_notify:
        sd_notifier.notify('STATUS={} - {}.'.format(timestamp_sd, unidecode(text)))


# Eclipse Paho callbacks - http://www.eclipse.org/paho/clients/python/docs/#callbacks
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print_line('MQTT connection established', console=True, sd_notify=True)
        print()
    else:
        print_line('Connection error with result code {} - {}'.format(str(rc), mqtt.connack_string(rc)), error=True)
        #kill main thread
        os._exit(1)


def on_publish(client, userdata, mid):
    #print_line('Data successfully published.')
    pass


def flores_to_openhab_items(flores, reporting_mode):
    print_line('Generating openHAB "miflora.items" file ...')
    items = list()
    items.append('// miflora.items - Generated by miflora-mqtt-daemon.')
    items.append('// Adapt to your needs! Things you probably want to modify:')
    items.append('//     Room group names, icons,')
    items.append('//     "gAll", "broker", "UnknownRoom"')
    items.append('')
    items.append('// Mi Flora specific groups')
    for param, param_properties in parameters.items():
        items.append('Group g{} "Mi Flora {} elements" (gAll)'.format(param.capitalize(), param_properties['pretty']))
    if reporting_mode == 'mqtt-json':
        for [flora_name, flora] in flores.items():
            location = flora['location'] if flora['location'] else 'UnknownRoom'
            items.append('\n// Mi Flora "{}" ({})'.format(flora['pretty'], flora['mac']))
            for [param, param_properties] in parameters.items():
                basic = 'Number {}_{}_{}'.format(location, flora_name.capitalize(), param.capitalize())
                label = '"{} {} {} [{} {}]"'.format(location, flora['pretty'], param_properties['pretty'], param_properties['typeformat'], param_properties['unit'].replace('%', '%%'))
                details = '<text> (g{}, g{})'.format(location, param.capitalize())
                channel = '{{mqtt="<[broker:{}/{}:state:JSONPATH($.{})]"}}'.format(base_topic, flora_name, param)
                items.append(' '.join([basic, label, details, channel]))
        items.append('')
        print('\n'.join(items))
    #elif reporting_mode == 'mqtt-homie':
    else:
        raise IOError('Given reporting_mode not supported for the export to openHAB items')


# Load configuration file
config = ConfigParser(delimiters=('=', ))
config.optionxform = str
config.read([os.path.join(sys.path[0], 'config.ini'), os.path.join(sys.path[0], 'config.local.ini')])

reporting_mode = config['General'].get('reporting_method', 'mqtt-json')
daemon_enabled = config['Daemon'].getboolean('enabled', True)
base_topic = config['MQTT'].get('base_topic', 'homie' if reporting_mode == 'mqtt-homie' else 'miflora').lower()
device_id = config['MQTT'].get('homie_device_id', 'miflora-mqtt-daemon').lower()
sleep_period = config['Daemon'].getint('period', 300)
miflora_cache_timeout = sleep_period - 1

# Check configuration
if not reporting_mode in ['mqtt-json', 'mqtt-homie', 'json']:
    print_line('Configuration parameter reporting_mode set to an invalid value', error=True, sd_notify=True)
    sys.exit(1)
if not config['Sensors']:
    print_line('No sensors found in configuration file "config.ini"', error=True, sd_notify=True)
    sys.exit(1)

print_line('Configuration accepted', console=False, sd_notify=True)

# MQTT connection
if reporting_mode in ['mqtt-json', 'mqtt-homie']:
    print_line('Connecting to MQTT broker ...')
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
        print_line('MQTT connection error. Please check your settings in the configuration file "config.ini"', error=True, sd_notify=True)
        sys.exit(1)
    else:
        mqtt_client.loop_start()
        sleep(1.0) # some slack to establish the connection

sd_notifier.notify('READY=1')

# Initialize Mi Flora sensors
flores = dict()
for [name, mac] in config['Sensors'].items():
    if not re.match("C4:7C:8D:[0-9A-F]{2}:[0-9A-F]{2}:[0-9A-F]{2}", mac):
        print_line('The MAC address "{}" seems to be in the wrong format. Please check your configuration'.format(mac), error=True, sd_notify=True)
        sys.exit(1)

    location = ''
    if '@' in name:
        name, location = name.split("@")
        location = location.replace(' ', '-')
    name_pretty = name
    name_clean = name.lower()
    for o, n in [[' ', '-'], ['ä', 'ae'], ['ö', 'oe'], ['ü', 'ue'], ['ß', 'ss']]:
        name_clean = name_clean.replace(o, n)
    name_clean = unidecode(name_clean)


    flora = dict()
    print('Adding sensor to device list and testing connection ...')
    print('Name:          "{}"'.format(name_pretty))
    #print_line('Attempting initial connection to Mi Flora sensor "{}" ({})'.format(name_pretty, mac), console=False, sd_notify=True)

    flora_poller = MiFloraPoller(mac=mac, cache_timeout=miflora_cache_timeout, retries=3)
    flora['poller'] = flora_poller
    flora['pretty'] = name_pretty
    flora['mac'] = flora_poller._mac
    flora['refresh'] = sleep_period
    flora['location'] = location
    flora['stats'] = {"count": 0, "success": 0, "failure": 0}
    try:
        flora_poller.fill_cache()
        flora_poller.parameter_value(MI_LIGHT)
        flora['firmware'] = flora_poller.firmware_version()
    except IOError:
        print_line('Failed to retrieve data from Mi Flora sensor "{}" ({}) during initial connection.'.format(name_pretty, mac), error=True, sd_notify=True)
    else:
        print('Internal name: "{}"'.format(name_clean))
        print('Device name:   "{}"'.format(flora_poller.name()))
        print('MAC address:   {}'.format(flora_poller._mac))
        print('Firmware:      {}'.format(flora_poller.firmware_version()))
        print_line('Initial connection to Mi Flora sensor "{}" ({}) successful'.format(name_pretty, mac), sd_notify=True)
    print()
    flores[name_clean] = flora

# Discovery Announcement
if reporting_mode == 'mqtt-json':
    print_line('Announcing Mi Flora devices to MQTT broker for auto-discovery ...')
    flores_info = dict()
    for [flora_name, flora] in flores.items():
        flora_info = {key: value for key, value in flora.items() if key not in ['poller', 'stats']}
        flora_info['topic'] = '{}/{}'.format(base_topic, flora_name)
        flores_info[flora_name] = flora_info
    mqtt_client.publish('{}/$announce'.format(base_topic), json.dumps(flores_info), retain=True)
    sleep(0.5) # some slack for the publish roundtrip and callback function
    print()
elif reporting_mode == 'mqtt-homie':
    print_line('Announcing Mi Flora devices to MQTT broker for auto-discovery ...')
    mqtt_client.publish('{}/{}/$homie'.format(base_topic, device_id), '2.1.0-alpha', 1, True)
    mqtt_client.publish('{}/{}/$online'.format(base_topic, device_id), 'true', 1, True)
    mqtt_client.publish('{}/{}/$name'.format(base_topic, device_id), device_id, 1, True)
    mqtt_client.publish('{}/{}/$fw/version'.format(base_topic, device_id), flora['firmware'], 1, True)

    nodes_list = ','.join([flora_name for [flora_name, flora] in flores.items()])
    mqtt_client.publish('{}/{}/$nodes'.format(base_topic, device_id), nodes_list, 1, True)

    for [flora_name, flora] in flores.items():
        topic_path = '{}/{}/{}'.format(base_topic, device_id, flora_name)
        mqtt_client.publish('{}/$name'.format(topic_path), flora['pretty'], 1, True)
        mqtt_client.publish('{}/$type'.format(topic_path), 'miflora', 1, True)
        mqtt_client.publish('{}/$properties'.format(topic_path), 'battery,conductivity,light,moisture,temperature', 1, True)
        mqtt_client.publish('{}/battery/$settable'.format(topic_path), 'false', 1, True)
        mqtt_client.publish('{}/battery/$unit'.format(topic_path), 'percent', 1, True)
        mqtt_client.publish('{}/battery/$datatype'.format(topic_path), 'int', 1, True)
        mqtt_client.publish('{}/battery/$range'.format(topic_path), '0:100', 1, True)
        mqtt_client.publish('{}/conductivity/$settable'.format(topic_path), 'false', 1, True)
        mqtt_client.publish('{}/conductivity/$unit'.format(topic_path), 'µS/cm', 1, True)
        mqtt_client.publish('{}/conductivity/$datatype'.format(topic_path), 'int', 1, True)
        mqtt_client.publish('{}/conductivity/$range'.format(topic_path), '0:*', 1, True)
        mqtt_client.publish('{}/light/$settable'.format(topic_path), 'false', 1, True)
        mqtt_client.publish('{}/light/$unit'.format(topic_path), 'lux', 1, True)
        mqtt_client.publish('{}/light/$datatype'.format(topic_path), 'int', 1, True)
        mqtt_client.publish('{}/light/$range'.format(topic_path), '0:50000', 1, True)
        mqtt_client.publish('{}/moisture/$settable'.format(topic_path), 'false', 1, True)
        mqtt_client.publish('{}/moisture/$unit'.format(topic_path), 'percent', 1, True)
        mqtt_client.publish('{}/moisture/$datatype'.format(topic_path), 'int', 1, True)
        mqtt_client.publish('{}/moisture/$range'.format(topic_path), '0:100', 1, True)
        mqtt_client.publish('{}/temperature/$settable'.format(topic_path), 'false', 1, True)
        mqtt_client.publish('{}/temperature/$unit'.format(topic_path), '°C', 1, True)
        mqtt_client.publish('{}/temperature/$datatype'.format(topic_path), 'float', 1, True)
        mqtt_client.publish('{}/temperature/$range'.format(topic_path), '*', 1, True)
    sleep(0.5) # some slack for the publish roundtrip and callback function
    print()

print_line('Initialization complete, starting MQTT publish loop', console=False, sd_notify=True)

flores_to_openhab_items(flores, reporting_mode)

# Sensor data retrieval and publication
while True:
    for [flora_name, flora] in flores.items():
        data = dict()
        attempts = 2
        flora['poller']._cache = None
        flora['poller']._last_read = None
        flora['stats']['count'] = flora['stats']['count'] + 1
        print_line('Retrieving data from sensor "{}" ...'.format(flora['pretty']))
        while attempts != 0 and not flora['poller']._cache:
            try:
                flora['poller'].fill_cache()
                flora['poller'].parameter_value(MI_LIGHT)
            except IOError:
                attempts = attempts - 1
                if attempts > 0:
                    print_line('Retrying ...', warning = True)
                flora['poller']._cache = None
                flora['poller']._last_read = None

        if not flora['poller']._cache:
            flora['stats']['failure'] = flora['stats']['failure'] + 1
            print_line('Failed to retrieve data from Mi Flora sensor "{}" ({}), success rate: {:.0%}'.format(
                flora['pretty'], flora['mac'], flora['stats']['success']/flora['stats']['count']
                ), error = True, sd_notify = True)
            print()
            continue
        else:
            flora['stats']['success'] = flora['stats']['success'] + 1

        for param,_ in parameters.items():
            data[param] = flora['poller'].parameter_value(param)
        print_line('Result: {}'.format(json.dumps(data)))
        
        if reporting_mode == 'mqtt-json':
            print_line('Publishing to MQTT topic "{}/{}"'.format(base_topic, flora_name))
            mqtt_client.publish('{}/{}'.format(base_topic, flora_name), json.dumps(data))
            sleep(0.5) # some slack for the publish roundtrip and callback function
        elif reporting_mode == 'mqtt-homie':
            print_line('Publishing data to MQTT base topic "{}/{}/{}"'.format(base_topic, device_id, flora_name))
            for [param, value] in data.items():
                mqtt_client.publish('{}/{}/{}/{}'.format(base_topic, device_id, flora_name, param), value, 1, False)
            sleep(0.5) # some slack for the publish roundtrip and callback function
        elif reporting_mode == 'json':
            data['timestamp'] = strftime('%Y-%m-%d %H:%M:%S', localtime())
            data['name'] = flora_name
            data['pretty_name'] = flora['pretty']
            data['mac'] = flora['mac']
            data['firmware'] = flora['firmware']
            print('Data for "{}": {}'.format(flora_name, json.dumps(data)))
        else:
            raise NameError('Unexpected reporting_mode.')
        print()

    print_line('Status messages published', console=False, sd_notify=True)

    if daemon_enabled:
        print_line('Sleeping ({} seconds) ...'.format(sleep_period))
        sleep(sleep_period)
        print()
    else:
        print_line('Execution finished in non-daemon-mode', sd_notify=True)
        if reporting_mode == 'mqtt-json':
            mqtt_client.disconnect()
        break
