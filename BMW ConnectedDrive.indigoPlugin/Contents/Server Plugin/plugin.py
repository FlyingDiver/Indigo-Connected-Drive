#! /usr/bin/env python
# -*- coding: utf-8 -*-

import indigo
import json
import logging
import requests
import time
import asyncio

from aiohttp import ClientSession
from bimmer_connected.account import ConnectedDriveAccount
from bimmer_connected.country_selector import get_region_from_name, valid_regions
from bimmer_connected.vehicle import VehicleViewDirection


def liters2gallons(liters):
    return float(liters) / 3.785411784


def km2miles(km):
    return float(km) * 0.62137


def no_convert(x):
    return x


def dict_to_states(prefix, the_dict, states_list, skips=None):
    for key in the_dict:
        if skips and key in skips:
            continue
        if isinstance(the_dict[key], list):
            list_to_states(f"{prefix}{key}_", the_dict[key], states_list, skips)
        elif isinstance(the_dict[key], dict):
            dict_to_states(f"{prefix}{key}_", the_dict[key], states_list, skips)
        elif the_dict[key]:
            states_list.append({'key': unicode(prefix + key.strip()), 'value': the_dict[key]})


def list_to_states(prefix, the_list, states_list, skips=None):
    for i in range(len(the_list)):
        if isinstance(the_list[i], list):
            list_to_states(f"{prefix}{i}_", the_list[i], states_list, skips)
        elif isinstance(the_list[i], dict):
            dict_to_states(f"{prefix}{i}_", the_list[i], states_list, skips)
        else:
            states_list.append({'key': unicode(prefix + unicode(i)), 'value': the_list[i]})


status_format = {
    "us": {
        "chargingLevelHv": (u"{}%", no_convert),
        "doorLockState": (u"{}", no_convert),
        "fuelPercent": (u"{}%", no_convert),
        "mileage": (u"{:.0f} miles", km2miles),
        "remainingFuel": (u"{:.1f} gal", liters2gallons),
        "remainingRangeFuelMls": (u"{:.0f} mi", no_convert),
    },
    "metric": {
        "chargingLevelHv": (u"{}%", no_convert),
        "doorLockState": (u"{}", no_convert),
        "fuelPercent": (u"{}%", no_convert),
        "mileage": (u"{} km", no_convert),
        "remainingFuel": (u"{} ltrs", no_convert),
        "remainingRangeFuel": (u"{} km", no_convert),
    }
}


async def get_status(username, password, region):
    account = ConnectedDriveAccount(username, password, get_region_from_name(region))
    account.update_vehicle_states()
    return account.vehicles


def light_flash(username, password, region, vin):
    account = ConnectedDriveAccount(username, password, get_region_from_name(region))
    vehicle = account.get_vehicle(vin)
    if not vehicle:
        return None
    status = vehicle.remote_services.trigger_remote_light_flash()
    return status.state


def door_lock(username, password, region, vin):
    account = ConnectedDriveAccount(username, password, get_region_from_name(region))
    vehicle = account.get_vehicle(vin)
    if not vehicle:
        return None
    status = vehicle.remote_services.trigger_remote_door_lock()
    return status.state


def door_unlock(username, password, region, vin):
    account = ConnectedDriveAccount(username, password, get_region_from_name(region))
    vehicle = account.get_vehicle(vin)
    if not vehicle:
        return None
    status = vehicle.remote_services.trigger_remote_door_unlock()
    return status.state


def horn(username, password, region, vin):
    account = ConnectedDriveAccount(username, password, get_region_from_name(region))
    vehicle = account.get_vehicle(vin)
    if not vehicle:
        return None
    status = vehicle.remote_services.trigger_remote_horn()
    return status.state


def air_conditioning(username, password, region, vin):
    account = ConnectedDriveAccount(username, password, get_region_from_name(region))
    vehicle = account.get_vehicle(vin)
    if not vehicle:
        return None
    status = vehicle.remote_services.trigger_remote_air_conditioning()
    return status.state


def send_message(username, password, region, vin, subject, text):
    """Send a message to car."""
    account = ConnectedDriveAccount(username, password, get_region_from_name(region))
    vehicle = account.get_vehicle(vin)
    msg_data = dict(
        text=text,
        subject=subject
    )
    vehicle.remote_services.trigger_send_message(msg_data)


class Plugin(indigo.PluginBase):

    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)
        self.pluginPrefs = pluginPrefs

        pfmt = logging.Formatter('%(asctime)s.%(msecs)03d\t[%(levelname)8s] %(name)20s.%(funcName)-25s%(msg)s', datefmt='%Y-%m-%d %H:%M:%S')
        self.plugin_file_handler.setFormatter(pfmt)
        self.logLevel = int(self.pluginPrefs.get("logLevel", logging.INFO))
        self.indigo_log_handler.setLevel(self.logLevel)
        self.logger.debug(f"logLevel = {self.logLevel}")

        self.updateFrequency = float(self.pluginPrefs.get('updateFrequency', "30")) * 60.0
        self.logger.debug(f"updateFrequency = {self.updateFrequency}")
        self.next_update = time.time()
        self.update_needed = False

        self.bridge_data = {}
        self.wrappers = {}
        self.read_threads = {}

        self.cd_accounts = {}
        self.cd_vehicles = {}
        self.vehicle_data = {}
        self.vehicle_states = {}

    def startup(self):
        self.logger.info("Starting Connected Drive")

    def shutdown(self):
        self.logger.info("Stopping Connected Drive")

    @staticmethod
    def validatePrefsConfigUi(valuesDict):
        errorDict = indigo.Dict()
        updateFrequency = int(valuesDict.get('updateFrequency', 15))
        if (updateFrequency < 5) or (updateFrequency > 60):
            errorDict['updateFrequency'] = "Update frequency is invalid - enter a valid number (between 5 and 60)"
        if len(errorDict) > 0:
            return False, valuesDict, errorDict
        return True

    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        if not userCancelled:
            self.logLevel = int(valuesDict.get("logLevel", logging.INFO))
            self.indigo_log_handler.setLevel(self.logLevel)
            self.updateFrequency = float(valuesDict['updateFrequency']) * 60.0
            self.next_update = time.time()
            self.logger.debug(f"closedPrefsConfigUi, logLevel = {self.logLevel}, updateFrequency = {self.updateFrequency}")

    ########################################

    def runConcurrentThread(self):
        try:
            while True:
                if (time.time() > self.next_update) or self.update_needed:
                    self.next_update = time.time() + self.updateFrequency
                    self.update_needed = False

                    cmd = {'cmd': 'vehicles'}
                    for devID in self.wrappers:
                        self.wrapper_write(indigo.devices[devID].id, cmd)
                self.sleep(1.0)
        except self.StopThread:
            pass

    ################################################################################

    def deviceStartComm(self, device):
        self.logger.info(f"{device.name}: Starting {device.deviceTypeId} Device")

        if device.deviceTypeId == "cdAccount":
            self.cd_accounts[device.id] = device.name

        elif device.deviceTypeId == "cdVehicle":
            self.cd_vehicles[device.address] = device.id
            self.update_needed = True

        else:
            self.logger.error(f"{device.name}: deviceStartComm: Unknown device type: {device.deviceTypeId}")

        device.stateListOrDisplayStateIdChanged()

    def deviceStopComm(self, device):
        self.logger.info(f"{device.name}: Stopping {device.deviceTypeId} Device {device.id}")

    def sendCommandAction(self, pluginAction, vehicleDevice, callerWaitingForResult):
        self.logger.debug(f"{vehicleDevice.name}: sendCommandAction {pluginAction.props['serviceCode']}")
        accountID = self.vehicle_data[vehicleDevice.address]['account']
        cmd = {'cmd': pluginAction.props["serviceCode"]}
        self.wrapper_write(accountID, cmd)

        self.logger.threaddebug(f"{acctDevice.name}: Received wrapper message:\n{json.dumps(data, sort_keys=True, indent=4, separators=(',', ': '))}")

        self.logger.debug("{}: Vehicle data message for: {}".format(acctDevice.name, data['vin']))

        # save the data
        self.vehicle_data[data['vin']] = {'account': acctDevID, 'properties': data['properties'], 'status': data['status']}

        # If there's an Indigo device for this vehicle, update it

        vehicleDevID = self.cd_vehicles.get(data['vin'], None)
        if not vehicleDevID:
            return
        vehicleDevice = indigo.devices.get(int(vehicleDevID), None)
        if not vehicleDevice:
            return

        states_list = []
        if data['status']:
            units = self.pluginPrefs.get('units', "us")
            state_key = vehicleDevice.pluginProps["state_key"]
            status_value = data['status'][state_key]
            ui_format, converter = status_format[units][state_key]
            states_list.append({'key': 'status', 'value': status_value, 'uiValue': ui_format.format(converter(status_value))})

            try:
                dict_to_states(u"", data['status'], states_list, skips=['DCS_CCH_Activation', 'DCS_CCH_Ongoing', 'cbsData'])
            except (Exception,):
                self.logger.debug(f"{acctDevice.name}: Error converting status to states for {data['vin']}")
                pass

        self.vehicle_states[vehicleDevice.id] = states_list

        try:
            vehicleDevice.stateListOrDisplayStateIdChanged()
            vehicleDevice.updateStatesOnServer(states_list)
        except TypeError as err:
            self.logger.error(f"{vehicleDevice.name}: invalid state type in states_list: {states_list}")

    #######################################
    # callback for state list changes, called from stateListOrDisplayStateIdChanged()
    #######################################
    def getDeviceStateList(self, device):
        state_list = indigo.PluginBase.getDeviceStateList(self, device)

        if device.id in self.vehicle_states and self.vehicle_states[device.id]:
            for item in self.vehicle_states[device.id]:
                key = item['key']
                value = item['value']
                if isinstance(value, bool):
                    dynamic_state = self.getDeviceStateDictForBoolTrueFalseType(unicode(key), unicode(key), unicode(key))
                    self.logger.threaddebug(f"{device.name}: getDeviceStateList, adding Bool state {key}, value {value}")
                elif isinstance(value, (float, int)):
                    dynamic_state = self.getDeviceStateDictForNumberType(unicode(key), unicode(key), unicode(key))
                    self.logger.threaddebug(f"{device.name}: getDeviceStateList, adding Number state {key}, value {value}")
                elif isinstance(value, (str, unicode)):
                    dynamic_state = self.getDeviceStateDictForStringType(unicode(key), unicode(key), unicode(key))
                    self.logger.threaddebug(f"{device.name}: getDeviceStateList, adding String state {key}, value {value}")
                else:
                    self.logger.debug(f"{device.name}: getDeviceStateList, unknown type for key = {key}, value {value}")
                    continue
                state_list.append(dynamic_state)
        return state_list

    ########################################
    #
    # callbacks from device creation UI
    #
    ########################################

    def get_vehicle_list(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.logger.threaddebug(f"get_vehicle_list: typeId = {typeId}, targetId = {targetId}, valuesDict = {valuesDict}")
        retList = []

        for v in self.vehicle_data.values():
            retList.append((v['properties']['vin'], f"{v['properties']['yearOfConstruction']} {v['properties']['model']}"))
        retList.sort(key=lambda tup: tup[1])
        return retList

    def get_vehicle_state_list(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.logger.threaddebug(f"get_vehicle_state_list: typeId = {typeId}, targetId = {targetId}, valuesDict = {valuesDict}")
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
    @staticmethod
    def menuChanged(valuesDict=None, typeId=None, devId=None):
        return valuesDict

    def menuDumpVehicles(self):
        for vin in self.vehicle_data:
            self.logger.info(f"Data for VIN {vin}:\n{json.dumps(self.vehicle_data[vin], sort_keys=True, indent=4, separators=(',', ': '))}")
        return True
