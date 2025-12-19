import socket
import ssl

HOST = "127.0.0.1"
PORT = 45541

context = ssl.create_default_context()
context.check_hostname = False
context.verify_mode = ssl.CERT_NONE  # because self-signed

with socket.create_connection((HOST, PORT)) as sock:
    with context.wrap_socket(sock, server_hostname=HOST) as ssock:
        print("🔐 Connected to TLS server")

        while True:
            msg = input("You: ")
            if msg.lower() == "exit":
                break

            ssock.sendall(msg.encode())
            data = ssock.recv(1024)
            print("Server:", data.decode())
