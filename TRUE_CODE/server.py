__author__ = "Nadav"
from protocols import HTTPSServer,RSA_Server, UDPServer
import threading

class Server:
    def __init__(self, ip, port):
        self.ip = ip
        self.port = port
        self.server = HTTPSServer(ip, port)
        self.sock_for_gateway = RSA_Server("localhost", 23456, dir_for_keys="ServerKeys")
        self.UDPServer = UDPServer("localhost", 44222, "localhost", 12345)

    def start(self):
        threading.Thread(target=self.server.start).start()
        threading.Thread(target=self.sock_for_gateway.contact_with_RSA).start()
        threading.Thread(target=self.UDPServer.run).start()

    def handle_client(client_sock, addr):
        pass

    def login(self, username, password):
        pass

    def signup(self, username, email, password):
        pass

    def forgot_password(self, email):
        pass    

    def buy_asset(self, asset_id, buyer_id):
        pass

    def sell_asset(self, asset_id, seller_id):
        pass

    def load_assets(self, number=10):
        pass

    def upload_image(self, image_data):
        pass

    def notify_client(self):
        pass

    
