#!/usr/bin/python
# get from https://wiki.mikrotik.com/wiki/Manual:API

import binascii
import hashlib
import select
import socket
import sys


class ApiRos(object):
    """
    Routeros API
    """
    sock = ''

    def __init__(self, host='', port=8728, user='', password='', debug=True):
        """
        Initialize object
        :param host: ip address of mikrotik device
        :param port: tcp port, 8728 by default, must be integer
        :param user: username
        :param password: password to access
        :param debug: if true, show information in console
        """
        self.current_tag = 0
        self.debug = debug

        if host:
            self.connect(host, port)
            if user:
                self.login(user, password)

    def connect(self, host, port):
        """
        Connect to mikrotik
        :param host: hostname to connect to (string, default previous host)
        :param port: port to connect to (integer, default previous port)
        :return:
        """
        # Try to open socket
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        except socket.error as e:
            print(("Socket creation error: %s" % e))

        # Try to connect to socket
        try:
            self.sock.connect((host, port))

        except socket.gaierror as e:
            print(("Address-related error connecting to server: %s" % e))
            sys.exit(1)

        except socket.error as e:
            print(("Connection error: %s" % e))
            sys.exit(1)

    def login(self, user, password):
        """
        Authentication on device
        :param user: username must be string
        :param password: password must be string
        :return:
        """
        chal = None

        for repl, attrs in self.talk(["/login"]):
            chal = binascii.unhexlify(attrs['=ret'])
        md = hashlib.md5()
        md.update('\x00'.encode())
        md.update(password.encode())
        md.update(chal)
        self.talk(["/login", "=name=" + user, "=response=00" + binascii.hexlify(md.digest()).decode()])

    def close(self):
        self.sock.close()

    def talk(self, words):
        if self.write_sentence(words) == 0:
            return
        r = []
        while True:
            i = self.read_sentence()
            if len(i) == 0:
                continue
            reply = i[0]
            attrs = {}
            for w in i[1:]:
                j = w.find('=', 1)
                if j == -1:
                    attrs[w] = ''
                else:
                    attrs[w[:j]] = w[j + 1:]
            r.append((reply, attrs))
            if reply == '!done':
                return r

    def write_sentence(self, words):
        ret = 0
        for w in words:
            self.write_word(w)
            ret += 1
        self.write_word('')
        return ret

    def read_sentence(self):
        r = []
        while True:
            w = self.read_word()
            if w == '':
                return r
            r.append(w)

    def write_word(self, w):
        # Uncomment to debug
        if self.debug:
            print(("<<< " + w))
        self.write_len(len(w))
        self.write_str(w)

    def read_word(self):
        ret = self.read_str(self.read_len())
        if self.debug:
            print((">>> " + ret))
        return ret

    def write_len(self, l):
        if l < 0x80:
            self.write_str(chr(l))
        elif l < 0x4000:
            l |= 0x8000
            self.write_str(chr((l >> 8) & 0xFF))
            self.write_str(chr(l & 0xFF))
        elif l < 0x200000:
            l |= 0xC00000
            self.write_str(chr((l >> 16) & 0xFF))
            self.write_str(chr((l >> 8) & 0xFF))
            self.write_str(chr(l & 0xFF))
        elif l < 0x10000000:
            l |= 0xE0000000
            self.write_str(chr((l >> 24) & 0xFF))
            self.write_str(chr((l >> 16) & 0xFF))
            self.write_str(chr((l >> 8) & 0xFF))
            self.write_str(chr(l & 0xFF))
        else:
            self.write_str(chr(0xF0))
            self.write_str(chr((l >> 24) & 0xFF))
            self.write_str(chr((l >> 16) & 0xFF))
            self.write_str(chr((l >> 8) & 0xFF))
            self.write_str(chr(l & 0xFF))

    def read_len(self):
        c = ord(self.read_str(1))
        if (c & 0x80) == 0x00:
            pass
        elif (c & 0xC0) == 0x80:
            c &= ~0xC0
            c <<= 8
            c += ord(self.read_str(1))
        elif (c & 0xE0) == 0xC0:
            c &= ~0xE0
            c <<= 8
            c += ord(self.read_str(1))
            c <<= 8
            c += ord(self.read_str(1))
        elif (c & 0xF0) == 0xE0:
            c &= ~0xF0
            c <<= 8
            c += ord(self.read_str(1))
            c <<= 8
            c += ord(self.read_str(1))
            c <<= 8
            c += ord(self.read_str(1))
        elif (c & 0xF8) == 0xF0:
            c = ord(self.read_str(1))
            c <<= 8
            c += ord(self.read_str(1))
            c <<= 8
            c += ord(self.read_str(1))
            c <<= 8
            c += ord(self.read_str(1))
        return c

    def write_str(self, string):
        n = 0
        while n < len(string):
            s = string[n:]
            r = self.sock.send(string[n:].encode())
            if r == 0:
                raise RuntimeError("connection closed by remote end")
            n += r

    def read_str(self, length):
        ret = ''
        while len(ret) < length:
            s = self.sock.recv(length - len(ret))
            if s == '':
                raise RuntimeError("connection closed by remote end")
            ret += s.decode()
        return ret

    @property
    def parse_out(self):
        """
        Parse output after write_sentence
        :return: dictionary
        """
        line = {}
        result = []
        # Reading output
        while True:
            r = select.select([self.sock], [], [], None)
            if self.sock in r[0]:
                # Something to read in socket, read sentence
                rows = self.read_sentence()

                for row in rows:
                    if row == '!re':
                        if line:
                            result.append(line)
                            line = {}
                        continue
                    if row == '!done':
                        result.append(line)
                        return result
                    row = row.split('=')[1:]
                    line[row[0]] = row[1]

    def execute(self, command):
        """
        Execute command
        Example of command:
        ["/ip/firewall/nat/add",
                    "=chain=dstnat",
                    "=action=dst-nat",
                    "=to-addresses=10.10.10.10",
                    "=to-ports=80",
                    "=protocol=tcp",
                    "=in-interface=ether1-gateway",
                    "=dst-port=80",
                    "=place-before=1",
                    "=comment=added_by_script"]

        For more information read https://wiki.mikrotik.com/wiki/Manual:API
        :param command: list (command with parameters)
        :return: dictionary
        """
        # Send command
        self.write_sentence(command)
        # Return parsed output
        return self.parse_out


def main():

    apiros = ApiRos(sys.argv[1])
    apiros.login(sys.argv[2], sys.argv[3])

    input_sentence = []

    while True:
        r = select.select([apiros.sock, sys.stdin], [], [], None)
        if apiros.sock in r[0]:
            # Something to read in socket, read sentence
            x = apiros.read_sentence()

        if sys.stdin in r[0]:
            # Read line from input and strip off newline
            line = sys.stdin.readline()
            line = line[:-1]

            # If empty line, send sentence and start with new
            # otherwise append to input sentence
            if line == '':
                apiros.write_sentence(input_sentence)
                input_sentence = []
            else:
                input_sentence.append(line)


if __name__ == '__main__':
    main()
