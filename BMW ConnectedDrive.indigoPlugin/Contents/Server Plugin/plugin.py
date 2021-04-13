#! /usr/bin/env python
# -*- coding: utf-8 -*-

import json
import logging
import requests
import time

from subprocess import Popen, PIPE
from threading import Thread


def liters2gallons(l):
    return float(l) / 3.785411784

def km2miles(km):
    return float(km) * 0.62137
    
def no_convert(x):
    return x
 
def dict_to_states(prefix, the_dict, states_list, skips=None):
     for key in the_dict:
        if skips and key in skips:
            continue
        if isinstance(the_dict[key], list):
            list_to_states(u"{}{}_".format(prefix, key), the_dict[key], states_list, skips)
        elif isinstance(the_dict[key], dict):
            dict_to_states(u"{}{}_".format(prefix, key), the_dict[key], states_list, skips)
        elif the_dict[key]:
            states_list.append({'key': unicode(prefix + key.strip()), 'value': the_dict[key]})
        
   
def list_to_states(prefix, the_list, states_list, skips=None):
     for i in range(len(the_list)):
        if isinstance(the_list[i], list):
            list_to_states(u"{}{}_".format(prefix, i), the_list[i], states_list, skips)
        elif isinstance(the_list[i], dict):
            dict_to_states(u"{}{}_".format(prefix, i), the_list[i], states_list, skips)
        else:
            states_list.append({'key': unicode(prefix + unicode(i)), 'value': the_list[i]})
   

status_format = {
    "us": {
        "chargingLevelHv":          (u"{}%", no_convert),
        "doorLockState":            (u"{}", no_convert),
        "fuelPercent":              (u"{}%", no_convert),
        "mileage":                  (u"{:.0f} miles", km2miles),
        "remainingFuel":            (u"{:.1f} gal", liters2gallons),
        "remainingRangeFuelMls":    (u"{:.0f} mi", no_convert),
    },
    "metric": {
        "chargingLevelHv":      (u"{}%", no_convert),
        "doorLockState":        (u"{}", no_convert),
        "fuelPercent":          (u"{}%", no_convert),
        "mileage":              (u"{} km", no_convert),
        "remainingFuel":        (u"{} ltrs", no_convert),
        "remainingRangeFuel":   (u"{} km", no_convert),
    }
}
        
   
class Plugin(indigo.PluginBase):

    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)
        pfmt = logging.Formatter('%(asctime)s.%(msecs)03d\t[%(levelname)8s] %(name)20s.%(funcName)-25s%(msg)s', datefmt='%Y-%m-%d %H:%M:%S')
        self.plugin_file_handler.setFormatter(pfmt)

        try:
            self.logLevel = int(self.pluginPrefs[u"logLevel"])
        except:
            self.logLevel = logging.INFO
        self.indigo_log_handler.setLevel(self.logLevel)
        self.logger.debug(u"logLevel = {}".format(self.logLevel))
        self.bridge_data ={}
        
    def startup(self):
        self.logger.info(u"Starting Connected Drive")
                
        self.updateFrequency = float(self.pluginPrefs.get('updateFrequency', "30")) *  60.0
        self.logger.debug(u"updateFrequency = {}".format(self.updateFrequency))
        self.next_update = time.time()
        self.update_needed = False

        self.wrappers = {}
        self.read_threads = {}
        
        self.cd_accounts = {}
        self.cd_vehicles = {}
        self.vehicle_data = {}
        self.vehicle_states = {}

    def shutdown(self):
        self.logger.info(u"Stopping Connected Drive")
        
    def validatePrefsConfigUi(self, valuesDict):
        self.logger.debug(u"validatePrefsConfigUi called")
        errorDict = indigo.Dict()

        updateFrequency = int(valuesDict['updateFrequency'])
        if (updateFrequency < 5) or (updateFrequency > 60):
            errorDict['updateFrequency'] = u"Update frequency is invalid - enter a valid number (between 5 and 60)"

        if len(errorDict) > 0:
            return (False, valuesDict, errorDict)

        return True
        
    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        if not userCancelled:
            try:
                self.logLevel = int(valuesDict[u"logLevel"])
            except:
                self.logLevel = logging.INFO
            self.indigo_log_handler.setLevel(self.logLevel)

            self.updateFrequency = float(valuesDict['updateFrequency']) * 60.0
            self.next_update = time.time()

            self.logger.debug(u"closedPrefsConfigUi, logLevel = {}, updateFrequency = {}".format(self.logLevel, self.updateFrequency))        

    ########################################
        
    def runConcurrentThread(self):
        self.logger.debug(u"runConcurrentThread starting")
        try:
            while True:
                
                if (time.time() > self.next_update) or self.update_needed:
                    self.next_update = time.time() + self.updateFrequency
                    self.update_needed = False
                    
                    # request update from each CD account
                    cmd = {'cmd': 'vehicles'} 
                    for devID in self.wrappers:
                        self.wrapper_write(indigo.devices[devID].id, cmd)

                self.sleep(1.0)

        except self.StopThread:
            self.logger.debug(u"runConcurrentThread ending")
            pass
                
################################################################################

    def wrapper_write(self, deviceID, msg):
        jsonMsg = json.dumps(msg)
        self.logger.threaddebug(u"Send wrapper message: {}".format(jsonMsg))
        self.wrappers[deviceID].stdin.write(u"{}\n".format(jsonMsg))


    def wrapper_read(self, acctDevID):
        wrapper = self.wrappers[acctDevID]
        while True:
            msg = wrapper.stdout.readline()
            acctDevice = indigo.devices[acctDevID]
            try:
                data = json.loads(msg)
            except:
                self.logger.debug(u"wrapper_read JSON decode error: {}".format(msg))
                return
                
            self.logger.threaddebug(u"{}: Received wrapper message:\n{}".format(acctDevice.name, json.dumps(data, sort_keys=True, indent=4, separators=(',', ': '))))

            if data['msg'] == 'echo':
                pass    
                
            elif data['msg'] == 'status':
                self.logger.debug("{}: {}".format(acctDevice.name, data['status']))
                acctDevice.updateStateOnServer(key="status", value=data['status'])
                
            elif data['msg'] == 'error':
                self.logger.error("{}: {}".format(acctDevice.name, data['error']))
                acctDevice.updateStateOnServer(key="status", value="Error")

            elif data['msg'] == 'vehicle':
                self.logger.debug("{}: Vehicle data message for: {}".format(acctDevice.name, data['vin']))

                # save the data
                self.vehicle_data[data['vin']] = {'account': acctDevID, 'properties': data['properties'], 'status': data['status']}
                
                # If there's an Indigo device for this vehicle, update it
                
                vehicleDevID = self.cd_vehicles.get(data['vin'], None)
                if not vehicleDevID:
                    continue       
                vehicleDevice = indigo.devices.get(int(vehicleDevID), None)
                if not vehicleDevice:
                    continue
                    
                states_list = []                
                if data['status']:       
                    units = self.pluginPrefs.get('units', "us")
                    state_key = vehicleDevice.pluginProps["state_key"]
                    status_value = data['status'][state_key]
                    ui_format, converter = status_format[units][state_key]
                    states_list.append({'key': 'status', 'value': status_value, 'uiValue': ui_format.format(converter(status_value))})

                    try:   
                        dict_to_states(u"", data['status'], states_list, skips=['DCS_CCH_Activation', 'DCS_CCH_Ongoing', 'cbsData'])   
                    except:
                        self.logger.debug("{}: Error converting status to states for {}".format(acctDevice.name, data['vin']))
                        pass
                    
                self.vehicle_states[vehicleDevice.id] = states_list

                try:     
                    vehicleDevice.stateListOrDisplayStateIdChanged()
                    vehicleDevice.updateStatesOnServer(states_list)
                except TypeError as err:
                    self.logger.error(u"{}: invalid state type in states_list: {}".format(vehicleDevice.name, states_list))   
        

           
            else:
                self.logger.error("{}: Unknown Message type '{}'".format(acctDevice.name, data['msg']))
               

    ########################################

    def getDeviceConfigUiValues(self, pluginProps, typeId, devId):
        self.logger.debug(u"getDeviceConfigUiValues, typeId = {}, devId = {}, pluginProps = {}".format(typeId, devId, pluginProps))
        valuesDict = pluginProps
        errorMsgDict = indigo.Dict()

        return (valuesDict, errorMsgDict)
             

    def deviceStartComm(self, device):
        self.logger.info(u"{}: Starting {} Device".format(device.name, device.deviceTypeId))

        if device.deviceTypeId == "cdAccount":
            self.cd_accounts[device.id] = device.name        
            
            try:
                # Start up the wrapper task   
#                argList = [self.pluginPrefs.get("py3path", "/usr/bin/python3"), './wrapper.py', device.pluginProps['username'], device.pluginProps['password'], device.pluginProps['region']] 
#                self.logger.debug(u"{}: deviceStartComm, argList = {}".format(device.name, argList))
#                self.wrappers[device.id] = Popen(argList, stdin=PIPE, stdout=PIPE, close_fds=True, bufsize=1, universal_newlines=True)
                
                argList = ['/bin/bash', '-c', "source .venv/bin/activate && python ./wrapper.py {} {} {}".format(device.pluginProps['username'], device.pluginProps['password'], device.pluginProps['region'])]
                self.wrappers[device.id] = Popen(argList, stdin=PIPE, stdout=PIPE, shell=False, close_fds=True, bufsize=1, universal_newlines=True)


            except:
                raise

            self.read_threads[device.id] = Thread(target=self.wrapper_read, args=(device.id,))            
            self.read_threads[device.id].daemon = True
            self.read_threads[device.id].start()
                                
        elif device.deviceTypeId == "cdVehicle":
            self.cd_vehicles[device.address] = device.id
            self.update_needed = True
            
        else:
            self.logger.error(u"{}: deviceStartComm: Unknown device type: {}".format(device.name, device.deviceTypeId))

        device.stateListOrDisplayStateIdChanged()
            
    def deviceStopComm(self, device):
        self.logger.info(u"{}: Stopping {} Device {}".format( device.name, device.deviceTypeId, device.id))

        if device.deviceTypeId == "cdAccount":
            self.wrappers[device.id].terminate()

    
    ########################################
    #
    # callback for state list changes, called from stateListOrDisplayStateIdChanged()
    #
    ########################################
    def getDeviceStateList(self, device):
        state_list = indigo.PluginBase.getDeviceStateList(self, device)

        if device.id in self.vehicle_states and self.vehicle_states[device.id]:
            
            for item in self.vehicle_states[device.id]:
                key = item['key']
                value = item['value']
                if isinstance(value, bool):
                    dynamic_state = self.getDeviceStateDictForBoolTrueFalseType(unicode(key), unicode(key), unicode(key))
                    self.logger.threaddebug(u"{}: getDeviceStateList, adding Bool state {}, value {}".format(device.name, key, value))
                elif isinstance(value, (float, int)):
                    dynamic_state = self.getDeviceStateDictForNumberType(unicode(key), unicode(key), unicode(key))
                    self.logger.threaddebug(u"{}: getDeviceStateList, adding Number state {}, value {}".format(device.name, key, value))
                elif isinstance(value, (str, unicode)):
                    dynamic_state = self.getDeviceStateDictForStringType(unicode(key), unicode(key), unicode(key))
                    self.logger.threaddebug(u"{}: getDeviceStateList, adding String state {}, value {}".format(device.name, key, value))
                else:
                    self.logger.debug(u"{}: getDeviceStateList, unknown type for key = {}, value {}".format(device.name, key, value))
                    continue
                    
                state_list.append(dynamic_state)

        return state_list


    ########################################
    #
    # callbacks from device creation UI
    #
    ########################################

    def get_vehicle_list(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.logger.threaddebug("get_vehicle_list: typeId = {}, targetId = {}, valuesDict = {}".format(typeId, targetId, valuesDict))
        retList = []
            
        for v in self.vehicle_data.values():
            retList.append((v['properties']['vin'], "{} {}".format(v['properties']['yearOfConstruction'], v['properties']['model'])))
        retList.sort(key=lambda tup: tup[1])            
        return retList

    def get_vehicle_state_list(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.logger.threaddebug("get_vehicle_state_list: typeId = {}, targetId = {}, valuesDict = {}".format(typeId, targetId, valuesDict))
        retList = []
            
        vin = valuesDict.get('address', None)
        if not vin:
            return retList
            
        vehicle_status = self.vehicle_data[vin]['status']
        for s in ['chargingLevelHv', 'fuelPercent', 'mileage', 'remainingFuel', 'remainingRangeFuel', 'doorLockState']:
            if s in vehicle_status:
                retList.append((s, s))
        retList.sort(key=lambda tup: tup[1])            
        return retList

    # doesn't do anything, just needed to force other menus to dynamically refresh
    def menuChanged(self, valuesDict = None, typeId = None, devId = None):
        return valuesDict
    
    def menuDumpVehicles(self):
        for vin in self.vehicle_data:
            self.logger.info(u"Data for VIN {}:\n{}".format(vin, json.dumps(self.vehicle_data[vin], sort_keys=True, indent=4, separators=(',', ': '))))
        return True


    def sendCommandAction(self, pluginAction, vehicleDevice, callerWaitingForResult):
        self.logger.debug(u"{}: sendCommandAction {} for vin {}".format(vehicleDevice.name, pluginAction.props["serviceCode"], vehicleDevice.address))
        accountID = self.vehicle_data[vehicleDevice.address]['account']
        cmd = {'cmd': pluginAction.props["serviceCode"], 'vin': vehicleDevice.address} 
        self.wrapper_write(accountID, cmd)


