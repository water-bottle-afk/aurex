import socket
import ssl

HOST = "127.0.0.1"
PORT = 45541

context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain(certfile="cert.pem", keyfile="key.pem")

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.bind((HOST, PORT))
    sock.listen(5)
    print(f"🔐 TLS Echo Server listening on {HOST}:{PORT}")

    with context.wrap_socket(sock, server_side=True) as ssock:
        conn, addr = ssock.accept()
        print("Client connected:", addr)

        while True:
            data = conn.recv(1024)
            if not data:
                break

            print("Received:", data.decode())
            conn.sendall(data)  # echo back

        conn.close()
        print("Client disconnected")
