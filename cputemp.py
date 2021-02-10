#!/usr/bin/python3

"""Copyright (c) 2019, Douglas Otwell

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import dbus
from advertisement import Advertisement
from service import Application, Service, Characteristic, Descriptor
from gpiozero import CPUTemperature
from satella.files import write_out_file_if_different
import io

GATT_CHRC_IFACE = "org.bluez.GattCharacteristic1"
GATT_CHRC_IFACE2 = "org.bluez.GattCharacteristic2"
NOTIFY_TIMEOUT = 4000


class SMOKAdvertisement(Advertisement):
    def __init__(self, index):
        Advertisement.__init__(self, index, "peripheral")
        self.add_local_name("SMOK")
        # transmit power
        self.include_tx_power = True


class SMOKService(Service):
    AUTHENTICATION_SVC_UUID = "00f25ec8-fd45-4828-a929-d658c9a86341"
    # TODO change this to ENV written while programming new RAPID module
    PASSKEY = "1234"

    def __init__(self, index):
        # Service.__init__(self, index, uuid, primary)
        # The difference between primary and secondary services is important to note.
        # A primary service is the standard type of GATT service that includes relevant,
        # standard functionality exposed by the GATT server. A secondary service, on the other hand,
        # is intended to be included only in other primary services and makes sense only as its modifier,
        # having no real meaning on its own. In practice, secondary services are rarely used.
        # oreilly.com
        Service.__init__(self, index, self.AUTHENTICATION_SVC_UUID, True)
        self.enable_operations = False
        self.add_characteristic(AuthenticationCharacteristic(self))
        self.add_characteristic(WlanConfCharacteristic(self))
        self.farenheit = True
        self.add_characteristic(TempCharacteristic(self))
        self.add_characteristic(UnitCharacteristic(self))

    def passkey_match(self, passkey):
        if passkey == self.PASSKEY:
            self.set_enable_operations(True)

    def is_farenheit(self):
        return self.farenheit

    def set_farenheit(self, farenheit):
        self.farenheit = farenheit

    def set_enable_operations(self, state):
        self.enable_operations = state

    def are_operations_enabled(self):
        return self.enable_operations

    def configure_wlan(self, value):
        # TODO Make script to configure wlan
        ssid = value.split('$')[0]
        password = value.split('$')[1]
        print("Hello")
        print(f"{ssid} + {password}")
        val = io.StringIO()
        val.write(f'''
                    ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
                    update_config=1
                    country=DE

                    network={{
                    ssid={ssid}
                    psk={password}
                    key_mgmt=WPA-PSK
                    proto=RSN WPA
                    }}
                ''')
        write_out_file_if_different('/etc/wpa_supplicant/wpa_supplicant@wlan0.conf', val.getvalue(), 'utf-8')


class TempCharacteristic(Characteristic):
    TEMP_CHARACTERISTIC_UUID = "00000002-710e-4a5b-8d75-3e5b444bc3cf"

    def __init__(self, service):
        self.notifying = False

        Characteristic.__init__(
            self, self.TEMP_CHARACTERISTIC_UUID,
            ["notify", "read"], service)
        self.add_descriptor(TempDescriptor(self))

    def get_temperature(self):
        if self.service.are_operations_enabled():
            value = []
            unit = "C"

            cpu = CPUTemperature()
            temp = cpu.temperature
            if self.service.is_farenheit():
                temp = (temp * 1.8) + 32
                unit = "F"

            strtemp = str(round(temp, 1)) + " " + unit
            for c in strtemp:
                value.append(dbus.Byte(c.encode()))

            return value
        else:
            return

    def set_temperature_callback(self):
        if self.notifying:
            value = self.get_temperature()
            self.PropertiesChanged(GATT_CHRC_IFACE, {"Value": value}, [])

        return self.notifying

    def StartNotify(self):
        if self.notifying:
            return

        if self.service.are_operations_enabled():
            self.notifying = True
            value = self.get_temperature()
            self.PropertiesChanged(GATT_CHRC_IFACE, {"Value": value}, [])
            self.add_timeout(NOTIFY_TIMEOUT, self.set_temperature_callback)
        else:
            return

    def StopNotify(self):
        self.notifying = False

    def ReadValue(self, options):
        value = self.get_temperature()
        return value


class TempDescriptor(Descriptor):
    TEMP_DESCRIPTOR_UUID = "2901"
    TEMP_DESCRIPTOR_VALUE = "CPU Temperature"

    def __init__(self, characteristic):
        Descriptor.__init__(
            self, self.TEMP_DESCRIPTOR_UUID,
            ["read"],
            characteristic)

    def ReadValue(self, options):
        value = []
        desc = self.TEMP_DESCRIPTOR_VALUE

        for c in desc:
            value.append(dbus.Byte(c.encode()))

        return value


class AuthenticationCharacteristic(Characteristic):
    AUTH_CHARACTERISTIC_UUID = "6a3139ba-da5e-433f-afb0-635b9d320f8f"

    def __init__(self, service):
        self.notifying = False
        Characteristic.__init__(
            self, self.AUTH_CHARACTERISTIC_UUID,
            ["write", "notify", "read"], service)
        self.add_descriptor(AuthenticationDescriptor(self))

    def WriteValue(self, value, options):
        val = ''.join([chr(v) for v in value])
        self.service.passkey_match(val)

    def ReadValue(self, options):
        return self.get_auth()

    def get_auth(self):
        if self.service.are_operations_enabled():
            return [dbus.Byte(str(1).encode())]
        else:
            return [dbus.Byte(str(0).encode())]

    def set_auth_callback(self):
        if self.notifying:
            value = self.get_auth()
            self.PropertiesChanged(GATT_CHRC_IFACE, {"Value": value}, [])

        return self.notifying

    def StartNotify(self):
        if self.notifying:
            return

        self.notifying = True
        value = self.get_auth()
        self.PropertiesChanged(GATT_CHRC_IFACE2, {"Value": value}, [])
        self.add_timeout(NOTIFY_TIMEOUT, self.set_auth_callback)

    def StopNotify(self):
        self.notifying = False


class AuthenticationDescriptor(Descriptor):
    AUTH_DESCRIPTOR_UUID = "2137"
    AUTH_DESCRIPTOR_VALUE = "Authentication passkey"

    def __init__(self, characteristic):
        Descriptor.__init__(self, self.AUTH_DESCRIPTOR_UUID, ["read"], characteristic)

    def ReadValue(self, options):
        value = []
        desc = self.AUTH_DESCRIPTOR_VALUE

        for c in desc:
            value.append(dbus.Byte(c.encode()))

        return value


class WlanConfCharacteristic(Characteristic):
    WIFI_CHARACTERISTIC_UUID = "a5a51086-393a-410e-83ca-dd7ab1ed70ac"

    def __init__(self, service):
        Characteristic.__init__(
            self,
            self.WIFI_CHARACTERISTIC_UUID,
            ["write"],
            service
        )
        self.add_descriptor(WlanDescriptor(self))

    def WriteValue(self, value, options):
        if self.service.are_operations_enabled():
            val = ''.join([chr(v) for v in value])
            self.service.configure_wlan(val)


class WlanDescriptor(Descriptor):
    WLAN_DESCRIPTOR_UUID = "2138"
    # not comma but $ separated
    WLAN_DESCRIPTOR_VALUE = "SSID and password, comma separated"

    def __init__(self, characteristic):
        Descriptor.__init__(self, self.WLAN_DESCRIPTOR_UUID, ["read"], characteristic)

    def ReadValue(self, options):
        value = []
        desc = self.WLAN_DESCRIPTOR_VALUE

        for c in desc:
            value.append(dbus.Byte(c.encode()))

        return value


class UnitCharacteristic(Characteristic):
    UNIT_CHARACTERISTIC_UUID = "00000003-710e-4a5b-8d75-3e5b444bc3cf"

    def __init__(self, service):
        Characteristic.__init__(
            self, self.UNIT_CHARACTERISTIC_UUID,
            ["read", "write"], service)
        self.add_descriptor(UnitDescriptor(self))

    def WriteValue(self, value, options):
        if self.service.are_operations_enabled():
            val = str(value[0]).upper()
            if val == "C":
                self.service.set_farenheit(False)
            elif val == "F":
                self.service.set_farenheit(True)

    def ReadValue(self, options):
        value = []

        if self.service.are_operations_enabled():
            if self.service.is_farenheit():
                val = "F"
            else:
                val = "C"
            value.append(dbus.Byte(val.encode()))

            return value
        else:
            return


class UnitDescriptor(Descriptor):
    UNIT_DESCRIPTOR_UUID = "2901"
    UNIT_DESCRIPTOR_VALUE = "Temperature Units (F or C)"

    def __init__(self, characteristic):
        Descriptor.__init__(
            self, self.UNIT_DESCRIPTOR_UUID,
            ["read"],
            characteristic)

    def ReadValue(self, options):
        value = []
        desc = self.UNIT_DESCRIPTOR_VALUE

        for c in desc:
            value.append(dbus.Byte(c.encode()))

        return value


app = Application()
app.add_service(SMOKService(0))
app.register()

adv = SMOKAdvertisement(0)
adv.register()

try:
    app.run()
except KeyboardInterrupt:
    app.quit()
