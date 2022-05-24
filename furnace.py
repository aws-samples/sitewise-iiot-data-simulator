"""
/*
 * Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
 * SPDX-License-Identifier: MIT-0
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy of this
 * software and associated documentation files (the "Software"), to deal in the Software
 * without restriction, including without limitation the rights to use, copy, modify,
 * merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
 * permit persons to whom the Software is furnished to do so.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
 * INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
 * PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
 * HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
 * OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
 * SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
 */
 
AWS IoT SiteWise industrial Furnance simulator

sqrt(x) 

"""
import json
import logging
import os
import sys
import time
import random
import uuid
import math

import boto3
from botocore.exceptions import ClientError
from ratelimiter import RateLimiter
from retrying import retry
import simpy

logger = logging.getLogger()
logger.setLevel(logging.INFO)
stream_hanlder = logging.StreamHandler(stream=sys.stdout)
formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
stream_hanlder.setFormatter(formatter)
logger.addHandler(stream_hanlder)

s3 = boto3.client("s3")
sitewise = boto3.client("iotsitewise")
MAX_REQUESTS_PER_PERIOD = 20
MAX_REQUESTS_PER_PERIOD_MODEL = 8
PERIOD_LENGTH_IN_SECONDS = 1

MIN_IDLE_TIME = 20
AVG_IDLE_TIME=1/30 #Every 30 seconds

MEASURMENT_INTERVAL = 5

STANDARD_RETRY_MAX_ATTEMPT_COUNT = 10

SETPOINT_PROP_NAME= "Setpoint"
TEMPERATURE_PROP_NAME= "Temperature"
POWER_PROP_NAME= "Power"
STATE_PROP_NAME = "State"
IDLE_STATE = 'IDLE'
HEATING_STATE = 'HEATING'
HOLDING_STATE = 'HOLDING'
COOLING_STATE = 'COOLING'

################ Utility functions #####################
def idle_time():
    """Return idle time"""
    return  MIN_IDLE_TIME + random.expovariate(AVG_IDLE_TIME)

################ Furnace simulation class ################

class Furnace(object):
    def __init__(self, sitewise_asset, env):
        self.env = env
        self.asset_id = sitewise_asset["assetId"]
        self.temperature = 0
        self.temperatureId = ""
        self.power = 0
        self.powerid = ""
        self.setpoint = 1000
        self.setpointid = ""
        self.state = IDLE_STATE
        self.stateid = ""

        #Heating curve
        self.TEMP_CURVE = [0.00, 408.25, 577.35, 707.11, 816.50, 912.87, 988.00, 1013.56, 1001.00]
        self.KW_HEATING_CURVE = [0, 7, 27, 30, 31, 29, 30, 30, 31]
        self.COOLING_CURVE = [999.00, 857.14, 375.00, 56.60, 5.96, 0.60, 0.0]

        for prop in sitewise_asset["assetProperties"]:
            if(prop["name"] == SETPOINT_PROP_NAME ):
                asset_prop_value = get_property_value_from_sitewise(sitewise_asset["assetId"], prop["id"])
                self.setpoint = asset_prop_value["propertyValue"]["value"]["doubleValue"]
                self.setpointid = prop["id"]
            elif(prop["name"] == TEMPERATURE_PROP_NAME ):
                self.temperatureId = prop["id"]
            elif(prop["name"] == POWER_PROP_NAME):
                self.powerid = prop["id"]
            elif(prop["name"] == STATE_PROP_NAME):
                self.stateid = prop["id"]
        
        #Start Simulation
        env.process(self.start())

    def start(self):
        while True:
            # Idle
            batch_put_property_value_to_sitewise(self.asset_id,self.stateid, IDLE_STATE)
            idleT = idle_time()
            logger.info("Furnace {} IDLE state updated in SiteWise at {}, weaking up in {} s".format(self.asset_id ,self.env.now, idleT))
            yield self.env.timeout(idleT)

            # Heating
            batch_put_property_value_to_sitewise(self.asset_id,self.stateid, HEATING_STATE)
            for i,t in enumerate(self.TEMP_CURVE):
                batch_put_property_value_to_sitewise(self.asset_id,self.temperatureId, t*self.setpoint/1000)
                batch_put_property_value_to_sitewise(self.asset_id,self.powerid, self.KW_HEATING_CURVE[i])
                logger.info("Furnace {} HEATING state updated in SiteWise at {} with: {} C and {} kW".format(self.asset_id ,self.env.now, t*self.setpoint/1000, self.KW_HEATING_CURVE[i]))
                yield self.env.timeout(MEASURMENT_INTERVAL)

            # Holding
            batch_put_property_value_to_sitewise(self.asset_id,self.stateid, HOLDING_STATE)
            #Adapt holding time base on reference setpoint of 760C, lower temperature needs longer heating time
            heating_iterations= math.ceil(int(16 / self.setpoint * 760))
            for i in range(heating_iterations):
                current_temp = self.setpoint + random.uniform(-0.5,0.5)
                current_KW = int(random.uniform(27,33))
                batch_put_property_value_to_sitewise(self.asset_id,self.temperatureId, current_temp)
                batch_put_property_value_to_sitewise(self.asset_id,self.powerid, current_KW)
                logger.info("Furnace {} HOLDING state updated in SiteWise at {} with {} C and {} kW".format(self.asset_id ,self.env.now, current_temp,current_KW))
                yield self.env.timeout(MEASURMENT_INTERVAL)
            #Add random wait to 
            yield self.env.timeout(random.uniform(-2.0,2.0) + (MEASURMENT_INTERVAL / 2.0) )

            # Cooling
            batch_put_property_value_to_sitewise(self.asset_id,self.stateid, COOLING_STATE)
            for t in self.COOLING_CURVE:
                batch_put_property_value_to_sitewise(self.asset_id,self.temperatureId, t*self.setpoint/1000)
                batch_put_property_value_to_sitewise(self.asset_id,self.powerid, 0)
                logger.info("Furnace {} COOLING state updated in SiteWise at {} with current temperature: {}".format(self.asset_id ,self.env.now, t*self.setpoint/1000))
                yield self.env.timeout(MEASURMENT_INTERVAL)

################### Main simulator function #######################

def main():
    model_id = ""
    simTime = 500

    if len(sys.argv) > 1:
        model_id = sys.argv[1]
        if len(sys.argv) == 3:
            simTime = int(sys.argv[2]) * 60
    else:
        print("Usage: furnace modelId [runforMin]")
        exit(-1)
  
    env = simpy.rt.RealtimeEnvironment(factor=1,strict=False)
    for asset in list_assets_generator(model_id):
        asset_summary = describe_asset_from_sitewise(asset["id"])
        setpoint_temperature = 1000
        furnace = Furnace(asset_summary , env)
        #print(json.dumps(furnace.__dict__))
        
    env.run(until=simTime)   


#################### Function to access the SiteWise API ######################
def is_retryable_error(exception):
    if isinstance(exception, ClientError):
        error_code = exception.response['Error']['Code']
        if error_code == 'ThrottlingException' or error_code == 'InternalFailureException':
            return True
    return False

def list_assets_generator(asset_model_id):
    token = None
    first_execution = True
    while first_execution or token is not None:
        first_execution = False
        asset_list_result = list_assets_from_sitewise(asset_model_id, next_token=token)
        token = asset_list_result.get("nextToken")
        for asset in asset_list_result["assetSummaries"]:
            yield asset

@RateLimiter(max_calls=MAX_REQUESTS_PER_PERIOD,
             period=PERIOD_LENGTH_IN_SECONDS)
@retry(retry_on_exception=is_retryable_error,
       stop_max_attempt_number=STANDARD_RETRY_MAX_ATTEMPT_COUNT)
def list_assets_from_sitewise(asset_model_id, next_token=None):
    if next_token is None:
        asset_lists_summary = sitewise.list_assets(
            assetModelId=asset_model_id, maxResults=250)
    else:
        asset_lists_summary = sitewise.list_assets(assetModelId=asset_model_id, nextToken=next_token, maxResults=250)
    return asset_lists_summary

@RateLimiter(max_calls=MAX_REQUESTS_PER_PERIOD,
             period=PERIOD_LENGTH_IN_SECONDS)
@retry(retry_on_exception=is_retryable_error,
       stop_max_attempt_number=STANDARD_RETRY_MAX_ATTEMPT_COUNT)
def describe_asset_from_sitewise(asset_id):
    asset_summary = sitewise.describe_asset(assetId=asset_id)
    return asset_summary

def get_property_value_from_sitewise(asset_id, property_id):
    property_value = sitewise.get_asset_property_value(assetId=asset_id, propertyId=property_id)
    return property_value

def batch_put_property_value_to_sitewise(asset_id, property_id, value):
    entries = []
    value_lable = "stringValue"
    if(isinstance(value,float)):
        value_lable = "doubleValue"
    elif(isinstance(value,int)):
        value_lable = "integerValue"
    elif(isinstance(value,bool)):
        value_lable = "booleanValue"

    entries.append(
        {
            'entryId': str(uuid.uuid4()),
            'assetId': asset_id,
            'propertyId': property_id,
            'propertyValues': [
                {
                    'value': {
                        value_lable: value
                    },
                    'timestamp' : {
                        'timeInSeconds': int(time.time())
                    },
                    'quality' : 'GOOD'
                }
            ] 
        })

    sitewise.batch_put_asset_property_value(entries=entries)

if __name__ == "__main__":
    main()
