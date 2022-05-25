The Industrial Furnace data simulator for AWS IoT SiteWise is related to the AWS IoT blog :  `Create insights by contextualizing industrial equipment data using AWS IoT SiteWise`

## Setup

Install the required dependecies:

```
python3 -m pip install -r requirements.txt
```

## Usage
You pass the `Factory` asset id as parameter and the simulator will send sample data to all child `Furnace` assets. The simulator reads the `Setpoint` attribute value on the Furnace asset to determine the `HOLDING` temparature. This feature can be used to vary the `HOLDING` duration and inducing anomalies on the `HOLDING` duration. 

Usage : python3 furnace.py Factory-Asset-Id simulation-duration-in-seconds


