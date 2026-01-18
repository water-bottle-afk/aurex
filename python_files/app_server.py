"""
App Server - Blockchain Transaction Client
Listens for block confirmations from PoW nodes via broadcast
Sends next transaction only after confirmation
"""

import socket
import time
import sys
import os
import json
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'blockchain'))

from json_ledger import JSONLedger


class AppServer:
    """Application server that sends transactions to blockchain nodes and listens for confirmations"""
    
    def __init__(self, host='127.0.0.1', port=13200):
        self.host = host
        self.port = port
        self.listen_port = 13290  # Port for receiving block confirmations
        self.nodes = [
            ('127.0.0.1', 13245),
            ('127.0.0.1', 13246),
            ('127.0.0.1', 13247),
        ]
        self.ledger = JSONLedger()
        self.last_block_confirmation = None
        self.confirmation_event = threading.Event()
        self.listening = False
        self.listener_thread = None
    
    def start_confirmation_listener(self):
        """Start listening for block confirmation broadcasts from nodes"""
        self.listener_thread = threading.Thread(target=self._run_listener, daemon=True)
        self.listener_thread.start()
        self.listening = True
    
    def _run_listener(self):
        """Listen for incoming block confirmations"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((self.host, self.listen_port))
            sock.listen(5)
            
            while self.listening:
                try:
                    sock.settimeout(1)
                    conn, addr = sock.accept()
                    
                    # Receive block confirmation
                    data = conn.recv(4096).decode('utf-8')
                    if data:
                        msg = json.loads(data)
                        if msg.get('type') == 'block_confirmation':
                            self.last_block_confirmation = msg
                            print(f"\n✅ BLOCK CONFIRMATION RECEIVED from {msg.get('miner_node_id', 'Unknown')}")
                            self.confirmation_event.set()
                    
                    conn.close()
                except socket.timeout:
                    continue
                except:
                    pass
            
            sock.close()
        except:
            pass
    
    def send_transaction(self, tx_data):
        """Send transaction to all nodes"""
        print(f"\n📤 Sending transaction...")
        print(f"   Asset: {tx_data.get('asset', 'N/A')}")
        print(f"   Price: ${tx_data.get('price', 'N/A')}")
        print()
        
        results = []
        for i, (host, port) in enumerate(self.nodes, 1):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(3)
                sock.connect((host, port))
                
                # Send transaction with confirmation port
                message = json.dumps({
                    'type': 'transaction', 
                    'data': tx_data,
                    'confirmation_host': self.host,
                    'confirmation_port': self.listen_port
                })
                sock.sendall(message.encode())
                sock.close()
                
                results.append(f"   ✅ Node {i} ({host}:{port})")
            except ConnectionRefusedError:
                results.append(f"   ❌ Node {i} ({host}:{port}) - refused")
            except socket.timeout:
                results.append(f"   ⏱ Node {i} ({host}:{port}) - timeout")
            except Exception as e:
                results.append(f"   ❌ Node {i} ({host}:{port}) - {str(e)}")
        
        print("Connection Results:")
        for result in results:
            print(result)
        
        connected = sum(1 for r in results if '✅' in r)
        print(f"\n✅ Connected to {connected}/{len(self.nodes)} nodes")
        
        if connected == 0:
            return
        
        # Wait for block confirmation from nodes
        print("⏳ Waiting for block confirmation from nodes...")
        self.confirmation_event.clear()
        
        # Wait indefinitely for confirmation from one of the nodes
        if self.confirmation_event.wait(timeout=None):
            confirmation = self.last_block_confirmation
            miner_node_id = confirmation.get('miner_node_id', 'Unknown')
            block_hash = confirmation.get('block_hash', '')[:16] + '...'
            
            print(f"   Hash: {block_hash}")
            print()
        
        # Show last 2 blocks
        print("="*70)
        print("📋 LEDGER - LAST 2 BLOCKS")
        print("="*70 + "\n")
        self.ledger.print_ledger()
        print("\n")
    
    def run_demo(self):
        """Run continuous demo - only sends next transaction after confirmation"""
        tx_num = 1
        
        while True:
            print("\n" + "="*70)
            print(f"TRANSACTION #{tx_num}")
            print("="*70)
            
            tx_data = {
                'asset': f'NFT_{tx_num:03d}',
                'price': 100.5 + tx_num
            }
            
            self.send_transaction(tx_data)
            tx_num += 1
            
            # Wait before sending next transaction
            print("⏸️  Waiting 10 seconds before next transaction...")
            time.sleep(10)
    
    def main(self):
        """Main entry point"""
        print("\n" + "="*70)
        print("🔗 APP SERVER - Blockchain Transaction Client")
        print("="*70)
        print(f"Listen Port: {self.listen_port}")
        print(f"Nodes: {len(self.nodes)}")
        print("="*70 + "\n")
        
        # Start confirmation listener
        self.start_confirmation_listener()
        print(f"[LISTENER] Started on port {self.listen_port}\n")
        
        # Check if nodes are ready
        print("[INIT] Checking if blockchain nodes are ready...")
        ready_count = 0
        
        for i, (host, port) in enumerate(self.nodes, 1):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                sock.connect((host, port))
                sock.close()
                print(f"   ✅ Node {i} on port {port} - READY")
                ready_count += 1
            except:
                print(f"   ❌ Node {i} on port {port} - NOT READY")
        
        print()
        
        if ready_count == 0:
            print("❌ No nodes available!")
            print("Start blockchain with: python launcher.py --nodes 3 --difficulty 4")
            sys.exit(1)
        
        self.run_demo()


if __name__ == "__main__":
    server = AppServer()
    try:
        server.main()
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Stopped\n")
        server.listening = False
        sys.exit(0)
