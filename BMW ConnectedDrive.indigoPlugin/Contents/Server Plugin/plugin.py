#! /usr/bin/env python
# -*- coding: utf-8 -*-

import json
import logging
import requests
import time

from bmwcdapi import ConnectedDrive

def liters2gallons(l):
    return float(l) / 3.785411784

def km2miles(km):
    return float(km) * 0.62137
    
def no_convert(x):
    return x
 
def dict_to_states(prefix, the_dict, states_list):
     for key in the_dict:
        if isinstance(the_dict[key], list):
            list_to_states(u"{}{}_".format(prefix, key), the_dict[key], states_list)
        elif isinstance(the_dict[key], dict):
            dict_to_states(u"{}{}_".format(prefix, key), the_dict[key], states_list)
        elif the_dict[key]:
            states_list.append({'key': unicode(prefix + key.strip()), 'value': the_dict[key]})
        
   
def list_to_states(prefix, the_list, states_list):
     for i in range(len(the_list)):
        if isinstance(the_list[i], list):
            list_to_states(u"{}{}_".format(prefix, i), the_list[i], states_list)
        elif isinstance(the_list[i], dict):
            dict_to_states(u"{}{}_".format(prefix, i), the_list[i], states_list)
        else:
            states_list.append({'key': unicode(prefix + unicode(i)), 'value': the_list[i]})
   

status_format = {
    "us": {
        "chargingLevelHv":      (u"{}%", no_convert),
        "doorLockState":        (u"{}", no_convert),
        "fuelPercent":          (u"{}%", no_convert),
        "mileage":              (u"{:.0f} miles", km2miles),
        "remainingFuel":        (u"{:.1f} gal", liters2gallons),
        "remainingRangeFuel":   (u"{:.0f} mi", km2miles),
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

        self.cd_accounts = {}
        self.cd_vehicles = {}

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
                    self.update_needed = False
                    self.next_update = time.time() + self.updateFrequency
                
                    for accountID, account in self.cd_accounts.items():
                        if time.time() > account.next_refresh:
                            account.get_tokens()                    

                        if account.authenticated:
                            account.update_vehicles()
                            indigo.devices[accountID].updateStateImageOnServer(indigo.kStateImageSel.SensorOn)
                        else:
                            self.logger.debug("ConnectedDrive account {} not authenticated, skipping update".format(accountID))
                            indigo.devices[accountID].updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)

                    # now update all the Indigo devices         
                    
                    for devID in self.cd_vehicles:
                        self.updateVehicle(devID)
                       
                self.sleep(2.0)

        except self.StopThread:
            self.logger.debug(u"runConcurrentThread ending")
            pass
                
    ########################################
                
    def deviceStartComm(self, dev):
        self.logger.info(u"{}: Starting {} Device".format(dev.name, dev.deviceTypeId))

        if dev.deviceTypeId == "cdAccount":
                        
            self.cd_accounts[dev.id] = ConnectedDrive(dev.pluginProps["region"],  dev.pluginProps["username"],  dev.pluginProps["password"])
            dev.updateStateOnServer(key="authenticated", value=self.cd_accounts[dev.id].authenticated)
                                   
        elif dev.deviceTypeId == "cdVehicle":
            self.cd_vehicles[dev.id] = None
            self.update_needed = True
            
        else:
            self.logger.error(u"{}: deviceStartComm: Unknown device type: {}".format(dev.name, dev.deviceTypeId))

        dev.stateListOrDisplayStateIdChanged()
            
    def deviceStopComm(self, dev):
        self.logger.info(u"{}: Stopping {} Device {}".format( dev.name, dev.deviceTypeId, dev.id))

    def updateVehicle(self, vehicleID):

        device = indigo.devices[vehicleID]
        accountID = device.pluginProps["account"]
        account = self.cd_accounts[int(accountID)]
        states_list = []

        data_results = account.get_vehicle_data(device.address)             
        if data_results:
            try:
                dict_to_states(u"v_", data_results, states_list)      
            except:
                pass
                
        status_results = account.get_vehicle_status(device.address)             
        if status_results:       
            try:   
                dict_to_states(u"s_", status_results, states_list)   
                units = self.pluginPrefs.get('units', "us")
                state_key = device.pluginProps["state_key"]
                status_value = status_results[state_key]
                ui_format, converter = status_format[units][state_key]
                states_list.append({'key': 'status', 'value': status_value, 'uiValue': ui_format.format(converter(status_value))})
            except:
                pass
        self.cd_vehicles[device.id] = states_list
        device.stateListOrDisplayStateIdChanged()

        try:     
            device.updateStatesOnServer(states_list)
        except TypeError as err:
            self.logger.error(u"{}: invalid state type in states_list: {}".format(device.name, states_list))   
        

    
    ########################################
    #
    # callback for state list changes, called from stateListOrDisplayStateIdChanged()
    #
    ########################################
    def getDeviceStateList(self, device):
        state_list = indigo.PluginBase.getDeviceStateList(self, device)
#        self.logger.threaddebug(u"{}: getDeviceStateList, base state_list = {}".format(device.name, state_list))

        if device.id in self.cd_vehicles and self.cd_vehicles[device.id]:
            
            for item in self.cd_vehicles[device.id]:
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

#        self.logger.threaddebug(u"{}: getDeviceStateList, final state_list = {}".format(device.name, state_list))
        return state_list


    ########################################
    #
    # callbacks from device creation UI
    #
    ########################################

    def get_account_list(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.logger.threaddebug("get_account_list: typeId = {}, targetId = {}, filter = {}, valuesDict = {}".format(typeId, targetId, filter, valuesDict))
        retList = []
        for dev in indigo.devices.iter("self.cdAccount"):
            self.logger.threaddebug(u"get_account_list adding: {}".format(dev.name))         
            retList.append((dev.id, dev.name))
        retList.sort(key=lambda tup: tup[1])
        return retList

    def get_vehicle_list(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.logger.threaddebug("get_vehicle_list: typeId = {}, targetId = {}, valuesDict = {}".format(typeId, targetId, valuesDict))
        retList = []
        accountID = valuesDict.get('account', None)
        if not accountID:
            return retList
            
        account = self.cd_accounts[int(accountID)]
        vehicles = account.get_vehicles()
        for v in vehicles:
            retList.append((v['vin'], "{} {}".format(v['yearOfConstruction'], v['model'])))
        retList.sort(key=lambda tup: tup[1])            
        return retList

    def get_vehicle_state_list(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.logger.threaddebug("get_vehicle_state_list: typeId = {}, targetId = {}, valuesDict = {}".format(typeId, targetId, valuesDict))
        retList = []
        accountID = valuesDict.get('account', None)
        if not accountID:
            return retList
            
        account = self.cd_accounts[int(accountID)]
        vin = valuesDict.get('address', None)
        if not vin:
            return retList
            
        vehicle_status = account.get_vehicle_status(vin)
        for s in ['chargingLevelHv', 'fuelPercent', 'mileage', 'remainingFuel', 'remainingRangeFuel', 'doorLockState']:
            if s in vehicle_status:
                retList.append((s, s))
        retList.sort(key=lambda tup: tup[1])            
        return retList

    # doesn't do anything, just needed to force other menus to dynamically refresh
    def menuChanged(self, valuesDict = None, typeId = None, devId = None):
        return valuesDict
    
    def menuDumpVehicles(self):
        self.logger.debug(u"menuDumpVehicles")
        for accountID, account in self.cd_accounts.items():
            account.dump_data()
        return True

