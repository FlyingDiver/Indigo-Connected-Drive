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
import urllib
import re
import xml.etree.ElementTree as etree  
import logging

#NORTH_AMERICA:
SERVER_URL = 'b2vapi.bmwgroup.us'
#CHINA:
#SERVER_URL = 'b2vapi.bmwgroup.cn:8592'
#REST_OF_WORLD:
#SERVER_URL = 'b2vapi.bmwgroup.com'

AUTH_API = 'https://{}/gcdm/oauth/token'
VEHICLE_API = 'https://{}/api/vehicle'

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:57.0) Gecko/20100101 Firefox/57.0"

class ConnectedDrive(object):

    def __init__(self, username, password):
        self.logger = logging.getLogger("Plugin.ConnectedDrive")

        self.bmwUsername = username
        self.bmwPassword = password
        self.accessToken = None
        self.tokenExpires = None

        self.logger.debug('ConnectedDrive __init__: self.tokenExpires {}'.format(self.tokenExpires))
        try:
            if (datetime.datetime.now() >= datetime.datetime.strptime(self.tokenExpires,"%Y-%m-%d %H:%M:%S.%f")):
                newTokenNeeded = True
            else:
                newTokenNeeded = False
        except:
            self.tokenExpires = 'NULL'
            newTokenNeeded = True

        if((self.tokenExpires == 'NULL') or (newTokenNeeded == True)):
            self.generateCredentials()
        else:
            self.authenticated = True

    def generateCredentials(self):
        """
        If previous token has expired, create a new one.
        New method to get oauth token from bimmer_connected lib
        """

        headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": "124",
                "Connection": "Keep-Alive",
                "Host": SERVER_URL,
                "Accept-Encoding": "gzip",
                "Authorization": "Basic blF2NkNxdHhKdVhXUDc0eGYzQ0p3VUVQOjF6REh4NnVuNGNEanli"
                                 "TEVOTjNreWZ1bVgya0VZaWdXUGNRcGR2RFJwSUJrN3JPSg==",
                "Credentials": "nQv6CqtxJuXWP74xf3CJwUEP:1zDHx6un4cDjybLENN3kyfumX2kEYigWPcQpdvDRpIBk7rOJ",
                "User-Agent": "okhttp/2.60",
        }

        values = {
            'grant_type': 'password',
            'scope': 'authenticate_user vehicle_data remote_services',
            'username': self.bmwUsername,
            'password': self.bmwPassword,
        }

        data = urllib.urlencode(values)
        url = AUTH_API.format(SERVER_URL)
        r = requests.post(url, data=data, headers=headers,allow_redirects=False)
        if (r.status_code != 200):
            self.authenticated = False
            return
        myPayLoad=r.json()

        self.accessToken=myPayLoad['access_token']
        self.tokenExpires = datetime.datetime.now() + datetime.timedelta(seconds=myPayLoad['expires_in'])
        self.logger.debug('ConnectedDrive generateCredentials: token {}, Expires {}'.format(self.accessToken, self.tokenExpires))
        self.authenticated = True
        return

               
    def queryData(self, vin):
        headers = {
            "Content-Type": "application/json",
            "User-agent": USER_AGENT,
            "Authorization" : "Bearer "+ self.accessToken
            }

        results = {}
        url = VEHICLE_API.format(SERVER_URL)

        r = requests.get('{}/dynamic/v1/{}?offset=-60'.format(url, vin), headers=headers,allow_redirects=True)
        results['comm_status'] = r.status_code
        if (r.status_code== 200):
            map=r.json() ['attributesMap']
            for k, v in map.items():
                results[k] = v

        r = requests.get('{}/navigation/v1/'.format(url, vin), headers=headers,allow_redirects=True)
        results['comm_status'] = r.status_code
        if (r.status_code== 200):
            map=r.json()
            for k, v in map.items():
                results[k] = v

        r = requests.get('{}/efficiency/v1/'.format(url, vin), headers=headers,allow_redirects=True)
        results['comm_status'] = r.status_code
        if (r.status_code== 200):
            map=r.json() ['lastTripList']
            for k, v in map.items():
                results[k] = v

        return results

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
            "Authorization" : "Bearer "+ self.accessToken
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
            "Authorization" : "Bearer "+ self.accessToken
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

