#! /usr/bin/env python
# -*- coding: utf-8 -*-

import indigo
import json
import logging
import requests
import time

import asyncio

try:
    from bimmer_connected.account import ConnectedDriveAccount
    from bimmer_connected.country_selector import get_region_from_name, valid_regions
    from bimmer_connected.vehicle import VehicleViewDirection
except ImportError:
    raise ImportError("'bimmer_connected' library missing.  Run 'pip3 install bimmer_connected' in Terminal window")

try:
    from aiohttp import ClientSession
except ImportError:
    raise ImportError("'aiohttp' library missing.  Run 'pip3 install aiohttp' in Terminal window")

def liters2gallons(liters):
    return float(liters) / 3.785411784


def km2miles(km):
    return float(km) * 0.62137


def no_convert(x):
    return x


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


async def get_account(username, password, region):
    account = ConnectedDriveAccount(username, password, get_region_from_name(region))
    return account


async def light_flash(username, password, region, vin):
    account = ConnectedDriveAccount(username, password, get_region_from_name(region))
    vehicle = account.get_vehicle(vin)
    if not vehicle:
        return None
    status = vehicle.remote_services.trigger_remote_light_flash()
    return status.state


async def door_lock(username, password, region, vin):
    account = ConnectedDriveAccount(username, password, get_region_from_name(region))
    vehicle = account.get_vehicle(vin)
    if not vehicle:
        return None
    status = vehicle.remote_services.trigger_remote_door_lock()
    return status.state


async def door_unlock(username, password, region, vin):
    account = ConnectedDriveAccount(username, password, get_region_from_name(region))
    vehicle = account.get_vehicle(vin)
    if not vehicle:
        return None
    status = vehicle.remote_services.trigger_remote_door_unlock()
    return status.state


async def horn(username, password, region, vin):
    account = ConnectedDriveAccount(username, password, get_region_from_name(region))
    vehicle = account.get_vehicle(vin)
    if not vehicle:
        return None
    status = vehicle.remote_services.trigger_remote_horn()
    return status.state


async def air_conditioning(username, password, region, vin):
    account = ConnectedDriveAccount(username, password, get_region_from_name(region))
    vehicle = account.get_vehicle(vin)
    if not vehicle:
        return None
    status = vehicle.remote_services.trigger_remote_air_conditioning()
    return status.state


async def send_message(username, password, region, vin, subject, text):
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
        self.logLevel = int(pluginPrefs.get("logLevel", logging.INFO))
        self.indigo_log_handler.setLevel(self.logLevel)
        self.logger.debug(f"logLevel = {self.logLevel}")

        self.updateFrequency = float(pluginPrefs.get('updateFrequency', "30")) * 60.0
        self.logger.debug(f"updateFrequency = {self.updateFrequency}")
        self.next_update = time.time() + self.updateFrequency

        self.units = pluginPrefs.get('units', "us")

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
                if time.time() > self.next_update:
                    self.next_update = time.time() + self.updateFrequency

                    for acctDevID in self.cd_accounts.keys():
                        self._do_update(indigo.devices[acctDevID])

                self.sleep(1.0)
        except self.StopThread:
            pass

    ################################################################################

    def deviceStartComm(self, device):
        self.logger.info(f"{device.name}: Starting {device.deviceTypeId} Device")

        if device.deviceTypeId == "cdAccount":
            self.cd_accounts[device.id] = device.name
            self._do_update(device)
            self.logger.info(f"{device.name}: {len(self.vehicle_data)} vehicles found.")

        elif device.deviceTypeId == "cdVehicle":
            self.cd_vehicles[device.address] = device.id

        else:
            self.logger.error(f"{device.name}: deviceStartComm: Unknown device type: {device.deviceTypeId}")

        device.stateListOrDisplayStateIdChanged()

    def deviceStopComm(self, device):
        self.logger.info(f"{device.name}: Stopping {device.deviceTypeId} Device {device.id}")

    def _do_update(self, cd_account):
        self.logger.debug(f"{cd_account.name}: Starting Update")

        account = asyncio.run(get_account(cd_account.pluginProps['username'], cd_account.pluginProps['password'], cd_account.pluginProps['region']))
        account.update_vehicle_states()

        for vehicle in account.vehicles:
            self.logger.debug(f"{cd_account.name}: Updating {vehicle.name} ({vehicle.vin})")

            # clean up the non=serializable data
            vehicle_dict = vehicle.as_dict()
            del vehicle_dict['status']
            status_dict = vehicle.status.as_dict()
            del status_dict['condition_based_services']
            del status_dict['lids']
            del status_dict['windows']
            del status_dict['timestamp']

            self.vehicle_data[vehicle.vin] = {'account': cd_account.id,
                                              'vehicle': vehicle_dict,
                                              'status': status_dict,
                                              }

            # If there's an Indigo device for this vehicle, update it

            vehicleDevID = self.cd_vehicles.get(vehicle.vin, None)
            if not vehicleDevID:
                self.logger.debug(f"{cd_account.name}: VIN not found: {vehicle.vin}")
                return
            vehicleDevice = indigo.devices.get(int(vehicleDevID), None)
            if not vehicleDevice:
                self.logger.debug(f"{cd_account.name}: Indigo device for vehicleDevID not found: {vehicleDevID}")
                return

            self.logger.debug(f"{cd_account.name}: Updating device {vehicleDevice.name} ({vehicleDevice.id})")

            states_list = [{'key': 'name', 'value': vehicle.name},
                           {'key': 'vin', 'value': vehicle.vin},
                           {'key': 'model', 'value': vehicle.model},
                           {'key': 'year', 'value': vehicle.year},
                           {'key': 'brand', 'value': vehicle.brand},
                           {'key': 'driveTrain', 'value': vehicle.driveTrain},
                           {'key': 'all_lids_closed', 'value': vehicle.all_lids_closed},
                           {'key': 'all_windows_closed', 'value': vehicle.all_windows_closed},
                           {'key': 'all_doors_locked', 'value': vehicle.door_lock_state == "LOCKED"},

                           {'key': 'fuel_percent', 'value': vehicle.fuel_percent},
                           ]

            self.vehicle_states[vehicleDevice.id] = states_list

            try:
                vehicleDevice.stateListOrDisplayStateIdChanged()
                vehicleDevice.updateStatesOnServer(states_list)
            except TypeError as err:
                self.logger.error(f"{vehicleDevice.name}: invalid state type in states_list: {states_list}")

    def get_vehicle_list(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.logger.threaddebug(f"get_vehicle_list: typeId = {typeId}, targetId = {targetId}, valuesDict = {valuesDict}")
        retList = []

        for v in self.vehicle_data.values():
            retList.append((v['vehicle']['attributes']['vin'], f"{v['vehicle']['attributes']['year']} {v['vehicle']['attributes']['model']}"))
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

    def fetchVehicleDataAction(self, action, device, callerWaitingForResult):
        vin = action.props["vin"]
        try:
            return json.dumps(self.vehicle_data[vin])
        except (Exception,):
            return json.dumps({})

    def menuDumpVehicles(self):
        for vin in self.vehicle_data:
            # self.logger.info(f"Data for VIN {vin}:\n{self.vehicle_data[vin]}")
            self.logger.info(
                f"Data for VIN {vin}:\n{json.dumps(self.vehicle_data[vin], skipkeys=True, sort_keys=True, indent=4, separators=(',', ': '))}")
        return True
