# ########################################################################### #
#        _____  _____  ___    ____________ _   _    _____ _   _ _____         #
#       /  __ \/  ___|/ _ \   | ___ \  _  \ | | |  |  __ \ | | |_   _|        #
#       | /  \/\ `--./ /_\ \  | |_/ / | | | | | |  | |  \/ | | | | |          #
#       | |     `--. \  _  |  |  __/| | | | | | |  | | __| | | | | |          #
#       | \__/\/\__/ / | | |  | |   | |/ /| |_| |  | |_\ \ |_| |_| |_         #
#        \____/\____/\_| |_/  \_|   |___/  \___/    \____/\___/ \___/         #
# ########################################################################### #
"""A GUI to operate the CSA STRATOS Power Distribution Unit

 Author:       Martin Laflamme (CSA)
 Contributors: Henry Lu (CSA), JF Cusson (CSA)
 ===========================================================================
 Features of this GUI:
 - All settings are updated internally as they are modified on the GUI, and
   when the GUI is closed (X or file->exit) they are saved in file
   "settings.ini".
 - A "PROFILE" determines which service is available to toggle or not.
   Equivalent to USER in old version. Note the new setting ACTIVE_PROFILE
   in "settings.ini", "[settings]" section, that will determine which
   profile will be active at startup of the GUI. NO NEED TO LOG IN
   ANYMORE. As before each PROFILE is specified in file "userControl.ini".
 - OUTPUT CONTROL section has been cleaned to have as less widget as
   possible, to give space to eventual graphs. The first button indicates
   in its text the service identifier (S1, S2...), the service label
   (as specified in section "[services]" in "settings.ini") and the
   service output state (ON/OFF). By pressing this button, a command will
   be sent to the PDU to toggle the state according to the current
   knowledge of the GUI. The PDU replies with a confirmation of the
   state of this service (i.e. channel). The second button displays
   the output current, and by pressing it you will request a REFRESH of
   this value on this specific channel. You can also press the column
   header button labeled "Amp." to request a REFRESH ALL.
   Gr1 and Gr2 checkbox are used to group services together for statistics
   (see "Power Usage" section). For now only two groups are available.
 - POWER USAGE section displays statistics on each group of service
   (i.e. number of Amp-hours used so far). More details TBD.
 - Note that as before, everything showned on the TMTC Log window is also
   saved on disk in a unique (to each time you start the GUI) file named
   with the date_time.txt.
 - As stated before, "settings.ini" is written back with the latest
   settings when the GUI is closed, however before modifying the file
   the GUI makes a backup copy in "settings.ini.backup". Just in case...
   So, if you open the GUI and you mess the settings and you want to
   revert, just copy back the backup file.
 - AUTO REFRESH has the same function as before, i.e. sending a request
   to update the current value of each ENABLED service

 Note on the PDU Controller itself (onboard):
 Default IP address is 192.168.1.177:50000. This value can be chanced via
 commands SETIP & SETPORT. It is stored in non-volatile memory immediately.
 There is no way to just query the ON/OFF state of a service, you need to
 assume that at startup it is OFF, and you go from there. If this GUI is
 executed when a service is already ON, it will think the output is OFF
 and therefore the first time you press on the toggle button it will just
 turn it ON again, and the TM will resynchronize your status. Full list
 of commands:

    - SETSRVC,serv_id,0/1       ==> reply = SRVCSET,serv_id,0/1
    - STATUS,serv_id            ==> reply = STATUS,serv_id,value_amp
    - RESET (resets IP address) ==> reply = "Resetting"
    - SETIP,a,b,c,d (e.g. SETIP,192,2,104,200)
                                ==> reply = IPSET,a,b,c,d
    - SETPORT,port              ==> reply = PORTSET,port
    - unrecognized command      ==> reply = CMDERROR

 ===========================================================================
 Written with Python 3.8.1 on Windows 10
 External Libraries:
   - PySimpleGUI (using tkinter) to manually create the GUI
   - matplotlib for the current graphs
 You need to install PySimpleGUI (for TKinter):

                    pip install pysimplegui

 This works from the Windows command line. You might want to update pip
 before proceeding, with:

                   python -m pip install --upgrade pip

 Documentation/demos: Demos.PySimpleGUI.org, www.PySimpleGUI.com
 ===========================================================================
 2.00 JFC - Calculate power consumption on each line or groups of
            lines.
 2.03 JFC - First complete prototype. Corrected incoherences between UTC and
            non-UTC timestamps
 2.04 JFC - Added Wh offset
"""
import configparser
import os
import shutil
import socket
from collections import OrderedDict
import time
from datetime import datetime, timezone
import PySimpleGUI as sg
from socket import *

# ========================================== #
# Make sure to update this VERSION_STRING!   #
# ========================================== #
VERSION_STRING = "2.04 (August 2021)"
# ========================================== #
DEBUG = False                                # Set to false in operation
CONFIG_FILE = "settings.ini"                # Path of config file
CONFIG_FILE_BACKUP = "settings.ini.backup"  # Just in case...
USER_CONTROL = "userControl.ini"
# timestamp = time.strftime("%Y%m%d_%H%M%S")  # timestamp
# LOG_FILE = timestamp + ".txt"  # log filename = YearMonthDay_HourMinuteSecond

_S1_ = 0    # Use these for indices, to reference services
_S2_ = 1
_S3_ = 2
_S4_ = 3
_S5_ = 4
_S6_ = 5
_HEATERS_ = 6

global in_flight
global battery
global window
global log                                  # Glogal custom log object (a simple one we define in this file)
global output                               # Global dictionary to keep data & state about each output
global group1, group2                       # Global dictionary to keep data & state about each group of outputs


# ########################################################################### #
#                           ██████╗ ██╗   ██╗██╗                              #
#                          ██╔════╝ ██║   ██║██║                              #
#                          ██║  ███╗██║   ██║██║                              #
#                          ██║   ██║██║   ██║██║                              #
#                          ╚██████╔╝╚██████╔╝██║                              #
#                           ╚═════╝  ╚═════╝ ╚═╝                              #
# ########################################################################### #
def make_window(theme, profiles, settings, services, devices):
    """Creates the GUI
    """
    sg.theme(theme)
    menu_def = [['&Application', ['E&xit']],
                ['&Help', ['&About']]]

    # ######################################################################### #
    # Creates the "settings" frame. The PROFILE drop down is fed with all users #
    # identified in the userControl.ini file, and the active one is forced from #
    # the field "profile" in section "settings" in settings.ini file. The       #
    # profile will determine which services (power line control) are available  #
    # for toggling on the GUI. Statistics on non-available services will still  #
    # be displayed (TODO: Verify if this is desirable)                          #
    # ######################################################################### #
    device_list = []
    for device in devices.keys():
        device_list.append(device)
    settings_layout = [
        [sg.Text('Dest. IP:', size=(12, 1)), sg.Input(key='-IPADDRESS-', size=(15, 1), enable_events=True, default_text=settings['ip'])],
        [sg.Text('Dest. Port:', size=(12, 1)), sg.Input(key='-TXPORT-', size=(15, 1), enable_events=True, default_text=settings['dest_port'])],
        # [sg.Text('Recv. Port:', size=(12, 1)), sg.Input(key='-RXPORT-', size=(15, 1), enable_events=True, disabled=True, default_text=settings['recv_port'])],
        [sg.Text('Auto Refresh (S):', size=(12, 1)), sg.Input(key='-AUTOREFRESH-', size=(15, 1), enable_events=True, default_text=settings['refresh_status'])],
        [sg.Text('Active Profile:', size=(12, 1)), sg.Combo(profiles.sections(), key='-PROFILE-', size=(15, 1), enable_events=True, default_value=settings['active_profile'])]
                       ]
    settings_frame = sg.Frame('Settings (settings.ini)', settings_layout)

    log_layout = [
        [sg.Text('Log File:'), sg.Input(key='-LOG_FILE-', size=(35, 1)), sg.Button('SET', key='-LOG_FILE_SET-')]
         # sg.Text('Earliest event at:'), sg.Input(key='-EARLIEST_EVENT-', size=(15, 1)), sg.Text('Current time:'), sg.Input(key='-CURRENT_TIME-', size=(15, 1))]
         # sg.Text('UTC:'), sg.Input(key='-CURRENT_TIME-', size=(20, 1))]
    ]
    log_frame = sg.Frame('Log', log_layout)

    tmtclog_layout = [[sg.Multiline(size=(100, 8), autoscroll=True, key='-TMTCLOG-')]]
    tmtclog_frame = sg.Frame('TMTC Log', tmtclog_layout)

    status_layout = [
        [sg.Button('START FLIGHT', key='-FLIGHT_TOGGLE-'), sg.Text('IDLE', key='-STATUS-', size=(10, 1), justification='center'), sg.Text('UTC:'), sg.Input(key='-CURRENT_TIME-', size=(20, 1))]
    ]
    status_frame = sg.Frame('Status', status_layout)

    outputctrl_layout = [
        [sg.Text('SERVICE (Press to toggle)', size=(40, 1), justification='center'), sg.Button('Amp.', key='-REFRESHALL-', size=(6, 1)), sg.Text('Gr1'), sg.Text('Gr2')],
        [sg.Button(get_service_text_status(_S1_, services), key='-S1TOGGLE-', size=(40, 1)), sg.Button('0.000', key='-S1REFRESH-', size=(6, 1)), sg.Checkbox('', key='-S1GR1-', enable_events=True), sg.Checkbox('', key='-S1GR2-', enable_events=True)],
        [sg.Button(get_service_text_status(_S2_, services), key='-S2TOGGLE-', size=(40, 1)), sg.Button('0.000', key='-S2REFRESH-', size=(6, 1)), sg.Checkbox('', key='-S2GR1-', enable_events=True), sg.Checkbox('', key='-S2GR2-', enable_events=True)],
        [sg.Button(get_service_text_status(_S3_, services), key='-S3TOGGLE-', size=(40, 1)), sg.Button('0.000', key='-S3REFRESH-', size=(6, 1)), sg.Checkbox('', key='-S3GR1-', enable_events=True), sg.Checkbox('', key='-S3GR2-', enable_events=True)],
        [sg.Button(get_service_text_status(_S4_, services), key='-S4TOGGLE-', size=(40, 1)), sg.Button('0.000', key='-S4REFRESH-', size=(6, 1)), sg.Checkbox('', key='-S4GR1-', enable_events=True), sg.Checkbox('', key='-S4GR2-', enable_events=True)],
        [sg.Button(get_service_text_status(_S5_, services), key='-S5TOGGLE-', size=(40, 1)), sg.Button('0.000', key='-S5REFRESH-', size=(6, 1)), sg.Checkbox('', key='-S5GR1-', enable_events=True), sg.Checkbox('', key='-S5GR2-', enable_events=True)],
        [sg.Button(get_service_text_status(_S6_, services), key='-S6TOGGLE-', size=(40, 1)), sg.Button('0.000', key='-S6REFRESH-', size=(6, 1)), sg.Checkbox('', key='-S6GR1-', enable_events=True), sg.Checkbox('', key='-S6GR2-', enable_events=True)]
    ]
    outputctrl_frame = sg.Frame('Output Control', outputctrl_layout)

    pwrusage_layout = [
        [sg.Checkbox('On Power Supply', key='-ON_POWER_SUPPLY-', enable_events=True)],
        [
            sg.Text('Nominal Voltage:'), sg.Input(key='-NOMINAL_VOLTAGE-', size=(5, 1), pad=(0, 0), default_text=settings['nominal_voltage'], disabled=True), sg.Text('V'),
            sg.Text('Total Battery Power:'), sg.Input(key='-TOTAL_BATTERY_POWER-', size=(5, 1), pad=(0, 0), default_text=settings['total_battery_power'], disabled=True), sg.Text('Wh'),
            sg.Text('Offset:'), sg.Input(key='-OFFSET_WH-', size=(5, 1), pad=(0, 0)), sg.Text('Wh')
        ],
        [
            sg.Text('Heater(s) consumption:'), sg.Input(key='-HEATERS_CONSUMPTION-', size=(5, 1), pad=(0, 0), default_text=settings['heaters_consumption'], disabled=True), sg.Text('A'),
            sg.Text('Heater Running Sum:'), sg.Text('n/a', key='-HEATERS_WH-', size=(10, 1), pad=(0, 0), background_color='white', text_color='black'), sg.Text('Wh')
        ],
        [
            sg.Text('Group #1:', size=(10, 1)), sg.Input(key='-GR1_A-', size=(10, 1), pad=(0, 0)), sg.Text('A'),
            sg.Text('Limit:'), sg.Input(key='-GR1_LIMIT_WH-', size=(10, 1), pad=(0, 0), default_text=settings['group1_limit']), sg.Text('Wh'),
            sg.Text('Running Sum:'), sg.Input(key='-GR1_WH-', size=(10, 1), pad=(0, 0)), sg.Text('Wh')
        ],
        [
            sg.Text('Group #2:', size=(10, 1)), sg.Input(key='-GR2_A-', size=(10, 1), pad=(0, 0)), sg.Text('A'),
            sg.Text('Limit:'), sg.Input(key='-GR2_LIMIT_WH-', size=(10, 1), pad=(0, 0), default_text=settings['group2_limit']), sg.Text('Wh'),
            sg.Text('Running Sum:'), sg.Input(key='-GR2_WH-', size=(10, 1), pad=(0, 0)), sg.Text('Wh')
        ],
        [sg.Text('Total:', size=(10, 1)), sg.Text('n/a', key='-GROUPS_A-', size=(10, 1), pad=(0, 0), background_color='white', text_color='black'), sg.Text('A')]
    ]
    pwrusage_frame = sg.Frame('Power Usage', pwrusage_layout)

    battery_status_layout = [
        # [sg.Text('Estimated\nTotal\nAvailable\nPower')],
        [sg.Text('n/a', key='-BATTERY_WH-', background_color='white', text_color='black', size=(10, 1), pad=(0, 0)), sg.Text('Wh')],
        [sg.ProgressBar(100, key='-BATTERY_PROGRESS-', orientation='v', size=(17, 15), bar_color=('green', 'grey'), style='classic', border_width=15)],
        [sg.Text('n/a', key='-BATTERY_PERCENT-', background_color='white', text_color='black', size=(10, 1), pad=(0, 0)), sg.Text('%')],
    ]
    battery_status_frame = sg.Frame('Battery Status', battery_status_layout)

    col1 = sg.Column([[settings_frame]])
    col2 = sg.Column([[tmtclog_frame]])
    col3 = sg.Column([[outputctrl_frame]])
    col4 = sg.Column([[pwrusage_frame, battery_status_frame]])
    col5 = sg.Column([[log_frame, status_frame]])

    layout = [[sg.Menu(menu_def, key='-MENU-')], [col5], [col1, col2], [col3, col4]]

    new_window = sg.Window('STRATOS PDU Service Control '+VERSION_STRING, layout)
    new_window.finalize()  # Needed so that we can immediately update widget states

    new_window['-S1GR1-'].update(services['service1_group1'] == 'True')
    new_window['-S1GR2-'].update(services['service1_group2'] == 'True')
    new_window['-S2GR1-'].update(services['service2_group1'] == 'True')
    new_window['-S2GR2-'].update(services['service2_group2'] == 'True')
    new_window['-S3GR1-'].update(services['service3_group1'] == 'True')
    new_window['-S3GR2-'].update(services['service3_group2'] == 'True')
    new_window['-S4GR1-'].update(services['service4_group1'] == 'True')
    new_window['-S4GR2-'].update(services['service4_group2'] == 'True')
    new_window['-S5GR1-'].update(services['service5_group1'] == 'True')
    new_window['-S5GR2-'].update(services['service5_group2'] == 'True')
    new_window['-S6GR1-'].update(services['service6_group1'] == 'True')
    new_window['-S6GR2-'].update(services['service6_group2'] == 'True')

    return new_window


# ########################################################################### #
# ########################################################################### #
def log_file_set_popup(filename):
    layout = [
        [sg.Text('Log file name:')],
        [sg.Input(key='-NEW_LOG_FILE-', size=(40, 1), default_text=filename)],
        [sg.Button('OK'), sg.Button('CANCEL')]
    ]
    popup = sg.Window('LOG FILE', layout).Finalize()
    is_cancel = True
    while True:
        event, values = popup.read()
        if event in (sg.WINDOW_CLOSED, 'CANCEL'):
            break
        elif event == 'OK':
            is_cancel = False
            break
        else:
            pass
    popup.close()
    if values and values['-NEW_LOG_FILE-']:
        print("Selecting " + values['-NEW_LOG_FILE-'])
        return is_cancel, values['-NEW_LOG_FILE-']
    else:
        return is_cancel, 'PDU_default_log.txt'


# ########################################################################### #
# ########################################################################### #
def log_file_exists_popup(filename):
    layout = [
        [sg.Text(f"Log file {filename} exists and contains data, do you want to load this data now?")],
        [sg.Button('YES-LOAD'), sg.Button('NO-DO NOT LOAD'), sg.Button('CANCEL-DO NOT SELECT THIS FILE')]
    ]
    popup = sg.Window('LOG FILE EXISTS', layout).Finalize()
    is_cancel = True
    is_load = False
    while True:
        event, values = popup.read()
        if event in (sg.WINDOW_CLOSED, 'CANCEL-DO NOT SELECT THIS FILE'):
            break
        elif event == 'YES-LOAD':
            is_cancel = False
            is_load = True
            break
        elif event == 'NO-DO NOT LOAD':
            is_cancel = False
            is_load = False
            break
        else:
            pass
    popup.close()
    return is_cancel, is_load


# ########################################################################### #
#                    ███╗   ███╗ █████╗ ██╗███╗   ██╗                         #
#                    ████╗ ████║██╔══██╗██║████╗  ██║                         #
#                    ██╔████╔██║███████║██║██╔██╗ ██║                         #
#                    ██║╚██╔╝██║██╔══██║██║██║╚██╗██║                         #
#                    ██║ ╚═╝ ██║██║  ██║██║██║ ╚████║                         #
#                    ╚═╝     ╚═╝╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝                         #
# ########################################################################### #
def main():
    """ Main entry point
    """
    global window, log, in_flight, battery
    global output, group1, group2  # output_current_accumulated_group1, output_current_accumulated_group2

    # -------------------------------------------------- #
    # Always starts with state IDLE (i.e. NOT in flight) #
    # -------------------------------------------------- #
    in_flight = False

    battery = {'nominal_voltage': 28.0, 'heaters_consumption': 0.9, 'max_wh': 3750, 'progress_wh': 3750, 'progress_percent': 100}
    output = {'current': [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
              'last_update_time': [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],  # Note: 7th item is for heater's last update
              # 'A': [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
              'accumulated_Wh': [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],    # Note: 7th item is for heater's accumulated Wh
              'is_on': [False, False, False, False, False, False]
              }
    group1 = {'A': 0.0, 'Wh': 0.0, 'limit_Wh': 0.0}
    group2 = {'A': 0.0, 'Wh': 0.0, 'limit_Wh': 0.0}

    # --------------------------------------------------- #
    # Reads all settings from the configuration file, and #
    # user profiles from another file.                    #
    # --------------------------------------------------- #
    settings, services, devices = read_settings_from_file(CONFIG_FILE)
    profiles = read_users(USER_CONTROL)

    # TODO: Validate settings before populating battery dictionary!!
    battery['nominal_voltage'] = settings['nominal_voltage']
    battery['heaters_consumption'] = settings['heaters_consumption']
    battery['max_wh'] = settings['total_battery_power']
    battery['progress_wh'] = settings['total_battery_power']

    # ------------------------------------------------------------#
    # Creates the main window, with the default PySimpleGUI theme #
    # ------------------------------------------------------------#
    window = make_window(sg.theme(), profiles, settings, services, devices)

    # ------------------------------------ #
    # Instantiate our simple custom logger #
    # ------------------------------------ #
    log = Logger()
    window['-LOG_FILE-'].update(settings['log_file'])
    is_selected_new = True
    while is_selected_new:
        event, values = window.read(timeout=1)  # ms
        is_selected_new, filename = log.set_filename(values['-LOG_FILE-'])
        window['-LOG_FILE-'].update(filename)
    settings['log_file'] = filename
    log.event("STARTING PDU CONTROLLER GUI "+VERSION_STRING)

    # ==================================================== #
    # Now disable the capacity to toggle services that are #
    # marked as DISABLED in the active profile.            #
    # ==================================================== #
    update_profile(profiles, settings)

    # ========================================================= #
    # Setup the network (Ethernet socket for exchanging packets #
    # with the device)                                          #
    # NOTE: There is no sock.bind(ipadd,port) defined here, I   #
    # assume this works because the socket will bind automati-  #
    # cally to whatever address will be used to SEND, such that #
    # the same PORT will be used for listening. TBC.            #
    # ========================================================= #
    sock = socket(AF_INET, SOCK_DGRAM)
    sock.settimeout(0.01)                   # Timeout of 10ms
    if settings['is_dual_port'] == 'True':
        print("Setting receive port. If this causes an error, set is_dual_port to False in settings.ini")
        sock.bind((settings['ip'], int(settings['recv_port'])))
    # sock.setblocking(False)   Seems we do not need this, rely on timeout

    # ---------------------------------------------------- #
    # This is the main loop where the events are processed #
    # Note that "window" will return events when they come #
    # but if there are none "window" will block 100ms.     #
    # Then, we'll peek on the Ethernet socket to see if we #
    # have a datagram packet coming in. The socket timeout #
    # value is set to 10ms. Note that it could probably be #
    # set as low as 1ms with no problem, since it will not #
    # be called at more than 10Hz.                         #
    # ---------------------------------------------------- #
    start = datetime.utcnow().timestamp()  # fraction of seconds since 1970
    is_first_refresh_done = False
    while True:
        event, values = window.read(timeout=100)  # ms
        if not is_first_refresh_done:
            refresh_telemetry_stats_on_gui(services, values)
            is_first_refresh_done = True
        # if event not in (sg.TIMEOUT_EVENT, sg.WIN_CLOSED):                Debug code
        #     print('============ Event = ', event, ' ==============')
        #     print('-------- Values Dictionary (key=value) --------')
        #     for key in values:
        #         print(key, ' = ', values[key])

        # ..................................................................... EXIT
        if event in (None, 'Exit'):
            print("Clicked Exit!")
            break

        # ----------------------------------------- #
        # Regenerate those at every iteration, just #
        # in case they changed at some point.       #
        # ----------------------------------------- #
        ip = values['-IPADDRESS-']
        if values['-TXPORT-'].isdigit():
            port = int(values['-TXPORT-'])
        destination = (ip, port)
        # ------------------------------------------------ #
        # Then see which event was triggered (if there was #
        # one), and proceed with what we need to do.       #
        # ------------------------------------------------ #
        # ..................................................................... This executes when no event
        if event == sg.TIMEOUT_EVENT:
            # --------------------------------------------------- #
            # First we check for expiration of AUTO-REFRESH delay #
            # --------------------------------------------------- #
            delay_sec = int(datetime.utcnow().timestamp() - start)
            auto_refresh_timer = values['-AUTOREFRESH-']
            if auto_refresh_timer.isdigit():
                if delay_sec >= int(values['-AUTOREFRESH-']):
                    send_refresh_all(sock, profiles, settings, destination)
                    start = datetime.utcnow().timestamp()     # restart the timer delay
                    # ----------------------------------------- #
                    # Take the opportunity to verify if heaters #
                    # accumulated some power consumption.       #
                    # ----------------------------------------- #
                    if in_flight:
                        if float(output['last_update_time'][_HEATERS_]) > 0.0:
                            delta = datetime.utcnow().timestamp() - output['last_update_time'][_HEATERS_]
                            if float(delta) > 0.0:
                                output['accumulated_Wh'][_HEATERS_] += (float(battery['heaters_consumption']) * (delta / 3600.0) * float(battery['nominal_voltage']))
                        output['last_update_time'][_HEATERS_] = datetime.utcnow().timestamp()
                    window['-HEATERS_WH-'].update(f"{output['accumulated_Wh'][_HEATERS_]:.3f}")
            # -------------------------------------------------------- #
            # Now we look at the network to see if we have a telemetry #
            # packet from the PDU to process.                          #
            # -------------------------------------------------------- #
            try:
                data, address = sock.recvfrom(2048)    # Will not block, timeout = 10ms
                # --------------------------------------------------- #
                # The logger will add the standard header, so this is #
                # what we take to parse the telemetry (since we need  #
                # the timestamp, which is not provided by the PDU.    #
                # --------------------------------------------------- #
                full_packet = log.rx(data.decode())
                print(full_packet)
                parse_telemetry(full_packet, is_save_to_log_file=True)
                refresh_telemetry_stats_on_gui(services, values)
            except:
                pass
            # ---------------------------------------- #
            # Update running time clock UTC and status #
            # ---------------------------------------- #
            window['-CURRENT_TIME-'].update(datetime.utcnow().isoformat(sep=' ', timespec='seconds'))
            if in_flight:
                window['-STATUS-'].update('IN FLIGHT', text_color='white', background_color='green')
            else:
                window['-STATUS-'].update('IDLE', text_color='white', background_color='red')
        # ..................................................................... ABOUT
        elif event == 'About':
            sg.popup('An application to control the CSA STRATOS Power Distribution Unit',
                     'VERSION: '+VERSION_STRING,
                     '(C) Canadian Space Agency 2021')
        # ..................................................................... SET LOG FILE
        elif event == '-LOG_FILE_SET-':
            proposed_filename = time.strftime("%Y%m%d_%H%M%S") + "-PDU LOG.txt"
            is_cancel, log_filename = log_file_set_popup(proposed_filename)
            if not is_cancel:
                log.set_filename(log_filename)
                window['-LOG_FILE-'].update(log_filename)
                settings['log_file'] = log_filename
        # ..................................................................... FLIGHT TOGGLE
        elif event == '-FLIGHT_TOGGLE-':
            if in_flight:               # There must be a way just to toggle...
                in_flight = False
                output['last_update_time'][_HEATERS_] = datetime.utcnow().timestamp()
                log.event("END_FLIGHT", is_save_to_log_file=True)     #NOTE: DO NOT CHANGE, "END_FLIGHT" is a keyword
                window['-FLIGHT_TOGGLE-'].update('START FLIGHT')
            else:
                in_flight = True
                log.event("START_FLIGHT", is_save_to_log_file=True)  # NOTE: DO NOT CHANGE, "START_FLIGHT" is a keyword
                window['-FLIGHT_TOGGLE-'].update('END FLIGHT')
        # ..................................................................... CHANGED DEVICE
        # elif event == '-DEVICE-':
        #     log.debug("Clicked Device Button to select: "+values['-DEVICE-'])
        #     settings['device'] = values['-DEVICE-']
        # ..................................................................... CHANGED IP ADDRESS
        elif event == '-IPADDRESS-':
            log.debug("[GROUND] Changed IP Address to: "+values['-IPADDRESS-'])
            settings['ip'] = values['-IPADDRESS-']
        # ..................................................................... CHANGED IP PORT
        elif event == '-TXPORT-':
            if values['-TXPORT-'].isdigit():
                log.debug("[GROUND] Changed IP Port to: "+values['-TXPORT-'])
                settings['port'] = values['-TXPORT-']
        # ..................................................................... AUTO REFRESH TIMER VALUE CHANGED
        elif event == '-AUTOREFRESH-':
            if values['-AUTOREFRESH-'].isdigit():
                log.debug("Changed Auto Refresh Status to: "+values['-AUTOREFRESH-'])
                settings['refresh_status'] = values['-AUTOREFRESH-']
        # ..................................................................... CLICKED "REFRESH ALL"
        elif event == '-REFRESHALL-':
            log.debug("Clicked REFRESH ALL")
            send_refresh_all(sock, profiles, settings, destination)
        # ..................................................................... SELECTED A NEW PROFILE
        elif event == '-PROFILE-':
            log.debug("Clicked Profile Button to select: "+values['-PROFILE-'])
            settings['active_profile'] = values['-PROFILE-']
            update_profile(profiles, settings)
        # ..................................................................... CLICKED TOGGLE S1
        elif event == '-S1TOGGLE-':
            log.debug("Clicked to toggle SERVICE 1 state")
            if output['is_on'][_S1_]:
                cmd = "SETSRVC,1,0"     # If ON, send command to turn OFF
            else:
                cmd = "SETSRVC,1,1"     # If OFF, send command to turn ON
            send_command(sock, cmd, destination)
        # ..................................................................... CLICKED TOGGLE S2
        elif event == '-S2TOGGLE-':
            log.debug("Clicked to toggle SERVICE 2 state")
            if output['is_on'][_S2_]:
                cmd = "SETSRVC,2,0"     # If ON, send command to turn OFF
            else:
                cmd = "SETSRVC,2,1"     # If OFF, send command to turn ON
            send_command(sock, cmd, destination)
        # ..................................................................... CLICKED TOGGLE S3
        elif event == '-S3TOGGLE-':
            log.debug("Clicked to toggle SERVICE 3 state")
            if output['is_on'][_S3_]:
                cmd = "SETSRVC,3,0"     # If ON, send command to turn OFF
            else:
                cmd = "SETSRVC,3,1"     # If OFF, send command to turn ON
            send_command(sock, cmd, destination)
        # ..................................................................... CLICKED TOGGLE S4
        elif event == '-S4TOGGLE-':
            log.debug("Clicked to toggle SERVICE 4 state")
            if output['is_on'][_S4_]:
                cmd = "SETSRVC,4,0"     # If ON, send command to turn OFF
            else:
                cmd = "SETSRVC,4,1"     # If OFF, send command to turn ON
            send_command(sock, cmd, destination)
        # ..................................................................... CLICKED TOGGLE S5
        elif event == '-S5TOGGLE-':
            log.debug("Clicked to toggle SERVICE 5 state")                                              # This COPY-PASTE stuff is
            if output['is_on'][_S5_]:                                                                           # looking for trouble
                cmd = "SETSRVC,5,0"     # If ON, send command to turn OFF                               # TODO: Find another way
            else:
                cmd = "SETSRVC,5,1"     # If OFF, send command to turn ON
            send_command(sock, cmd, destination)
        # ..................................................................... CLICKED TOGGLE S6
        elif event == '-S6TOGGLE-':
            log.debug("Clicked to toggle SERVICE 6 state")
            if output['is_on'][_S6_]:
                cmd = "SETSRVC,6,0"     # If ON, send command to turn OFF
            else:
                cmd = "SETSRVC,6,1"     # If OFF, send command to turn ON
            send_command(sock, cmd, destination)
        # ..................................................................... CLICKED REFRESH S1
        elif event == '-S1REFRESH-':
            log.debug("Clicked to refresh SERVICE 1 status")
            send_command(sock, "STATUS,1", destination)
        # ..................................................................... CLICKED REFRESH S2
        elif event == '-S2REFRESH-':
            log.debug("Clicked to refresh SERVICE 2 status")
            send_command(sock, "STATUS,2", destination)
        # ..................................................................... CLICKED REFRESH S3
        elif event == '-S3REFRESH-':
            log.debug("Clicked to refresh SERVICE 3 status")
            send_command(sock, "STATUS,3", destination)
        # ..................................................................... CLICKED REFRESH S4
        elif event == '-S4REFRESH-':
            log.debug("Clicked to refresh SERVICE 4 status")
            send_command(sock, "STATUS,4", destination)
        # ..................................................................... CLICKED REFRESH S5
        elif event == '-S5REFRESH-':
            log.debug("Clicked to refresh SERVICE 5 status")
            send_command(sock, "STATUS,5", destination)
        # ..................................................................... CLICKED REFRESH S6
        elif event == '-S6REFRESH-':
            log.debug("Clicked to refresh SERVICE 6 status")
            send_command(sock, "STATUS,6", destination)
        # .....................................................................
        elif event == "Set Theme":
            # TODO: See if we want to implement this. For now it is not.
            log.debug("Clicked Set Theme!")
            theme_chosen = values['-THEME LISTBOX-'][0]
            print("[LOG] User Chose Theme: " + str(theme_chosen))
            window.close()
            window = make_window(theme_chosen)
        else:
            services['service1_group1'] = f"{values['-S1GR1-']}"
            services['service1_group2'] = f"{values['-S1GR2-']}"
            services['service2_group1'] = f"{values['-S2GR1-']}"
            services['service2_group2'] = f"{values['-S2GR2-']}"
            services['service3_group1'] = f"{values['-S3GR1-']}"
            services['service3_group2'] = f"{values['-S3GR2-']}"
            services['service4_group1'] = f"{values['-S4GR1-']}"
            services['service4_group2'] = f"{values['-S4GR2-']}"
            services['service5_group1'] = f"{values['-S5GR1-']}"
            services['service5_group2'] = f"{values['-S5GR2-']}"
            services['service6_group1'] = f"{values['-S6GR1-']}"
            services['service6_group2'] = f"{values['-S6GR2-']}"

    window.close()

    save_settings_to_file(CONFIG_FILE, settings, devices, services)

    print("-- EXITING APPLICATION --")
    exit(0)


# =========================================================================== #
#          ___ ___ _  _ ___     ___ ___  __  __ __  __   _   _  _ ___         #
#         / __| __| \| |   \   / __/ _ \|  \/  |  \/  | /_\ | \| |   \        #
#         \__ \ _|| .` | |) | | (_| (_) | |\/| | |\/| |/ _ \| .` | |) |       #
#         |___/___|_|\_|___/   \___\___/|_|  |_|_|  |_/_/ \_\_|\_|___/        #
# =========================================================================== #
def send_command(sock, command, destination):
    """ Used to send a command to the PDU over Ethernet at "destination" (IP,PORT)
    """
    global log
    log.tx(command, is_save_to_log_file=True)
    sock.sendto(command.encode(), destination)


# =========================================================================== #
#       ___ __  __ ___    ___ ___ ___ ___ ___ ___ _  _     _   _    _         #
#      / __|  \/  |   \  | _ \ __| __| _ \ __/ __| || |   /_\ | |  | |        #
#     | (__| |\/| | |) | |   / _|| _||   / _|\__ \ __ |  / _ \| |__| |__      #
#      \___|_|  |_|___/  |_|_\___|_| |_|_\___|___/_||_| /_/ \_\____|____|     #
# =========================================================================== #
def send_refresh_all(sock, profiles, settings, destination):
    """ Will send commands to get current values for services enabled in the active profile
        NOTE: Because of the new groups calculations, we need status of all outputs
        all of the time!
    """
    send_command(sock, 'STATUS,1', destination)
    send_command(sock, 'STATUS,2', destination)
    send_command(sock, 'STATUS,3', destination)
    send_command(sock, 'STATUS,4', destination)
    send_command(sock, 'STATUS,5', destination)
    send_command(sock, 'STATUS,6', destination)

    # global log
    # active_profile = profiles[settings['active_profile']]
    # if active_profile['control1'] == "ENABLE":
    #     send_command(sock, 'STATUS,1', destination)
    # if active_profile['control2'] == "ENABLE":
    #     send_command(sock, 'STATUS,2', destination)
    # if active_profile['control3'] == "ENABLE":
    #     send_command(sock, 'STATUS,3', destination)
    # if active_profile['control4'] == "ENABLE":
    #     send_command(sock, 'STATUS,4', destination)
    # if active_profile['control5'] == "ENABLE":
    #     send_command(sock, 'STATUS,5', destination)
    # if active_profile['control6'] == "ENABLE":
    #     send_command(sock, 'STATUS,6', destination)


# =========================================================================== #
#    ___  _   ___  ___ ___   _____ ___ _    ___ __  __ ___ _____ _____   __   #
#   | _ \/_\ | _ \/ __| __| |_   _| __| |  | __|  \/  | __|_   _| _ \ \ / /   #
#   |  _/ _ \|   /\__ \ _|    | | | _|| |__| _|| |\/| | _|  | | |   /\ V /    #
#   |_|/_/ \_\_|_\|___/___|   |_| |___|____|___|_|  |_|___| |_| |_|_\ |_|     #
# =========================================================================== #
def parse_telemetry(raw_packet, is_save_to_log_file):
    """ Parse any incoming telemetry packet and update the GUI accordingly.
        Note that the packet must be in the standard format:
        SRC,YYYY-MM-DD HH:MM:SS.sss,PKT_ID,...
    """
    global window, log, output, battery, in_flight

    packet = raw_packet.split(",")

    if len(packet) < 3:
        log.warning("TM packet too short,"+raw_packet, is_save_to_log_file)
        return

    source = packet[0]
    try:
        time_of_reception = datetime.fromisoformat(packet[1]).timestamp()
    except:
        log.warning(f"ERROR: timestamp could not be decoded: {packet[1]}", is_save_to_log_file)
        time_of_reception = datetime.utcnow().timestamp()
    header = packet[2]  # Get message header

    if source != 'PDU':
        # ---------------------------------------------------------- #
        # The only things that we will process, if it is not TM from #
        # PDU, are some EVENTS                                       #
        # ---------------------------------------------------------- #
        # ......................................................................... EVENT
        if header == "EVENT":
            if packet[3] == "START_FLIGHT":
                in_flight = True
                output['last_update_time'][_HEATERS_] = time_of_reception
            elif packet[3] == "END_FLIGHT" and float(output['last_update_time'][_HEATERS_]) > 0.0:
                in_flight = False
                delta = time_of_reception - output['last_update_time'][_HEATERS_]
                if float(delta) > 0.0:
                    output['accumulated_Wh'][_HEATERS_] += (float(battery['heaters_consumption']) * (delta / 3600.0) * float(battery['nominal_voltage']))
                output['last_update_time'][_HEATERS_] = 0.0
        return  # This is not from the PDU, will not process further

    # ......................................................................... SRVCSET
    if header == "SRVCSET":  # Update service state
        if len(packet) < 5:
            log.warning("SRVCSET packet error - Too short", is_save_to_log_file)
        else:
            service_id, service_state = packet[3], packet[4]
            if service_id.isdigit():
                index = int(service_id)
                if (index >= 1) and (index <= 6):
                    index = index - 1   # The array starts at zero!
                    output['is_on'][index] = (service_state == '1')
                else:
                    log.warning(f"Service index ({service_id}) out of range for SRVCSET received", is_save_to_log_file)
            else:
                log.warning(f"Bad service index ({service_id}) for SRVCSET received", is_save_to_log_file)
    # ......................................................................... STATUS
    elif header == "STATUS":
        if len(packet) < 5:
            log.warning("STATUS packet error - Too short", is_save_to_log_file)
        else:
            service_id, value = packet[3], packet[4]
            if service_id.isdigit():
                index = int(service_id)
                if (index >= 1) and (index <= 6):
                    index = index - 1   # The array starts at zero!
                    output['current'][index] = float(value)
                    # ------------------------------ #
                    # Calculated accumulated current #
                    # ------------------------------ #
                    if output['last_update_time'][index] > 0.0:
                        delta = time_of_reception - output['last_update_time'][index]
                        # output['accumulated_A'][index] += output['current'][index]
                        output['accumulated_Wh'][index] += (output['current'][index] * (delta/3600.0) * float(battery['nominal_voltage']))
                        # print(f"Accumulated[{index}={output['accumulated_Ah'][index]}")  ########################################################## TODO: Remove
                    output['last_update_time'][index] = time_of_reception
                else:
                    log.warning(f"Service index ({service_id}) out of range for STATUS received", is_save_to_log_file)
            else:
                log.warning(f"Bad service index ({service_id}) for STATUS received", is_save_to_log_file)
    # .........................................................................
    elif header == "IPSET":
        pass
    # .........................................................................
    elif header == "PORTSET":
        pass
    # .........................................................................
    elif header == "Resetting":
        pass
    # .........................................................................
    elif header == "CMDERROR":
        pass
    # .........................................................................
    else:
        # The rest is unexpected, we might want to flag it
        pass


# ########################################################################### #
#               ___ ___ ___ ___ ___ ___ _  _    ___ _   _ ___                 #
#              | _ \ __| __| _ \ __/ __| || |  / __| | | |_ _|                #
#              |   / _|| _||   / _|\__ \ __ | | (_ | |_| || |                 #
#              |_|_\___|_| |_|_\___|___/_||_|  \___|\___/|___|                #
# ########################################################################### #
def refresh_telemetry_stats_on_gui(services, values):
    """ Refresh all GUI elements related to dynamic telemetry values
    """
    global window, battery, output, group1, group2

    window['-S1TOGGLE-'].update(get_service_text_status(_S1_, services), button_color=get_service_color_status(_S1_))
    window['-S2TOGGLE-'].update(get_service_text_status(_S2_, services), button_color=get_service_color_status(_S2_))
    window['-S3TOGGLE-'].update(get_service_text_status(_S3_, services), button_color=get_service_color_status(_S3_))
    window['-S4TOGGLE-'].update(get_service_text_status(_S4_, services), button_color=get_service_color_status(_S4_))
    window['-S5TOGGLE-'].update(get_service_text_status(_S5_, services), button_color=get_service_color_status(_S5_))
    window['-S6TOGGLE-'].update(get_service_text_status(_S6_, services), button_color=get_service_color_status(_S6_))
    window['-S1REFRESH-'].Update(f"{output['current'][_S1_]:.3f}")
    window['-S2REFRESH-'].Update(f"{output['current'][_S2_]:.3f}")
    window['-S3REFRESH-'].Update(f"{output['current'][_S3_]:.3f}")
    window['-S4REFRESH-'].Update(f"{output['current'][_S4_]:.3f}")
    window['-S5REFRESH-'].Update(f"{output['current'][_S5_]:.3f}")
    window['-S6REFRESH-'].Update(f"{output['current'][_S6_]:.3f}")
    # .........................................................................Group 1
    group1['Wh'] = 0.0
    group1['A'] = 0.0
    if values['-S1GR1-']:
        group1['A'] += output['current'][_S1_]
        group1['Wh'] += output['accumulated_Wh'][_S1_]
    if values['-S2GR1-']:
        group1['A'] += output['current'][_S2_]
        group1['Wh'] += output['accumulated_Wh'][_S2_]
    if values['-S3GR1-']:
        group1['A'] += output['current'][_S3_]
        group1['Wh'] += output['accumulated_Wh'][_S3_]
    if values['-S4GR1-']:
        group1['A'] += output['current'][_S4_]
        group1['Wh'] += output['accumulated_Wh'][_S4_]
    if values['-S5GR1-']:
        group1['A'] += output['current'][_S5_]
        group1['Wh'] += output['accumulated_Wh'][_S5_]
    if values['-S6GR1-']:
        group1['A'] += output['current'][_S6_]
        group1['Wh'] += output['accumulated_Wh'][_S6_]
    window['-GR1_A-'].Update(f"{group1['A']:.3f}")
    window['-GR1_WH-'].Update(f"{group1['Wh']:.3f}")
    limit = float(values['-GR1_LIMIT_WH-'])
    if limit > 0.0:
        threshold = limit * 0.1
        if limit - group1['Wh'] <= threshold:
            window['-GR1_LIMIT_WH-'].update(background_color='red')
            window['-GR1_WH-'].update(background_color='red')
        else:
            window['-GR1_LIMIT_WH-'].update(background_color='white')
            window['-GR1_WH-'].update(background_color='white')
    # .........................................................................Group 2
    group2['Wh'] = 0.0
    group2['A'] = 0.0
    if values['-S1GR2-']:
        group2['A'] += output['current'][_S1_]
        group2['Wh'] += output['accumulated_Wh'][_S1_]
    if values['-S2GR2-']:
        group2['A'] += output['current'][_S2_]
        group2['Wh'] += output['accumulated_Wh'][_S2_]
    if values['-S3GR2-']:
        group2['A'] += output['current'][_S3_]
        group2['Wh'] += output['accumulated_Wh'][_S3_]
    if values['-S4GR2-']:
        group2['A'] += output['current'][_S4_]
        group2['Wh'] += output['accumulated_Wh'][_S4_]
    if values['-S5GR2-']:
        group2['A'] += output['current'][_S5_]
        group2['Wh'] += output['accumulated_Wh'][_S5_]
    if values['-S6GR2-']:
        group2['A'] += output['current'][_S6_]
        group2['Wh'] += output['accumulated_Wh'][_S6_]
    window['-GR2_A-'].Update(f"{group2['A']:.3f}")
    window['-GR2_WH-'].Update(f"{group2['Wh']:.3f}")
    limit = float(values['-GR2_LIMIT_WH-'])
    if limit > 0.0:
        threshold = limit * 0.1
        if limit - group2['Wh'] <= threshold:
            window['-GR2_LIMIT_WH-'].update(background_color='red')
            window['-GR2_WH-'].update(background_color='red')
        else:
            window['-GR2_LIMIT_WH-'].update(background_color='white')
            window['-GR2_WH-'].update(background_color='white')
    # .........................................................................Total Groups
    total_groups_A = float(group1['A']) + float(group2['A'])
    print(f"updating total currant for groups: {total_groups_A}")
    window['-GROUPS_A-'].Update(f"{total_groups_A:.3f}")
    # .........................................................................Battery
    battery['progress_wh'] = 0.0
    total_used = float(output['accumulated_Wh'][_S1_])
    total_used += float(output['accumulated_Wh'][_S2_])
    total_used += float(output['accumulated_Wh'][_S3_])
    total_used += float(output['accumulated_Wh'][_S4_])
    total_used += float(output['accumulated_Wh'][_S5_])
    total_used += float(output['accumulated_Wh'][_S6_])
    total_used += float(output['accumulated_Wh'][_HEATERS_])
    offset = 0.0
    if values['-OFFSET_WH-']:
        if values['-OFFSET_WH-'].isdigit():
            offset = float(values['-OFFSET_WH-'])
    total_used += offset
    battery['progress_wh'] = float(battery['max_wh']) - total_used
    window['-BATTERY_WH-'].update(f"{battery['progress_wh']:.3f}")
    battery_percent = int(float(battery['progress_wh']) / float(battery['max_wh']) * 100.0)
    window['-BATTERY_PERCENT-'].update(f"{battery_percent}")
    if battery_percent > 100:
        window['-BATTERY_PROGRESS-'].update_bar(100)
    elif battery_percent < 0:
        window['-BATTERY_PROGRESS-'].update_bar(0)
    else:
        window['-BATTERY_PROGRESS-'].update_bar(battery_percent)


# ########################################################################### #
# ########################################################################### #
def get_service_color_status(service_id):
    """ Return a color scheme for the service button, according to service status
    """
    global output
    if output['is_on'][service_id]:
        color = ('white', 'green')
        return color
    else:
        color = ('white', 'firebrick3')
        return color


# ########################################################################### #
# ########################################################################### #
def get_service_text_status(service, services):
    """ Provides a text with the service id (e.g. S1, S2...), service name & status
        "service" must be as defined in header (i.e. _S1_, _S2_ etc...)
    """
    global output

    text = f'S{service+1}- UNDEFINED SERVICE - N/A'
    if service == _S1_:
        if output['is_on'][service]:
            text = 'S1- ' + services['service1'] + ' - ON'
        else:
            text = 'S1- ' + services['service1'] + ' - OFF'
    if service == _S2_:
        if output['is_on'][service]:
            text = 'S2- ' + services['service2'] + ' - ON'
        else:
            text = 'S2- ' + services['service2'] + ' - OFF'
    if service == _S3_:
        if output['is_on'][service]:
            text = 'S3- ' + services['service3'] + ' - ON'
        else:
            text = 'S3- ' + services['service3'] + ' - OFF'
    if service == _S4_:
        if output['is_on'][service]:
            text = 'S4- ' + services['service4'] + ' - ON'
        else:
            text = 'S4- ' + services['service4'] + ' - OFF'
    if service == _S5_:
        if output['is_on'][service]:
            text = 'S5- ' + services['service5'] + ' - ON'
        else:
            text = 'S5- ' + services['service5'] + ' - OFF'
    if service == _S6_:
        if output['is_on'][service]:
            text = 'S6- ' + services['service6'] + ' - ON'
        else:
            text = 'S6- ' + services['service6'] + ' - OFF'
    return text


# ########################################################################### #
# ########################################################################### #
def update_profile(profiles, settings):
    """ Updates the GUI capability according to current profile

    For now it will disable the buttons used to toggle power outputs on the
    services that are marked as DISABLED.
    TODO: Handle exceptions!
    """
    global window
    active_profile = profiles[settings['active_profile']]
    window['-S1TOGGLE-'].update(disabled=(active_profile['control1'] == "DISABLE"))
    window['-S2TOGGLE-'].update(disabled=(active_profile['control2'] == "DISABLE"))
    window['-S3TOGGLE-'].update(disabled=(active_profile['control3'] == "DISABLE"))
    window['-S4TOGGLE-'].update(disabled=(active_profile['control4'] == "DISABLE"))
    window['-S5TOGGLE-'].update(disabled=(active_profile['control5'] == "DISABLE"))
    window['-S6TOGGLE-'].update(disabled=(active_profile['control6'] == "DISABLE"))


# ########################################################################### #
#                           _           _   _   _                             #
#           _ _ ___ __ _ __| |  ___ ___| |_| |_(_)_ _  __ _ ___               #
#          | '_/ -_) _` / _` | (_-</ -_)  _|  _| | ' \/ _` (_-<               #
#          |_| \___\__,_\__,_| /__/\___|\__|\__|_|_||_\__, /__/               #
#                                                     |___/                   #
# ########################################################################### #
def read_settings_from_file(filename):
    """ Reads the settings from file and organize them

    Input a filename, will output the services, devices and general settings
    e.g. services, devices, settings = read_settings_from_file("settings.ini")
    """
    parser = configparser.ConfigParser()
    parser.read(filename)
    # ============================================ #
    # Settings file has three sections, parse them #
    # ============================================ #
    settings = parser['settings']
    services = parser['services']
    devices = parser['devices']
    return settings, services, devices


# ########################################################################### #
# ########################################################################### #
def save_settings_to_file(filename, settings, devices, services):
    """ Save all settings in filename
    """
    parser = configparser.ConfigParser()
    # TODO: There might be a better way to just re-insert the sections into the "parser"! Find it
    # ....................................
    settings_dictionary = OrderedDict()
    for key, value in settings.items():
        settings_dictionary[key] = value
    # ...................................
    devices_dictionary = OrderedDict()
    for key, value in devices.items():
        devices_dictionary[key] = value
    # ...................................
    services_dictionary = OrderedDict()
    for key, value in services.items():
        services_dictionary[key] = value
    # ...................................
    parser.read_dict(OrderedDict((
        ('settings', settings),
        ('devices', devices),
        ('services', services),
    )))
    shutil.copy2(CONFIG_FILE, CONFIG_FILE_BACKUP)
    with open(CONFIG_FILE, 'w') as configfile:
        parser.write(configfile)


# ########################################################################### #
#             ___             _   ___          __ _ _                         #
#            | _ \___ __ _ __| | | _ \_ _ ___ / _(_) |___ ___                 #
#            |   / -_) _` / _` | |  _/ '_/ _ \  _| | / -_|_-<                 #
#            |_|_\___\__,_\__,_| |_| |_| \___/_| |_|_\___/__/                 #
# ########################################################################### #
def read_users(filename):
    """ Reads filename to extract all users (profiles) and return them
    """
    profiles_parser = configparser.ConfigParser()
    profiles_parser.read(filename)
    return profiles_parser


# =========================================================================== #
#           ██╗      ██████╗  ██████╗  ██████╗ ███████╗██████╗                #
#           ██║     ██╔═══██╗██╔════╝ ██╔════╝ ██╔════╝██╔══██╗               #
#           ██║     ██║   ██║██║  ███╗██║  ███╗█████╗  ██████╔╝               #
#           ██║     ██║   ██║██║   ██║██║   ██║██╔══╝  ██╔══██╗               #
#           ███████╗╚██████╔╝╚██████╔╝╚██████╔╝███████╗██║  ██║               #
#           ╚══════╝ ╚═════╝  ╚═════╝  ╚═════╝ ╚══════╝╚═╝  ╚═╝               #
# =========================================================================== #
class Logger:
    """ Sends to console, in TMTC log window and on file
    """
    global window

    # ======================================================================= #
    # ======================================================================= #
    def __init__(self):
        self.log_filename = 'pdu_default_log.txt'

    # ======================================================================= #
    # ======================================================================= #
    def set_filename(self, filename):
        # TODO: Validate filename
        is_selected_new = False
        if os.path.exists(filename):
            if os.stat(filename).st_size > 0:
                is_cancel, is_load = log_file_exists_popup(filename)
                if is_cancel:
                    # -------------------------------------------------------------- #
                    # File exists, we were warned about it and we cancelled, meaning #
                    # we want to select another filename                             #
                    # -------------------------------------------------------------- #
                    is_cancel, filename = log_file_set_popup(filename)
                    if is_cancel:
                        pass        # Here, what is really happening is not clear in my mind...
                    else:
                        is_selected_new = True
                elif is_load:
                    # --------------------------------------------------- #
                    # File exists, we were warned about it and we decided #
                    # to load the data it already contains. Proceed.      #
                    # --------------------------------------------------- #
                    self.load_log(filename)
            else:
                pass  # File is empty, just us the filename and do not offer to load data
        else:
            pass  # File does not exists already, just use this filename
        print("Using " + filename)
        self.log_filename = filename
        return is_selected_new, filename

    # ======================================================================= #
    # ======================================================================= #
    def load_log(self, filename):
        # TODO: Validate filename and check for exceptions when opening
        print("================== LOADING LOG FILE " + filename + "=====================")
        file = open(filename, 'r')
        count = 0
        # .....................................................................
        while True:
            count += 1
            line = file.readline()
            if not line:        # if line is empty end of file is reached
                break
            line_stripped = line.strip()
            log.as_is(line_stripped, is_save_to_log_file=False)
            parse_telemetry(line_stripped, is_save_to_log_file=False)
        # .....................................................................
        file.close()

    # ======================================================================= #
    # ======================================================================= #
    def as_is(self, msg, is_save_to_log_file=True):
        """ Print to log window and file, as is
        """
        window['-TMTCLOG-'].update(msg + '\n', append=True)
        if is_save_to_log_file:
            with open(self.log_filename, 'a') as logfile:
                logfile.write(msg + '\n')

    # ======================================================================= #
    # ======================================================================= #
    def rx(self, msg, is_save_to_log_file=True):
        """ To log a packet received from the PDU
        """
        log_msg = 'PDU,' + datetime.utcnow().isoformat(sep=' ', timespec='milliseconds') + ',' + msg
        window['-TMTCLOG-'].update(log_msg + '\n', append=True)
        if is_save_to_log_file:
            with open(self.log_filename, 'a') as logfile:
                logfile.write(log_msg + '\n')
        return log_msg

    # ======================================================================= #
    # ======================================================================= #
    def tx(self, msg, is_save_to_log_file=True):
        """ To log a packet sent to the PDU
        """
        log_msg = 'GND,' + datetime.utcnow().isoformat(sep=' ', timespec='milliseconds') + ',' + msg
        window['-TMTCLOG-'].update(log_msg + '\n', append=True)
        if is_save_to_log_file:
            with open(self.log_filename, 'a') as logfile:
                logfile.write(log_msg + '\n')
        return log_msg

    # ======================================================================= #
    # ======================================================================= #
    def info(self, msg, is_save_to_log_file=True):
        log_msg = 'GND,' + datetime.utcnow().isoformat(sep=' ', timespec='milliseconds') + ',INFO,' + msg
        window['-TMTCLOG-'].update(log_msg + '\n', append=True)
        if is_save_to_log_file:
            with open(self.log_filename, 'a') as logfile:
                logfile.write(log_msg + '\n')
        return log_msg

    # ======================================================================= #
    # ======================================================================= #
    def event(self, msg, is_save_to_log_file=True):
        log_msg = 'GND,' + datetime.utcnow().isoformat(sep=' ', timespec='milliseconds') + ',EVENT,' + msg
        window['-TMTCLOG-'].update(log_msg + '\n', append=True)
        if is_save_to_log_file:
            with open(self.log_filename, 'a') as logfile:
                logfile.write(log_msg + '\n')
        return log_msg

    # ======================================================================= #
    # ======================================================================= #
    def warning(self, msg, is_save_to_log_file=True):
        log_msg = 'GND,' + datetime.utcnow().isoformat(sep=' ', timespec='milliseconds') + ',WARNING,' + msg
        print(log_msg)
        window['-TMTCLOG-'].update(log_msg + '\n', append=True)
        if is_save_to_log_file:
            with open(self.log_filename, 'a') as logfile:
                logfile.write(log_msg + '\n')
        return log_msg

    # ======================================================================= #
    # ======================================================================= #
    def debug(self, msg, is_save_to_log_file=False):
        """ Will do something ONLY if global variable DEBUG == True. And then, does
            the same as "info" but does not write to log file.
        """
        if DEBUG:
            log_msg = datetime.utcnow().isoformat(sep=' ', timespec='milliseconds') + ' - ' + msg
            print(log_msg)
            window['-TMTCLOG-'].update(log_msg + '\n', append=True)
            if is_save_to_log_file:
                with open(self.log_filename, 'a') as logfile:
                    logfile.write(log_msg + '\n')
            return log_msg


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


# ########################################################################### #
# ########################################################################### #
if __name__ == '__main__':
    main()
