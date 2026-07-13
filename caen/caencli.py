#!/bin/env python3
import sys
import datetime
from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter
import socket

BUFFER_SIZE = 100000


class tcp_util:
    """Utility class for tcp communication management."""

    def __init__(self, ip, port):
        self.ip = ip
        self.port = port
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.headerBytes = 4
        self.connectSocket()

    def __del__(self):
        """Destructor, closes socket"""
        try:
            self.closeSocket()
        except:
            pass

    def connectSocket(self):
        """Connects socket"""
        self.socket.connect((self.ip, self.port))

    def closeSocket(self):
        """Closes socket connection"""
        self.socket.close()

    def sendMessage(self, message):
        """Encodes message and sends it on socket"""
        encodedMessage = self.encodeMessage(message)
        self.socket.send(encodedMessage)

    def encodeMessage(self, message):
        """Encodes message adding 4 bytes header"""
        messageLength = len(message) + self.headerBytes + 4
        N = 0
        encodedMessage = (
            (messageLength).to_bytes(4, byteorder="big")
            + N.to_bytes(4, byteorder="big")
            + message.encode("utf-8")
        )
        return encodedMessage


class caen:
    def on(self, channel, verbose=True):
        self.send("TurnOn,PowerSupplyId:caen,ChannelId:" + channel, verbose=verbose)

    def off(self, channel, verbose=True):
        self.send("TurnOff,PowerSupplyId:caen,ChannelId:" + channel, verbose=verbose)

    def send(self, message, receive=False, verbose=True):
        if verbose:
            print(str(datetime.datetime.now()), message)
        tcpClass = tcp_util(ip="192.168.0.45", port=7000)
        tcpClass.sendMessage(message)
        if receive:
            data = tcpClass.socket.recv(BUFFER_SIZE)[8:].decode("utf-8")
            if verbose:
                print(data)


if __name__ == "__main__":
    parser = ArgumentParser(formatter_class=ArgumentDefaultsHelpFormatter)
    parser.add_argument(
        "-c",
        "--channel",
        dest="channel",
        required=True,
        help="channel number for LV Caen control. e.g. BLV02",
    )
    parser.add_argument(
        "--on",
        dest="action",
        action="store_const",
        const="on",
        help="turn on the specified channel",
    )
    parser.add_argument(
        "--off",
        dest="action",
        action="store_const",
        const="off",
        help="turn off the specified channel",
    )
    args = parser.parse_args()

    if not args.action:
        print("Action (--on or --off) is required.")
        sys.exit(1)

    caen_controller = caen()
    if args.action == "on":
        caen_controller.on(args.channel)
    elif args.action == "off":
        caen_controller.off(args.channel)

    print("DONE")
