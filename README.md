# Indigo-ConnectedDrive
Plugin for the BMW Connected Drive portal

| Requirement            |                     |   |
|------------------------|---------------------|---|
| Minimum Indigo Version | 2022.1              |   |
| Python Library (API)   | Unofficial          |   |
| Requires Local Network | No                  |   |
| Requires Internet      | Yes                 |   |
| Hardware Interface     | None                |   |

## Installation Instructions

In Terminal.app enter:

`pip3 install bimmer_connected==0.9.0 aiohttp httpx`

Create a "Connected Drive Account" device with your Connected Drive login credentials.

Wait for the  plugin to report number of vehicles found in Indigo Log.

Create "Connected Drive Vehicle" devices as needed.


## Accessing additional vehicle data

Additional data (beyond the device states) can be accessed using a Python script, like this:

    import json
   	import indigo

	cd_plugin = indigo.server.getPlugin("com.flyingdiver.indigoplugin.bmw-cd")
	if not cd_plugin.isEnabled():
   		indigo.server.log(("Connected Drive Plugin not enabled")
   		exit()
    
	props = {
    	'vin':"PUT YOUR VIN HERE" 
	}
	vehicle_json = cd_plugin.executeAction("fetchVehicleData", props=props, waitUntilDone=True)
	vehicle_data = json.loads(vehicle_json)
	indigo.server.log(f"Got data for {vehicle_data['vehicle']['data']['year']} {vehicle_data['vehicle']['data']['model']}")
