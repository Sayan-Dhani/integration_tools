#!/bin/env python3
#create QT GUI with one button to send message to TCP server
import sys
from PyQt5.QtWidgets import QApplication, QWidget, QPushButton, QVBoxLayout, QTextEdit, QHBoxLayout, QFrame, QLabel
from PyQt5.QtCore import pyqtSlot, QTimer, QThread, pyqtSignal, QObject
import socket
import json
BUFFER_SIZE = 100000

class CAENQueryThread(QThread):
    """Thread class for handling CAEN queries"""
    dataReady = pyqtSignal(dict)  # Signal to emit when data is received
    error = pyqtSignal(str)  # Signal to emit when error occurs

    def __init__(self, ip='192.168.0.45', port=7000):
        super().__init__()
        self.ip = ip
        self.port = port
        self.message = None
        self.receive = False
        self.running = True

    def setup_query(self, message, receive=False):
        """Setup the query to be executed"""
        self.message = message
        self.receive = receive
        
    def stop(self):
        """Stop the thread"""
        self.running = False
        self.wait()

    def run(self):
        """Thread's main method"""
        if not self.message:
            return

        try:
            tcpClass = tcp_util(ip=self.ip, port=self.port)
            tcpClass.sendMessage(self.message)
            
            if self.receive:
                data = tcpClass.socket.recv(BUFFER_SIZE)
                length = data[3] | (data[2] << 8) | (data[1] << 16) | (data[0] << 24)
                while len(data) < length :
                    print("wait for more data",len(data), length)
                    chunk=tcpClass.socket.recv(BUFFER_SIZE)
                    if not chunk:
                        break
                    data+=chunk
                data=data[8:].decode("utf-8")

                parsedData = {}
                for token in data.split(','):
                    if token.startswith('caen'):
                        key, value = token.split(":")
                        value = float(value)
                        parsedData[key] = value
                self.dataReady.emit(parsedData)
            
            tcpClass.closeSocket()
            
        except Exception as e:
            self.error.emit(str(e))

class tcp_util():
    """Utility class for tcp
    comunication management. """
    def __init__(self, ip, port):
        self.ip          = ip
        self.port        = port
        self.socket      = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.headerBytes = 4

        self.connectSocket()
        pass

    def __del__ (self):
        """Desctuctor, closes socket"""
        try:
            self.closeSocket()
        except:
            pass

    def connectSocket(self):
        """Connects socket"""
        self.socket.connect((self.ip,self.port))
        pass

    def closeSocket(self):
        """Closes socket connection"""
        self.socket.close()
        pass

    def sendMessage(self,message):
        """Encodes message and sends it on socket"""
        encodedMessage = self.encodeMessage(message)
        self.socket.send(encodedMessage)
        pass

    def encodeMessage(self,message):
        """Encodes message adding 4 bytes header"""
        messageLength = len(message) + self.headerBytes +4
        N=0
        encodedMessage = (messageLength).to_bytes(4, byteorder='big') + N.to_bytes(4, byteorder='big') + message.encode('utf-8')
        return encodedMessage

from argparse import Namespace

class CAENControl(QObject):
    """CAEN control logic without UI elements"""
    def __init__(self, ui):
        super().__init__()
        self.ui = ui
        self.channels = {"LV": "LV7.1", "HV": "HV0.11"}
        self.led = {
            'LV': self.ui.lvLed,
            'HV': self.ui.hvLed
        }
        self.label = {
            'LV': self.ui.lvLabel,
            'HV': self.ui.hvLabel
        }
        
        # Create query thread
        self.queryThread = CAENQueryThread()
        self.queryThread.dataReady.connect(self.handle_query_response)
        self.queryThread.error.connect(self.handle_query_error)

        # Connect buttons
        self.ui.lvOnButton.clicked.connect(lambda: self.on(self.channels["LV"]))
        self.ui.lvOffButton.clicked.connect(lambda: self.safe_lv_off())
        self.ui.hvOnButton.clicked.connect(lambda: self.on(self.channels["HV"] ))
        self.ui.hvOffButton.clicked.connect(lambda: self.off(self.channels["HV"] ))

        # Create timer for periodic update
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)
        self.timer.start(2000)
        self.lv_off_when_hv_off=False

    def safe_lv_off(self):

        if self.lv_off_when_hv_off : # if the user insists we switch off
            self.off(self.channels["LV"])
        self.off(self.channels["HV"])
        self.lv_off_when_hv_off=True 

    def setLV(self,channel_name):
        self.channels["LV"]=channel_name

    def setHV(self,channel_name):
        self.channels["HV"]=channel_name

    def __del__(self):
        """Cleanup when widget is destroyed"""
        self.queryThread.stop()

    @pyqtSlot()
    def update(self):
        """Periodic update method"""
        self.queryThread.setup_query('GetStatus,PowerSupplyId:caen', True)
        self.queryThread.start()

    def handle_query_response(self, data):
        """Handle the response from query thread"""
        try:
            if data['caen_'+self.channels["LV"]+'_IsOn'] < 0.5:
                        self.lv_off_when_hv_off = False
                        
            for hl,channel in self.channels.items():
                if self.lv_off_when_hv_off :
                        self.led[hl].setStyleSheet("background-color: yellow")
                else:
                    if data['caen_'+channel+'_IsOn'] > 0.5:
                        self.led[hl].setStyleSheet("background-color: green")
                    else:
                        self.led[hl].setStyleSheet("background-color: red")
                if hl=="HV":
                    self.label[hl].setText(
                    f'V: {data["caen_"+channel+"_Voltage"]:3.1f}V '
                    f'C: {data["caen_"+channel+"_Current"]:2.1f}uA '
                    )
                    # Check if we need to turn off LV based on HV voltage
                    if self.lv_off_when_hv_off and data["caen_"+channel+"_Voltage"] <= 10.0:
                        print("Switching OFF LV ")
                        self.off(self.channels["LV"])
                        
                else:
                    self.label[hl].setText(
                    f'V: {data["caen_"+channel+"_Voltage"]:2.1f}V '
                    f'C: {data["caen_"+channel+"_Current"]:1.1f}A '
                    f'P: {data["caen_"+channel+"_Voltage"]*data["caen_"+channel+"_Current"]:1.1f}W'
                    )
        except Exception as e:
            print(f"Error handling response: {e}")

    def handle_query_error(self, error_msg):
        """Handle errors from query thread"""
        print(f"Query error: {error_msg}")

    @pyqtSlot()
    def on(self, channel):
        print(f'TurnOn,PowerSupplyId:caen,ChannelId:{channel}')
        self.queryThread.setup_query(f'TurnOn,PowerSupplyId:caen,ChannelId:{channel}')
        self.queryThread.start()

    @pyqtSlot()
    def off(self, channel):
        print(f'TurnOff,PowerSupplyId:caen,ChannelId:{channel}')
        self.queryThread.setup_query(f'TurnOff,PowerSupplyId:caen,ChannelId:{channel}')
        self.queryThread.start()

def main():
    app = QApplication(sys.argv)
    ex = caenGUI()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()


