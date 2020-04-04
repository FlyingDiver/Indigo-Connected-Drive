#! /usr/bin/env python
# -*- coding: utf-8 -*-
#
# Modified from for use with Indigo:
# 
# **** bmwcdapi.py ****
# https://github.com/jupe76/bmwcdapi
#
# Query vehicle data from the BMW ConnectedDrive Website, i.e. for BMW i3
# Based on the excellent work by Sergej Mueller
# https://github.com/sergejmueller/battery.ebiene.de
#
# Permission to use, copy, modify, and distribute this software for any
# purpose with or without fee is hereby granted, provided that the above
# copyright notice and this permission notice appear in all copies.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
# WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
# ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
# WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
# ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
# OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

import json
import requests
import time
import datetime
import logging
import indigo

cd_servers = { 
    'NA' : 'b2vapi.bmwgroup.us',
    'CN' : 'b2vapi.bmwgroup.cn:8592',
    'WD' : 'b2vapi.bmwgroup.com'
}
            
VEHICLE_API = 'https://{}/api/vehicle'

AUTH_URL = 'https://{server}/gcdm/oauth/token'
BASE_URL = 'https://{server}/webapi/v1'
VEHICLES_URL = BASE_URL + '/user/vehicles'
VEHICLE_VIN_URL = VEHICLES_URL + '/{vin}'
VEHICLE_STATUS_URL = VEHICLE_VIN_URL + '/status'

REMOTE_SERVICE_STATUS_URL = VEHICLE_VIN_URL + '/serviceExecutionStatus?serviceType={service_type}'
REMOTE_SERVICE_URL = VEHICLE_VIN_URL + "/executeService"
VEHICLE_IMAGE_URL = VEHICLE_VIN_URL + "/image?width={width}&height={height}&view={view}"
VEHICLE_POI_URL = VEHICLE_VIN_URL + '/sendpoi'


USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:57.0) Gecko/20100101 Firefox/57.0"

class ConnectedDrive(object):

    def __init__(self, region, username, password):
        self.logger = logging.getLogger("Plugin.ConnectedDrive")

        self.serverURL = cd_servers[region]
        self.bmwUsername = username
        self.bmwPassword = password
        self.access_token = None
        self.refresh_token = None
        self.next_refresh = None
        self.account_data = None
        self.authenticated = False
        
        self.get_tokens()


    def get_tokens(self):

        headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": "124",
                "Connection": "Keep-Alive",
                "Host": self.serverURL,
                "Accept-Encoding": "gzip",
                "Authorization": "Basic blF2NkNxdHhKdVhXUDc0eGYzQ0p3VUVQOjF6REh4NnVuNGNEanli"
                                 "TEVOTjNreWZ1bVgya0VZaWdXUGNRcGR2RFJwSUJrN3JPSg==",
                "Credentials": "nQv6CqtxJuXWP74xf3CJwUEP:1zDHx6un4cDjybLENN3kyfumX2kEYigWPcQpdvDRpIBk7rOJ",
                "User-Agent": "okhttp/2.60",
        }

        data = {
            'grant_type': 'password',
            'scope': 'authenticate_user vehicle_data remote_services',
            'username': self.bmwUsername,
            'password': self.bmwPassword,
        }

        try:
            r = requests.post(AUTH_URL.format(server=self.serverURL), data=data, headers=headers, allow_redirects=False)
        except requests.RequestException, e:
            self.authenticated = False
            self.logger.error(u"get_tokens AUTH Error, exception = {}".format(e))
            return
        if (r.status_code != requests.codes.ok):
            self.logger.error('get_tokens AUTH call failed, response code = {}'.format(r.status_code))
            self.authenticated = False
            return
        
        payload = r.json()
        self.logger.threaddebug("Auth Info =\n{}".format(json.dumps(payload, sort_keys=True, indent=4, separators=(',', ': '))))

        self.access_token=payload['access_token']
        self.refresh_token=payload['refresh_token']
        expires_in = payload['expires_in']
        self.logger.debug('ConnectedDrive get_tokens: token {}, Expires in {}'.format(self.access_token, expires_in))
        self.next_refresh = time.time() + (float(expires_in) * 0.80)
        self.authenticated = True
               
    def update_vehicles(self):
        self.logger.debug('ConnectedDrive update_vehicles')
        
        headers = {
            "Content-Type": "application/json",
            "User-agent": USER_AGENT,
            "Authorization" : "Bearer "+ self.access_token
            }

        try:
            r = requests.get(VEHICLES_URL.format(server=self.serverURL), headers=headers, allow_redirects=True)
        except requests.RequestException, e:
            self.logger.error(u"ConnectedDrive Account Update Error, exception = {}".format(e))
            return
            
        if r.status_code != requests.codes.ok:
            self.logger.error(u"ConnectedDrive Account Update failed, response = '{}'".format(r.text))                
            return

        self.account_data = r.json()    

        timestamp = datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
        latLong=indigo.server.getLatitudeAndLongitude()
        params = {
            'deviceTime': timestamp,
            'dlat': latLong[0],
            'dlon': latLong[1],
        }
           
        for v in self.account_data['vehicles']:
            try:
                r = requests.get(VEHICLE_STATUS_URL.format(server=self.serverURL, vin=v['vin']), headers=headers, params=params, allow_redirects=True)
            except requests.RequestException, e:
                self.logger.error(u"ConnectedDrive Vehicle Update Error, exception = {}".format(e))
                continue
            try:
                self.account_data[v['vin']] = r.json()['vehicleStatus']
            except:
                self.logger.debug('ConnectedDrive no vehicleStatus, data =\n{}'.format(r.json()))
            

        self.logger.threaddebug("update_vehicles account_data =\n{}".format(json.dumps(self.account_data, sort_keys=True, indent=4, separators=(',', ': '))))

    def get_vehicles(self):
        self.logger.debug('ConnectedDrive get_vehicles')
        return self.account_data['vehicles']

    def get_vehicle_data(self, vin):
        self.logger.debug('ConnectedDrive get_vehicle_data: {}'.format(vin))
        for v in self.account_data['vehicles']:
            if v['vin'] == vin:
                return v
        return None
        
    def get_vehicle_status(self, vin):
        self.logger.debug('ConnectedDrive get_vehicle_status: {}'.format(vin))
        try:
            data = self.account_data[vin]
        except:
            return None
        return data
        
    def dump_data(self):
        self.logger.info("Vehicle Data:\n" + json.dumps(self.account_data, sort_keys=True, indent=4, separators=(',', ': ')))
             
    
    def executeService(self, vin, service):
        # lock doors:     RDL
        # unlock doors:   RDU
        # light signal:   RLF
        # sound horn:     RHB
        # climate:        RCN

        #https://www.bmw-connecteddrive.de/api/vehicle/remoteservices/v1/WBYxxxxxxxx123456/history

        # query execution status retries and interval time
        MAX_RETRIES = 9
        INTERVAL = 10 #secs

        self.logger.debug("executing service " + service)

        serviceCodes ={
            'climate' : 'RCN', 
            'lock': 'RDL', 
            'unlock' : 'RDU',
            'light' : 'RLF',
            'horn': 'RHB'}

        command = serviceCodes[service]
        headers = {
            "Content-Type": "application/json",
            "User-agent": USER_AGENT,
            "Authorization" : "Bearer "+ self.access_token
            }

        #initalize vars
        execStatusCode=0
        remoteServiceStatus=""

        r = requests.post('{}/remoteservices/v1/{}/{}'.format(VEHICLE_API, vin, command), headers=headers,allow_redirects=True)
        if (r.status_code!= 200):
            execStatusCode = 70 #errno ECOMM, Communication error on send

        #<remoteServiceStatus>DELIVERED_TO_VEHICLE</remoteServiceStatus>
        #<remoteServiceStatus>EXECUTED</remoteServiceStatus>
        #wait max. ((MAX_RETRIES +1) * INTERVAL) = 90 secs for execution 
        if(execStatusCode==0):
            for i in range(MAX_RETRIES):
                time.sleep(INTERVAL)
                r = requests.get('{}/remoteservices/v1/{}/state/execution'.format(VEHICLE_API, vin), headers=headers,allow_redirects=True)
                #self.logger.debug("status execstate " + str(r.status_code) + " " + r.text)
                root = etree.fromstring(r.text)
                remoteServiceStatus = root.find('remoteServiceStatus').text
                #self.logger.debug(remoteServiceStatus)
                if(remoteServiceStatus=='EXECUTED'):
                    execStatusCode= 0 #OK
                    break

        if(remoteServiceStatus!='EXECUTED'):
            execStatusCode = 62 #errno ETIME, Timer expired

        return execStatusCode

    def sendMessage(self, vin, message):
        # Endpoint: https://www.bmw-connecteddrive.de/api/vehicle/myinfo/v1
        # Type: POST
        # Body:
        # {
        #   "vins": ["<VINNUMBER>"],
        #   "message": "CONTENT",
        #   "subject": "SUBJECT"
        # }

        headers = {
            "Content-Type": "application/json",
            "User-agent": USER_AGENT,
            "Authorization" : "Bearer "+ self.access_token
            }

        #initalize vars
        execStatusCode=0

        values = {'vins' : [vin],
                    'message' : message[1],
                    'subject' : message[0]
                    }
        r = requests.post('{}/myinfo/v1'.format(VEHICLE_API), data=json.dumps(values), headers=headers,allow_redirects=True)
        if (r.status_code!= 200):
            execStatusCode = 70 #errno ECOMM, Communication error on send

        return execStatusCode

