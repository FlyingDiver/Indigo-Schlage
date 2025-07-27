#! /usr/bin/env python
# -*- coding: utf-8 -*-

import indigo
import logging
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
        self.lock_devices = {}  # dict of lock devices by address

    ########################################

    def startup(self):
        self.logger.debug("startup called")

        self._schlage = Schlage(Auth(self.pluginPrefs.get("username"), self.pluginPrefs.get("password")))
        locks = self._schlage.locks()

        self.logger.info(f"Found {len(locks)} locks")
        self.logger.debug(f"Locks: {locks}")

    def shutdown(self):
        self.logger.debug("shutdown called")

    ########################################

    def deviceStartComm(self, device):

        self.logger.info(f"{device.name}: Starting device for lock '{device.address}'")
        self.lock_devices[device.address] = device.id

    def deviceStopComm(self, device):
        self.logger.info(f"{device.name}: Stopping device for lock '{device.address}'")
        del self.lock_devices[device.address]

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

        return retList

    def menuChanged(self, valuesDict, typeId=0, devId=0):
        self.logger.debug(f"menuChanged: {typeId = }, {devId = }, {valuesDict = }")
        return valuesDict

    ########################################
    # Relay/Dimmer Action methods
    ########################################

    def actionControlDimmerRelay(self, action, device):
        self.logger.debug(f"{device.name}: sending {action.deviceAction} ({action.actionValue}) to {device.address}")
        msg_data = {"type": "call_service", "target": {"entity_id": device.address}}

        if device.deviceTypeId == "ha_lock":
            msg_data['domain'] = 'lock'
            if action.deviceAction == indigo.kDeviceAction.TurnOn:
                msg_data['service'] = SERVICE_LOCK
                self.send_ws(msg_data)

            elif action.deviceAction == indigo.kDimmerRelayAction.TurnOff:
                msg_data['service'] = SERVICE_UNLOCK
                self.send_ws(msg_data)
            else:
                self.logger.warning(f"{device.name}: actionControlDimmerRelay: {device.address} does not support {action.deviceAction}")
