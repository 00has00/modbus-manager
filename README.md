# Modbus Manager
Modbus Manager was written in python to run on Raspberry Pi.
It connects to a PLC (in this case a DL06) via ModBus RTU and 
then sends data back to an automation controller (in this case OpenHab)
via an MQTT message bus.

It supports receiving commands via MQTT and sending status updates.

 - The top part of the script is configruation for services and sensors.

## Prerequisites
  - Python 2.7   (Upgrade to 3.x required changes to threading... tfh)
  - Python 2.7 Threading libraries
  - Paho MQTT Client and python libraries (eclipse.org or pip)
  - PyModbus python libraries (pip)
