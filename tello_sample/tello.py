import threading
import socket
import sys
import time
import re

instance = None
is_actual_machine = True
self_port_for_actual_machine = 9000
actual_tello_address = ("192.168.10.1", 8889)
self_port_for_vr_machine = 8889
vr_tello_address = ("127.0.0.1", 8889)

class Tello:

    __instance = None

    def __init__(self):
        Tello.__instance = self

        self.abort_flag = False
        self.host = ''

        if is_actual_machine:
            self.port = self_port_for_actual_machine
            self.tello_address = actual_tello_address
        else:
            self.port = self_port_for_vr_machine
            self.tello_address = vr_tello_address
            
        self.locaddr = (self.host,self.port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        self.sock.bind(self.locaddr)
        self.response = None
        self.recvThread = threading.Thread(target=self.recv)
        self.recvThread.start()
        
        if not is_actual_machine: Tello.getInstance().send('name sample', False)

    def __del__(self):
        """Closes the local sock."""
        self.sock.close()

    def recv(self):
        while True: 
            try:
                self.response, server = self.sock.recvfrom(1518)
                print(self.response.decode(encoding="utf-8"))
            except Exception:
                print ('\nExit . . .\n')
                break
    def send(self, buf, is_wait):
        if not ValidateCommand(buf):
            print("Please submit the correct value.")
            return
        self.response = None
        msg = buf
        msg = msg.encode(encoding="utf-8")
        sent = self.sock.sendto(msg, self.tello_address)
        print(buf)
        if is_wait == False:
            return
        while True:
            if self.response != None:
                time.sleep(0.1)
                return
            if self.abort_flag == True:
                return
    def abort(self):
        self.abort_flag = True

    @staticmethod
    def getInstance():
        if Tello.__instance == None:
            Tello()
        return Tello.__instance

def SwitchPortNum():
    global is_actual_machine
    is_actual_machine = False

def Send(buf, is_wait = True):
    instance = Tello.getInstance()
    instance.send(buf, is_wait)
    if not is_actual_machine and buf == 'land':
        instance.send("emergency", True)
        instance.send("disconnect", False)
        instance.abort()
        del instance

def ValidateCommand(cmd):
    if re.fullmatch('streamon', cmd) \
       or re.fullmatch('streamoff', cmd) \
       or re.fullmatch('tof\?', cmd) \
       or re.fullmatch('fpv', cmd) \
       or re.fullmatch('tpv', cmd) \
       or re.fullmatch('cam [a-z]+', cmd) \
       or re.fullmatch('ping', cmd) \
       or re.fullmatch('name [a-zA-Z0-9]+', cmd) \
       or re.fullmatch('command', cmd) \
       or re.fullmatch('takeoff', cmd) \
       or re.fullmatch('land', cmd) \
       or re.fullmatch('emergency', cmd) \
       or re.fullmatch('up [0-9]+', cmd) \
       or re.fullmatch('down [0-9]+', cmd) \
       or re.fullmatch('left [0-9]+', cmd) \
       or re.fullmatch('right [0-9]+', cmd) \
       or re.fullmatch('forward [0-9]+', cmd) \
       or re.fullmatch('back [0-9]+', cmd) \
       or re.fullmatch('cw [0-9]+', cmd) \
       or re.fullmatch('ccw [0-9]+', cmd) \
       or re.fullmatch('go -?[0-9]+ -?[0-9]+ -?[0-9]+ [0-9]+', cmd) \
       or re.fullmatch('curve -?[0-9]+ -?[0-9]+ -?[0-9]+ -?[0-9]+ -?[0-9]+ -?[0-9]+ [0-9]+', cmd) \
       or re.fullmatch('speed [0-9]+', cmd) \
       or re.fullmatch('rc -?[0-9]+ -?[0-9]+ -?[0-9]+ -?[0-9]+', cmd) \
       or re.fullmatch('wifi', cmd) \
       or re.fullmatch('speed\?', cmd) \
       or re.fullmatch('battery\?', cmd) \
       or re.fullmatch('time\?', cmd) \
       or re.fullmatch('height\?', cmd) \
       or re.fullmatch('temp\?', cmd) \
       or re.fullmatch('attitude\?', cmd) \
       or re.fullmatch('baro\?', cmd) \
       or re.fullmatch('acceleration\?', cmd) \
       or re.fullmatch('disconnect', cmd) \
       or re.fullmatch('flip [a-z]', cmd) :
        return True
    return False

def Emergency():
    instance = Tello.getInstance()
    instance.send("emergency", True)
    if not is_actual_machine: instance.send("disconnect", False)
    instance.abort()
    del instance
