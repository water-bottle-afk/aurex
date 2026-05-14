
if __name__ == "__main__":
    from protocols import RSA_Client
    from config import SERVER_IP, SERVER_PORT
    c = RSA_Client(SERVER_IP, SERVER_PORT)
    c.start()