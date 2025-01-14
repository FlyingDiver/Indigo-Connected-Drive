#! /usr/bin/env python
# -*- coding: utf-8 -*-

import indigo
import json
import logging
import contextlib
import time
import datetime
import asyncio
from aiohttp import ClientSession
import threading

from math import radians, cos, sin, asin, sqrt
from pint import UnitRegistry

from bimmer_connected.account import MyBMWAccount
from bimmer_connected.api.regions import get_region_from_name, valid_regions
from bimmer_connected.vehicle.vehicle import VehicleViewDirection
from bimmer_connected.utils import MyBMWJSONEncoder

AUTH_TOKEN_PLUGIN_PREF = 'auth_tokens-{}'
CAPTCHA_URL = "https://bimmer-connected.readthedocs.io/en/stable/captcha.html"

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
    a = sin(d_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(d_lon / 2) ** 2
    c = 2 * asin(sqrt(a))
    # Radius of earth in kilometers is 6371
    km = 6371 * c
    return km

########################################################################################

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
        self.next_update = time.time() + 30.0  # give time for devices to get initialized
        self.need_update = False

        self.units = pluginPrefs.get('units', "us")
        self.ureg = UnitRegistry()

        self.bridge_data = {}
        self.wrappers = {}
        self.read_threads = {}

        self.cd_accounts = {}
        self.cd_vehicles = {}
        self.vehicle_data = {}
        self.triggers = []

        self.event_loop = None
        self.async_thread = None

    def startup(self):
        threading.Thread(target=self.run_async_thread).start()

    def run_async_thread(self):
        self.logger.debug("run_async_thread starting")
        self.event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.event_loop)
        self.event_loop.run_until_complete(self.async_main())
        self.event_loop.close()
        self.logger.debug("run_async_thread exiting")

    async def async_main(self):
        self.logger.debug("async_main starting")

        while True:
            await asyncio.sleep(0.1)
            if self.stopThread:
                self.logger.debug("async_main: stopping")
                break

            if time.time() > self.next_update or self.need_update:
                self.next_update = time.time() + self.updateFrequency
                self.need_update = False

                for dev_id in self.cd_accounts.keys():
                    await self.do_account_update(dev_id)

        self.logger.debug("async_main: exiting")

########################################################################################

    def validate_prefs_config_ui(self, valuesDict):
        self.logger.debug(f"validate_prefs_config_ui {dict(valuesDict)=}")
        errorDict = indigo.Dict()
        updateFrequency = int(valuesDict.get('updateFrequency', 15))
        if (updateFrequency < 5) or (updateFrequency > 60):
            errorDict['updateFrequency'] = "Update frequency is invalid - enter a valid number (between 5 and 60)"
        if len(errorDict) > 0:
            return False, valuesDict, errorDict
        return True

    def closed_prefs_config_ui(self, valuesDict, userCancelled):
        if not userCancelled:
            self.logLevel = int(valuesDict.get("logLevel", logging.INFO))
            self.indigo_log_handler.setLevel(self.logLevel)
            self.updateFrequency = float(valuesDict['updateFrequency']) * 60.0
            self.next_update = time.time()
            self.logger.debug(f"closed_prefs_config_ui, logLevel = {self.logLevel}, updateFrequency = {self.updateFrequency}")

    ########################################################################################

    def get_device_config_ui_values(self, pluginProps, typeId, devId):
        self.logger.debug(f"get_device_config_ui_values, {typeId=}, {devId=}")
        valuesDict = indigo.Dict(pluginProps)
        errorsDict = indigo.Dict()

        if typeId == "cdAccount":
            valuesDict["captcha_token"] = None

        return valuesDict, errorsDict

    def validate_device_config_ui(self, valuesDict, typeId, devId):
        self.logger.debug(f"validate_device_config_ui, {typeId=}, {devId=}, {dict(valuesDict)=}")
        errorsDict = indigo.Dict()

        if typeId == "cdAccount":
            if not valuesDict.get("username", None) or len(valuesDict.get("username")) == 0:
                errorsDict["username"] = "Username is required"
            if not valuesDict.get("password", None) or len(valuesDict.get("password")) == 0:
                errorsDict["password"] = "Password is required"
            if not valuesDict.get("region", None) or len(valuesDict.get("region")) == 0:
                errorsDict["region"] = "Region is required"
            if valuesDict.get("region", None) not in valid_regions():
                errorsDict["region"] = "Region is invalid"
            if not valuesDict.get("captcha_token", None) or len(valuesDict.get("captcha_token")) == 0:
                errorsDict["captcha_token"] = "Captcha token is required"

        elif typeId == "cdVehicle":
            pass

        if len(errorsDict):
            return False, valuesDict, errorsDict

        return True, valuesDict

    def closed_device_config_ui(self, valuesDict, userCancelled, typeId, devId):
        if userCancelled:
            self.logger.debug(f"closed_device_config_ui: User cancelled")
            return

        self.logger.debug(f"closed_device_config_ui, {typeId=}, {devId=}, {dict(valuesDict)=}")

        # Attempt to create a MyBMWAccount object to validate the credentials
        try:
            account = MyBMWAccount(valuesDict.get("username"),
                                   valuesDict.get("password"),
                                   get_region_from_name(valuesDict.get("region")),
                                   hcaptcha_token=valuesDict.get("captcha_token"))
        except Exception as e:
            self.logger.debug(f"get_tokens create account error: {e}")

            for trigger in indigo.triggers.iter("self"):
                if trigger.pluginTypeId == "auth_error":
                    indigo.trigger.execute(trigger)

            return

        self.cd_accounts[devId] = account
        try:
            auth_data = asyncio.run(self.get_account_data(account))
        except Exception as e:
            self.logger.debug(f"get_tokens get data error: {e}")

            for trigger in indigo.triggers.iter("self"):
                if trigger.pluginTypeId == "auth_error":
                    indigo.trigger.execute(trigger)
            return

        if auth_data:
            self.pluginPrefs[AUTH_TOKEN_PLUGIN_PREF.format(devId)] = json.dumps(auth_data)
            self.savePluginPrefs()

        self.need_update = True

        return valuesDict

    def open_browser_to_captcha(self, valuesDict, typeId, devId):
        self.logger.info(f"Captcha URL:{CAPTCHA_URL}")
        self.browserOpen(CAPTCHA_URL)

    ########################################
    # Trigger (Event) handling
    ########################################

    def triggerStartProcessing(self, trigger):
        self.logger.debug(f"{trigger.name}: Adding Trigger")
        assert trigger.id not in self.triggers
        self.triggers.append(trigger.id)

    def triggerStopProcessing(self, trigger):
        self.logger.debug(f"{trigger.name}: Removing Trigger")
        assert trigger.id in self.triggers
        self.triggers.remove(trigger.id)

    ################################################################################

    def device_start_comm(self, device):
        self.logger.info(f"{device.name}: Starting {device.deviceTypeId} Device")

        if device.deviceTypeId == "cdAccount":

            account = MyBMWAccount(device.pluginProps['username'], device.pluginProps['password'], get_region_from_name(device.pluginProps['region']))
            self.cd_accounts[device.id] = account
            if auth_json := self.pluginPrefs.get(AUTH_TOKEN_PLUGIN_PREF.format(device.id)):
                with contextlib.suppress(json.JSONDecodeError):
                    account.set_refresh_token(**json.loads(auth_json))
            else:
                self.logger.warning(f"{device.name}: No auth data found")

        elif device.deviceTypeId == "cdVehicle":
            self.need_update = True
            self.cd_vehicles[device.address] = device.id

        else:
            self.logger.error(f"{device.name}: deviceStartComm: Unknown device type: {device.deviceTypeId}")

        device.stateListOrDisplayStateIdChanged()

    def device_stop_comm(self, device):
        self.logger.info(f"{device.name}: Stopping {device.deviceTypeId} Device {device.id}")

        if device.deviceTypeId == "cdAccount":
            del self.cd_accounts[device.id]

        elif device.deviceTypeId == "cdVehicle":
            del self.cd_vehicles[device.address]

    async def get_account_data(self, account):
        self.logger.debug(f"get_account_data")

        try:
            await account.get_vehicles()
        except Exception as e:
            self.logger.warning(f"get_account_data get_vehicles error: {e}")
            return None

        return {
            "refresh_token": account.config.authentication.refresh_token,
            "gcid": account.config.authentication.gcid,
            "access_token": account.config.authentication.access_token,
        }

    async def do_account_update(self, account_dev_id):
        account_dev = indigo.devices[int(account_dev_id)]
        self.logger.debug(f"{account_dev.name}: do_account_update")

        cd_account = self.cd_accounts[account_dev_id]
        auth_data = await self.get_account_data(cd_account)
        if not auth_data:
            return

        self.logger.debug(f"{account_dev.name}: {auth_data=}")

        states_list = [{'key': 'refresh_token', 'value': auth_data['refresh_token']},
                       {'key': 'gcid', 'value': auth_data['gcid']},
                       {'key': 'auth_token', 'value': auth_data['access_token']}]
        account_dev.updateStatesOnServer(states_list)

        self.pluginPrefs[AUTH_TOKEN_PLUGIN_PREF.format(account_dev_id)] = json.dumps(auth_data)
        self.savePluginPrefs()

        for vehicle in cd_account.vehicles:

            # convert vehicle data to a pure Python dict and save it
            self.vehicle_data[vehicle.vin] = {'account': account_dev_id, 'vehicle': json.loads(json.dumps(vehicle, cls=MyBMWJSONEncoder))}

            # look for an Indigo device that matches this vehicle
            vehicleDevID = self.cd_vehicles.get(vehicle.vin)
            if not vehicleDevID:
                self.logger.debug(f"{account_dev.name}: VIN not found: {vehicle.vin}")
                continue

            vehicleDevice = indigo.devices.get(int(vehicleDevID))
            if not vehicleDevice:
                self.logger.debug(f"{account_dev.name}: Indigo device for vehicleDevID not found: {vehicleDevID}")
                continue

            self.logger.debug(f"{account_dev.name}: Updating {vehicle.name} ({vehicle.vin}) -->  {vehicleDevice.name} ({vehicleDevice.id})")

            try:
                (latitude, longitude) = indigo.server.getLatitudeAndLongitude()
                distance = haversine(longitude, latitude, vehicle.vehicle_location.location.longitude, vehicle.vehicle_location.location.latitude)
            except (Exception,):
                distance = 0.0

            states_list = [{'key': 'vin', 'value': vehicle.vin},
                           {'key': 'brand', 'value': vehicle.brand},
                           {'key': 'driveTrain', 'value': vehicle.drive_train},
                           {'key': 'is_vehicle_active', 'value': vehicle.is_vehicle_active},
                           {'key': 'timestamp', 'value': vehicle.timestamp.replace(tzinfo=datetime.timezone.utc).astimezone().strftime("%d %b %Y %H:%M:%S %Z")},
                           {'key': 'model', 'value': vehicle.data['attributes']['model']},
                           {'key': 'year', 'value': vehicle.data['attributes']['year']},
                           {'key': 'all_lids_closed', 'value': vehicle.doors_and_windows.all_lids_closed},
                           {'key': 'all_windows_closed', 'value': vehicle.doors_and_windows.all_windows_closed},
                           {'key': 'open_windows', 'value': ""},
                           {'key': 'door_lock_state', 'value': vehicle.doors_and_windows.door_lock_state},
                           {'key': 'is_charger_connected', 'value': vehicle.fuel_and_battery.is_charger_connected},
                           {'key': 'remaining_fuel_percent', 'value': vehicle.fuel_and_battery.remaining_fuel_percent},
                           {'key': 'remaining_battery_percent', 'value': vehicle.fuel_and_battery.remaining_battery_percent},
                           {'key': 'last_update', 'value': time.strftime("%d %b %Y %H:%M:%S %Z")},
                           ]

            if self.units == "metric":  # use API results directly
                states_list.append({'key': 'mileage', 'value': vehicle.mileage[0],
                                    'uiValue': f"{vehicle.mileage[0]} {vehicle.mileage[1]}"})
                states_list.append({'key': 'remaining_fuel', 'value': vehicle.fuel_and_battery.remaining_fuel.value,
                                    'uiValue': f"{vehicle.fuel_and_battery.remaining_fuel.value} L"})
                states_list.append({'key': 'remaining_range_total', 'value': vehicle.fuel_and_battery.remaining_range_total.value,
                                   'uiValue': f"{vehicle.fuel_and_battery.remaining_range_total.value} km"})
                states_list.append({'key': 'distance', 'value': distance,
                                    'uiValue': f"{distance} km"})

            else:                        # convert to US units
                mileage = (vehicle.mileage[0] * self.ureg.kilometer).to(self.ureg.miles)
                states_list.append({'key': 'mileage', 'value': int(mileage.magnitude), 'uiValue': f"{int(mileage.magnitude)} mi"})

                fuel = (vehicle.fuel_and_battery.remaining_fuel.value * self.ureg.liter).to(self.ureg.gallon)
                states_list.append({'key': 'remaining_fuel', 'value': float(fuel.magnitude), 'uiValue': f"{fuel.magnitude:.1f} gal"})

                range = (vehicle.fuel_and_battery.remaining_range_total.value * self.ureg.kilometer).to(self.ureg.miles)
                states_list.append({'key': 'remaining_range_total', 'value': int(range.magnitude), 'uiValue': f"{int(range.magnitude)} mi"})

                distance = (distance * self.ureg.kilometer).to(self.ureg.miles)
                states_list.append({'key': 'distance', 'value': float(distance.magnitude), 'uiValue': f"{distance.magnitude:.2f} mi"})

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
            status_value = ""
            status_ui = ""
            for state in states_list:
                if state['key'] == state_key:
                    status_value = state['value']
                    status_ui = state['uiValue']
                    break
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
    def menu_changed(valuesDict=None, typeId=None, devId=None):
        return valuesDict

    def fetch_vehicle_data_action(self, action, device, callerWaitingForResult):
        vin = action.props["vin"]
        try:
            return json.dumps(self.vehicle_data[vin])
        except (Exception,):
            return json.dumps({})

    def menu_dump_vehicles(self):
        for vin in self.vehicle_data:
            self.logger.info(
                f"Data for VIN {vin}:\n{json.dumps(self.vehicle_data[vin], skipkeys=True, sort_keys=True, indent=4, separators=(',', ': '))}")
        return True

    def send_command_action(self, plugin_action, vehicle_device, callerWaitingForResult):
        self.logger.debug(f"{vehicle_device.name}: send_command_action {plugin_action.props['serviceCode']} for VIN {vehicle_device.address}")
        cd_account_device = indigo.devices[int(self.vehicle_data[vehicle_device.address]['account'])]
        self.logger.debug(f"{vehicle_device.name}: send_command_action using cd_account_device: {cd_account_device.name}")

        self.event_loop.create_task(self.async_send_command_action(cd_account_device, vehicle_device.address, plugin_action))

        # schedule an update shortly
        self.next_update = time.time() + 30.0

    async def async_send_command_action(self, cd_account_device, vin, plugin_action):
        cd_account = self.cd_accounts[cd_account_device.id]
        vehicle = cd_account.get_vehicle(vin)
        if not vehicle:
            self.logger.warning(f"{cd_account_device.name}: async_send_command_action: vehicle not found")
            return None

        match plugin_action.props["serviceCode"]:
            case 'light':
                status = await vehicle.remote_services.trigger_remote_light_flash()

            case 'lock':
                status = await vehicle.remote_services.trigger_remote_door_lock()

            case 'unlock':
                status = await vehicle.remote_services.trigger_remote_door_unlock()

            case 'horn':
                status = await vehicle.remote_services.trigger_remote_horn()

            case 'climate':
                status = await vehicle.remote_services.trigger_remote_air_conditioning()

            case 'climate_off':
                status = await vehicle.remote_services.trigger_remote_air_conditioning_stop()

            case 'charge_start':
                status = await vehicle.remote_services.trigger_charge_start()

            case 'charge_stop':
                status = await vehicle.remote_services.trigger_charge_stop()

            case 'send_poi':
                poi_data = {
                    "lat": float(plugin_action.props["poi_lat"]),
                    "lon": float(plugin_action.props["poi_lon"]),
                    "name": plugin_action.props["poi_name"],
                    "street": plugin_action.props["poi_address"],
                    "city": plugin_action.props["poi_city"],
                    "postal_code": plugin_action.props["poi_postal"],
                    "country": plugin_action.props["poi_country"],
                }
                try:
                    status = await vehicle.remote_services.trigger_send_poi(poi_data)
                except Exception as e:
                    self.logger.warning(f"{vin}: send_command_action send_poi error: {e}")
                    return None

            case _:
                self.logger.warning(f"{vin}: send_command_action unknown serviceCode: {plugin_action.props['serviceCode']}")
                return None

        self.logger.debug(f"{vehicle.name}: send_command_action {plugin_action.props['serviceCode']} result: {status.state}")
