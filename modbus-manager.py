#! /usr/bin/env python3

##
##
##

import threading
import time
import json
import paho.mqtt.client as mqtt
from collections import deque
from pymodbus.client import ModbusSerialClient as ModbusClient


##
##Node Configureation
MQTT_SERVER = "mqtt-server"
STATE = "active"
LOCATION = "garage"
STATUS_INTERVAL=300

mqttretries = 2

BASE = "/" + STATE + "/" + LOCATION
SUB = BASE + "/+/control"
SYS_STATUS_QUEUE = BASE + "/system/status"
SYS_MESSAGE_QUEUE = BASE + "/system/messages"

##
## Modbus Configuration
MODBUS_TYPE = 'rtu'
MODBUS_PORT = '/dev/ttyUSB0'
MODBUS_BAUDRATE = 9600
MODBUS_UNITID = 2

##
## Modbus Exception Codes
MODBUS_EXCEPTIONS = (
        "",
        "ILLEGAL FUNCTION",
        "ILLEGAL DATA ADDRESS",
        "ILLEGAL DATA VALUE",
        "SERVER DEVICE FAILURE",
        "ACKNOWLEDGE",
        "SERVER DEVICE BUSY",
        "MEMORY PARITY ERROR",
        "GATEWAY PATH UNAVAILABLE",
        "GATEWAY TARGET DEVICE FAILED TO RESPOND"
        )




##
##Sensor Definitions
## Move to a config file someday...
##
sensors = {
    'bore_pump_run': {
        'init':'default',
        'access':('read','write'),
        'status':0,
	'status-update':1,
        'control':"",
        'type':'modbus-memory',
        'address':3078
        },

    'transfer_pump_run': {
        'init':'default',
        'access':('read','write'),
        'status':0,
	'status-update':1,
        'control':"",
        'type':'modbus-memory',
        'address':3072
        },
    # status=1 - bore_pump fault
    'bore_pump_fault': {
        'init':'current',
        'access':('read'),
        'status':0,
        'status-update':1,
        'control':"",
        'type':'modbus-input',
        'address':2055
        },

    'bore_tank_level': {
        'init':'current',
        'access':('read'),
        'status':0,
        'status-update':1,
        'control':"",
        'type':'modbus-analog',
        'address':0x108,
        'register':0,
        'name':"Bore Tank",
        'outputMax':85000,
        'sensorMax':5000,
        'sensorMin':28
        },

    'house_tank_level': {
        'init':'current',
        'access':('read'),
        'status':0,
        'status-update':1,
        'control':"",
        'type':'modbus-analog',
        'address':0x108,
        'register':2,
        'name':"House Tank",
        'outputMax':40000,
        'sensorMax':7805,
        'sensorMin':28
        },

    'rain_tank_level': {
        'init':'current',
        'access':('read'),
        'status':0,
        'status-update':1,
        'control':"",
        'type':'modbus-analog',
        'address':0x108,
        'register':1,
        'name':"Rain Tank",
        'outputMax':80000,
        'sensorMax':5600,
        'sensorMin':28
        }
    }


##
##
## MQTT Callback Functions
def mqtt_on_connect(client, userdata, flags, rc):
    global mqttretries
    mqttretries = 0
    print("MQTT Connection established to host: " + str(MQTT_SERVER))

def mqtt_on_disconnect(client, userdata, rc):
    global mqttretries
    if rc != 0:
        print("Unexpected disconnection.")
    mqttretries += 1
    if mqttretries > 3:
        ERR_FATAL=1
    else:
        mqttc.connect(MQTT_SERVER)

def mqtt_on_message(client, userdata, message):
    #print("MQTT Received message '" + str(message.payload) + "' on topic '" + message.topic + "' with QoS " + str(message.qos))
    try:
        payload = message.payload.decode('utf-8')
    except UnicodeDecodeError:
        payload = message.payload

    fractions = message.topic.split("/")
    if fractions[1] == 'active':
        if fractions[2] == LOCATION:
            if fractions[4] == 'control':
                ## SPLIT OUT SYSTEM COMMAND PROCESSING TO A SEPERATE FUNCTION.
                if fractions[3] == 'system' and fractions[4] == 'control' and payload == 'showSensors':
                    #print("publishing to: " + SYS_STATUS_QUEUE)
                    mqttc.publish( SYS_STATUS_QUEUE, json.dumps(sensors) )
                else:
                    ## NEED TO MAKE MORE GENERIC ONE DAY, VERY FOCUSED ON receiving ON|OFF MESSAGES
                    msg = { 'sensor':fractions[3], 'action':fractions[4], 'msg':payload }
                    with messageQueueLock:
                        messageQueue.append(msg)

##
##
## Modbus Functions

def modbus_bit_read(address):
    sts = modbusHandle.read_coils(int(address),count=1,slave=MODBUS_UNITID)
    if sts.bits[0] == True:
        return 1
    else:
        return 0

def modbus_bit_write(address, data=None):
    if data == None:
        data =0
    #print("Setting address" + str(hex(address)) + " to: " + str(data))
    if data == 0:
        sts = modbusHandle.write_coil(int(address), False, slave=MODBUS_UNITID)
        return sts
    if data == 1:
        sts = modbusHandle.write_coil(int(address), True, slave=MODBUS_UNITID)
        return sts
    return 0xff

def modbus_input_read(address):
    #print("Reading Address" + str(address))
    #return 0
    sts = modbusHandle.read_discrete_inputs(int(address), count=1, slave=MODBUS_UNITID)
    if sts.bits[0] == True:
        return 1
    else:
        return 0

def modbus_analog_read(address, register=None):
    if register == None:
        register = 0

    #print("Reading address: " + str(address) + " Register: " + str(register))
    #return 2222

    sts = modbusHandle.read_holding_registers(address, count=4, slave=MODBUS_UNITID)
    #print(sts)
    try:
        assert(sts.function_code < 0x80)
    except Exception as exc:
        print("Modbus Error: " + str(MODBUS_EXCEPTIONS[sts.exception_code]))
        return -1
    return int(sts.registers[register])


##
## Sensor Type to Function mapping
TYPE_TO_FUNCTIONS_MAP = {
    'modbus-memory': {
        'read': modbus_bit_read,
        'write': modbus_bit_write
        },
    'modbus-input': {
        'read': modbus_input_read
        },
    'modbus-analog': {
        'read': modbus_analog_read
        }
    }

##
##
## Sensor Activity Function
## THIS FUNCTION MUST BE CALLED WHILE HOLDING THE modbusQueueLock TO PREVENT PROBLEMS
## i.e.
##  with modbusQueueLock:
##      sensor_activity(...)...
##  blah..
def sensor_activity(sensor, instruction, data=None):

    if sensor == None:
        print("sensor_activity: request for action on non-existent sensor")
        mqttc.publish(SYS_MESSAGE_QUEUE, payload="sensor_activity; request for action on non-existent sensor")
        return -1

    if instruction not in [ 'init', 'read', 'write' ]:
        print("sensor_activity: no comprehension of instruction: " + str(instruction))
        return -1
    
    if instruction == 'init':
        run_function = TYPE_TO_FUNCTIONS_MAP[sensor['type']]['read']
        if sensor['init'] == 'current':
          #print(str(run_function))
            if 'register' in sensor:
                status = run_function( sensor['address'], register=sensor['register'] )
            else:
                status = run_function( sensor['address'] )
            sensor['status'] = status
            #print("Status = " + str(status))
        if sensor['init'] == 'default':
            run_function = TYPE_TO_FUNCTIONS_MAP[sensor['type']]['write']
            if 'register' in sensor:
                status = run_function(sensor['address'], register=sensor['register'] )
            else:
                status = run_function(sensor['address'])
        return 0

    run_function = TYPE_TO_FUNCTIONS_MAP[sensor['type']][instruction]
    if instruction == 'write':
        status = run_function( sensor['address'], data=data )
    else:
        if 'register' in sensor:
            ret = run_function(sensor['address'], register=sensor['register'] )
	    # analog sensors need to return, not just the value, but the min, max, and output transform.
	    status = str(ret) + " " + str(sensor['sensorMin']) + " " + str(sensor['sensorMax']) + " " + str(sensor['outputMax'])
        else:
            status = run_function(sensor['address'])
    #print("Status = " + str(status))
    return status




##
##
## Thread run() functions
def mqttManager():
    mqttc.loop_forever()

def commandManager():
    lcl = threading.local()
    while True:
        time.sleep(5)
        if len(messageQueue) != 0:
            with messageQueueLock:
                lcl.msg = messageQueue.popleft()
            if lcl.msg['sensor'] not in sensors:
                lcl.notice = "Received message for non-existant sensor: " + lcl.msg['sensor'] + "... Discarding."
                #print(lcl.notice)
                mqttc.publish(SYS_MESSAGE_QUEUE, payload=lcl.notice)
                continue
            if lcl.msg['action'] == 'control' and 'write' in sensors[lcl.msg['sensor']]['access']:
                if lcl.msg['msg'] == 'on':
                    with modbusQueueLock:
                        sensor_activity(sensors[lcl.msg['sensor']], 'write', 1)
                    sensors[lcl.msg['sensor']]['status'] = '1'
                    mqttc.publish(BASE + "/" + lcl.msg['sensor'] + "/status", payload='1')
                elif lcl.msg['msg'] == 'off':
                    with modbusQueueLock:
                        sensor_activity(sensors[lcl.msg['sensor']], 'write', 0)
                    sensors[lcl.msg['sensor']]['status'] = '0'
                    mqttc.publish(BASE + "/" + lcl.msg['sensor'] + "/status", payload='0')
                elif lcl.msg['msg'] == 'status':
                    mqttc.publish(BASE + "/" + lcl.msg['sensor'] + "/status", payload=str(sensors[lcl.msg['sensor']]['status']))
                else:
                    lcl.notice= "Received invalid instruction '" + lcl.msg['msg'] + "' for sensor: " + lcl.msg['sensor'] + "... Discarding."
                    mqttc.publish(SYS_MESSAGE_QUEUE, payload=lcl.notice)


def statusManager():
    lcl = threading.local()
    lcl.sensors_to_status = []

    print("Queueing Sensors for statusing...")
    for sensor in sensors:
        if 'status-update' in sensors[sensor]:
            lcl.sensors_to_status.append(sensor)
            print("  Added: " + str(sensor))

    while True:
        for sensor in lcl.sensors_to_status:
            with modbusQueueLock:
                lcl.status = sensor_activity(sensors[sensor], 'read')
            sensors[sensor]['status'] = lcl.status
            mqttc.publish(BASE + "/" + str(sensor) + "/status", payload=str(lcl.status) )
        time.sleep (STATUS_INTERVAL)
    

##
##
## Main
##

## Share Data
messageQueue = deque([])
messageQueueLock = threading.RLock()

modbusQueueLock = threading.RLock()



tMqttManager = threading.Thread(name='tMqttmanager', target=mqttManager)
tCommandManager = threading.Thread(name='tCommandManager', target=commandManager)
tStatusManager = threading.Thread(name='tStatusManager', target=statusManager)

tMqttManager.daemon = True
tCommandManager.daemon = True
tStatusManager.daemon = True


##
## Setup MQTT
print("Setting up MQTT handlers...")
try:
    from paho.mqtt.enums import CallbackAPIVersion
    mqttc = mqtt.Client(CallbackAPIVersion.VERSION1)
except ImportError:
    mqttc = mqtt.Client()
mqttc.on_connect = mqtt_on_connect
mqttc.on_message = mqtt_on_message
mqttc.on_disconnect = mqtt_on_disconnect
mqttc.connect(MQTT_SERVER)
mqttc.subscribe(SUB)

tMqttManager.start()
time.sleep(1)


##
## Setup ModBus
print("Setting up Modbus handlers...")
modbusHandle = ModbusClient(port=MODBUS_PORT, baudrate=MODBUS_BAUDRATE)
if modbusHandle.connect() == False:
    mqttc.publish(SYS_MESSAGE_QUEUE, payload="ERR_FATAL: Failed to start ModBus connection")
    exit()
else:
    print("ModBus Connection Established")


##
## Initialise sensor data structures
print("Initialising Sensors...")
for sensor in sensors:
    #print("{0}: {1}".format(sensor, sensors[sensor]['type']))
    with modbusQueueLock:
        sensor_activity(sensors[sensor], 'init')


##
## Starting Command Manager
print("Starting CommandManager Thread...")
tCommandManager.start()

##
## Kick off Status_manager
print("Starting StatusManager Thread...")
tStatusManager.start()

time.sleep(1)
print("Ready!")

while True:
    time.sleep(300)
    print("--MARK--")
