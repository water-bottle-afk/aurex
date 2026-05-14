__author__ = "Nadav"
from protocols import HTTPSServer,RSA_Server, UDPServer
from config import SERVER_IP, SERVER_PORT, GATEWAY_IP, GATEWAY_PORT, SERVER_PORT_FOR_GATEWAY
import threading

class Server:
    def __init__(self, ip=SERVER_IP, port=SERVER_PORT):
        self.client_listener = RSA_Server(ip, port, dir_for_keys="ServerKeys", name="ClientListener")
        self.client_listener.handle_client = self.communicate_with_client
        
        self.gateway_listener = RSA_Server(ip, SERVER_PORT_FOR_GATEWAY, dir_for_keys="ServerKeys", name="GatewayListener")
        self.gateway_listener.handle_client = self.communicate_with_gateway

    def start(self):
        # הפעלת שני השרתים בטרדים נפרדים כדי שלא יחסמו אחד את השני
        threading.Thread(target=self.client_listener.start, daemon=True).start()
        threading.Thread(target=self.gateway_listener.start, daemon=True).start()
        
        print("Main Server is running (Listening for Clients and Gateway)...")

    def communicate_with_client(self, comm):
        self.client_listener.contact_with_RSA(comm)
        
        while True:
            msg = comm.recv_one_message()
            if not msg: break
            # כאן מטפלים ב-Login ובקשות מהאפליקציה
            if msg.get("type") == "LOGIN":
                # ביצוע הלוגיקה...
                pass

    def communicate_with_gateway(self, comm):

        self.gateway_listener.contact_with_RSA(comm)
        
        while True:
            msg = comm.recv_one_message()
            if not msg: break
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

if __name__ == "__main__":
    server = Server()
    print(f"[*] Starting server at {SERVER_IP}:{SERVER_PORT}...")
    server.start()

