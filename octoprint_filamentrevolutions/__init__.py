# coding=utf-8
from __future__ import absolute_import

import octoprint.plugin
from octoprint.events import Events
import RPi.GPIO as GPIO
from time import sleep
from flask import jsonify


class ComputerVisionAnalyse(octoprint.plugin.StartupPlugin,
                                 octoprint.plugin.EventHandlerPlugin,
                                 octoprint.plugin.TemplatePlugin,
                                 octoprint.plugin.SettingsPlugin,
                                 octoprint.plugin.BlueprintPlugin):

    def initialize(self):
        self._logger.info(
            "Running RPi.GPIO version '{0}'".format(GPIO.VERSION))
        if GPIO.VERSION < "0.6":       # Need at least 0.6 for edge detection
            raise Exception("RPi.GPIO must be greater than 0.6")
        GPIO.setwarnings(False)        # Disable GPIO warnings

    @octoprint.plugin.BlueprintPlugin.route("/irregular", methods=["GET"])
    def api_get_irregular(self):
        status = "-1"
        if self.nonuniform_sensor_enabled():
            status = "0" if self.no_irregular() else "1"
        return jsonify(status=status)

    @octoprint.plugin.BlueprintPlugin.route("/overfilled", methods=["GET"])
    def api_get_overfilled(self):
        status = "-1"
        if self.overfill_sensor_enabled():
            status = "0" if self.no_overfilled() else "1"
        return jsonify(status=status)

    @property
    def nonuniform_pin(self):
        return int(self._settings.get(["nonuniform_pin"]))

    @property
    def overfill_pin(self):
        return int(self._settings.get(["overfill_pin"]))

    @property
    def nonuniform_bounce(self):
        return int(self._settings.get(["nonuniform_bounce"]))

    @property
    def overfill_bounce(self):
        return int(self._settings.get(["overfill_bounce"]))

    @property
    def nonuniform_switch(self):
        return int(self._settings.get(["nonuniform_switch"]))

    @property
    def overfill_switch(self):
        return int(self._settings.get(["overfill_switch"]))

    @property
    def mode(self):
        return int(self._settings.get(["mode"]))

    @property
    def no_irregular_gcode(self):
        return str(self._settings.get(["no_irregular_gcode"])).splitlines()
			
    @property
    def no_overfilled_gcode(self):
        return str(self._settings.get(["no_overfilled_gcode"])).splitlines()

    @property
    def nonuniform_pause_print(self):
        return self._settings.get_boolean(["nonuniform_pause_print"])

    @property
    def overfill_pause_print(self):
        return self._settings.get_boolean(["overfill_pause_print"])

    @property
    def send_gcode_only_once(self):
        return self._settings.get_boolean(["send_gcode_only_once"])

    def _setup_sensor(self):
        if self.nonuniform_sensor_enabled() or self.overfill_sensor_enabled():
            if self.mode == 0:
                self._logger.info("Using Board Mode")
                GPIO.setmode(GPIO.BOARD)
            else:
                self._logger.info("Using BCM Mode")
                GPIO.setmode(GPIO.BCM)

            if self.nonuniform_sensor_enabled():
                self._logger.info(
                    "Filament Nonuniform Sensor active on GPIO Pin [%s]" % self.nonuniform_pin)
                GPIO.setup(self.nonuniform_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            else:
                self._logger.info("nonuniform Sensor Pin not configured")

            if self.overfill_sensor_enabled():
                self._logger.info(
                    "Filament Overfill Sensor active on GPIO Pin [%s]" % self.overfill_pin)
                GPIO.setup(self.overfill_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            else:
                self._logger.info("Overfill Sensor Pin not configured")

        else:
            self._logger.info(
                "Pins not configured, won't work unless configured!")

    def on_after_startup(self):
        self._logger.info("Filament Sensors Revolutions started")
        self._setup_sensor()

    def get_settings_defaults(self):
        return dict(
            nonuniform_pin=-1,   # Default is no pin
            nonuniform_bounce=250,  # Debounce 250ms
            nonuniform_switch=1,    # Normally Open
            no_irregular_gcode='',
            nonuniform_pause_print=True,

            overfill_pin=-1,  # Default is no pin
            overfill_bounce=250,  # Debounce 250ms
            overfill_switch=1,  # Normally Closed
            no_overfilled_gcode='',
            overfill_pause_print=True,

            mode=0,    # Board Mode
            send_gcode_only_once=False,  # Default set to False for backward compatibility
        )

    def on_settings_save(self, data):
        octoprint.plugin.SettingsPlugin.on_settings_save(self, data)
        self._setup_sensor()

    def nonuniform_sensor_triggered(self):
        return self.nonuniform_triggered
			
    def overfill_sensor_triggered(self):
        return self.overfill_triggered

    def nonuniform_sensor_enabled(self):
        return self.nonuniform_pin != -1

    def overfill_sensor_enabled(self):
        return self.overfill_pin != -1

    def no_irregular(self):
        return GPIO.input(self.nonuniform_pin) != self.nonuniform_switch

    def no_overfilled(self):
        return GPIO.input(self.overfill_pin) != self.overfill_switch

    def get_template_configs(self):
        return [dict(type="settings", custom_bindings=False)]

    def on_event(self, event, payload):
        # Early abort in case of out ot filament when start printing, as we
        # can't change with a cold nozzle
        if event is Events.PRINT_STARTED:
            if self.nonuniform_sensor_enabled() and self.no_irregular():
                self._logger.info("Printing aborted: no irregular detected!")
                self._printer.cancel_print()
            if self.overfill_sensor_enabled() and self.no_overfilled():
                self._logger.info("Printing aborted: filament overfilled!")
                self._printer.cancel_print()

        # Enable sensor
        if event in (
            Events.PRINT_STARTED,
            Events.PRINT_RESUMED
        ):
            if self.nonuniform_sensor_enabled():
                self._logger.info(
                    "%s: Enabling filament nonuniform sensor." % (event))
                self.nonuniform_triggered = 0  # reset triggered state
                GPIO.remove_event_detect(self.nonuniform_pin)
                GPIO.add_event_detect(
                    self.nonuniform_pin, GPIO.BOTH,
                    callback=self.nonuniform_sensor_callback,
                    bouncetime=self.nonuniform_bounce
                )
            if self.overfill_sensor_enabled():
                self._logger.info(
                    "%s: Enabling filament overfill sensor." % (event))
                self.overfill_triggered = 0  # reset triggered state
                GPIO.remove_event_detect(self.overfill_pin)
                GPIO.add_event_detect(
                    self.overfill_pin, GPIO.BOTH,
                    callback=self.overfill_sensor_callback,
                    bouncetime=self.overfill_bounce
                )

        # Disable sensor
        elif event in (
            Events.PRINT_DONE,
            Events.PRINT_FAILED,
            Events.PRINT_CANCELLED,
            Events.ERROR
        ):
            self._logger.info("%s: Disabling irregular sensors." % (event))
            if self.nonuniform_sensor_enabled():
                GPIO.remove_event_detect(self.nonuniform_pin)
            if self.overfill_sensor_enabled():
                GPIO.remove_event_detect(self.overfill_pin)

    def nonuniform_sensor_callback(self, _):
        sleep(self.nonuniform_bounce/1000)

        # If we have previously triggered a state change we are still out
        # of filament. Log it and wait on a print resume or a new print job.
        if self.nonuniform_sensor_triggered():
            self._logger.info("Sensor callback but no trigger state change.")
            return

        if self.no_irregular():
            # Set the triggered flag to check next callback
            self.nonuniform_triggered = 1
            self._logger.info("Out of irregular!")
            if self.send_gcode_only_once:
                self._logger.info("Sending GCODE only once...")
            else:
                # Need to resend GCODE (old default) so reset trigger
                self.nonuniform_triggered = 0
            if self.nonuniform_pause_print:
                self._logger.info("Pausing print.")
                self._printer.pause_print()
            if self.no_irregular_gcode:
                self._logger.info("Sending out of irregular GCODE")
                self._printer.commands(self.no_irregular_gcode)
        else:
            self._logger.info("Irregular detected!")
            if not self.nonuniform_pause_print:
                self.nonuniform_triggered = 0

    def overfill_sensor_callback(self, _):
        sleep(self.overfill_bounce/1000)

        # If we have previously triggered a state change we are still out
        # of filament. Log it and wait on a print resume or a new print job.
        if self.overfill_sensor_triggered():
            self._logger.info("Sensor callback but no trigger state change.")
            return

        if self.no_overfilled():
            # Set the triggered flag to check next callback
            self.overfill_triggered = 1
            self._logger.info("Filament overfilled!")
            if self.send_gcode_only_once:
                self._logger.info("Sending GCODE only once...")
            else:
                # Need to resend GCODE (old default) so reset trigger
                self.overfill_triggered = 0
            if self.overfill_pause_print:
                self._logger.info("Pausing print.")
                self._printer.pause_print()
            if self.no_overfilled_gcode:
                self._logger.info("Sending overfilled GCODE")
                self._printer.commands(self.no_overfilled_gcode)
        else:
            self._logger.info("Filament not overfilled!")
            if not self.overfilled_pause_print:
                self.overfill_triggered = 0

    def get_update_information(self):
        return dict(
            filamentrevolutions=dict(
                displayName="Computer Vision Analyse",
                displayVersion=self._plugin_version,

                # version check: github repository
                #type="github_release",
                #user="RomRider",
                #repo="Octoprint-Filament-Revolutions",
                #current=self._plugin_version,

                # update method: pip
                #pip="https://github.com/RomRider/Octoprint-Filament-Revolutions/archive/{target_version}.zip"
            )
        )


__plugin_name__ = "Computer Vision Analyse"
__plugin_version__ = "1.0.0"


def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = ComputerVisionAnalyse()

    global __plugin_hooks__
    __plugin_hooks__ = {
        "octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information
    }


def __plugin_check__():
    try:
        import RPi.GPIO
    except ImportError:
        return False

    return True
