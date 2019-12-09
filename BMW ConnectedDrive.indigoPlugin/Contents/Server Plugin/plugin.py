#! /usr/bin/env python
# -*- coding: utf-8 -*-

import json
import logging
import requests
import time

from bmwcdapi import ConnectedDrive

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
        self.next_update = time.time() + self.updateFrequency
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
                
                    for devID, device in self.cd_vehicles.iteritems():
                        accountID = device.pluginProps["account"]
                        account = self.cd_accounts[int(accountID)]
                        results = account.queryData(device.address)
                        self.logger.debug(u"{}: runConcurrentThread, results = {}".format(device.name, results))        
             
                        states_list = []
                        for key in results:
                            states_list.append({'key': key.strip(), 'value': results[key]})
                        device.updateStatesOnServer(states_list)

                        
                self.sleep(2.0)

        except self.StopThread:
            self.logger.debug(u"runConcurrentThread ending")
            pass
                
    ########################################
                
    def deviceStartComm(self, dev):
        self.logger.info(u"{}: Starting {} Device {}".format(dev.name, dev.deviceTypeId, dev.id))
        dev.stateListOrDisplayStateIdChanged()

        if dev.deviceTypeId == "cdAccount":
                        
            cdAccount = ConnectedDrive(dev.pluginProps["username"],  dev.pluginProps["password"])
            self.cd_accounts[dev.id] = cdAccount
                                    
        elif dev.deviceTypeId == "cdVehicle":
            self.cd_vehicles[dev.id] = dev
            self.update_needed = True
            
        else:
            self.logger.error(u"{}: deviceStartComm: Unknown device type: {}".format(dev.name, dev.deviceTypeId))

            
    def deviceStopComm(self, dev):
        self.logger.info(u"{}: Stopping {} Device {}".format( dev.name, dev.deviceTypeId, dev.id))

    def didDeviceCommPropertyChange(self, oldDevice, newDevice):
        if oldDevice.address != newDevice.address:
            return True
        return False
            

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

    # doesn't do anything, just needed to force other menus to dynamically refresh
    def menuChanged(self, valuesDict = None, typeId = None, devId = None):
        return valuesDict
    
