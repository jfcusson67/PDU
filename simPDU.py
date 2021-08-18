import socket
import time
from random import uniform

from socket import *

def main():
    rx_port = 10001
    tx_port = 10002
    print(f"STARTING simPDU with rx port = {rx_port} and txt port = {tx_port}")
    sock = socket(AF_INET, SOCK_DGRAM)
    sock.bind(('localhost', rx_port))
    sock.settimeout(0.01)  # Timeout of 10ms
    print("Pret a recevoir les paquets")
    while True:
        try:
            data, addr = sock.recvfrom(2048)  # Will not block, timeout = 10ms
            raw_packet = data.decode()
            print('RX: ' + raw_packet)
            element = raw_packet.split(',')
            print(len(element))
            if element[0] == 'SETSRVC':
                return_packet = f'SRVCSET,{element[1]},{element[2]}'
                print('TX: '+return_packet)
                sock.sendto(return_packet.encode(), ('localhost', tx_port))
            elif element[0] == 'STATUS':
                value = uniform(0.5, 1.0)
                return_packet = f'STATUS,{element[1]},{value:.3f}'
                print('TX: '+return_packet)
                sock.sendto(return_packet.encode(), ('localhost', tx_port))
            elif element[0] == 'SETIP':
                return_packet = f'IPSET,{element[1]},{element[2]},{element[3]},{element[4]}'
                print('TX: '+return_packet)
                sock.sendto(return_packet.encode(), ('localhost', tx_port))
            elif element[0] == 'SETPORT':
                return_packet = f'PORTSET,{element[1]}'
                print('TX: ' + return_packet)
                sock.sendto(return_packet.encode(), ('localhost', tx_port))
            elif element[0] == 'RESET':
                return_packet = 'Resetting'
                print('TX: '+return_packet)
                sock.sendto(return_packet.encode(), ('localhost', tx_port))
            else:
                return_packet = 'CMDERROR'
                print('TX: '+return_packet)
                sock.sendto(return_packet.encode(), ('localhost', tx_port))
        except:
            pass
        time.sleep(0.1)


# ########################################################################### #
# ########################################################################### #
if __name__ == '__main__':
    main()