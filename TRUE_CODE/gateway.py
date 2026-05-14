__author__ = "Nadav"

from protocols import RSA_Client,RSA_Server, UDPServer
from config import GATEWAY_UDP_PORT, GATEWAY_IP, GATEWAY_PORT, SERVER_IP, SERVER_PORT, GATEWAY_BLOCKCHAIN_PORT
import threading
class GatewayServer:
    def __init__(self):
        # 1. שרת שמקשיב ל-Blockchain Nodes
        self.node_listener = RSA_Server(GATEWAY_IP, GATEWAY_BLOCKCHAIN_PORT, dir_for_keys="GatewayKeys")
        # הזרקת הלוגיקה: מה לעשות כשנוד מתחבר
        self.node_listener.handle_client = self.handle_node_connection

        # 2. לקוח שמתחבר לשרת הראשי (Main Server)
        self.server_client = RSA_Client(SERVER_IP, SERVER_PORT)
        self.server_client.communicate_with_server = self.communicate_with_main_server 

        # 3. שרת UDP לגילוי צמתים (Discovery)
        self.udp_service = UDPServer(GATEWAY_IP, GATEWAY_UDP_PORT, GATEWAY_IP, GATEWAY_BLOCKCHAIN_PORT)

        dict_of_msg = {"BUY_ASSET": self.buy_asset,
                       "SELL_ASSET": self.sell_asset,
                       "PUBLISH_TX": self.publish_tx}
        

        self.nodes = [] # list of connected nodes (after discovery)
        
        
        last_block_founder_ip = None
        last_block_founder_port = None


    def start(self):
        # הפעלת שירות ה-UDP בטרד נפרד
        threading.Thread(target=self.udp_service.run, daemon=True).start()
        
        # התחברות לשרת הראשי (ביצוע ה-Handshake של ה-RSA כקליינט)
        # אנחנו מריצים את ה-start של הקליינט בטרד כדי שלא יחסום אם השרת הראשי למטה
        threading.Thread(target=self.server_client.start, daemon=True).start()
        
        # הפעלת השרת שמקשיב לנודים
        # זה יריץ את ה-accept() בלולאה, לכן כדאי בטרד נפרד אם ה-Gateway עושה עוד דברים
        threading.Thread(target=self.node_listener.start, daemon=True).start()
        
        print(f"[Gateway] Operational. Routing between Nodes and Server...")
        while True: time.sleep(1)

    def handle_node_connection(self, comm):
        self.node_listener.contact_with_RSA(comm) # ביצוע Handshake מאובטח
        
        while True:
            msg = comm.recv_one_message() 
            if not msg:
                break
            
            # --- כאן קורה הניתוב (The Routing) ---
            # אם קיבלנו הודעה מהנוד, אנחנו מעבירים אותה לשרת הראשי דרך הקליינט שלנו
            if self.server_client.communication: # מוודא שהקליינט מחובר
                self.server_client.communication.send_one_message(msg)
                print(f"[Gateway] Routed message from Node to Main Server")

    def communicate_with_main_server(self, comm):
        self.server_client.contact_with_RSA(comm) # ביצוע Handshake מאובטח
        
        while True:
            msg = comm.recv_one_message() 
            if not msg:
                break
            
            # כאן מטפלים בהודעות שמגיעות מהשרת הראשי (למשל פקודות לקנות/למכור נכסים)
            # בהתאם לסוג ההודעה, נוכל לשלוח פקודות לנודים או לעדכן את הסטטוס שלנו

    def send_to_nodes(self, msg):
        """פונקציית עזר אם השרת הראשי רוצה לשלוח משהו לכל הנודים"""
        # (דורש ניהול רשימת קליינטים בתוך node_listener אם תרצה להוסיף)
        pass

    def broadcast_to_blockchain(self, msg, sock_sender):
        for node in self.nodes:
            if node != sock_sender:
                self.send_tx_to_node(node, msg)

    def send_tx_to_node(self, node_sock, tx_data):
        node_sock.send_one_message(tx_data)


    def buy_asset(self, asset_id, buyer_id):
        pass

    def sell_asset(self, asset_id, seller_id):
        pass

    def publish_tx(self, tx_data):
        self.broadcast_to_blockchain(tx_data, None)

