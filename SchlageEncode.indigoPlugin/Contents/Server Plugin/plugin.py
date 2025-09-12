#! /usr/bin/env python
# -*- coding: utf-8 -*-

import indigo
import logging
import time
import json
from pyschlage import Auth, Schlage

################################################################################

class Plugin(indigo.PluginBase):

    ########################################
    # Main Plugin Functions
    ########################################
    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)

        pfmt = logging.Formatter('%(asctime)s.%(msecs)03d\t[%(levelname)8s] %(name)20s.%(funcName)-25s%(msg)s', datefmt='%Y-%m-%d %H:%M:%S')
        self.plugin_file_handler.setFormatter(pfmt)
        self.logLevel = int(pluginPrefs.get("logLevel", logging.INFO))
        self.logger.debug(f"{self.logLevel=}")
        self.indigo_log_handler.setLevel(self.logLevel)
        self.plugin_file_handler.setLevel(self.logLevel)
        self.pluginPrefs = pluginPrefs

        self._schlage = None
        self.lock_devices = {}  # dict of Indigo lock devices by device ID
        self.found_locks = {}  # dict of found Schlage lock objects by MAC address

        self.update_needed = False

        self.updateFrequency = float(self.pluginPrefs.get('updateFrequency', "15")) * 60.0
        self.logger.debug(f"updateFrequency = {self.updateFrequency}")
        self.next_update = time.time() + self.updateFrequency

    def validatePrefsConfigUi(self, valuesDict):    # noqa
        errorDict = indigo.Dict()
        updateFrequency = int(valuesDict['updateFrequency'])
        if (updateFrequency < 3) or (updateFrequency > 60):
            errorDict['updateFrequency'] = "Update frequency is invalid - enter a valid number (between 3 and 60)"
        if len(errorDict) > 0:
            return False, valuesDict, errorDict
        return True

    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        if not userCancelled:
            self.logLevel = int(valuesDict.get("logLevel", logging.INFO))
            self.indigo_log_handler.setLevel(self.logLevel)
            self.plugin_file_handler.setLevel(self.logLevel)
            self.logger.debug(f"logLevel = {str(self.logLevel)}")

            self.updateFrequency = float(valuesDict['updateFrequency']) * 60.0
            self.logger.debug(f"updateFrequency = {self.updateFrequency}")
            self.next_update = time.time()
            self.update_needed = True

    ########################################

    def startup(self):
        self.logger.debug("startup called")

        self._schlage = Schlage(Auth(self.pluginPrefs.get("username"), self.pluginPrefs.get("password")))

        locks = self._schlage.locks()
        for lock in locks:
            self.found_locks[lock.mac_address] = lock
            self.logger.info(f"Found Schlage Lock: {lock.name}@{lock.mac_address} ({lock.model_name})")
            self.logger.debug(f"{lock}")

        users = self._schlage.users()
        for user in users:
            self.logger.debug(f"Schlage User: {user})")

    def shutdown(self):
        self.logger.debug("shutdown called")

    def run_concurrent_thread(self):
        self.logger.debug("run_concurrent_thread called")
        try:
            while True:
                self.sleep(10.0)
                if (time.time() > self.next_update) or self.update_needed:
                    self.update_needed = False
                    self.next_update = time.time() + self.updateFrequency

                    for device_id in self.lock_devices.keys():
                        self.update_lock(indigo.devices[device_id])

        except self.StopThread:
            pass
        self.logger.debug("run_concurrent_thread terminating")

    def update_lock(self, device):

        lock = self.lock_devices[device.id]
        lock.refresh()

        if lock.is_locked:
            device.updateStateOnServer("onOffState", True)
        else:
            device.updateStateOnServer("onOffState", False)

        # Update the device's states with the latest lock info
        update_list = [
            {'key': "device_id", 'value': lock.device_id},
            {'key': "device_type", 'value': lock.device_type},
            {'key': "name", 'value': lock.name},
            {'key': "model_name", 'value': lock.model_name},
            {'key': "connected", 'value': lock.connected},
            {'key': "is_jammed", 'value': lock.is_jammed},
            {'key': "beeper_enabled", 'value': lock.beeper_enabled},
            {'key': "auto_lock_time", 'value': lock.auto_lock_time},
            {'key': "lock_and_leave_enabled", 'value': lock.lock_and_leave_enabled},
            {'key': "firmware_version", 'value': lock.firmware_version},
            {'key': "mac_address", 'value': lock.mac_address},
            {'key': "batteryLevel", 'value': lock.battery_level, 'uiValue': f"{lock.battery_level}%"},
        ]
        device.updateStatesOnServer(update_list)

        if lock.is_jammed:
            for trigger in indigo.triggers.iter("self"):
                if trigger.pluginTypeId == "lock_jammed":
                    trigger_dict = {"schlage-lock-jammed": True,
                                    "lock-id": lock.device_id,
                                    "clock-name": lock.name}
                    indigo.trigger.execute(trigger, trigger_data=trigger_dict)

        self.logger.debug(f"{device.name}: Lock '{lock.name}' is {'locked' if lock.is_locked else 'unlocked'}, battery at {lock.battery_level}%")

    ########################################

    def deviceStartComm(self, device):

        self.logger.info(f"{device.name}: Starting device for lock '{device.address}'")
        self.lock_devices[device.id] = self.found_locks[device.address]
        self.update_lock(device)

    def deviceStopComm(self, device):
        self.logger.info(f"{device.name}: Stopping device for lock '{device.address}'")
        del self.lock_devices[device.id]

    @staticmethod
    def didDeviceCommPropertyChange(oldDevice, newDevice):
        if oldDevice.address != newDevice.address:
            return True
        return False

    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        if not userCancelled:
            self.logger.threaddebug(f"closedPrefsConfigUi: valuesDict = {valuesDict}")
            self.logLevel = int(self.pluginPrefs.get("logLevel", logging.INFO))
            self.indigo_log_handler.setLevel(self.logLevel)
            self.logger.debug(f"logLevel = {self.logLevel}")

    def get_lock_list(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.logger.debug(f"get_lock_list: {filter = }, {typeId = }, {valuesDict = }, {targetId = }")
        retList = []
        for lock in self.found_locks.values():
            retList.append((lock.mac_address, f"{lock.name} ({lock.model_name})"))
        return retList

    def menuChanged(self, valuesDict, typeId=0, devId=0):
        self.logger.debug(f"menuChanged: {typeId = }, {devId = }, {valuesDict = }")
        return valuesDict

    ########################################
    # Relay/Dimmer Action methods
    ########################################

    def actionControlDimmerRelay(self, action, device):
        self.logger.debug(f"{device.name}: sending {action.deviceAction} to {device.address}")

        if device.deviceTypeId != "lock":
            self.logger.warning(f"{device.name}: actionControlDimmerRelay: {device.address} is not a Lock device")
            return

        if action.deviceAction == indigo.kDeviceAction.Lock:
            self.lock_devices[device.id].lock()

        elif action.deviceAction == indigo.kDeviceAction.Unlock:
            self.lock_devices[device.id].unlock()
            self.update_needed = True

        else:
            self.logger.warning(f"{device.name}: actionControlDimmerRelay: {device.address} does not support {action.deviceAction}")
