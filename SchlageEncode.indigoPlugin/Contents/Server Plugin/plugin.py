#! /usr/bin/env python
# -*- coding: utf-8 -*-

import indigo # noqa
import logging
import time
from pyschlage import Auth, Schlage
from pyschlage.exceptions import NotAuthorizedError, UnknownError

K_UPDATE_DELAY = 10.0  # delay after lock action before requesting update

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

        self._auth = None
        self._schlage = None
        self.lock_devices = {}  # dict of Indigo lock devices by device ID
        self.found_locks = {}  # dict of found Schlage lock objects by MAC address

        self.updateFrequency = float(self.pluginPrefs.get('updateFrequency', "15")) * 60.0
        self.logger.debug(f"updateFrequency = {self.updateFrequency}")
        self.next_update = time.time() + self.updateFrequency

    def validatePrefsConfigUi(self, valuesDict):    # noqa
        errorDict = indigo.Dict()

        if 'username' not in valuesDict or len(valuesDict['username'].strip()) == 0:
            errorDict['username'] = "Username cannot be empty"
        if 'password' not in valuesDict or len(valuesDict['password'].strip()) == 0:
            errorDict['password'] = "Password cannot be empty"

        updateFrequency = int(valuesDict.get('updateFrequency', 60))
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

    ########################################

    def startup(self):
        self.logger.debug("startup called")

        self._auth = Auth(self.pluginPrefs.get("username"), self.pluginPrefs.get("password"))
        self._auth.authenticate()
        self._schlage = Schlage(self._auth)
        self.get_locks()

    def shutdown(self):
        self.logger.debug("shutdown called")

    def get_locks(self):
        locks = self._schlage.locks(include_access_codes=False)
        for lock in locks:
            self.found_locks[lock.mac_address] = lock
            self.logger.debug(f"Found {lock}")

    def menu_update_locks(self):
        self.get_locks()
        return True

    def run_concurrent_thread(self):
        try:
            while True:
                self.sleep(1.0)
                if time.time() > self.next_update:
                    self.next_update = time.time() + self.updateFrequency

                    for device_id in self.lock_devices.keys():
                        self.update_lock(indigo.devices[device_id])

        except self.StopThread:
            pass

    def update_lock(self, device):

        lock = self.lock_devices[device.id]
        try:
            lock.refresh()
        except NotAuthorizedError as e:
            self.logger.error(f"pyschlage.exceptions.NotAuthorizedError: {e}")
            return
        except UnknownError as e:
            self.logger.error(f"pyschlage.exceptions.UnknownError: {e}")
            return

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
            self.logger.warning(f"{device.name}: Lock '{lock.name}' is jammed")
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
            self.next_update = time.time() + K_UPDATE_DELAY

        elif action.deviceAction == indigo.kDeviceAction.Unlock:
            self.lock_devices[device.id].unlock()
            self.next_update = time.time() + K_UPDATE_DELAY

        else:
            self.logger.warning(f"{device.name}: actionControlDimmerRelay: {device.address} does not support {action.deviceAction}")
