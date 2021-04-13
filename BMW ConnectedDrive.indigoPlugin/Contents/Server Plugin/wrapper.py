import asyncio
import sys
import json
import requests
import logging

from aiohttp import ClientSession
from pathlib import Path
from bimmer_connected.account import ConnectedDriveAccount
from bimmer_connected.country_selector import get_region_from_name, valid_regions
from bimmer_connected.vehicle import VehicleViewDirection


def msg_write(msg):
    sys.stdout.write(u"{}\n".format(msg))
    sys.stdout.flush()

async def main(args) -> None:

    async with ClientSession() as websession:
        try:
            account = ConnectedDriveAccount(sys.argv[1], sys.argv[2], get_region_from_name(sys.argv[3]))

        except Exception as err:
            msg_write(json.dumps({'msg': 'status', 'status': "Login Error"}))
            msg_write(json.dumps({'msg': 'error', 'error': err.args}))
            return

        msg_write(json.dumps({'msg': 'status', 'status': "Login Complete"}))

        # process requests from the plugin
                      
        for line in sys.stdin:

            logging.debug("Wrapper got command: {}".format(line.rstrip()))
            
            request = json.loads(line.rstrip())
            msg_write(json.dumps({'msg': 'echo', 'request': request}))
            cmd = request['cmd']
            
            if cmd == 'stop':
                msg_write(json.dumps({'msg': 'status', 'status': "Stopped"}))
                logging.debug("Wrapper stopping")
                break

            elif cmd == 'vehicles':
                account.update_vehicle_states()
                logging.debug("vehicles command: {} vehicles".format(len(account.vehicles)))
                msg_write(json.dumps({'msg': 'status', 'status': "Update OK"}))
                for vehicle in account.vehicles:
                    msg_write(json.dumps({'msg': 'vehicle', 'vin': vehicle.vin, 'properties': vehicle.attributes, 'status': vehicle.state.attributes["STATUS"]}))

            elif cmd == 'light':
                vehicle = account.get_vehicle(request['vin'])
                if not vehicle:
                    msg_write(json.dumps({'msg': 'error', 'error': f"Vehicle with VIN '{request['vin']}' not found."}))
                    return
                status = vehicle.remote_services.trigger_remote_light_flash()
                logging.debug("light command status: {}".format(status))
                msg_write(json.dumps({'msg': 'status', 'status': f"light_flash for {request['vin']} is {status.state}"}))

            elif cmd == 'lock':
                vehicle = account.get_vehicle(request['vin'])
                if not vehicle:
                    msg_write(json.dumps({'msg': 'error', 'error': f"Vehicle with VIN '{request['vin']}' not found."}))
                    return
                status = vehicle.remote_services.trigger_remote_door_lock()
                logging.debug("lock command status: {}".format(status))
                msg_write(json.dumps({'msg': 'status', 'status': f"door_lock for {request['vin']} is {status.state}"}))

            elif cmd == 'unlock':
                vehicle = account.get_vehicle(request['vin'])
                if not vehicle:
                    msg_write(json.dumps({'msg': 'error', 'error': f"Vehicle with VIN '{request['vin']}' not found."}))
                    return
                status = vehicle.remote_services.trigger_remote_door_unlock()
                logging.debug("unlock command status: {}".format(status))
                msg_write(json.dumps({'msg': 'status', 'status': f"door_unlock for {request['vin']} is {status.state}"}))

            elif cmd == 'horn':
                vehicle = account.get_vehicle(request['vin'])
                if not vehicle:
                    msg_write(json.dumps({'msg': 'error', 'error': f"Vehicle with VIN '{request['vin']}' not found."}))
                    return
                status = vehicle.remote_services.trigger_remote_horn()
                logging.debug("horn command status: {}".format(status))
                msg_write(json.dumps({'msg': 'status', 'status': f"horn for {request['vin']} is {status.state}"}))

            elif cmd == 'climate':
                vehicle = account.get_vehicle(request['vin'])
                if not vehicle:
                    msg_write(json.dumps({'msg': 'error', 'error': f"Vehicle with VIN '{request['vin']}' not found."}))
                    return
                status = vehicle.remote_services.trigger_remote_air_conditioning()
                logging.debug("climate command status: {}".format(status))
                msg_write(json.dumps({'msg': 'status', 'status': f"air_conditioning for {request['vin']} is {status.state}"}))

    
# actual start of the program
    
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(name)s - %(message)s', datefmt='%m/%d/%Y %I:%M:%S %p', level=int(sys.argv[4]))

asyncio.run(main(sys.argv))
