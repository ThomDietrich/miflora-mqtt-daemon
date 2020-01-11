# Docker images for miflora-mqtt-daemon

_A simple Linux python script to query arbitrary Mi Flora plant sensor devices and send the data to an **MQTT** broker._

For more info: [miflora-mqtt-daemon](https://github.com/ThomDietrich/miflora-mqtt-daemon)

All credits go to Thom Dietrich for creating miflora-mqtt-daemon.

[](demo.gif)


# Image Variants

[Miflora2mqtt](https://hub.docker.com/r/raymondmm/miflora2mqtt) Docker images come in different variations and are supported by manifest lists (auto-detect architecture). This makes it more easy to deploy in a multi architecture Docker environment. E.g. a Docker Swarm with mix of Raspberry Pi's and amd64 nodes. But also in a non-multi architecture Docker environment, there is no need to explicit add the tag for the architecture to use.

All images are based on Alpine Linux.

Supported architectures are: `amd64`, `arm32v6`, `arm32v7` and `arm64v8`.

# Usage

## Docker run

```shell script
docker run -it -e TZ=Europe/Amsterdam --network=host -v <host_path_to_config>:/config --name miflora raymondmm/miflora2mqtt:latest
```

## Docker stack / compose

```yaml
################################################################################
# Miflora Stack
################################################################################
#$ docker stack deploy miflora --compose-file docker-compose-miflora.yml

# hcitool lescan
# sudo ip link set dev eth0 down && sudo ip link set dev eth0 up
################################################################################
version: "3.7"

services:
  miflora:
    image: raymondmm/miflora2mqtt:latest
    environment:
      - TZ=Europe/Amsterdam
    networks:
      hostnet: {}
    volumes:
      - <host_path_to_config>:/config
    deploy:
      placement:
        constraints: [node.hostname == rpi-2]
      replicas: 1

networks:
  hostnet:
    external: true
    name: host
```

# Bluetooth
Below a few steps to run on a Raspberry PI 3B with Ubuntu server installed.

```shell script
sudo apt install bluez
```

```shell script
sudo ln -s /lib/firmware /etc/firmware
```

Remove console=ttyAMA0,115200 from /boot/firmware/cmdline.txt

```shell script
sudo nano /boot/firmware/cmdline.txt
```

```shell script
sudo hciattach /dev/ttyAMA0 bcm43xx 921600 -
```

## Verify
```shell script
dmesg | grep -i 'bluetooth'
```

```shell script
sudo hcitool dev
```

```shell script
sudo bluetoothctl -v
```

```shell script
sudo hcitool lescan
```

## Cronjob

```shell script
sudo nano /etc/cron.hourly/hci0-restart
```

```shell script
#!/bin/bash
hciconfig hci0 down
hciconfig hci0 up
hcitool lescan
```

```shell script
sudo chmod 755 /etc/cron.hourly/hci0-restart
```

```shell script
sudo cat /var/log/syslog | grep CRON
```
