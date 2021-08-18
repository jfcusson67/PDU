# ########################################################################### #
#        _____  _____  ___    ____________ _   _    _____ _   _ _____         #
#       /  __ \/  ___|/ _ \   | ___ \  _  \ | | |  |  __ \ | | |_   _|        #
#       | /  \/\ `--./ /_\ \  | |_/ / | | | | | |  | |  \/ | | | | |          #
#       | |     `--. \  _  |  |  __/| | | | | | |  | | __| | | | | |          #
#       | \__/\/\__/ / | | |  | |   | |/ /| |_| |  | |_\ \ |_| |_| |_         #
#        \____/\____/\_| |_/  \_|   |___/  \___/    \____/\___/ \___/         #
# ########################################################################### #
# Author:       Martin Laflamme (CSA)                                         #
# Contributors: Henry Lu (CSA), JF Cusson (CSA)                               #
# =========================================================================== #
# Written with Python 3.8.1 on Windows 10                                     #
# External Libraries:                                                         #
#   - PySimpleGUI (using tkinter) to manually create the GUI                  #
#   - matplotlib for the current graphs                                       #
# =========================================================================== #
# Version 2.00 JFC - Calculate power consumption on each line or groups of    #
# lines.                                                                      #
# ########################################################################### #

import PySimpleGUI as sg
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
import threading
import datetime
import time
import struct
import sys
import logging
import configparser
from collections import OrderedDict
from functools import partial
from queue import Queue
from socket import *

# ========================================== #
# Make sure to update this VERSION_STRING!   #
# ========================================== #
VERSION_STRING = "2.00 (June 2021)"
# ==========================================#
CONFIG_FILE = 'settings.ini'  # Path of config file
timestamp = time.strftime("%Y%m%d_%H%M%S")  # timestamp
LOG_FILE = timestamp + ".txt"  # log filename = YearMonthDay_HourMinuteSecond
USER_CONTROL = "userControl.ini"

running = True

GUI_THREAD_RATE = 500  # Thread loop rate, in milliseconds
SEND_RECEIVE_RATE = 0.5  # Thread loop rate, in seconds
WAKEUP_WAIT = 0.5  # Wait for ethernet device to wakeup, in seconds

# TODO move queues out of global scope
receiveQ = Queue(10)
sendQ = Queue(10)


# =========================================================================== #
# Main thread that handles GUI changes and parses received messages           #
# =========================================================================== #
class GUIThread:

    # ======================================================================= #
    # ======================================================================= #
    def __init__(self, master):
        self.counter = 0  # Counter for triggering auto refresh
        # Read config file
        parser = configparser.ConfigParser()
        parser.read(CONFIG_FILE)
        # Settings file has three sections
        self.configSettings = parser['settings']
        self.configDevices = parser['devices']
        self.configServices = parser['services']

        # Create services
        services = []
        for index, (key, value) in enumerate(self.configServices.items(), 1):
            services.append(Service(index, value))  # index starts at 1

        # Create settings
        # TODO use settings key as settings label
        settings = []
        settings.append(Setting('device', "Unit", self.configSettings['device']))
        settings.append(Setting('ip', "Destination IP", self.configSettings['ip']))
        settings.append(Setting('port', "Destination Port",
                                self.configSettings['port']))
        settings.append(Setting('refresh_status', "Auto Refresh\nStatus (sec)",
                                self.configSettings['refresh_status']))
        # ----------------#
        # Create the GUI #
        # ----------------#
        self.gui = GUI(master, services, settings, self.configDevices)  # Start GUI

        # -----------------------------------------------------------#
        # Create thread dedicated to sending and receiving messages #
        # -----------------------------------------------------------#
        self.sendReceiveThread = SendReceiveThread()
        self.sendReceiveThread.start()

    def run(self):
        """
        This method parses received messages, requests status updates,
        and redraws the GUI. These are run in a loop.
        """
        if not receiveQ.empty():
            rawPacket = receiveQ.get()  # Retrieve a message from the other thread
            self.gui.logger.info("Received: " + rawPacket)

            packet = rawPacket.split(",")
            header = packet[0]  # Get message header
            if header == "SRVCSET":  # Update service state
                nb, value = packet[1], packet[2]
                self.gui.services[int(nb) - 1].setState(value)
                msg = "STATUS," + packet[1]
                self.gui.send(msg)
            elif header == "STATUS":
                nb, value = packet[1], packet[2]
                self.gui.services[int(nb) - 1].setStatus(value)
            elif header == "IPSET":
                ip = '.'.join(packet[1:])
                self.gui.currentIP = ip
            elif header == "PORTSET":
                self.gui.currentPort = packet[1]
            elif header == "Resetting":
                self.gui.currentIP = "192.168.1.177"
                self.gui.currentPort = "50000"
                self.gui.settings[1].value = "192.168.1.177"
                self.gui.updateSetting(self.gui.settings[1])
                self.gui.settings[2].value = "50000"
                self.gui.updateSetting(self.gui.settings[2])
            else:
                pass

        # Automatic status retrieval
        # refreshRate = int(self.gui.getSetting('refresh_status')) * 60 * 1000
        refreshRate = int(self.gui.getSetting('refresh_status')) * 1000
        if refreshRate > 0:
            if self.counter >= refreshRate:
                self.gui.refreshStatus()
                self.counter = 0
            else:
                self.counter += GUI_THREAD_RATE

        # Check if GUI elements have been updated. If so, redraw them.
        for service in self.gui.services:
            if service.updated:
                self.gui.updateService(service)
                service.updated = False
        self.gui.master.after(GUI_THREAD_RATE, self.run)  # Loop this method


# =========================================================================== #
# Thread to receive and send messages through UDP socket.                     #
# =========================================================================== #
class SendReceiveThread(threading.Thread):

    # ======================================================================= #
    # ======================================================================= #
    def __init__(self):
        threading.Thread.__init__(self)
        self.sock = socket(AF_INET, SOCK_DGRAM)
        self.sock.settimeout(1)

    # ======================================================================= #
    # Send a command to the destination. dest must be in the form of          #
    # (IP address, port).                                                     #
    # ======================================================================= #
    def send(self, command, dest):
        self.sock.sendto(command.encode(), dest)

    # ======================================================================= #
    # Run this thread. This is called when Thread.start() is called.          #
    # ======================================================================= #
    def run(self):
        while running:
            if not sendQ.empty():
                # Expect to get command, destintion, and MAC address from the queue
                command, dest, mac = sendQ.get()
                self.send(command, dest)

            time.sleep(SEND_RECEIVE_RATE)  # Allow time for a response

            try:
                # Receive packet and place data in queue
                data, addr = self.sock.recvfrom(2048)
                receiveQ.put(data.decode())
            except:  # TODO catch timeout specifically
                pass


# =========================================================================== #
# This class represents a service on the PDU that can be activated of         #
# deactivated.                                                                #
# =========================================================================== #
class Service:

    # ======================================================================= #
    # ======================================================================= #
    def __init__(self, nb, label):
        self.nb = nb
        self.label = label
        self.status = "0.000"
        self.state = 0  # Initial state is 0, or off
        self.updated = False  # Whether the GUI element requires an update
        self.serviceButton = self.serviceLabel = self.serviceIndicator = self.statusIndicator = self.refreshButton = None

    # ======================================================================= #
    # Update the state of this service.                                       #
    # ======================================================================= #
    def setState(self, state):
        self.state = int(state)
        self.updated = True

    # ======================================================================= #
    # Update the status of this service.                                      #
    # ======================================================================= #
    def setStatus(self, status):
        self.status = status
        self.updated = True

    # ======================================================================= #
    # Update the label of the service                                         #
    # ======================================================================= #
    def setLabel(self, label):
        self.label = label
        # print(label)
        self.updated = True


# =========================================================================== #
# =========================================================================== #
class Setting:
    """"This class represents a setting that the user can modify."""

    nb = 0  # Keep a count of number of settings.

    # ======================================================================= #
    # ======================================================================= #
    def __init__(self, key, label, value):
        self.key = key
        self.label = label
        self.value = value
        self.updated = False  # Whether the setting has been updated
        self.settingButton = self.settingValue = None
        Setting.nb += 1
        self.nb = Setting.nb


# =========================================================================== #
# This class represents all of the GUI elements                               #
# =========================================================================== #
class GUI:

    # TODO: whenever an update occurs, destroy previous GUI element
    # before creating new one

    # ===============================================================
    # ===============================================================
    def __init__(self, master, services, settings, devices):
        # ===============================================================
        self.master = master
        self.services = services
        self.settings = settings
        self.devices = devices
        self.currentIP = "192.168.1.177"
        self.currentPort = "50000"

        master.title("STRATOS Power Distribution Unit Service Control")
        master.config(background="#FFFFFF")
        master.protocol("WM_DELETE_WINDOW", self.endApplication)

        # Configure default logger. Outputs to console.
        logging.basicConfig(filename=LOG_FILE, level=logging.INFO,
                            format='%(asctime)s - %(message)s')
        self.logger = logging.getLogger()

        # Settings Frame
        self.settingsFrame = tk.LabelFrame(
            master, text="Settings", bg="lightgrey", borderwidth=2, relief="groove", width=380, height=250)
        self.settingsFrame.grid(row=1, column=0, padx=10, pady=(20, 10))
        # self.settingsFrame.grid_columnconfigure(1, weight=1)
        self.settingsFrame.grid_rowconfigure(1, weight=1)

        for setting in self.settings:
            if setting.label == "Unit":
                pass
            else:
                setting.settingLabel = tk.Label(
                    self.settingsFrame, bg="lightgrey", text=setting.label, width=14)
                setting.settingLabel.grid(row=(setting.nb) - 1, column=0, pady=10)
                if setting.key == "ip":
                    self.currentIP = setting.value
                elif setting.key == "port":
                    self.currentPort = setting.value

                self.updateSetting(setting)

        resetButton = tk.Button(
            self.settingsFrame, text="Reset", width=4, command=partial(self.reset))
        resetButton.grid(row=len(self.settings) + 2, column=2,
                         padx=(0, 10), pady=(10, 15))

        # Services Frame
        self.servicesFrame = tk.LabelFrame(
            master, text="Output Control", bg="lightgrey", borderwidth=2, relief="groove", width=200, height=200)
        self.servicesFrame.grid(row=2, columnspan=2, padx=10,
                                pady=(10, 20), sticky="news")
        # self.servicesFrame.grid_columnconfigure(1, weight=1)

        ColumnHeading1 = tk.Label(
            self.servicesFrame, bg="lightgrey", text="SERVICE", width=30)
        ColumnHeading1.grid(row=1, column=1, padx=5, pady=5)

        ColumnHeading2 = tk.Label(
            self.servicesFrame, bg="lightgrey", text="STATE", width=5)
        ColumnHeading2.grid(row=1, column=2, padx=5, pady=5)

        ColumnHeading3 = tk.Label(
            self.servicesFrame, bg="lightgrey", text="Current (A)", width=10)
        ColumnHeading3.grid(row=1, column=3, padx=(10, 10), pady=5)

        for service in self.services:
            self.updateService(service)

        refreshStatusButton = tk.Button(
            self.servicesFrame, text="Refresh All", width=10, command=partial(self.refreshStatus))
        refreshStatusButton.grid(row=1, column=4, padx=(10, 10), pady=5)

        # Log Frame
        self.logFrame = tk.LabelFrame(
            master, text="TMTC Log", bg="lightgrey", borderwidth=2, relief="groove", width=100, height=200)
        self.logFrame.grid(row=1, column=1, padx=10, pady=(20, 10))
        # self.logFrame.grid_columnconfigure(0, weight=1)
        scrollbar = tk.Scrollbar(self.logFrame)
        scrollbar.grid(row=1, column=1, sticky="nsew")
        logBox = tk.Text(self.logFrame, width=55, height=14,
                         wrap="word", yscrollcommand=scrollbar.set)
        scrollbar.config(command=logBox.yview)
        logBox.configure(state='disabled')
        logBox.grid(row=1, column=0, sticky="nsew")

        # Attach handler to display logs in log box
        self.logger.addHandler(TextHandler(logBox))

    def updateSetting(self, setting, editMode=False):
        """
		Update the GUI elements related to the settings
		"""
        # Destroy existing GUI elements
        if setting.settingValue:
            setting.settingValue.destroy()
        if setting.settingButton:
            setting.settingButton.destroy()

        if editMode:

            # if setting.key == 'device':  # Device setting uses Combobox widget
            #	deviceList = list(self.devices.keys())
            #	setting.settingValue = tk.ttk.Combobox(
            #		self.settingsFrame, values=deviceList, width=12)
            #	setting.settingValue.current(deviceList.index(setting.value))
            #	setting.settingValue.configure(state="readonly")
            # else:  # Other settings use Entry widget
            setting.settingValue = tk.Entry(self.settingsFrame, width=12)
            setting.settingValue.insert(0, setting.value)
            setting.settingButton = tk.Button(
                self.settingsFrame, text="Save", width=4, command=partial(self.saveSetting, setting))
        else:
            setting.settingValue = tk.Label(
                self.settingsFrame, text=setting.value, width=15, anchor="center")
            setting.settingButton = tk.Button(
                self.settingsFrame, text="Edit", width=4, command=partial(self.updateSetting, setting, True))
        setting.settingValue.grid(row=(setting.nb - 1), column=1, padx=5, pady=5)
        setting.settingButton.grid(
            row=(setting.nb - 1), column=2, padx=(0, 10), pady=16)

    def saveSetting(self, setting):
        """
		Save setting values after editing.
		"""
        setting.value = setting.settingValue.get()
        if setting.key == "ip":
            msg = "SETIP," + setting.value
            self.send(msg)
        elif setting.key == "port":
            msg = "SETPORT," + setting.value
            self.send(msg)
        self.updateSetting(setting)

    def updateLabel(self, service):
        newEntry = newLabel.get()
        newLabel.delete(0, 'end')
        Service.setLabel(service, newEntry)
        labelScreen.destroy()

    def changeLabelScreen(self, service):
        """
		Pop up new window to enter label name
		"""
        global labelScreen
        labelScreen = tk.Toplevel()
        labelScreen.title("Change Label Name")
        labelScreen.config(bg="lightgrey")
        labelScreen.geometry("350x100")

        global newEntry
        global newLabel
        newEntry = tk.StringVar()

        newLabel = tk.Entry(labelScreen, width=50)
        newLabel.grid(row=0, padx=20, pady=10)

        # self.closeButton = tk.Button(labelScreen, text = "Save modifications",command = partial(Service.setLabel, newEntry))
        closeButton = tk.Button(
            labelScreen, text="Save modifications", command=lambda: self.updateLabel(service))
        closeButton.grid(row=1, padx=20, pady=5)
        newLabel.delete(0, 'end')

    def updateService(self, service):
        """
		Update the GUI elements of a service.
		"""
        # Destroy existing elements
        if service.serviceButton:
            service.serviceButton.destroy()
        if service.serviceIndicator:
            service.serviceIndicator.destroy()
        if service.statusIndicator:
            service.statusIndicator.destroy()
        if service.refreshButton:
            service.serviceButton.destroy()
        if service.serviceLabel:
            service.serviceLabel.destroy()

        service.serviceLabel = tk.Label(
            self.servicesFrame, text=service.label, width=40)
        service.serviceLabel.bind(
            "<Double-Button-1>", lambda event: self.changeLabelScreen(service))
        service.serviceLabel.grid(row=service.nb + 1, column=1, padx=(10, 10), pady=5)

        service.serviceButton = tk.Button(self.servicesFrame, text="Service " + str(
            service.nb), command=partial(self.setService, service))
        service.serviceButton.grid(
            row=service.nb + 1, column=0, padx=(10, 20), pady=10)

        service.serviceIndicator = tk.Canvas(
            self.servicesFrame, width=20, height=20, bg="green" if service.state else "red")
        service.serviceIndicator.grid(
            row=(service.nb + 1), column=2, padx=15, pady=5, sticky="EW")

        service.statusIndicator = tk.Label(
            self.servicesFrame, text=service.status, width=5, anchor="center")
        service.statusIndicator.grid(
            row=(service.nb + 1), column=3, padx=5, pady=5, sticky="EW")

        service.refreshButton = tk.Button(
            self.servicesFrame, text="Refresh", command=partial(self.refreshSingleStatus, service))
        service.refreshButton.grid(
            row=service.nb + 1, column=4, padx=5, pady=10)

        # set the state of the button depending on the user service access
        if serviceStatus[service.nb - 1] == "ENABLE":
            pass
        elif serviceStatus[service.nb - 1] == "DISABLE":
            service.serviceButton.config(state="disabled")
            service.refreshButton.config(state="disabled")

    def setService(self, service):
        """
		Activate or deactivate a service
		"""
        print("set service state")
        msg = "SETSRVC," + str(service.nb) + "," + \
              ("0" if service.state else "1")
        self.send(msg)

    def getSetting(self, key):
        """
		Get a setting object based on its key
		"""
        # TODO find a more efficient way to get a setting
        for setting in self.settings:
            if setting.key == key:
                return setting.value
        return None

    def refreshStatus(self):
        """
		Get the status of all services.
		"""
        for service in self.services:
            if serviceStatus[service.nb - 1] == "DISABLE":
                pass
            else:
                msg = "STATUS," + str(service.nb)
                self.send(msg)

    def refreshSingleStatus(self, service):
        """
		Get the status of 1 service.
		"""
        msg = "STATUS," + str(service.nb)
        self.send(msg)

    def reset(self):
        """
		reset ucontroller
		"""
        answer = tk.messagebox.askokcancel(
            "Warning",
            "Resetting the unit will revert the IP Address to 192.168.1.177 and the Port to 50000. Do not use during flight. Do you still want to reset the unit?")
        if answer:
            msg = "RESET"
            self.send(msg)
        else:
            pass

    def send(self, command):
        """
		Put a message, its destination, and the destination MAC in the queue
		"""
        # dest = (self.getSetting('ip'), int(self.getSetting('port')))
        dest = (self.currentIP, int(self.currentPort))
        sendQ.put((command, dest, self.devices[self.getSetting('device')]))
        self.logger.info("Sending: " + command)

    def endApplication(self):
        """
		Save settings and exit application when the X button is clicked.
		"""
        global running
        running = False  # Stop child threads
        parser = configparser.ConfigParser()

        settings = OrderedDict()
        for s in self.settings:
            settings[s.key] = s.value

        services = OrderedDict()
        for index, s in enumerate(self.services, 1):
            services['service' + str(index)] = s.label

        devices = OrderedDict()
        for key, value in self.devices.items():
            devices[key] = value

        parser.read_dict(OrderedDict((
            ('settings', settings),
            ('devices', devices),
            ('services', services),
        )))

        with open(CONFIG_FILE, 'w') as configFile:
            parser.write(configFile)

        self.master.destroy()


# =========================================================================== #
# Custom logging handler that logs messages to the text box widget.           #
# =========================================================================== #
class TextHandler(logging.Handler):

    def __init__(self, text):
        logging.Handler.__init__(self)
        self.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
        self.setLevel(logging.INFO)
        self.text = text

    def emit(self, record):
        msg = self.format(record)
        self.text.configure(state='normal')
        self.text.insert(tk.END, msg + '\n')
        self.text.see(tk.END)  # Scroll to end of textbox
        self.text.configure(state='disabled')


# =========================================================================== #
# This class deals with the user login and access to the services             #
# =========================================================================== #
class UserLogin:

    def __init__(self, master):

        self.master = master
        # master = tk.Toplevel()
        master.title("Login Screen")
        master.config(bg="lightgrey")
        master.geometry("220x200")
        global usernameEntry
        usernameEntry = tk.StringVar()

        # Set login page
        tk.Label(self.master, text="Enter Username",
                 anchor="center").grid(row=0, padx=15, pady=15)
        username = tk.Entry(self.master, textvariable=usernameEntry, width=30)
        username.grid(row=1, column=0, padx=15, pady=15)

        logButton = tk.Button(self.master, text="Login",
                              width=10, anchor="center", command=self.checkUser)
        # logButton.bind("<Return>", lambda event: self.checkUser())
        logButton.grid(row=2, padx=15, pady=15)

    # ======================================================================= #
    # Validate users                                                          #
    # ======================================================================= #
    def checkUser(self):

        parser = configparser.ConfigParser()
        parser.read(USER_CONTROL)

        # contains the satus (EN/DIS) of a service
        global serviceStatus
        serviceStatus = []

        # list of the users
        sectionList = parser.sections()

        for index in range(len(sectionList)):
            if usernameEntry.get() == sectionList[index]:
                validLabel = tk.Label(self.master, text="Valid User")
                validLabel.grid(row=3, padx=15, pady=10)
                newlist = list(parser.items(sectionList[index]))

                for control, servNum in enumerate(newlist):
                    serviceStatus.append(servNum[1])
                # user is valid
                self.master.destroy()
                break
            elif usernameEntry.get() != sectionList[index]:
                invalidLabel = tk.Label(self.master, text="Invalid Username", width=25)
                invalidLabel.grid(row=3, padx=15, pady=10)

    # print(serviceStatus)#DEBUG


# ===================================================================#
# ===================================================================#
if __name__ == "__main__":
    # ===================================================================#
    root = tk.Tk()
    # master = tk.Toplevel()

    userlogin = UserLogin(root)
    # root.protocol("WM_DELETE_WINDOW", "disable")
    root.wait_window(root)

    root = tk.Tk()
    guiThread = GUIThread(root)
    root.after(0, guiThread.run)
    root.mainloop()
