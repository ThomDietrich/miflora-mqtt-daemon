# Xiaomi Mi Flora Plant Sensor MQTT Client/Daemon

A simple Linux python script to query arbitrary Mi Flora plant sensor devices and send the data to an **MQTT** broker,
e.g., the famous [Eclipse Mosquitto](https://projects.eclipse.org/projects/technology.mosquitto).
After data made the hop to the MQTT broker it can be used by home automation software, like [openHAB](https://openhab.org) or Home Assistant.

![Demo gif for command line execution](demo.gif)

The program can be executed in **daemon mode** to run continuously in the background, e.g., as a systemd service.

## About Mi Flora
* [Xiaomi Mi Flora sensors](https://xiaomi-mi.com/sockets-and-sensors/xiaomi-huahuacaocao-flower-care-smart-monitor) ([e.g. 12-17€](https://www.aliexpress.com/wholesale?SearchText=xiaomi+mi+flora+plant+sensor)) are meant to keep your plants alive by monitoring soil moisture, soil conductivity and light conditions
* The sensor uses Bluetooth Low Energy (BLE) and has a rather limited range
* A coin cell battery is used as power source, which should last between 1.5 to 2 years under normal conditions
* Food for thought: The sensor can also be used for other things than plants, like in the [fridge](https://community.openhab.org/t/refrigerator-temperature-sensors/40076) or as [door and blind sensor](https://community.openhab.org/t/miflora-cheap-window-and-door-sensor-water-sensor-blind-sensor-etc/38232)

## Features

* Tested with Mi Flora firmware v2.6.2, v2.6.4, v2.6.6, v3.1.4, others anticipated
* Build on top of [open-homeautomation/miflora](https://github.com/open-homeautomation/miflora)
* Highly configurable
* Data publication via MQTT
* Configurable topic and payload:
    * JSON encoded
    * following the [Homie Convention v2.0.5](https://github.com/marvinroger/homie)
    * following the [mqtt-smarthome architecture proposal](https://github.com/mqtt-smarthome/mqtt-smarthome)
    * using the [HomeAssistant MQTT discovery format](https://home-assistant.io/docs/mqtt/discovery/)
    * using the [ThingsBoard.io](https://thingsboard.io/) MQTT interface
* Announcement messages to support auto-discovery services
* MQTT authentication support
* No special/root privileges needed
* Daemon mode (default)
* Systemd service, sd\_notify messages generated
* MQTT-less mode, printing data directly to stdout/file
* Automatic generation of openHAB items and rules
* Reliable and intuitive
* Tested on Raspberry Pi 3 and Raspberry Pi 0W


![Promotional image](https://xiaomi-mi.com/uploads/ck/xiaomi-flower-monitor-001.jpg)

### Readings

The Mi Flora sensor offers the following plant and soil readings:

| Name            | Description |
|-----------------|-------------|
| `temperature`   | Air temperature, in [°C] (0.1°C resolution) |
| `light`         | [Sunlight intensity](https://aquarium-digest.com/tag/lumenslux-requirements-of-a-cannabis-plant/), in [lux] |
| `moisture`      | [Soil moisture](https://observant.zendesk.com/hc/en-us/articles/208067926-Monitoring-Soil-Moisture-for-Optimal-Crop-Growth), in [%] |
| `conductivity`  | [Soil fertility](https://www.plantcaretools.com/measure-fertilization-with-ec-meters-for-plants-faq), in [µS/cm] |
| `battery`       | Sensor battery level, in [%] |

## Prerequisites

An MQTT broker is needed as the counterpart for this daemon.
Even though an MQTT-less mode is provided, it is not recommended for normal smart home automation integration.
MQTT is huge help in connecting different parts of your smart home and setting up of a broker is quick and easy.

## Installation

On a modern Linux system just a few steps are needed to get the daemon working.
The following example shows the installation under Debian/Raspbian below the `/opt` directory:

```shell
sudo apt install git python3 python3-pip bluetooth bluez

git clone https://github.com/ThomDietrich/miflora-mqtt-daemon.git /opt/miflora-mqtt-daemon

cd /opt/miflora-mqtt-daemon
sudo pip3 install -r requirements.txt
```

The daemon depends on `gatttool`, an external tool provided by the package `bluez` installed just now.
Make sure gatttool is available on your system by executing the command once:

```shell
gatttool --help
```

## Configuration

To match personal needs, all operation details can be configured using the file [`config.ini`](config.ini.dist).
The file needs to be created first:

```shell
cp /opt/miflora-mqtt-daemon/config.{ini.dist,ini}
vim /opt/miflora-mqtt-daemon/config.ini
```

**Attention:**
You need to add at least one sensor to the configuration.
Scan for available Mi Flora sensors in your proximity with the command:

```shell
sudo hcitool lescan
```

Interfacing your Mi Flora sensor with this program is harmless.
The device will not be modified and will still work with the official Xiaomi app.

## Execution

A first test run is as easy as:

```shell
python3 /opt/miflora-mqtt-daemon/miflora-mqtt-daemon.py
```

With a correct configuration the result should look similar to the the screencap above.
Pay attention to communication errors due to distance related weak BLE connections.

Using the command line argument `--config`, a directory where to read the config.ini file from can be specified, e.g.

```shell
python3 /opt/miflora-mqtt-daemon/miflora-mqtt-daemon.py --config /opt/miflora-config
```

The extensive output can be reduced to error messages:

```shell
python3 /opt/miflora-mqtt-daemon/miflora-mqtt-daemon.py > /dev/null
```

### Continuous Daemon/Service

You most probably want to execute the program **continuously in the background**.
This can be done either by using the internal daemon or cron.

**Attention:** Daemon mode must be enabled in the configuration file (default).

1. Systemd service - on systemd powered systems the **recommended** option
   
   ```shell
   sudo cp /opt/miflora-mqtt-daemon/template.service /etc/systemd/system/miflora.service

   sudo systemctl daemon-reload

   sudo systemctl start miflora.service
   sudo systemctl status miflora.service

   sudo systemctl enable miflora.service
   ```

1. Screen Shell - Run the program inside a [screen shell](https://www.howtoforge.com/linux_screen):
   
   ```shell
   screen -S miflora-mqtt-daemon -d -m python3 /path/to/miflora-mqtt-daemon.py
   ```

## Usage with Docker

A Dockerfile in the repository can be used to build a docker container from the sources with a command such as:

```shell
docker build -t miflora-mqtt-daemon .
```

Running the container in interactive mode works like this:

```shell
docker run -it --name miflora-mqtt-daemon -v .:/config miflora-mqtt-daemon
```

To run the container in daemon mode use `-d` flag:

```shell
docker run -d --name miflora-mqtt-daemon -v .:/config miflora-mqtt-daemon
```

The `/config` volume can be used to provide a directory on the host which contains your `config.ini` file (e.g. the `.` in the above example could represent `/opt/miflora-mqtt-daemon`).
You may need to tweak the network settings (e.g. `--network host`) for Docker depending on how your system is set up.

## Integration

In the "mqtt-json" reporting mode, data will be published to the MQTT broker topic "`miflora/sensorname`" (e.g. `miflora/petunia`, names configurable).
An example:

```json
{"light": 5424, "moisture": 30, "temperature": 21.4, "conductivity": 1020, "battery": 100}
```

This data can be subscribed to and processed by other applications, like [openHAB](https://openhab.org).

Enjoy!


### openHAB (v1.x MQTT Binding)

To make further processing of the sensor readings as easy as possible, the program has an integrated generator for openHAB Items definitions.
To generate a complete listing of Items, which you can then copy and adapt to your openHAB setup, execute:

```shell
python3 /opt/miflora-mqtt-daemon/miflora-mqtt-daemon.py --gen-openhab
```

The following code snippet shows a simple example of how a Mi Flora openHAB Items file could look like for the above example:

```java
// miflora.items

// Mi Flora specific groups
Group gBattery "Mi Flora sensor battery level elements" (gAll)
Group gTemperature "Mi Flora air temperature elements" (gAll)
Group gMoisture "Mi Flora soil moisture elements" (gAll)
Group gConductivity "Mi Flora soil conductivity/fertility elements" (gAll)
Group gLight "Mi Flora sunlight intensity elements" (gAll)

// Mi Flora "Big Blue Petunia" (C4:7C:8D:60:DC:E6)
Number Balcony_Petunia_Battery "Balcony Petunia Sensor Battery Level [%d %%]" <text> (gBalcony, gBattery) {mqtt="<[broker:miflora/petunia:state:JSONPATH($.battery)]"}
Number Balcony_Petunia_Temperature "Balcony Petunia Air Temperature [%.1f °C]" <text> (gBalcony, gTemperature) {mqtt="<[broker:miflora/petunia:state:JSONPATH($.temperature)]"}
Number Balcony_Petunia_Moisture "Balcony Petunia Soil Moisture [%d %%]" <text> (gBalcony, gMoisture) {mqtt="<[broker:miflora/petunia:state:JSONPATH($.moisture)]"}
Number Balcony_Petunia_Conductivity "Balcony Petunia Soil Conductivity/Fertility [%d µS/cm]" <text> (gBalcony, gConductivity) {mqtt="<[broker:miflora/petunia:state:JSONPATH($.conductivity)]"}
Number Balcony_Petunia_Light "Balcony Petunia Sunlight Intensity [%d lux]" <text> (gBalcony, gLight) {mqtt="<[broker:miflora/petunia:state:JSONPATH($.light)]"}
```

Paste the presented items definition into an openHAB items file and you are ready to go.
Be sure to install the used MQTT Binding and JSONPath Transformation openHAB addons beforehand.

### openHAB (v2.x MQTT Binding) with internal broker 

The following shows an example of a textual configuration using the new MQTT plugin introduced with openHAB 2.4. The example also uses the new internal broker.

#### Thing file

```java
Bridge mqtt:systemBroker:MqttBroker "MQTT Broker" [ brokerid="embedded-mqtt-broker" ]
{
    Thing topic FicusBenjamin "Ficus Benjamin"
    {
        Channels:
            Type number : light         "Light Intensity"   [ stateTopic="miflora/FicusBenjamin", transformationPattern="JSONPATH:$.light" ]
            Type number : battery       "Battery Charge"    [ stateTopic="miflora/FicusBenjamin", transformationPattern="JSONPATH:$.battery" ]
            Type number : temperature   "Temperature"       [ stateTopic="miflora/FicusBenjamin", transformationPattern="JSONPATH:$.temperature" ]
            Type number : conductivity  "Soil Fertility"    [ stateTopic="miflora/FicusBenjamin", transformationPattern="JSONPATH:$.conductivity" ]
            Type number : moisture      "Soil Moisture"     [ stateTopic="miflora/FicusBenjamin", transformationPattern="JSONPATH:$.moisture" ]
    }
}
```

#### Item file

```java
Number:Illuminance      Miflora_Ficus_Light         "Light Intensity Ficus [%d lx]"     <light>         { channel="mqtt:topic:MqttBroker:FicusBenjamin:light" }
Number:Dimensionless    Miflora_Ficus_Battery       "Battery Charge Ficus [%d %%]"      <battery>       { channel="mqtt:topic:MqttBroker:FicusBenjamin:battery" }
Number:Temperature      Miflora_Ficus_Temperature   "Temperature Ficus [%.1f °C]"       <temperature>   { channel="mqtt:topic:MqttBroker:FicusBenjamin:temperature" }
Number                  Miflora_Ficus_Conductivity  "Soil Fertility Ficus [%d µS/cm]"   <lawnmower>     { channel="mqtt:topic:MqttBroker:FicusBenjamin:conductivity" }
Number:Dimensionless    Miflora_Ficus_Moisture      "Soil Moisture Ficus [%d %%]"       <humidity>      { channel="mqtt:topic:MqttBroker:FicusBenjamin:moisture" }
```

### ThingsBoard

to integrate with [ThingsBoard.io](https://thingsboard.io/):

1. in your `config.ini` set `reporting_method = thingsboard-json`
1. in your `config.ini` assign unique sensor names for your plants
1. on the ThingsBoard platform create devices and use `Access token` as `Credential type` and the chosen sensor name as token


----

#### Disclaimer and Legal

> *Xiaomi* and *Mi Flora* are registered trademarks of *BEIJING XIAOMI TECHNOLOGY CO., LTD.*
> 
> This project is a community project not for commercial use.
> The authors will not be held responsible in the event of device failure or withered plants.
> 
> This project is in no way affiliated with, authorized, maintained, sponsored or endorsed by *Xiaomi* or any of its affiliates or subsidiaries.
