
import sys
import socket
import unittest

from time import sleep
from pprint import pprint


TCP_RETRY_TIME = 2.0

class nmeaTCP():
    """
    Connect to a TCP socket that provides NMEA data in
    some form.

    Handle error conditions, yield a value when the server has
    produces something.
    """
    def __init__(self, remoteaddr):
        assert type(remoteaddr) == tuple
        assert len(remoteaddr) == 2
        self.remoteaddr = remoteaddr

        self.sock = None
        self.sockfd = None

    def connect(self):
        while True:
            if self.sockfd is not None:
                break

            try:
                self.sock = socket.create_connection(self.remoteaddr)
                self.sockfd = self.sock.makefile()
            except socket.error as e:
                self.sock = None
                sleep(TCP_RETRY_TIME)

    def forever(self):
        while True:
            if not self.sockfd:
                self.connect()

            try:
                line = self.sockfd.readline()  # blocking
            except socket.error as e:
                self.sockfd = None
                sleep(TCP_RETRY_TIME)
            else:
                yield line


if __name__ == "__main__":
    unittest.main()
