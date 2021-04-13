import asyncio
import sys
import json
import requests

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

            print("Got: {}".format(line), file=sys.stderr)
            
            request = json.loads(line.rstrip())
            msg_write(json.dumps({'msg': 'echo', 'request': request}))
            cmd = request['cmd']
            
            if cmd == 'stop':
                msg_write(json.dumps({'msg': 'status', 'status': "Stopped"}))
                break

            elif cmd == 'vehicles':
                account.update_vehicle_states()
                msg_write(json.dumps({'msg': 'status', 'status': "Update OK"}))
                for vehicle in account.vehicles:
                    msg_write(json.dumps({'msg': 'vehicle', 'vin': vehicle.vin, 'properties': vehicle.attributes, 'status': vehicle.state.attributes["STATUS"]}))

            elif cmd == 'light_flash':
                vehicle = account.get_vehicle(request['vin'])
                if not vehicle:
                    msg_write(json.dumps({'msg': 'error', 'error': f"Vehicle with VIN '{request['vin']}' not found."}))
                    return
                status = vehicle.remote_services.trigger_remote_light_flash()
                print("light_flash: {}".format(status), file=sys.stderr)
                msg_write(json.dumps({'msg': 'status', 'status': f"light_flash for {request['vin']} is {status.state}"}))

            elif cmd == 'door_lock':
                vehicle = account.get_vehicle(request['vin'])
                if not vehicle:
                    msg_write(json.dumps({'msg': 'error', 'error': f"Vehicle with VIN '{request['vin']}' not found."}))
                    return
                status = vehicle.remote_services.trigger_remote_door_lock()
                print("door_lock: {}".format(status), file=sys.stderr)
                msg_write(json.dumps({'msg': 'status', 'status': f"door_lock for {request['vin']} is {status.state}"}))

            elif cmd == 'door_unlock':
                vehicle = account.get_vehicle(request['vin'])
                if not vehicle:
                    msg_write(json.dumps({'msg': 'error', 'error': f"Vehicle with VIN '{request['vin']}' not found."}))
                    return
                status = vehicle.remote_services.trigger_remote_door_unlock()
                print("door_unlock: {}".format(status), file=sys.stderr)
                msg_write(json.dumps({'msg': 'status', 'status': f"door_unlock for {request['vin']} is {status.state}"}))

            elif cmd == 'horn':
                vehicle = account.get_vehicle(request['vin'])
                if not vehicle:
                    msg_write(json.dumps({'msg': 'error', 'error': f"Vehicle with VIN '{request['vin']}' not found."}))
                    return
                status = vehicle.remote_services.trigger_remote_horn()
                print("horn: {}".format(status), file=sys.stderr)
                msg_write(json.dumps({'msg': 'status', 'status': f"horn for {request['vin']} is {status.state}"}))

            elif cmd == 'air_conditioning':
                vehicle = account.get_vehicle(request['vin'])
                if not vehicle:
                    msg_write(json.dumps({'msg': 'error', 'error': f"Vehicle with VIN '{request['vin']}' not found."}))
                    return
                status = vehicle.remote_services.trigger_remote_air_conditioning()
                print("air_conditioning: {}".format(status), file=sys.stderr)
                msg_write(json.dumps({'msg': 'status', 'status': f"air_conditioning for {request['vin']} is {status.state}"}))

#             elif cmd == 'send_poi':
#                 vehicle = account.get_vehicle(request['vin'])
#                 if not vehicle:
#                     msg_write(json.dumps({'msg': 'error', 'error': f"Vehicle with VIN '{request['vin']}' not found."}))
#                     return
#                 poi = PointOfInterest(request['latitude'], request['longitude'], request['name'], 
#                         request['street'], request['city'], request['postalcode'], request['country'])
#                 vehicle.send_poi(poi)
# 
    
# actual start of the program
    
asyncio.run(main(sys.argv))
