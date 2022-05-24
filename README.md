AWS IoT SiteWise data simulator for industrial furnace demo related to the AWS IoT blog post Used in blog post :  `Create insights by contextualizing industrial equipment data using AWS IoT SiteWise`

You pass the `Factory` asset id as parameter and the simulator will send sample data to all child `Furnace` assets. The simulator reads the `Setpoint` attribute value on the Furnace asset to determine the `HOLDING` temparature. This feature can be used to vary the `HOLDING` duration and inducing anomalies on the `HOLDING` duration. 

Usage : python3 furnace.py <Factory Asset Id> <simulation duration in seconds>


