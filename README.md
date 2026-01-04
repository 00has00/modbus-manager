# Modbus Manager

> **Note:** This project was converted from Python 2 to Python 3 on 2026-01-05 to ensure compatibility with modern libraries and interpreters.

Modbus Manager was written in python to run on Raspberry Pi.
It connects to a PLC (in this case a DL06) via ModBus RTU and 
then sends data back to an automation controller (in this case OpenHab)
via an MQTT message bus.

It supports receiving commands via MQTT and sending status updates.

 - The top part of the script is configruation for services and sensors.

## Prerequisites
  - Python 3.x
  - Paho MQTT Client (`paho-mqtt`)
  - PyModbus (`pymodbus`)
