"""
UPS Monitor python plugin for Domoticz

Author: Logread, adapted from the NUT utilities (see Network UPS Tools project at http://networkupstools.org/)

Version:    0.0.1: alpha
            0.0.2: beta, changed status device to Alert v.s. multilevel switch with alarm icon
            0.1.0: 1st stable version
            0.1.1: small bux fix, edit incorrect some devices labels (AC v.s. DC)
"""
"""
<plugin key="NUT_UPS" name="UPS Monitor" author="logread" version="0.1.1" wikilink="http://www.domoticz.com/wiki/plugins/NUT_UPS.html" externallink="http://networkupstools.org/">
    <params>
        <param field="Address" label="UPS NUT Server IP Address" width="200px" required="true" default="127.0.0.1"/>
        <param field="Port" label="Port" width="40px" required="true" default="3493"/>
        <param field="Mode1" label="UPS NUT name" width="200px" required="true" default="ups"/>
        <param field="Mode6" label="Debug" width="75px">
            <options>
                <option label="True" value="Debug"/>
                <option label="False" value="Normal"  default="true" />
            </options>
        </param>
    </params>
</plugin>
"""
import Domoticz
import telnetlib
from datetime import datetime, timedelta

class BasePlugin:

    def __init__(self):
        self.debug = False
        self.error = False
        self.nextpoll = datetime.now()
        self.pollinterval = 60  #Time in seconds between two polls
        self.variables = {
            # key:              [device label, unit, value, device number, used by default]
            "battery.charge":   ["UPS Charge",          "%", None,  2, 1],
            "battery.runtime":  ["UPS Backup Time",     "s", None,  3, 1],
            "input.voltage":    ["UPS AC Input",        "V", None,  4, 0],
            "ups.load":         ["UPS Load",            "%", None,  5, 0],
            "ups.realpower":    ["UPS Power",           "W", None,  6, 0],
            "input.frequency":  ["UPS AC Frequency",   "Hz", None, 7, 0],
            "ups.status":       ["UPS Status",          "",  0,     1, 1]
        }
        return

    def onStart(self):
        Domoticz.Debug("onStart called")
        if Parameters["Mode6"] == 'Debug':
            self.debug = True
            Domoticz.Debugging(1)
            DumpConfigToLog()
        else:
            Domoticz.Debugging(0)

        # create the mandatory child device if it does not yet exist
        if 1 not in Devices:
            Domoticz.Device(Name="UPS Status Mode", Unit=1, TypeName="Alert", Used=1).Create()
            Devices[1].Update(nValue=0, sValue="") # Grey icon to reflect not yet polled

    def onStop(self):
        Domoticz.Debug("onStop called")
        Domoticz.Debugging(0)


    def onCommand(self, Unit, Command, Level, Hue):
        Domoticz.Debug(
            "onCommand called for Unit " + str(Unit) + ": Parameter '" + str(Command) + "', Level: " + str(Level))

    def onHeartbeat(self):
        now = datetime.now()
        if now >= self.nextpoll:
            self.nextpoll = now + timedelta(seconds=self.pollinterval)
            # poll the NUT UPS server
            try:
                nut = telnetlib.Telnet(host=Parameters["Address"], port=Parameters["Port"], timeout=5)
            except:
                Domoticz.Error("Cannot communicate with NAT Server at address {} / port {}".format(Parameters["Address"], port=Parameters["Port"]))
            else:
                nut.write(bytes("LIST VAR {}\n".format(Parameters["Mode1"]), "utf-8"))
                response = nut.read_until(b"\n").decode()
                if response == "BEGIN LIST VAR {}\n".format(Parameters["Mode1"]):
                    response = nut.read_until(bytes("END LIST VAR {}\n".format(Parameters["Mode1"]), "utf-8")).decode()
                    offset = len("VAR {} ".format(Parameters["Mode1"]))
                    end_offset = 0 - (len("END LIST VAR %s\n" % Parameters["Mode1"]) + 1)
                    for current in response[:end_offset].split("\n"):
                        key = str(current[offset:].split('"')[0].replace(" ", ""))
                        data = current[offset:].split('"')[1]
                        if key in self.variables:
                            self.variables[key][2] = data
                else:
                    Domoticz.Error("Error reading UPS variables: {}".format(response.replace("\n", "")))
                nut.close()
                for key in self.variables:
                    Domoticz.Debug("Variable {} = {}".format(self.variables[key][0], self.variables[key][2]))
                    if self.variables[key][2] != None:  # skip any variables not reported by the NUT server
                        self.UpdateDevice(key)  # create/update the relevant child devices

    def UpdateDevice(self, key):
        # inner function to perform the actual update
        def DoUpdate(Unit, nValue, sValue):
            try:
                Devices[Unit].Update(nValue=nValue, sValue=sValue)
            except:
                Domoticz.Error("Failed to update device unit " + str(Unit))
        # Make sure that the Domoticz device still exists (they can be deleted) before updating it
        if self.variables[key][3] in Devices:
            if key == "ups.status":
                nvalue = 1 if "OL" in self.variables[key][2] else 4
                svalue = "On Line" if "OL" in self.variables[key][2] else "Backup Power"
                if Devices[self.variables[key][3]].sValue != svalue:
                    DoUpdate(self.variables[key][3], nvalue, svalue)
            else:
                nvalue = 0
                svalue = str(self.variables[key][2])
                DoUpdate(self.variables[key][3], nvalue, svalue)
        elif key != "ups.status":
            #  create device and make a recursive call to update it
            Domoticz.Device(Name=self.variables[key][0], Unit=self.variables[key][3], TypeName="Custom",
                            Image= 17, Options={"Custom": "1;{}".format(self.variables[key][1])},
                            Used=self.variables[key][4]).Create()
            self.UpdateDevice(key)

global _plugin
_plugin = BasePlugin()

def onStart():
    global _plugin
    _plugin.onStart()

def onStop():
    global _plugin
    _plugin.onStop()

def onCommand(Unit, Command, Level, Hue):
    global _plugin
    _plugin.onCommand(Unit, Command, Level, Hue)

def onHeartbeat():
    global _plugin
    _plugin.onHeartbeat()

# Plugin specific functions ---------------------------------------------------

# Generic helper functions
def DumpConfigToLog():
    for x in Parameters:
        if Parameters[x] != "":
            Domoticz.Debug( "'" + x + "':'" + str(Parameters[x]) + "'")
    Domoticz.Debug("Device count: " + str(len(Devices)))
    for x in Devices:
        Domoticz.Debug("Device:           " + str(x) + " - " + str(Devices[x]))
        Domoticz.Debug("Device ID:       '" + str(Devices[x].ID) + "'")
        Domoticz.Debug("Device Name:     '" + Devices[x].Name + "'")
        Domoticz.Debug("Device nValue:    " + str(Devices[x].nValue))
        Domoticz.Debug("Device sValue:   '" + Devices[x].sValue + "'")
        Domoticz.Debug("Device LastLevel: " + str(Devices[x].LastLevel))
    return
