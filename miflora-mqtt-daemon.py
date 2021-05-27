#!/usr/bin/env python3

import ssl
import sys
import re
import json
import os.path
import argparse
from time import time, sleep, localtime, strftime
from collections import OrderedDict
from colorama import init as colorama_init
from colorama import Fore, Back, Style
from configparser import ConfigParser
from unidecode import unidecode
from miflora.miflora_poller import MiFloraPoller, MI_BATTERY, MI_CONDUCTIVITY, MI_LIGHT, MI_MOISTURE, MI_TEMPERATURE
from btlewrap import BluepyBackend, GatttoolBackend, BluetoothBackendException
from bluepy.btle import BTLEException
import paho.mqtt.client as mqtt
import sdnotify
from signal import signal, SIGPIPE, SIG_DFL
signal(SIGPIPE,SIG_DFL)

project_name = 'Xiaomi Mi Flora Plant Sensor MQTT Client/Daemon'
project_url = 'https://github.com/ThomDietrich/miflora-mqtt-daemon'

parameters = OrderedDict([
    (MI_LIGHT, dict(name="LightIntensity", name_pretty='Sunlight Intensity', typeformat='%d', unit='lux', device_class="illuminance")),
    (MI_TEMPERATURE, dict(name="AirTemperature", name_pretty='Air Temperature', typeformat='%.1f', unit='°C', device_class="temperature")),
    (MI_MOISTURE, dict(name="SoilMoisture", name_pretty='Soil Moisture', typeformat='%d', unit='%', device_class="humidity")),
    (MI_CONDUCTIVITY, dict(name="SoilConductivity", name_pretty='Soil Conductivity/Fertility', typeformat='%d', unit='µS/cm')),
    (MI_BATTERY, dict(name="Battery", name_pretty='Sensor Battery Level', typeformat='%d', unit='%', device_class="battery"))
])

if False:
    # will be caught by python 2.7 to be illegal syntax
    print('Sorry, this script requires a python3 runtime environment.', file=sys.stderr)

# Argparse
parser = argparse.ArgumentParser(description=project_name, epilog='For further details see: ' + project_url)
parser.add_argument('--config_dir', help='set directory where config.ini is located', default=sys.path[0])
parse_args = parser.parse_args()

# Intro
colorama_init()
print(Fore.GREEN + Style.BRIGHT)
print(project_name)
print('Source:', project_url)
print(Style.RESET_ALL)

# Systemd Service Notifications - https://github.com/bb4242/sdnotify
sd_notifier = sdnotify.SystemdNotifier()

# Logging function
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

# Identifier cleanup
def clean_identifier(name):
    clean = name.strip()
    for this, that in [[' ', '-'], ['ä', 'ae'], ['Ä', 'Ae'], ['ö', 'oe'], ['Ö', 'Oe'], ['ü', 'ue'], ['Ü', 'Ue'], ['ß', 'ss']]:
        clean = clean.replace(this, that)
    clean = unidecode(clean)
    return clean

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

# Load configuration file
config_dir = parse_args.config_dir

config = ConfigParser(delimiters=('=', ), inline_comment_prefixes=('#'))
config.optionxform = str
try:
    with open(os.path.join(config_dir, 'config.ini')) as config_file:
        config.read_file(config_file)
except IOError:
    print_line('No configuration file "config.ini"', error=True, sd_notify=True)
    sys.exit(1)

reporting_mode = config['General'].get('reporting_method', 'mqtt-json')
used_adapter = config['General'].get('adapter', 'hci0')
daemon_enabled = config['Daemon'].getboolean('enabled', True)

if reporting_mode == 'mqtt-homie':
    default_base_topic = 'homie'
elif reporting_mode == 'homeassistant-mqtt':
    default_base_topic = 'homeassistant'
elif reporting_mode == 'thingsboard-json':
    default_base_topic = 'v1/devices/me/telemetry'
elif reporting_mode == 'wirenboard-mqtt':
    default_base_topic = ''
else:
    default_base_topic = 'miflora'

base_topic = config['MQTT'].get('base_topic', default_base_topic).lower()
sleep_period = config['Daemon'].getint('period', 300)
miflora_cache_timeout = sleep_period - 1

# Check configuration
if reporting_mode not in ['mqtt-json', 'mqtt-homie', 'json', 'mqtt-smarthome', 'homeassistant-mqtt', 'thingsboard-json', 'wirenboard-mqtt']:
    print_line('Configuration parameter reporting_mode set to an invalid value', error=True, sd_notify=True)
    sys.exit(1)
if not config['Sensors']:
    print_line('No sensors found in configuration file "config.ini"', error=True, sd_notify=True)
    sys.exit(1)
if reporting_mode == 'wirenboard-mqtt' and base_topic:
    print_line('Parameter "base_topic" ignored for "reporting_method = wirenboard-mqtt"', warning=True, sd_notify=True)


print_line('Configuration accepted', console=False, sd_notify=True)

# MQTT connection
if reporting_mode in ['mqtt-json', 'mqtt-smarthome', 'homeassistant-mqtt', 'thingsboard-json', 'wirenboard-mqtt']:
    print_line('Connecting to MQTT broker ...')
    mqtt_client = mqtt.Client()
    mqtt_client.on_connect = on_connect
    mqtt_client.on_publish = on_publish
    if reporting_mode == 'mqtt-json':
        mqtt_client.will_set('{}/$announce'.format(base_topic), payload='{}', retain=True)
    elif reporting_mode == 'mqtt-smarthome':
        mqtt_client.will_set('{}/connected'.format(base_topic), payload='0', retain=True)

    if config['MQTT'].getboolean('tls', False):
        # According to the docs, setting PROTOCOL_SSLv23 "Selects the highest protocol version
        # that both the client and server support. Despite the name, this option can select
        # “TLS” protocols as well as “SSL”" - so this seems like a resonable default
        mqtt_client.tls_set(
            ca_certs=config['MQTT'].get('tls_ca_cert', None),
            keyfile=config['MQTT'].get('tls_keyfile', None),
            certfile=config['MQTT'].get('tls_certfile', None),
            tls_version=ssl.PROTOCOL_SSLv23
        )

    mqtt_username = os.environ.get("MQTT_USERNAME", config['MQTT'].get('username'))
    mqtt_password = os.environ.get("MQTT_PASSWORD", config['MQTT'].get('password', None))

    if mqtt_username:
        mqtt_client.username_pw_set(mqtt_username, mqtt_password)
    try:
        mqtt_client.connect(os.environ.get('MQTT_HOSTNAME', config['MQTT'].get('hostname', 'localhost')),
                            port=int(os.environ.get('MQTT_PORT', config['MQTT'].get('port', '1883'))),
                            keepalive=config['MQTT'].getint('keepalive', 60))
    except:
        print_line('MQTT connection error. Please check your settings in the configuration file "config.ini"', error=True, sd_notify=True)
        sys.exit(1)
    else:
        if reporting_mode == 'mqtt-smarthome':
            mqtt_client.publish('{}/connected'.format(base_topic), payload='1', retain=True)
        if reporting_mode != 'thingsboard-json':
            mqtt_client.loop_start()
            sleep(1.0) # some slack to establish the connection

sd_notifier.notify('READY=1')

# Initialize Mi Flora sensors
flores = OrderedDict()
for [name, mac] in config['Sensors'].items():
    if not re.match("[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}", mac.lower()):
        print_line('The MAC address "{}" seems to be in the wrong format. Please check your configuration'.format(mac), error=True, sd_notify=True)
        sys.exit(1)

    if '@' in name:
        name_pretty, location_pretty = name.split('@')
    else:
        name_pretty, location_pretty = name, ''
    name_clean = clean_identifier(name_pretty)
    location_clean = clean_identifier(location_pretty)

    flora = OrderedDict()
    print('Adding sensor to device list and testing connection ...')
    print('Name:          "{}"'.format(name_pretty))
    # print_line('Attempting initial connection to Mi Flora sensor "{}" ({})'.format(name_pretty, mac), console=False, sd_notify=True)

    flora_poller = MiFloraPoller(mac=mac, backend=BluepyBackend, cache_timeout=miflora_cache_timeout, retries=3, adapter=used_adapter)
    flora['poller'] = flora_poller
    flora['name_pretty'] = name_pretty
    flora['mac'] = flora_poller._mac
    flora['refresh'] = sleep_period
    flora['location_clean'] = location_clean
    flora['location_pretty'] = location_pretty
    flora['stats'] = {"count": 0, "success": 0, "failure": 0}
    flora['firmware'] = "0.0.0"
    try:
        flora_poller.fill_cache()
        flora_poller.parameter_value(MI_LIGHT)
        flora['firmware'] = flora_poller.firmware_version()
    except (IOError, BluetoothBackendException, BTLEException, RuntimeError, BrokenPipeError) as e:
        print_line('Initial connection to Mi Flora sensor "{}" ({}) failed due to exception: {}'.format(name_pretty, mac, e), error=True, sd_notify=True)
    else:
        print('Internal name: "{}"'.format(name_clean))
        print('Device name:   "{}"'.format(flora_poller.name()))
        print('MAC address:   {}'.format(flora_poller._mac))
        print('Firmware:      {}'.format(flora_poller.firmware_version()))
        print_line('Initial connection to Mi Flora sensor "{}" ({}) successful'.format(name_pretty, mac), sd_notify=True)
        if int(flora_poller.firmware_version().replace(".", "")) < 319:
            print_line('Mi Flora sensor with a firmware version before 3.1.9 is not supported. Please update now.'.format(name_pretty, mac), error=True, sd_notify=True)

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
    mqtt_client = OrderedDict()
    print_line('Announcing Mi Flora devices to MQTT broker for auto-discovery ...')

    for [flora_name, flora] in flores.items():
        print_line('Connecting to MQTT broker for "{}" ...'.format(flora['name_pretty']))
        mqtt_client[flora_name.lower()] = mqtt.Client(flora_name.lower())
        mqtt_client[flora_name.lower()].on_connect = on_connect
        mqtt_client[flora_name.lower()].on_publish = on_publish
        mqtt_client[flora_name.lower()].will_set('{}/{}/$state'.format(base_topic, flora_name.lower()), payload='disconnected', retain=True)

        if config['MQTT'].getboolean('tls', False):
            # According to the docs, setting PROTOCOL_SSLv23 "Selects the highest protocol version
            # that both the client and server support. Despite the name, this option can select
            # “TLS” protocols as well as “SSL”" - so this seems like a resonable default
            mqtt_client[flora_name.lower()].tls_set(
                ca_certs=config['MQTT'].get('tls_ca_cert', None),
                keyfile=config['MQTT'].get('tls_keyfile', None),
                certfile=config['MQTT'].get('tls_certfile', None),
                tls_version=ssl.PROTOCOL_SSLv23
            )

        mqtt_username = os.environ.get("MQTT_USERNAME", config['MQTT'].get('username'))
        mqtt_password = os.environ.get("MQTT_PASSWORD", config['MQTT'].get('password', None))

        if mqtt_username:
            mqtt_client[flora_name.lower()].username_pw_set(mqtt_username, mqtt_password)
        try:
            mqtt_client[flora_name.lower()].connect(os.environ.get('MQTT_HOSTNAME', config['MQTT'].get('hostname', 'localhost')),
                                port=int(os.environ.get('MQTT_PORT', config['MQTT'].get('port', '1883'))),
                                keepalive=config['MQTT'].getint('keepalive', 60))
        except:
            print_line('MQTT connection error. Please check your settings in the configuration file "config.ini"', error=True, sd_notify=True)
            sys.exit(1)
        else:
            mqtt_client[flora_name.lower()].loop_start()
            sleep(1.0) # some slack to establish the connection

        topic_path = '{}/{}'.format(base_topic, flora_name.lower())

        mqtt_client[flora_name.lower()].publish('{}/$homie'.format(topic_path), '3.0', 1, True)
        mqtt_client[flora_name.lower()].publish('{}/$name'.format(topic_path), flora['name_pretty'], 1, True)
        mqtt_client[flora_name.lower()].publish('{}/$state'.format(topic_path), 'ready', 1, True)
        mqtt_client[flora_name.lower()].publish('{}/$mac'.format(topic_path), flora['mac'], 1, True)
        mqtt_client[flora_name.lower()].publish('{}/$stats'.format(topic_path), 'interval,timestamp', 1, True)
        mqtt_client[flora_name.lower()].publish('{}/$stats/interval'.format(topic_path), flora['refresh'], 1, True)
        mqtt_client[flora_name.lower()].publish('{}/$stats/timestamp'.format(topic_path), strftime('%Y-%m-%dT%H:%M:%S%z', localtime()), 1, True)
        mqtt_client[flora_name.lower()].publish('{}/$fw/name'.format(topic_path), 'miflora-firmware', 1, True)
        mqtt_client[flora_name.lower()].publish('{}/$fw/version'.format(topic_path), flora['firmware'], 1, True)
        mqtt_client[flora_name.lower()].publish('{}/$nodes'.format(topic_path), 'sensor', 1, True)

        sensor_path = '{}/sensor'.format(topic_path)

        mqtt_client[flora_name.lower()].publish('{}/$name'.format(sensor_path), 'miflora', 1, True)
        mqtt_client[flora_name.lower()].publish('{}/$properties'.format(sensor_path), 'battery,conductivity,light,moisture,temperature', 1, True)

        mqtt_client[flora_name.lower()].publish('{}/battery/$name'.format(sensor_path), 'battery', 1, True)
        mqtt_client[flora_name.lower()].publish('{}/battery/$settable'.format(sensor_path), 'false', 1, True)
        mqtt_client[flora_name.lower()].publish('{}/battery/$unit'.format(sensor_path), '%', 1, True)
        mqtt_client[flora_name.lower()].publish('{}/battery/$datatype'.format(sensor_path), 'integer', 1, True)
        mqtt_client[flora_name.lower()].publish('{}/battery/$format'.format(sensor_path), '0:100', 1, True)
        mqtt_client[flora_name.lower()].publish('{}/battery/$retained'.format(sensor_path), 'true', 1, True)

        mqtt_client[flora_name.lower()].publish('{}/conductivity/$name'.format(sensor_path), 'conductivity', 1, True)
        mqtt_client[flora_name.lower()].publish('{}/conductivity/$settable'.format(sensor_path), 'false', 1, True)
        mqtt_client[flora_name.lower()].publish('{}/conductivity/$unit'.format(sensor_path), 'µS/cm', 1, True)
        mqtt_client[flora_name.lower()].publish('{}/conductivity/$datatype'.format(sensor_path), 'integer', 1, True)
        mqtt_client[flora_name.lower()].publish('{}/conductivity/$format'.format(sensor_path), '0:*', 1, True)
        mqtt_client[flora_name.lower()].publish('{}/conductivity/$retained'.format(sensor_path), 'true', 1, True)

        mqtt_client[flora_name.lower()].publish('{}/light/$name'.format(sensor_path), 'light', 1, True)
        mqtt_client[flora_name.lower()].publish('{}/light/$settable'.format(sensor_path), 'false', 1, True)
        mqtt_client[flora_name.lower()].publish('{}/light/$unit'.format(sensor_path), 'lux', 1, True)
        mqtt_client[flora_name.lower()].publish('{}/light/$datatype'.format(sensor_path), 'integer', 1, True)
        mqtt_client[flora_name.lower()].publish('{}/light/$format'.format(sensor_path), '0:50000', 1, True)
        mqtt_client[flora_name.lower()].publish('{}/light/$retained'.format(sensor_path), 'true', 1, True)

        mqtt_client[flora_name.lower()].publish('{}/moisture/$name'.format(sensor_path), 'moisture', 1, True)
        mqtt_client[flora_name.lower()].publish('{}/moisture/$settable'.format(sensor_path), 'false', 1, True)
        mqtt_client[flora_name.lower()].publish('{}/moisture/$unit'.format(sensor_path), '%', 1, True)
        mqtt_client[flora_name.lower()].publish('{}/moisture/$datatype'.format(sensor_path), 'integer', 1, True)
        mqtt_client[flora_name.lower()].publish('{}/moisture/$format'.format(sensor_path), '0:100', 1, True)
        mqtt_client[flora_name.lower()].publish('{}/moisture/$retained'.format(sensor_path), 'true', 1, True)

        mqtt_client[flora_name.lower()].publish('{}/temperature/$name'.format(sensor_path), 'temperature', 1, True)
        mqtt_client[flora_name.lower()].publish('{}/temperature/$settable'.format(sensor_path), 'false', 1, True)
        mqtt_client[flora_name.lower()].publish('{}/temperature/$unit'.format(sensor_path), '°C', 1, True)
        mqtt_client[flora_name.lower()].publish('{}/temperature/$datatype'.format(sensor_path), 'float', 1, True)
        mqtt_client[flora_name.lower()].publish('{}/temperature/$format'.format(sensor_path), '*', 1, True)
        mqtt_client[flora_name.lower()].publish('{}/temperature/$retained'.format(sensor_path), 'true', 1, True)
    sleep(0.5) # some slack for the publish roundtrip and callback function
    print()
elif reporting_mode == 'homeassistant-mqtt':
    print_line('Announcing Mi Flora devices to MQTT broker for auto-discovery ...')
    for [flora_name, flora] in flores.items():
        state_topic = '{}/sensor/{}/state'.format(base_topic, flora_name.lower())
        for [sensor, params] in parameters.items():
            discovery_topic = 'homeassistant/sensor/{}/{}/config'.format(flora_name.lower(), sensor)
            payload = OrderedDict()
            payload['name'] = "{} {}".format(flora_name, sensor.title())
            payload['unique_id'] = "{}-{}".format(flora['mac'].lower().replace(":", ""), sensor)
            payload['unit_of_measurement'] = params['unit']
            if 'device_class' in params:
                payload['device_class'] = params['device_class']
            payload['state_topic'] = state_topic
            payload['value_template'] = "{{{{ value_json.{} }}}}".format(sensor)
            payload['device'] = {
                    'identifiers' : ["MiFlora{}".format(flora['mac'].lower().replace(":", ""))],
                    'connections' : [["mac", flora['mac'].lower()]],
                    'manufacturer' : 'Xiaomi',
                    'name' : flora_name,
                    'model' : 'MiFlora Plant Sensor (HHCCJCY01)',
                    'sw_version': flora['firmware']
            }
            payload['expire_after'] = '3600'
            mqtt_client.publish(discovery_topic, json.dumps(payload), 1, True)
elif reporting_mode == 'gladys-mqtt':
    print_line('Announcing Mi Flora devices to MQTT broker for auto-discovery ...')
    
    for [flora_name, flora] in flores.items():
        topic_path = '{}/mqtt:miflora:{}/feature'.format(base_topic, flora_name.lower())
        data = OrderedDict()
        for param,_ in parameters.items():
            data[param] = flora['poller'].parameter_value(param)
        mqtt_client.publish('{}/mqtt:battery/state'.format(topic_path),data['battery'],1,True)
        mqtt_client.publish('{}/mqtt:moisture/state'.format(topic_path),data['moisture'],1,True)
        mqtt_client.publish('{}/mqtt:light/state'.format(topic_path),data['light'],1,True)
        mqtt_client.publish('{}/mqtt:conductivity/state'.format(topic_path),data['conductivity'],1,True)
        mqtt_client.publish('{}/mqtt:temperature/state'.format(topic_path),data['temperature'],1,True)


    sleep(0.5) # some slack for the publish roundtrip and callback function
    print()
elif reporting_mode == 'wirenboard-mqtt':
    print_line('Announcing Mi Flora devices to MQTT broker for auto-discovery ...')
    for [flora_name, flora] in flores.items():
        mqtt_client.publish('/devices/{}/meta/name'.format(flora_name), flora_name, 1, True)
        topic_path = '/devices/{}/controls'.format(flora_name)
        mqtt_client.publish('{}/battery/meta/type'.format(topic_path), 'value', 1, True)
        mqtt_client.publish('{}/battery/meta/units'.format(topic_path), '%', 1, True)
        mqtt_client.publish('{}/conductivity/meta/type'.format(topic_path), 'value', 1, True)
        mqtt_client.publish('{}/conductivity/meta/units'.format(topic_path), 'µS/cm', 1, True)
        mqtt_client.publish('{}/light/meta/type'.format(topic_path), 'value', 1, True)
        mqtt_client.publish('{}/light/meta/units'.format(topic_path), 'lux', 1, True)
        mqtt_client.publish('{}/moisture/meta/type'.format(topic_path), 'rel_humidity', 1, True)
        mqtt_client.publish('{}/temperature/meta/type'.format(topic_path), 'temperature', 1, True)
        mqtt_client.publish('{}/timestamp/meta/type'.format(topic_path), 'text', 1, True)
    sleep(0.5) # some slack for the publish roundtrip and callback function
    print()

print_line('Initialization complete, starting MQTT publish loop', console=False, sd_notify=True)


# Sensor data retrieval and publication
while True:
    for [flora_name, flora] in flores.items():
        data = OrderedDict()
        attempts = 2
        flora['poller']._cache = None
        flora['poller']._last_read = None
        flora['stats']['count'] += 1
        print_line('Retrieving data from sensor "{}" ...'.format(flora['name_pretty']))
        while attempts != 0 and not flora['poller']._cache:
            try:
                flora['poller'].fill_cache()
                flora['poller'].parameter_value(MI_LIGHT)
            except (IOError, BluetoothBackendException, BTLEException, RuntimeError, BrokenPipeError) as e:
                attempts -= 1
                if attempts > 0:
                    if len(str(e)) > 0:
                        print_line('Retrying due to exception: {}'.format(e), error=True)
                    else:
                        print_line('Retrying ...', warning=True)
                flora['poller']._cache = None
                flora['poller']._last_read = None

        if not flora['poller']._cache:
            flora['stats']['failure'] += 1
            if reporting_mode == 'mqtt-homie':
                mqtt_client[flora_name.lower()].publish('{}/{}/$state'.format(base_topic, flora_name.lower()), 'disconnected', 1, True)
            print_line('Failed to retrieve data from Mi Flora sensor "{}" ({}), success rate: {:.0%}'.format(
                flora['name_pretty'], flora['mac'], flora['stats']['success']/flora['stats']['count']
                ), error = True, sd_notify = True)
            print()
            continue
        else:
            flora['stats']['success'] += 1

        for param,_ in parameters.items():
            data[param] = flora['poller'].parameter_value(param)
        print_line('Result: {}'.format(json.dumps(data)))

        if reporting_mode == 'mqtt-json':
            print_line('Publishing to MQTT topic "{}/{}"'.format(base_topic, flora_name))
            mqtt_client.publish('{}/{}'.format(base_topic, flora_name), json.dumps(data))
            sleep(0.5) # some slack for the publish roundtrip and callback function
        elif reporting_mode == 'thingsboard-json':
            print_line('Publishing to MQTT topic "{}" username "{}"'.format(base_topic, flora_name))
            mqtt_client.username_pw_set(flora_name)
            mqtt_client.reconnect()
            sleep(1.0)
            mqtt_client.publish('{}'.format(base_topic), json.dumps(data))
            sleep(0.5) # some slack for the publish roundtrip and callback function
        elif reporting_mode == 'homeassistant-mqtt':
            print_line('Publishing to MQTT topic "{}/sensor/{}/state"'.format(base_topic, flora_name.lower()))
            mqtt_client.publish('{}/sensor/{}/state'.format(base_topic, flora_name.lower()), json.dumps(data))
            sleep(0.5) # some slack for the publish roundtrip and callback function
        elif reporting_mode == 'gladys-mqtt':
            print_line('Publishing to MQTT topic "{}/mqtt:miflora:{}/feature"'.format(base_topic, flora_name.lower()))
            mqtt_client.publish('{}/mqtt:miflora:{}/feature'.format(base_topic, flora_name.lower()), json.dumps(data))
            sleep(0.5) # some slack for the publish roundtrip and callback function
        elif reporting_mode == 'mqtt-homie':
            print_line('Publishing data to MQTT base topic "{}/{}"'.format(base_topic, flora_name.lower()))
            mqtt_client[flora_name.lower()].publish('{}/{}/$state'.format(base_topic, flora_name.lower()), 'ready', 1, True)
            for [param, value] in data.items():
                mqtt_client[flora_name.lower()].publish('{}/{}/sensor/{}'.format(base_topic, flora_name.lower(), param), value, 1, True)
            mqtt_client[flora_name.lower()].publish('{}/{}/$stats/timestamp'.format(base_topic, flora_name.lower()), strftime('%Y-%m-%dT%H:%M:%S%z', localtime()), 1, True)
            sleep(0.5) # some slack for the publish roundtrip and callback function
        elif reporting_mode == 'mqtt-smarthome':
            for [param, value] in data.items():
                print_line('Publishing data to MQTT topic "{}/status/{}/{}"'.format(base_topic, flora_name, param))
                payload = dict()
                payload['val'] = value
                payload['ts'] = int(round(time() * 1000))
                mqtt_client.publish('{}/status/{}/{}'.format(base_topic, flora_name, param), json.dumps(payload), retain=True)
            sleep(0.5)  # some slack for the publish roundtrip and callback function
        elif reporting_mode == 'wirenboard-mqtt':
            for [param, value] in data.items():
                print_line('Publishing data to MQTT topic "/devices/{}/controls/{}"'.format(flora_name, param))
                mqtt_client.publish('/devices/{}/controls/{}'.format(flora_name, param), value, retain=True)
            mqtt_client.publish('/devices/{}/controls/{}'.format(flora_name, 'timestamp'), strftime('%Y-%m-%d %H:%M:%S', localtime()), retain=True)
            sleep(0.5)  # some slack for the publish roundtrip and callback function
        elif reporting_mode == 'json':
            data['timestamp'] = strftime('%Y-%m-%d %H:%M:%S', localtime())
            data['name'] = flora_name
            data['name_pretty'] = flora['name_pretty']
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
