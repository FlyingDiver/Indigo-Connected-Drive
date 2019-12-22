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
                        else:
                            self.logger.debug("ConnectedDrive account {} not authenticated, skipping update".format(accountID))

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
                                    
        elif dev.deviceTypeId == "cdVehicle":
            self.cd_vehicles[dev.id] = dev
            self.update_needed = True
            
        else:
            self.logger.error(u"{}: deviceStartComm: Unknown device type: {}".format(dev.name, dev.deviceTypeId))

        dev.stateListOrDisplayStateIdChanged()

            
    def deviceStopComm(self, dev):
        self.logger.info(u"{}: Stopping {} Device {}".format( dev.name, dev.deviceTypeId, dev.id))

    def didDeviceCommPropertyChange(self, oldDevice, newDevice):
        if oldDevice.address != newDevice.address:
            return True
        return False
            
    # =============================================================================
    def getDeviceStateList(self, dev):
        """
        Assign data keys to device state names (Indigo)

        The getDeviceStateList() method pulls out all the keys in self.finalDict and
        assigns them to device states. It returns the modified stateList which is then
        written back to the device in the main thread. This method is automatically
        called by

            stateListOrDisplayStateIdChanged()

        and by Indigo when Triggers and Control Pages are built. Note that it's not
        possible to override Indigo's sorting of devices states which will present them
        as A, B, a, b.

        -----

        :param dev:
        :return state_list:
        """
        
        state_list = indigo.PluginBase.getDeviceStateList(self, dev)
        self.logger.debug(u"{}: getDeviceStateList, base state_list = {}".format(dev.name, state_list))

#        if dev.id in self.cd_vehicles.keys():
#            for key in sorted(self.cd_vehicles[dev.id].finalDict.keys()):
#                dynamic_state = self.getDeviceStateDictForStringType(unicode(key), unicode(key), unicode(key))
#                state_list.append(dynamic_state)

        self.logger.debug(u"{}: getDeviceStateList, final state_list = {}".format(dev.name, state_list))
        return state_list


    def updateVehicle(self, vehicleID):

        device = indigo.devices[vehicleID]
        accountID = device.pluginProps["account"]
        account = self.cd_accounts[int(accountID)]
        states_list = []
        results = account.get_vehicle_status(device.address)             
        self.logger.threaddebug(u"{}: get_vehicle_status for {} =\n{}".format(device.name, device.address, results))        
        for key in results:
            self.logger.threaddebug(u"{}: get_vehicle_status adding key {}".format(device.name, key))        
            if key in ['DCS_CCH_Activation', 'DCS_CCH_Ongoing', 'cbsData', 'checkControlMessages', 'vin']:
                continue
            elif key == 'position':
                try:
                    states_list.append({'key': 'gps_heading', 'value': results[key]['heading']})
                    states_list.append({'key': 'gps_lat', 'value': results[key]['lat']})
                    states_list.append({'key': 'gps_lon', 'value': results[key]['lon']})   
                except:
                    self.logger.debug("Position key error, skipping gps states: {}".format(results[key]))
                                     
            else:
                states_list.append({'key': key.strip(), 'value': results[key]})

        results = account.get_vehicle_data(device.address)             
        self.logger.threaddebug(u"{}: get_vehicle_data for {} =\n{}".format(device.name, device.address, results))        
        for key in results:
            self.logger.threaddebug(u"{}: get_vehicle_data adding key {}".format(device.name, key))        
            if key in ['breakdownNumber', 'dealer', 'vin']:
                continue
            else:
                states_list.append({'key': key.strip(), 'value': results[key]})
    
        device.updateStatesOnServer(states_list)
        self.logger.debug(u"{}: states updated".format(device.name))        


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

    # doesn't do anything, just needed to force other menus to dynamically refresh
    def menuChanged(self, valuesDict = None, typeId = None, devId = None):
        return valuesDict
    
    def menuDumpVehicles(self):
        self.logger.debug(u"menuDumpVehicles")
        for accountID, account in self.cd_accounts.items():
            account.dump_data()
        return True

