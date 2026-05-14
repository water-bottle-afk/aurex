__author__ = "Nadav"
from protocols import RSA_Client,RSA_Server, UDPClient
import threading

class BlockchainNode:
    def __init__(self, ip, port, ledger_path, symbol=None):
        self.ip = ip
        self.port = port
        self.ledger_path = ledger_path
        self.symbol = symbol

    def connect_to_gateway(self):
        gateway_udp_port = None
        self.sock_for_udp_gateway = UDPClient(gateway_udp_port) #gateway ip known
        gateway_ip, gateway_port = self.sock_for_udp_gateway.run()

        self.sock_for_gateway = RSA_Client(gateway_ip, gateway_port)
        threading.Thread(target=self.sock_for_gateway.contant_with_RSA).start()

        self.sock_for_asking = RSA_Server("localhost", 12345, dir_for_keys=f"Node{self.symbol}Keys")

    def mine(self, tx):
        pass

    def validate_tx(self, tx):
        pass
    def add_tx_to_ledger(self, tx):
        pass

    def update_balances(self, tx):
        pass

    def notify_gateway(self, tx):
        msg = f"PUBLISH_TX|{self.ip}|{self.port}" + tx
        msg = msg.encode()
        self.sock_for_gateway.send_one_message(tx)

    def ask_for_ledger_and_balance(self):
        ip,port = self.sock_for_gateway.get_last_founder_ip_port()
        
        asking_sock = RSA_Client(ip, port)
        threading.Thread(target=asking_sock.contant_with_RSA).start()
        asking_sock.send_one_message(b"ASK_FOR_BALANCE")    
        balance = asking_sock.recv_one_message()
        asking_sock.send_one_message(b"ASK_FOR_LEDGER")
        ledger = asking_sock.recv_one_message()

        return balance, ledger
    
    def give_balance(self, asking_sock):
        balance = self.get_balance()
        asking_sock.send_one_message(balance.encode())

    def give_ledger(self, asking_sock):
        ledger = self.get_ledger()
        asking_sock.send_one_message(ledger.encode())



