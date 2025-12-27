from classes import PROTO, CustomLogger
import threading


class Client:
    """
    Blockchain Protocol Client - handles TLS communication with server.
    All UI is handled by the Flutter/Dart application.
    """

    def __init__(self, ip, port, logging_level):
        self.logger = CustomLogger("Client", logging_level)
        self.Print = self.logger.Print
        self.logging_level = logging_level
        self.PROTO = PROTO("Client", logging_level=logging_level)
        
        # Connect to server with TLS
        try:
            self.PROTO.connect(ip, port, use_tls=True)
            self._send_start_message()
        except Exception as e:
            self.Print(f"Failed to connect to server: {e}", 40)
            raise

        # Message handlers for protocol responses
        self.message_handlers = {
            "LOGED": self._handle_login_response,
            "SIGND": self._handle_signup_response,
            "SENTM": self._handle_verification_code_sent,
            "VRFYD": self._handle_code_verified,
            "UPDTD": self._handle_password_updated,
            "EXTLG": self._handle_logout,
        }

        self.is_encrypted = True  # TLS is always encrypted
        self.is_connected = True

        # Start receive loop in background thread
        threading.Thread(target=self._recv_loop, daemon=True).start()

    def _send_start_message(self):
        """
        Send initial START message to establish connection.
        Protocol message 1: START (client → server)
        """
        msg = b"START|Client_Connect"
        self.PROTO.send_one_message(msg)
        
        # Wait for ACCPT (Accept connection) response
        response = self.PROTO.recv_one_message()
        if response is None:
            raise Exception("No response from server")
        
        try:
            query = response[:5].decode().strip()
            if query == "ACCPT":
                self.Print("Connection accepted by server", 20)
            else:
                raise Exception(f"Unexpected response: {query}")
        except Exception as e:
            self.Print(f"Error in connection handshake: {e}", 40)
            raise

    def _recv_loop(self):
        """
        Continuously receive and process messages from server.
        Processes protocol messages and calls appropriate handlers.
        """
        while self.is_connected:
            try:
                bin_content = self.PROTO.recv_one_message()
                if bin_content is None:
                    self.Print("Connection closed by server", 20)
                    self.is_connected = False
                    break
                
                # Parse message: first 5 bytes are query code, then '|', then data
                try:
                    query = bin_content[:5].decode().strip()
                    data = bin_content[6:].decode() if len(bin_content) > 6 else ""
                except Exception as decode_error:
                    self.Print(f"Error decoding message: {decode_error}", 40)
                    continue
                
                # Handle error messages
                if "ERR" in query:
                    self.Print(f"Server error {query}: {data}", 40)
                # Handle registered message handlers
                elif query in self.message_handlers:
                    handler = self.message_handlers[query]
                    threading.Thread(target=handler, args=(data,), daemon=True).start()
                else:
                    self.Print(f"Unrecognized query: {query}", 40)
                    
            except Exception as e:
                self.Print(f"Error in recv_loop: {e}", 50)
                break

    # ====== PROTOCOL METHODS ======

    def login(self, username, password):
        """
        Login process - sends LOGIN message to server.
        Protocol message 6: LOGIN (client → server)
        """
        try:
            msg = f"LOGIN|{username}|{password}"
            
            if len(msg) <= 60000:  # the size field is two bytes (max 65535)
                self.PROTO.send_one_message(msg.encode())
                self.Print(f"Sent: {msg}", 20)
            else:
                self.Print("Login data is too long!", 40)
        except Exception as e:
            self.Print(f"Error in login: {e}", 40)

    def _handle_login_response(self, data):
        """Handle login response from server"""
        self.Print(f"Login response: {data}", 20)

    def signup(self, username, password, confirm_password, email):
        """
        Sign up process - sends SGNUP message to server.
        Protocol message 5: SGNUP (client → server)
        """
        try:
            msg = f"SGNUP|{username}|{password}|{confirm_password}|{email}"
            
            if len(msg) <= 60000:
                self.PROTO.send_one_message(msg.encode())
                self.Print(f"Sent: {msg}", 20)
            else:
                self.Print("Signup data is too long!", 40)
        except Exception as e:
            self.Print(f"Error in signup: {e}", 40)

    def _handle_signup_response(self, data):
        """Handle signup response from server"""
        self.Print(f"Signup response: {data}", 20)

    def send_verification_code(self, email):
        """
        Email verification code request - sends SCODE message to server.
        Protocol message 9: SCODE (client → server)
        """
        try:
            msg = f"SCODE|{email}"
            
            if len(msg) <= 60000:
                self.PROTO.send_one_message(msg.encode())
                self.Print(f"Sent: {msg}", 20)
            else:
                self.Print("Email is too long!", 40)
        except Exception as e:
            self.Print(f"Error in send_verification_code: {e}", 40)

    def _handle_verification_code_sent(self, data):
        """Handle verification code sent response"""
        self.Print(f"Verification code sent: {data}", 20)

    def verify_code(self, email, code):
        """
        Verify code process - sends VRFYC message to server.
        Protocol message 10: VRFYC (client → server)
        """
        try:
            msg = f"VRFYC|{email}|{code}"
            
            if len(msg) <= 60000:
                self.PROTO.send_one_message(msg.encode())
                self.Print(f"Sent: {msg}", 20)
            else:
                self.Print("Verification data is too long!", 40)
        except Exception as e:
            self.Print(f"Error in verify_code: {e}", 40)

    def _handle_code_verified(self, data):
        """Handle code verification response"""
        self.Print(f"Code verified: {data}", 20)

    def update_password(self, email, new_password, confirm_password):
        """
        Update password process - sends UPDTE message to server.
        Protocol message 11: UPDTE (client → server)
        """
        try:
            msg = f"UPDTE|{email}|{new_password}|{confirm_password}"
            
            if len(msg) <= 60000:
                self.PROTO.send_one_message(msg.encode())
                self.Print(f"Sent: {msg}", 20)
            else:
                self.Print("Password update data is too long!", 40)
        except Exception as e:
            self.Print(f"Error in update_password: {e}", 40)

    def _handle_password_updated(self, data):
        """Handle password update response"""
        self.Print(f"Password updated: {data}", 20)

    def logout(self):
        """
        Logout process - sends LGOUT message to server.
        Protocol message 7: LGOUT (client → server)
        """
        try:
            msg = "LGOUT|"
            self.PROTO.send_one_message(msg.encode())
            self.Print(f"Sent: {msg}", 20)
        except Exception as e:
            self.Print(f"Error in logout: {e}", 40)

    def _handle_logout(self, data):
        """Handle logout response"""
        self.Print(f"Logout response: {data}", 20)

    def close(self):
        """Close connection to server"""
        try:
            self.is_connected = False
            self.PROTO.close()
            self.Print("Connection closed", 20)
        except Exception as e:
            self.Print(f"Error closing connection: {e}", 40)


# Example usage
if __name__ == "__main__":
    import time
    
    logging_level = 10
    
    try:
        # Connect to server
        client = Client("172.16.64.109", 23456, logging_level)
        
        # Keep client running to receive messages
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        client.close()
    except Exception as e:
        print(f"Error: {e}")

