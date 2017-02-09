# MQTT Flora daemon

The MQTT Flora daemon is a simple daemon to query arbitrary MiFlora plant sensor devices, and send the data to an MQTT server (in my case an embedded one from [Home Assistant](https://home-assistant.io/). It can be configured to match personal needs using the `config.ini` file, and can be daemonized using standard shell foo.

```bash
pip install -r requirements.txt
python mqtt-flora.py &
```
