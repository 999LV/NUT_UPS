"""
UPS Monitor python plugin for Domoticz

Author: Logread, adapted from the NUT utilities (see Network UPS Tools project at http://networkupstools.org/)

Version:    0.0.1: alpha
            0.0.2: beta, changed status device to Alert v.s. multilevel switch with alarm icon
            0.1.0: 1st stable version
            0.1.1: small bux fix, edit incorrect some devices labels (AC v.s. DC)
            0.1.2: code change to avoid bug that appeared with domoticz version 3.8035
                    (devices no longer can be created and updated in the same pass
            0.1.3: code cleanup
            0.2.0: added a more comprehensive list of NUT status variables. Thanks to domoticz forum user @ycahome
            0.2.1: in case of communication error or invalid data received, stop updating devices (thanks
                    to domoticz forum user @hamster) and mark the status device as "timed out" to display in red in GUI
            0.2.2: added authentication option (thanks to domoticz forum user @copernicnic)
            0.2.3: fixed incorrect indent
"""
"""
<plugin key="NUT_UPS" name="UPS Monitor" author="logread" version="0.2.3" wikilink="http://www.domoticz.com/wiki/plugins/NUT_UPS.html" externallink="http://networkupstools.org/">
    <params>
        <param field="Address" label="UPS NUT Server IP Address" width="200px" required="true" default="127.0.0.1"/>
        <param field="Port" label="Port" width="40px" required="true" default="3493"/>
        <param field="Username" label="Username" width="200px" required="false" default=""/>
        <param field="Password" label="Password" width="200px" required="false" default=""/>
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
        self.error = True
        self.timeoutversion = False
        self.timeout = False
        self.nextpoll = datetime.now()
        self.pollinterval = 60  #Time in seconds between two polls
        self.variables = {
            # key:              [device label,         unit, value, device number, used by default]
            "ups.status":       ["UPS Status",          "",  0,     1, 1],
            "battery.charge":   ["UPS Charge",          "%", None,  2, 1],
            "battery.runtime":  ["UPS Backup Time",     "s", None,  3, 1],
            "input.voltage":    ["UPS AC Input",        "V", None,  4, 0],
            "ups.load":         ["UPS Load",            "%", None,  5, 0],
            "ups.realpower":    ["UPS Power",           "W", None,  6, 0],
            "input.frequency":  ["UPS AC Frequency",   "Hz", None,  7, 0]
        }
        self.status = {
            #code       (display,           alarm level)
            "OL":       ("ONLINE",          1), # On line (mains is present)
            "OB":       ("ONBATTERY",       4), # On battery (mains is not present)
            "LB":       ("LOWBATTERY",      4), # Low battery
            "HB":       ("HIGHBATTERY",     1), # High battery
            "RB":       ("REPLACEBATTERY",  3), # The battery needs to be replaced
            "CHRG":     ("CHARGING",        1), # The battery is charging
            "DISCHRG":  ("DISCHARGING",     3), # The battery is discharging (inverter is providing load power)
            "BYPASS":   ("BYPASS",          3), # UPS bypass circuit is active - no battery protection is available
            "CAL":      ("CALLIBRATION",    1), # UPS is currently performing runtime calibration (on battery)
            "OFF":      ("OFF",             0), # UPS is offline and is not supplying power to the load
            "OVER":     ("OVERLOAD",        4), # UPS is overloaded
            "TRIM":     ("SMARTTRIM",       3), # UPS is trimming incoming voltage (called "buck" in some hardware)
            "BOOST":    ("BOOST",           3), # UPS is boosting incoming voltage
            "FSD":      ("FORCE_SHUTDOWN",  4)  # Forced Shutdown
        }
        self.statusflags = []
        self.alert = 0
        self.telnettimeout = 2  # seconds
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
        # check if our version of domoticz supports the "TimedOut" device attribute (I cannot remember which version of
        # domoticz has this implemented, so best is to check if supported by "trial and error" method)
        try:
            temp = Devices[1].TimedOut
        except AttributeError:
            self.timeoutversion = False
        else:
            self.timeoutversion = True

    def onStop(self):
        Domoticz.Debug("onStop called")
        Domoticz.Debugging(0)


    def onHeartbeat(self):
        now = datetime.now()
        if now >= self.nextpoll:
            self.nextpoll = now + timedelta(seconds=self.pollinterval)
            # poll the NUT UPS server
            try:
                nut = telnetlib.Telnet(host=Parameters["Address"], port=Parameters["Port"], timeout=5)
            except Exception as errorcode:
                Domoticz.Error("Cannot communicate with NUT Server at {}:{} due to {}".format(
                    Parameters["Address"], Parameters["Port"], errorcode.args))
                self.error = True
                self.UpdateDevice("ups.status")  # we flag the error to the status device
            else:
                # proceed with authentication if parameters are present
                if Parameters["Username"] != "" and Parameters["Password"] != "":
                    try:
                        nut.write(bytes("USERNAME %s\n" % Parameters["Username"], "utf-8"))
                        result = nut.read_until(b"\n", self.telnettimeout).decode()
                        if result[:2] != "OK":
                            raise Exception(result.replace("\n", ""))
                        nut.write(bytes("PASSWORD %s\n" % Parameters["Password"], "utf-8"))
                        result = nut.read_until(b"\n", self.telnettimeout).decode()
                        if result[:2] != "OK":
                            raise Exception(result.replace("\n", ""))
                    except Exception as errorcode:
                        Domoticz.Error("Authentication error: {}".format(errorcode.args))
                        self.error = True
                        self.UpdateDevice("ups.status")  # we flag the error to the status device
                        nut.close()
                        return
                # read NUT variables
                nut.write(bytes("LIST VAR {}\n".format(Parameters["Mode1"]), "utf-8"))
                response = nut.read_until(b"\n", self.telnettimeout).decode()
                if response == "BEGIN LIST VAR {}\n".format(Parameters["Mode1"]):
                    response = nut.read_until(bytes("END LIST VAR {}\n".format(Parameters["Mode1"]), "utf-8"),
                                              self.telnettimeout).decode()
                    offset = len("VAR {} ".format(Parameters["Mode1"]))
                    end_offset = 0 - (len("END LIST VAR %s\n" % Parameters["Mode1"]) + 1)
                    for current in response[:end_offset].split("\n"):
                        key = str(current[offset:].split('"')[0].replace(" ", ""))
                        data = current[offset:].split('"')[1]
                        if key in self.variables:
                            self.variables[key][2] = data
                    self.error = False
                else:
                    Domoticz.Error("Error reading UPS variables: {}".format(response.replace("\n", "")))
                    self.error = True
                nut.close()
                self.statusflags = []  # reset status flags list
                self.alert = 0  # reset alarm level to 0
                for key in self.variables:
                    Domoticz.Debug("Variable {} = {}".format(self.variables[key][0], self.variables[key][2]))
                    if self.variables[key][2]:  # skip any variables not reported by the NUT server
                        self.UpdateDevice(key)  # create/update the relevant child devices


    def UpdateDevice(self, key):

        # inner function to perform the actual update
        def DoUpdate(Unit=0, nValue=0, sValue="", TimedOut=0):
            try:
                if self.timeoutversion:  # Device attribute TimeOut exists in the host domoticz version or not
                    Devices[Unit].Update(nValue=nValue, sValue=sValue, TimedOut=TimedOut)
                else:
                    Devices[Unit].Update(nValue=nValue, sValue=sValue)
            except Exception as errorcode:
                Domoticz.Error("Failed to update device unit {} due to {}".format(Unit, errorcode.args))

        # Make sure that the Domoticz device still exists (they can be deleted) before updating it
        if self.variables[key][3] in Devices:
            if key == "ups.status":
                if self.error:
                    nvalue = 0
                    svalue = "COMMUNICATION ERROR"
                    timedout = True
                else:
                    # iterate over the codes in the status string
                    for word in self.variables[key][2].split(" "):
                        try:
                            temp = self.status[word]
                        except KeyError:
                            # code not in our list of possible statuses... do not "translate" but report as is
                            self.statusflags.append(str(word))
                        else:
                            # code is known so translated and alert level updated accordingly
                            self.statusflags.append(self.status[word][0])
                            self.alert = max(self.alert, self.status[word][1])
                    nvalue = self.alert
                    svalue = " ".join(self.statusflags)
                    timedout = False
                if timedout != self.timeout:
                    self.timeout = timedout
                    timedoutchange = True
                else:
                    timedoutchange = False
                if Devices[self.variables[key][3]].sValue != svalue or timedoutchange:
                    DoUpdate(self.variables[key][3], nvalue, svalue, timedout)
            else:
                if not self.error:
                    nvalue = 0
                    svalue = str(self.variables[key][2])
                    DoUpdate(self.variables[key][3], nvalue, svalue)
        elif key != "ups.status":
            Domoticz.Device(Name=self.variables[key][0], Unit=self.variables[key][3], TypeName="Custom",
                            Image= 17, Options={"Custom": "1;{}".format(self.variables[key][1])},
                            Used=self.variables[key][4]).Create()
            # Update upon next poll (recursive call to update device broken in some domoticz versions)


global _plugin
_plugin = BasePlugin()

def onStart():
    global _plugin
    _plugin.onStart()

def onStop():
    global _plugin
    _plugin.onStop()

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
