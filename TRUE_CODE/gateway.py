__author__ = "Nadav"

from protocols import RSA_Client,RSA_Server, UDPServer
import threading
class GatewayServer:
    def __init__(self):
        self.sock_for_blockchain = RSA_Server("localhost", 12345, dir_for_keys="GatewayKeys", Gateway=True)
        self.sock_for_server = RSA_Client("localhost", 23456) #server ip known
        self.UDPServer = UDPServer("localhost", 44221, "localhost", 12345)
        

        dict_of_msg = {"BUY_ASSET": self.BUY_ASSET,
                       "SELL_ASSET": self.SELL_ASSET,
                       "PUBLISH_TX": self.PUBLISH_TX}
        self.nodes = [] # list of connected nodes (after discovery)
        
        
        last_block_founder_ip = None
        last_block_founder_port = None

        
    def start(self):
        threading.Thread(target=self.UDPServer.run).start()
        threading.Thread(target=self.sock_for_blockchain.contact_with_RSA).start()
        threading.Thread(target=self.sock_for_server.contant_with_RSA).start()

    def broadcast_to_blockchain(self, msg, sock_sender):
        for node in self.nodes:
            if node != sock_sender:
                self.send_tx_to_node(node, msg)

    def send_tx_to_node(self, node_sock, tx_data):
        node_sock.send_one_message(tx_data)


    def BUY_ASSET(self, asset_id, buyer_id):
        pass

    def SELL_ASSET(self, asset_id, seller_id):
        pass

