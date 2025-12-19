__author__ = "Nadav"

import datetime
import smtplib
import ssl
from email.message import EmailMessage
import random
from classes import DB, PROTO, Func, CustomLogger
import queue
import threading


class Server:
    def __init__(self, cln_sock, addr, logging_level, tid):
        self.username = ""
        self.db = DB()
        self.PROTO = None
        self.cln_sock = cln_sock
        self.addr = addr
        self.tid = tid
        self.logger = CustomLogger(f"Server no.{tid}", logging_level)
        self.logging_level  = logging_level
        self.Print = self.logger.Print
        self.dict_of_operations = {b"CONCT": self.login, b"SGNUP": self.sign_up,
                                   b"SCODE": self.send_code, b'VRFYC': self.verify_code,
                                   b'UPDTE': self.update_password, b'READY': self.make_ready,
                                   b'CANCL': self.cancel_ready, b'LGOUT': self.logging_out_user,
                                   b'FUNCT': self.handle_game_request}

        self.to_continue = True
        self.thread_num = 1
        self.email_sender = "aurex.main.service@gmail.com"
        self.email_app_password = 'hbwcmfmewpcpjvvh'
        self.has_DH = True
        self.has_RSA = True

        self.is_ready_for_game = False
        self.moves_to_perform = queue.Queue()

        self.moves_to_check_by_game_server = []

    def run(self):
        t = threading.Thread(target=self.handle_client, args=(self.cln_sock, self.addr)).start()

    def make_ready(self, lst_of_parameters):
        self.is_ready_for_game = True
        return "LISTD|ok"

    def cancel_ready(self, lst_of_parameters):
        self.is_ready_for_game = False
        return "CACLD|ok"

    def logging_out_user(self, lst_of_parameters):
        self.username = ""
        return "EXTLG|ok"

    def get_users(self):
        return self.db.get_users()

    def create_code_for_email(self):
        code = random.randint(100000, 999999)
        code = str(code)
        return code

    def check_info(self, username, password, validate_password, email):
        flag = True
        for item in [username, password, validate_password, email]:
            flag = flag and item != ""
        flag = flag and (password == validate_password)
        return flag

    def send_one_message(self, data, encryption=True):
        self.PROTO.send_one_message(data, encryption)

    def recv_one_message(self, encryption=True):
        return self.PROTO.recv_one_message(encryption)

    def handle_encryption_method(self, cln_socket, addr):
        self.PROTO = PROTO(f"Server no.{self.tid}", self.logging_level, self.tid, cln_sock=cln_socket)
        data = self.recv_one_message(encryption=False)
        if "DH" in data.decode():
            if self.has_DH:
                self.PROTO.send_one_message(b"ANSOK|yes", False)
                self.contant_with_DH()
            else:
                self.PROTO.send_one_message(b"ERR02|no", False)
                self.handle_encryption_method(cln_socket, addr)
        if "RSA" in data.decode():
            if self.has_RSA:
                self.PROTO.send_one_message(b"ANSOK|yes", False)
                self.contact_with_RSA()
            else:
                self.PROTO.send_one_message(b"ERR02|no", False)
                self.handle_encryption_method(cln_socket, addr)

    def handle_client(self, cln_socket, addr):
        """
        Handles communication with a connected client.
        """
        try:
            self.handle_encryption_method(cln_socket, addr)
        except:
            self.Print(f"An error occurred. Server {self.tid} exit.",40)
            self.to_continue = False
        while self.to_continue:
            try:
                bin_data = self.PROTO.recv_one_message()
                if bin_data is None:
                    self.Print(f"Client closed connection. Server {self.tid} exit.", 20)
                    self.to_continue = False
                    self.is_ready_for_game = False
                    break  # exit while loop

                query = bin_data[:5]
                content = bin_data[6:]
                threading.Thread(target=self.handle_query, args=(query, content), daemon=True).start()

            except Exception as e:
                self.Print(f"An error occurred. {e}. Server {self.tid} exit.", 40)
                self.to_continue = False
        self.PROTO.close()

    def perform_moves(self):
        while True:
            func = self.moves_to_perform.get(block=True)
            self.send_one_message(func.encode())


    def contant_with_DH(self):
        bin_data = self.PROTO.recv_one_message(False)
        query, parameters = bin_data.split(b'|')
        self.PROTO.set_parameters_dh(parameters)
        self.PROTO.send_one_message(b"ANSOK|yes", False)

        bin_data = self.PROTO.recv_one_message(False)
        query, public_key = bin_data.split(b'|')
        self.PROTO.create_shared_key_dh(public_key)
        msg = b"GTKEY|" + self.PROTO.get_public_key_dh()
        self.PROTO.send_one_message(msg, False)

    def contact_with_RSA(self):
        bin_data = self.PROTO.recv_one_message(False)
        if bin_data == b"CRTKY":
            self.PROTO.create_RSA_keys()
            msg = b"GETKY|" + self.PROTO.get_public_key_RSA()
            self.PROTO.send_one_message(msg, False)
            bin_data = self.PROTO.recv_one_message(False)
            query = bin_data[:5]
            encrypted_key = bin_data[6:]
            if query == b"GETKY":
                self.PROTO.get_encrypted_AES_key(encrypted_key)
                self.PROTO.send_one_message(b"ANSOK|yes")

    def login(self, lst_of_parameters):
        """
        :return: Success or failure message.
        """
        username = lst_of_parameters[0]
        password = lst_of_parameters[1]
        if self.db.is_exist(username, password):
            msg = "LOGED|Connection Succeed"
            self.username = username
        else:
            self.username = ""
            msg = "ERR03|Connection Failed"
        return msg

    def send_code(self, lst_of_parameters):
        # gets [email]

        email = lst_of_parameters[0]
        username = email
        user_by_email = self.db.get_user_by_email(email)
        user_by_username = self.db.get_user_by_username(username)

        if user_by_email is not None:
            email_code = self.create_code_for_email()
            time_until_available = datetime.datetime.now() + datetime.timedelta(minutes=5)
            user_by_email.set_reset_time(time_until_available)
            user_by_email.set_verification_code(email_code)

            self.db.update_info(user_by_email.get_username(), user_by_email)
            return self.send_email(email, email_code, time_until_available)

        if user_by_username is not None:
            email_code = self.create_code_for_email()
            time_until_available = datetime.datetime.now() + datetime.timedelta(minutes=5)
            user_by_username.set_reset_time(time_until_available)
            user_by_username.set_verification_code(email_code)

            self.db.update_info(user_by_username.get_username(), user_by_username)
            return self.send_email(user_by_username.get_email(), email_code, time_until_available)

        return "ERR04|An Error occurred with sending the code."

    def send_email(self, email_receiver, email_code, time_until_available):
        """ Sends an email using SMTP with SSL. """
        em = EmailMessage()
        em["From"] = self.email_sender
        em["To"] = email_receiver
        em["Subject"] = "Email Verification Code"
        em.set_content(
            f"Your Code is: {email_code}. Available until {time_until_available.strftime('%d/%m/%Y %H:%M:%S')}.")

        context = ssl.create_default_context()

        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as smtp:
                smtp.login(self.email_sender, self.email_app_password)
                smtp.sendmail(self.email_sender, email_receiver, em.as_string())
            return "SENTM|Email sent successfully"
        except Exception as e:
            return f"ERR05|An error occurred. Error sending email: {e}"

    def verify_code(self, lst_of_parameters):
        # the user could send an email by typing his email/username
        # gets [email/username, code_to_check]
        email = lst_of_parameters[0]
        username = email
        code_to_check = lst_of_parameters[1]
        user_by_email = self.db.get_user_by_email(email)
        user_by_username = self.db.get_user_by_username(username)

        if user_by_email is not None:
            if user_by_email.is_code_match_and_available(datetime.datetime.now(), code_to_check):
                return "VRFYD|Code is Correct!"
        if user_by_username is not None:
            if user_by_username.is_code_match_and_available(datetime.datetime.now(), code_to_check):
                return "VRFYD|Code is Correct!"
        return "ERR06|Error with verification code!"

    def update_password(self, lst_of_parameters):
        # gets [email, new_password1, new_password2]
        email = lst_of_parameters[0]
        username = lst_of_parameters[0]
        pass1 = lst_of_parameters[1]
        pass2 = lst_of_parameters[2]
        if pass1 == '' or pass2 == '':
            return "ERR08|At least one of the passwords is empty"
        if pass1 != pass2:
            return "ERR07|The two password are the same!"

        user_by_email = self.db.get_user_by_email(email)
        user_by_username = self.db.get_user_by_username(username)
        #checking for new password
        if user_by_email is not None:
            if user_by_email.get_password() == pass1:
                return "ERR09|Choose a new password!"

        if user_by_username is not None:
            if user_by_username.get_password() == pass1:
                return "ERR09|Choose a new password!"

        if user_by_email is not None:
            user_by_email.set_password(pass1)
            user_by_email.set_reset_time(None)
            user_by_email.set_verification_code(None)
            self.db.update_info(user_by_email.get_username(), user_by_email)
            return "UPDTD|Password has updated"
        if user_by_username is not None:
            user_by_username.set_password(pass1)
            user_by_username.set_reset_time(None)
            user_by_username.set_verification_code(None)
            self.db.update_info(user_by_username.get_username(), user_by_username)
            return "UPDTD|Password has updated"
        return "ERR09|An error occurred with the update process."

    def sign_up(self, lst_of_parameters):
        """
        Handles user registration.

        :return: Success or failure message.
        """
        username = lst_of_parameters[0]
        password = lst_of_parameters[1]
        validate_password = lst_of_parameters[2]
        email = lst_of_parameters[3]
        if self.check_info(username, password, validate_password, email):
            if self.db.add_user(username, password, email):
                msg = f"SIGND|{username} has been added"
            else:
                msg = f"ERR10|Failed to add user."
        else:
            msg = f"ERR10|Failed to add user."
        return msg


    def handle_query(self, query, bin_content):
        try:
            if query == b'FUNCT':
                self.handle_game_request(bin_content)
            else:
                lst_of_parameters = bin_content.decode().split('|')
                func = self.dict_of_operations[query]
                msg = func(lst_of_parameters)
                msg_to_send = msg.encode()
                self.send_one_message(msg_to_send)
        except Exception as e:
            msg = "ERR01|An error occurred."
            msg_to_send = msg.encode()
            self.send_one_message(msg_to_send)


    def handle_game_request(self, bin_content):
        func = Func.from_str(bin_content.decode())
        self.moves_to_check_by_game_server.append(func)

"""
The "big server class" uses the server class, to match between client to a mini-srv for himself.
"""

import socket
import threading
from classes import CustomLogger


class Big_Server:
    def __init__(self, ip, port, logging_level):
        self.srv_socket = socket.socket()
        self.ip = ip
        self.port = port
        self.to_continue = True
        self.show_db = True
        self.logger = CustomLogger("Big Server Class", logging_level)
        self.Print = self.logger.Print
        self.logging_level = logging_level

        self.tid = 0

    def run(self, lst_of_mini_servers):
        try:
            self.lst = lst_of_mini_servers
            self.srv_socket.bind((self.ip, self.port))
            self.srv_socket.listen(5)
            self.Print("Big server is running..", 10)
            while self.to_continue:
                self.tid += 1
                cln_sock, addr = self.srv_socket.accept()
                t = threading.Thread(target=self.handle_client, args=(cln_sock, addr, self.tid))
                t.start()
        except OSError as e:
            self.Print(f"CONNECTION ERROR! {e}", 50)
        except Exception as e:
            self.Print(f"ERROR! {e}", 50)

    def handle_client(self, cln_sock, addr, tid):
        mini_srv = Server(cln_sock, addr, self.logging_level, tid)
        self.lst.append(mini_srv)
        if self.show_db:
            self.Print(mini_srv.get_users(), 10)
            self.show_db = False
        mini_srv.run()


import socket
import ssl

class TempServer:
    def __init__(self):
        ip, port = "0.0.0.0", 23456

        # Create normal TCP socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind((ip, port))
        self.sock.listen(5)

        # Create SSL context (TLS server)
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.load_cert_chain(certfile="cert.pem", keyfile="key.pem")

        print(f"TLS server listening on {ip}:{port}")

    def start(self):
        while True:
            client_sock, addr = self.sock.accept()
            print("Client connected:", addr)

            # Wrap socket with TLS
            with self.context.wrap_socket(client_sock, server_side=True) as tls_sock:
                while True:
                    data = tls_sock.recv(1024)
                    if not data:
                        break
                    print("Received:", data.decode())

            print("Client disconnected")


if __name__ == "__main__":
    temp_srv = TempServer()
    temp_srv.start()
