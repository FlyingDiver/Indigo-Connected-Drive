#! /usr/bin/env python
# -*- coding: utf-8 -*-

import indigo
import json
import logging
import requests
import time
import datetime
import asyncio
from importlib.metadata import version
from math import radians, cos, sin, asin, sqrt

try:
    from aiohttp import ClientSession
    from bimmer_connected.account import MyBMWAccount
    from bimmer_connected.api.regions import get_region_from_name, valid_regions
    from bimmer_connected.vehicle.vehicle import VehicleViewDirection
    from bimmer_connected.utils import MyBMWJSONEncoder
except ImportError as err:
    raise ImportError("'Required Python libraries missing.  Run 'pip3 install bimmer_connected aiohttp' in Terminal window, then reload plugin.")

def haversine(lon1, lat1, lon2, lat2):
    """
    Calculate the great circle distance between two points
    on the earth (specified in decimal degrees)
    """
    # convert decimal degrees to radians
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    # haversine formula
    d_lon = lon2 - lon1
    d_lat = lat2 - lat1
    a = sin(d_lat/2)**2 + cos(lat1) * cos(lat2) * sin(d_lon/2)**2
    c = 2 * asin(sqrt(a))
    # Radius of earth in kilometers is 6371
    km = 6371 * c
    return km

async def get_account_data(username, password, region):
    account = MyBMWAccount(username, password, get_region_from_name(region))
    await account.get_vehicles()
    return account

async def light_flash(username, password, region, vin):
    account = MyBMWAccount(username, password, get_region_from_name(region))
    vehicle = account.get_vehicle(vin)
    if not vehicle:
        return None
    status = vehicle.remote_services.trigger_remote_light_flash()
    return status.state

async def door_lock(username, password, region, vin):
    account = MyBMWAccount(username, password, get_region_from_name(region))
    vehicle = account.get_vehicle(vin)
    if not vehicle:
        return None
    status = vehicle.remote_services.trigger_remote_door_lock()
    return status.state


async def door_unlock(username, password, region, vin):
    account = MyBMWAccount(username, password, get_region_from_name(region))
    vehicle = account.get_vehicle(vin)
    if not vehicle:
        return None
    status = vehicle.remote_services.trigger_remote_door_unlock()
    return status.state


async def horn(username, password, region, vin):
    account = MyBMWAccount(username, password, get_region_from_name(region))
    vehicle = account.get_vehicle(vin)
    if not vehicle:
        return None
    status = vehicle.remote_services.trigger_remote_horn()
    return status.state


async def air_conditioning(username, password, region, vin):
    account = MyBMWAccount(username, password, get_region_from_name(region))
    vehicle = account.get_vehicle(vin)
    if not vehicle:
        return None
    status = vehicle.remote_services.trigger_remote_air_conditioning()
    return status.state

async def air_conditioning_off(username, password, region, vin):
    account = MyBMWAccount(username, password, get_region_from_name(region))
    vehicle = account.get_vehicle(vin)
    if not vehicle:
        return None
    status = vehicle.remote_services.trigger_remote_air_conditioning_stop()
    return status.state

async def charge_now(username, password, region, vin):
    account = MyBMWAccount(username, password, get_region_from_name(region))
    vehicle = account.get_vehicle(vin)
    if not vehicle:
        return None
    status = vehicle.remote_services.trigger_charge_nowp()
    return status.state

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
        self.next_update = time.time() + 30.0   # give time for devices to get initialized
        self.need_update = False

        self.units = pluginPrefs.get('units', "us")

        self.bridge_data = {}
        self.wrappers = {}
        self.read_threads = {}

        self.cd_accounts = {}
        self.cd_vehicles = {}
        self.vehicle_data = {}

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
                if time.time() > self.next_update or self.need_update:
                    self.next_update = time.time() + self.updateFrequency
                    self.need_update = False

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
            self.need_update = True
            self.cd_vehicles[device.address] = device.id

        else:
            self.logger.error(f"{device.name}: deviceStartComm: Unknown device type: {device.deviceTypeId}")

        device.stateListOrDisplayStateIdChanged()

    def deviceStopComm(self, device):
        self.logger.info(f"{device.name}: Stopping {device.deviceTypeId} Device {device.id}")

    def _do_update(self, cd_account):
        try:
            account = asyncio.run(get_account_data(cd_account.pluginProps['username'], cd_account.pluginProps['password'], cd_account.pluginProps['region']))
        except Exception as e:
            self.logger.warning(f"{cd_account.name}: get_account error: {e}")
            return

        for vehicle in account.vehicles:

            # convert vehicle data to a pure Python dict and save it
            self.vehicle_data[vehicle.vin] = {'account': cd_account.id, 'vehicle': json.loads(json.dumps(vehicle, cls=MyBMWJSONEncoder))}

            # look for an Indigo device and matches this vehicle
            vehicleDevID = self.cd_vehicles.get(vehicle.vin, None)
            if not vehicleDevID:
                self.logger.debug(f"{cd_account.name}: VIN not found: {vehicle.vin}")
                return

            vehicleDevice = indigo.devices.get(int(vehicleDevID), None)
            if not vehicleDevice:
                self.logger.debug(f"{cd_account.name}: Indigo device for vehicleDevID not found: {vehicleDevID}")
                return

            self.logger.debug(f"{cd_account.name}: Updating {vehicle.name} ({vehicle.vin}) -->  {vehicleDevice.name} ({vehicleDevice.id})")

            try:
                (latitude, longitude) = indigo.server.getLatitudeAndLongitude()
                distance = haversine(longitude, latitude, vehicle.vehicle_location.location.longitude, vehicle.vehicle_location.location.latitude)
            except (Exception,):
                distance = 0.0

            states_list = [{'key': 'vin', 'value': vehicle.vin},
                           {'key': 'brand', 'value': vehicle.brand},
                           {'key': 'driveTrain', 'value': vehicle.drive_train},
                           {'key': 'is_vehicle_active', 'value': vehicle.is_vehicle_active},
                           {'key': 'is_service_required', 'value': vehicle.condition_based_services.is_service_required},
                           {'key': 'mileage', 'value': vehicle.mileage[0], 'uiValue': f"{vehicle.mileage[0]} {vehicle.mileage[1]}"},
                           {'key': 'timestamp', 'value': vehicle.timestamp.replace(tzinfo=datetime.timezone.utc).astimezone().strftime("%d %b %Y %H:%M:%S %Z")},
                           {'key': 'model', 'value': vehicle.data['attributes']['model']},
                           {'key': 'year', 'value': vehicle.data['attributes']['year']},
                           {'key': 'all_lids_closed', 'value': vehicle.doors_and_windows.all_lids_closed},
                           {'key': 'all_windows_closed', 'value': vehicle.doors_and_windows.all_windows_closed},
                           {'key': 'open_windows', 'value': ""},
                           {'key': 'door_lock_state', 'value': vehicle.doors_and_windows.door_lock_state},
                           {'key': 'is_charger_connected', 'value': vehicle.fuel_and_battery.is_charger_connected},
                           {'key': 'remaining_fuel', 'value': vehicle.fuel_and_battery.remaining_fuel.value},
                           {'key': 'remaining_fuel_percent', 'value': vehicle.fuel_and_battery.remaining_fuel_percent},
                           {'key': 'remaining_range_total', 'value': vehicle.fuel_and_battery.remaining_range_total.value},
                           {'key': 'remaining_battery_percent', 'value': vehicle.fuel_and_battery.remaining_battery_percent},
                           {'key': 'distance', 'value': distance},
                           {'key': 'last_update', 'value': time.strftime("%d %b %Y %H:%M:%S %Z")},
                           ]

            if vehicle.vehicle_location:
                states_list.append({'key': 'gps_lat', 'value': vehicle.vehicle_location.location.latitude})
                states_list.append({'key': 'gps_long', 'value': vehicle.vehicle_location.location.longitude})
                states_list.append({'key': 'gps_heading', 'value': vehicle.vehicle_location.heading})

            open_lid_list = ""
            if not vehicle.doors_and_windows.all_lids_closed:
                open_lid_list = ", ".join(lid.name for lid in vehicle.doors_and_windows.open_lids)
            states_list.append({'key': 'open_lids', 'value': open_lid_list})

            open_window_list = ""
            if not vehicle.doors_and_windows.all_windows_closed:
                open_window_list = ", ".join(window.name for window in vehicle.doors_and_windows.open_windows)
            states_list.append({'key': 'open_windows', 'value': open_window_list})

            state_key = vehicleDevice.pluginProps["state_key"]
            match state_key:
                case 'mileage':
                    status_value = vehicle.mileage[0]
                    status_ui = f"{vehicle.mileage[0]} {vehicle.mileage[1]}"

                case 'remaining_fuel':
                    status_value = vehicle.fuel_and_battery.remaining_fuel[0]
                    status_ui = f"{vehicle.fuel_and_battery.remaining_fuel.value} {vehicle.fuel_and_battery.remaining_fuel.unit}"

                case 'remaining_fuel_percent':
                    status_value = vehicle.fuel_and_battery.remaining_fuel_percent
                    status_ui = f"{vehicle.fuel_and_battery.remaining_fuel_percent}%"

                case 'remaining_battery_percent':
                    status_value = vehicle.fuel_and_battery.remaining_battery_percent
                    status_ui = f"{vehicle.fuel_and_battery.remaining_battery_percent}%"

                case 'remaining_range_total':
                    status_value = vehicle.fuel_and_battery.remaining_range_total[0]
                    status_ui = f"{vehicle.fuel_and_battery.remaining_range_total[0]} {vehicle.fuel_and_battery.remaining_range_total[1]}"

                case 'door_lock_state':
                    status_value = vehicle.doors_and_windows.door_lock_state
                    status_ui = f"{vehicle.doors_and_windows.door_lock_state}"

                case _:
                    status_value = ""
                    status_ui = ""
            states_list.append({'key': 'status', 'value': status_value, 'uiValue': status_ui})
            vehicleDevice.updateStatesOnServer(states_list)

    def get_vehicle_list(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.logger.threaddebug(f"get_vehicle_list: typeId = {typeId}, targetId = {targetId}, valuesDict = {valuesDict}")
        retList = []

        for v in self.vehicle_data.values():
            retList.append((v['vehicle']['vin'], f"{v['vehicle']['data']['attributes']['year']} {v['vehicle']['data']['attributes']['model']}"))
        retList.sort(key=lambda tup: tup[1])
        return retList

    def get_vehicle_state_list(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.logger.threaddebug(f"get_vehicle_state_list: typeId = {typeId}, targetId = {targetId}, valuesDict = {valuesDict}")
        retList = []
        for s in ['mileage', 'remaining_fuel', 'remaining_fuel_percent', 'remaining_battery_percent', 'remaining_range_total', 'door_lock_state']:
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

    def sendCommandAction(self, pluginAction, vehicleDevice, callerWaitingForResult):
        self.logger.debug(f"{vehicleDevice.name}: sendCommandAction {pluginAction.props['serviceCode']} for VIN {vehicleDevice.address}")
        cd_account = indigo.devices[int(self.vehicle_data[vehicleDevice.address]['account'])]
        self.logger.debug(f"{vehicleDevice.name}: sendCommandAction using cd_account: {cd_account.name}")

        match pluginAction.props["serviceCode"]:
            case 'light':
                ret = asyncio.run(light_flash(cd_account.pluginProps['username'], cd_account.pluginProps['password'], cd_account.pluginProps['region'],
                                vehicleDevice.address))
                self.logger.debug(f"{vehicleDevice.name}: sendCommandAction {pluginAction.props['serviceCode']} result: {ret}")

            case 'lock':
                ret = asyncio.run(door_lock(cd_account.pluginProps['username'], cd_account.pluginProps['password'], cd_account.pluginProps['region'],
                                vehicleDevice.address))
                self.logger.debug(f"{vehicleDevice.name}: sendCommandAction {pluginAction.props['serviceCode']} result: {ret}")

            case 'unlock':
                ret = asyncio.run(door_unlock(cd_account.pluginProps['username'], cd_account.pluginProps['password'], cd_account.pluginProps['region'],
                              vehicleDevice.address))
                self.logger.debug(f"{vehicleDevice.name}: sendCommandAction {pluginAction.props['serviceCode']} result: {ret}")

            case 'horn':
                ret = asyncio.run(horn(cd_account.pluginProps['username'], cd_account.pluginProps['password'], cd_account.pluginProps['region'],
                                vehicleDevice.address))
                self.logger.debug(f"{vehicleDevice.name}: sendCommandAction {pluginAction.props['serviceCode']} result: {ret}")

            case 'climate':
                ret = asyncio.run(air_conditioning(cd_account.pluginProps['username'], cd_account.pluginProps['password'], cd_account.pluginProps['region'],
                                vehicleDevice.address))
                self.logger.debug(f"{vehicleDevice.name}: sendCommandAction {pluginAction.props['serviceCode']} result: {ret}")

            case 'climate_off':
                ret = asyncio.run(air_conditioning_off(cd_account.pluginProps['username'], cd_account.pluginProps['password'], cd_account.pluginProps['region'],
                                vehicleDevice.address))
                self.logger.debug(f"{vehicleDevice.name}: sendCommandAction {pluginAction.props['serviceCode']} result: {ret}")

            case 'charge_now':
                ret = asyncio.run(charge_now(cd_account.pluginProps['username'], cd_account.pluginProps['password'], cd_account.pluginProps['region'],
                                vehicleDevice.address))
                self.logger.debug(f"{vehicleDevice.name}: sendCommandAction {pluginAction.props['serviceCode']} result: {ret}")

            case _:
                self.logger.warning(f"{vehicleDevice.name}: sendCommandAction unknown serviceCode: {serviceCode}")

        # schedule an update shortly
        self.next_update = time.time() + 30.0
