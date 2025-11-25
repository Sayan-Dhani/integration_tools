#!/bin/env python3
import sys
import socket
import json

from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QCheckBox,
)
from PyQt5.QtCore import pyqtSlot, QTimer, QThread, pyqtSignal, Qt
from PyQt5.QtGui import QFont

BUFFER_SIZE = 100000


class tcp_util:
    """Utility class for TCP communication with the CAEN server."""

    def __init__(self, ip, port):
        self.ip = ip
        self.port = port
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.settimeout(0.5)
        self.headerBytes = 4
        
        self.connectSocket()
        pass    

    def __del__(self):
        """Destructor, closes socket
        """
        try:
            self.closeSocket()
        except Exception:
            pass

    def connectSocket(self):
        """Connects socket
        """
        self.socket.connect((self.ip, self.port))
        pass

    def closeSocket(self):
        """Closes socket connection
        """
        self.socket.close()
        pass

    def sendMessage(self, message):
        """Encodes message and sends it on socket
        """
        encodedMessage = self.encodeMessage(message)
        self.socket.send(encodedMessage)
        pass

    def encodeMessage(self, message):
        """
        Encodes message adding 8-byte header:
        [4 bytes: total length] [4 bytes: reserved/0] [payload]
        """
        messageLength = len(message) + self.headerBytes + 4
        N = 0
        encodedMessage = (
            messageLength.to_bytes(4, byteorder="big")
            + N.to_bytes(4, byteorder="big")
            + message.encode("utf-8")
        )
        return encodedMessage


class CAENQueryThread(QThread):
    """
    Thread class for handling CAEN queries.
    Uses internal queues so GUI can enqueue multiple commands.
    """

    dataReady = pyqtSignal(dict)  # Emitted when parsed data is ready
    error = pyqtSignal(str)       # Emitted when an error occurs

    def __init__(self, ip="192.168.404.45", port=7000):
        super().__init__()
        self.ip = ip
        self.port = port
        self.message = None
        self.receive = False
        self.running = True
        self.queue = []         # list of messages to send
        self.receiveQueue = []  # list of booleans: whether to read a reply

    def setup_query(self, message, receive=False):
        """Queue a new query to be executed by the thread."""
        self.queue.append(message)
        self.receiveQueue.append(receive)

    def stop(self):
        """Stop the thread"""
        self.running = False
        self.wait()
        
    def run(self):
        """Thread's main method : Process the queued messages."""
        while self.queue:
            #create lock
            self.message = self.queue.pop(0)
            self.receive = self.receiveQueue.pop(0)
            try:
                tcpClass = tcp_util(ip=self.ip, port=self.port)
                tcpClass.sendMessage(self.message)
                if self.receive:
                    data = b""
                    while True:
                        try:
                            chunk = tcpClass.socket.recv(BUFFER_SIZE)
                            if not chunk:
                                break
                            data += chunk
                        except Exception:
                            break

                    # Strip 8-byte header
                    data = data[8:]
                    data = data.decode("utf-8")

                    parsedData = {}
                    for token in data.split(","):
                        if token.startswith("caen"):
                            key, value = token.split(":")
                            value = float(value)
                            parsedData[key] = value

                    self.dataReady.emit(parsedData)

                tcpClass.closeSocket()

            except Exception as e:
                self.error.emit(str(e))


class caenGUI8LV(QWidget):
    """
    GUI for 8 LV channels.
    Features per-channel:
    - ON/OFF buttons
    - LED for ON/OFF state
    - Voltage/Current (and power) display
    - Current setpoint QLineEdit + 'Set I' button
    """

    def __init__(self, ip="192.168.404.45", port=7000):
        super().__init__()
    
        # Create timer for periodic update
        self.channels = []
        self.led = {}
        self.label = {}
        self.current_inputs = {}
        self.setI_buttons = {}
        self.last_response = None

        # Create query thread
        self.queryThread = CAENQueryThread(ip=ip, port=port)
        self.queryThread.dataReady.connect(self.handle_query_response)
        self.queryThread.error.connect(self.handle_query_error)

        # Timer to periodically request status
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_status)
        
        # build the UI
        self.initUI()
        
        #start periodic status update
        self.timer.start(2000)  # ms

    def change_host(self, ip, port):
        """
        Change host IP and port (e.g. from command line arguments).
        """
        # Disconnect old thread signals
        try:
            self.queryThread.dataReady.disconnect()
            self.queryThread.error.disconnect()
        except Exception:
            pass

        self.queryThread = CAENQueryThread(ip=ip, port=port)
        self.queryThread.dataReady.connect(self.handle_query_response)
        self.queryThread.error.connect(self.handle_query_error)

    def initUI(self):
        self.setWindowTitle("Inner Tracker CAEN GUI - 8 LV Channels")

        self.main_layout = QVBoxLayout()
        self.setLayout(self.main_layout)
        
        # Safety checkbox to enable/disable current setting
        self.enable_current_checkbox = QCheckBox("Enable current setting (safety)")
        self.enable_current_checkbox.stateChanged.connect(self.toggle_current_setting)
        self.main_layout.addWidget(self.enable_current_checkbox)

        # Define 8 LV channels: LV15.0 ... LV15.7
        for i in range(8):
            self.channels.append(f"LV15.{i}")

        for channel in self.channels:
            hlayout = QHBoxLayout()
            self.main_layout.addLayout(hlayout)

            # Channel label
            ch_label = QLabel(channel + ":")
            ch_label.setFont(QFont("Arial", 10))
            hlayout.addWidget(ch_label)
            
            # Current set text box
            current_input = QLineEdit()
            current_input.setFixedWidth(60)
            current_input.setPlaceholderText("Iset (A)")
            self.current_inputs[channel] = current_input
            hlayout.addWidget(current_input)

            # 'Set I' button
            btn_setI = QPushButton("Set I", self)
            btn_setI.setMinimumWidth(50)
            btn_setI.clicked.connect(
                lambda checked, ch=channel: self.set_current(ch)
            )
            btn_setI.setEnabled(False)               # ← DISABLE by default
            self.setI_buttons[channel] = btn_setI    # ← STORE button
            hlayout.addWidget(btn_setI)
            
            # ON button
            btn_on = QPushButton("ON", self)
            btn_on.setMinimumWidth(40)
            btn_on.clicked.connect(
                lambda checked, ch=channel: self.turn_on(ch)
            )
            hlayout.addWidget(btn_on)

            # OFF button
            btn_off = QPushButton("OFF", self)
            btn_off.setMinimumWidth(40)
            btn_off.clicked.connect(
                lambda checked, ch=channel: self.turn_off(ch)
            )
            hlayout.addWidget(btn_off)

            # Voltage/Current label
            self.label[channel] = QLabel("n/a")
            self.label[channel].setFont(QFont("Arial", 9))
            hlayout.addWidget(self.label[channel])

            # LED indicator (QFrame used as LED)
            self.led[channel] = QFrame(self)
            self.led[channel].setFrameShape(QFrame.Box)
            self.led[channel].setFixedSize(25, 25)
            self.led[channel].setStyleSheet("background-color: red")
            hlayout.addWidget(self.led[channel])

        self.show()
        
    def toggle_current_setting(self, state):
        """
        Enable or disable all 'Set I' buttons based on the safety checkbox.
        """
        enabled = (state == Qt.Checked)
        for btn in self.setI_buttons.values():
            btn.setEnabled(enabled)
        
    # ---------------- Periodic status update ----------------

    @pyqtSlot()
    def update_status(self):
        """
        Periodic update method:
        ask the server for the status of all channels.
        """
        print("Update")
        
        message = "GetStatus,PowerSupplyId:caen"
        self.queryThread.setup_query(message, True)

        if not self.queryThread.isRunning():
            self.queryThread.start()
        else:
            # If it is still running, we just queued the command
            # and it will be handled in the same run loop.
            print("Query thread already running, skipping update")
            pass

    # ---------------- Handle responses / errors ----------------

    def handle_query_response(self, ret):
        """
        Called when a GetStatus response is received and parsed.
        ret: dict of caen_* keys with float values.
        """
        self.last_response = ret.copy()
        try:
            for channel in self.channels:
                try:
                    # ON/OFF LED
                    is_on = ret.get(f"caen_{channel}_IsOn", 0.0)
                    if is_on > 0.5:
                        self.led[channel].setStyleSheet("background-color: green")
                    else:
                        self.led[channel].setStyleSheet("background-color: red")

                    # Voltage & Current
                    v_key = f"caen_{channel}_Voltage"
                    i_key = f"caen_{channel}_Current"
                    if v_key in ret and i_key in ret:
                        V = ret[v_key]
                        I = ret[i_key]
                        P = V * I
                        self.label[channel].setText(
                            f"V: {V:4.1f} V  |  I: {I:4.2f} A  ({P:4.1f} W)"
                        )
                    else:
                        self.label[channel].setText(
                            f'V: {ret["caen_"+channel+"_Voltage"]:3.1f}V\nI: {ret["caen_"+channel+"_Current"]:1.2f}uA'
                        )
                        # self.label[channel].setText("n/a")

                except Exception:
                    print("No info for", channel)
        except Exception:
            print("Cannot parse CAEN data")

    def handle_query_error(self, error_msg):
        print(f"Query error: {error_msg}")

    # ---------------- Channel control methods ----------------

    @pyqtSlot()
    def turn_on(self, channel):
        """
        Send 'TurnOn' command for the selected channel.
        """
        message = f"TurnOn,PowerSupplyId:caen,ChannelId:{channel}"
        print(message)
        self.queryThread.setup_query(message, receive=False)

        if not self.queryThread.isRunning():
            print("Starting query thread")
            self.queryThread.start()

    @pyqtSlot()
    def turn_off(self, channel):
        """
        Send 'TurnOff' command for the selected channel.
        """
        message = f"TurnOff,PowerSupplyId:caen,ChannelId:{channel}"
        print(message)
        self.queryThread.setup_query(message, receive=False)

        if not self.queryThread.isRunning():
            print("Starting query thread")
            self.queryThread.start()

    @pyqtSlot()
    def set_current(self, channel):
        """
        Send 'SetCurrent' command for the selected channel
        using the value from the QLineEdit.
        NOTE: If your server uses a different command name
        (e.g. SetISet), change it here.
        """
        text = self.current_inputs[channel].text().strip()
        try:
            value = float(text)
        except ValueError:
            print(f"Invalid current value for {channel}: '{text}'")
            return

        # Adjust "SetCurrent" to your actual server protocol if needed.
        message = (
            f"SetCurrent,PowerSupplyId:caen,ChannelId:{channel},Value:{value}"
        )
        print(message)
        self.queryThread.setup_query(message, receive=False)

        if not self.queryThread.isRunning():
            self.queryThread.start()


# ------------------------- main -------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="INNER TRACKER CAEN GUI - 8 LV Channels")
    parser.add_argument(
        "--ip",
        type=str,
        default="192.168.404.45",
        help="IP address of the CAEN server",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=7000,
        help="Port of the CAEN server",
    )
    args = parser.parse_args()

    app = QApplication(sys.argv)
    gui = caenGUI8LV(ip=args.ip, port=args.port)
    sys.exit(app.exec_())
