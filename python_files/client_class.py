from classes import UDPClient

import threading
from classes import PROTO, Func, CustomLogger
import time



class Client():

    def __init__(self, ip, port, logging_level):

        self.game = None
        self.logger = CustomLogger("Client", logging_level)
        self.Print = self.logger.Print
        self.logging_level = logging_level
        self.PROTO = PROTO("Client", logging_level=logging_level)
        self.PROTO.connect(ip, port)

        # Functions dictionary
        self.function_dict = {
            "Login": self.login_clicked,
            "Sign up": self.signup_clicked,
            "Get verification code": self.get_verification_code,
            "Verify code": self.verify_code,
            "Update password": self.update_user_password
        }

        self.dict_of_operations = {"LOGED": self.process_login, "SIGND": self.proccess_signup,
                                   "SENTM": self.process_get_verification_code, 'VRFYD': self.process_verify_code,
                                   'UPDTD': self.process_update_user_password, 'ANSPB': self.show_problem_info,
                                   "FUNCT": self.process_func, "LISTD": self.process_start_lobby,
                                   "CACLD": self.process_cancel,
                                   'EXTLG': self.process_logout}

        # Add these new instance variables for GIF animation control
        self.animating = False
        self.gif_frames = []
        self.gif_frame_index = 0
        self.animation_job = None  # Store the after() job ID

        self.is_encrypted = False

        self.set_window()
        self.window.mainloop()
        self.ready_for_game = False

        self.username_for_game = ""

    def recv_loop(self):
        """
        starting only after the encryption phase
        """
        while True:
            try:
                bin_content = self.PROTO.recv_one_message()
                query, data = bin_content.decode().split('|', maxsplit=1)
                if "ERR" in query:
                    threading.Thread(
                        target=self.show_problem_info, args=(query, data), daemon=True).start()  # close after ending
                elif query in self.dict_of_operations:
                    threading.Thread(target=self.dict_of_operations[query], args=(data,), daemon=True).start()
                else:
                    self.Print(f"Unrecognized query: {query}", 40)
            except Exception as e:
                self.Print(f"Error in recv_loop: {e}", 50)

    

    def login_clicked(self, val_after1=None):
        """ login process """
        msg = f"CONCT|{self.username.get()}|{self.password.get()}"
        if len(msg) <= 60000:  # the size field is two bytes
            self.PROTO.send_one_message(msg.encode())
        else:
            showinfo(title="Information", message="At least ONE fields is too long!!")

    def process_login(self, data):
        showinfo(title="Information", message=data)
        self.username_for_game = self.username.get()
        self.clear()
        self.window.after(0, self.until_game_tab)

    def signup_clicked(self):
        msg = f"SGNUP|{self.username.get()}|{self.password.get()}|{self.validate_password.get()}|{self.email.get()}"
        if len(msg) <= 60000:  # the size field is two bytes
            self.PROTO.send_one_message(msg.encode())
        else:
            showinfo(title="Information", message="At least ONE field is too long!!")

    def proccess_signup(self, data):
        showinfo(title="Information", message=data)
        self.clear()

    def get_verification_code(self):
        """ email vericifcation code process"""
        email_receiver = self.email.get()
        msg = f"SCODE|{email_receiver}"
        if len(msg) <= 60000:  # the size field is two bytes
            self.PROTO.send_one_message(msg.encode())
        else:
            showinfo(title="Information", message="At least ONE fields is too long!!")

    def process_get_verification_code(self, data):
        showinfo(title="Information", message=data)
        self.email_entry.configure(state="disabled")
        self.send_code_button.configure(state="disabled")
        # Show verification code widgets
        self.verification_code_label.grid()
        self.verification_code_entry.grid()
        self.verify_code_button.grid()

    def verify_code(self):
        code = self.email_entered_code.get()
        email_receiver = self.email.get()
        msg = f"VRFYC|{email_receiver}|{code}"
        if len(msg) <= 60000:  # the size field is two bytes
            self.PROTO.send_one_message(msg.encode())
        else:
            showinfo(title="Information", message="At least ONE fields is too long!!")

    def process_verify_code(self, data):
        showinfo(title="Information", message=data)
        self.verification_code_label.grid_remove()
        self.verification_code_entry.grid_remove()
        self.verify_code_button.grid_remove()

        # Show update password widgets
        self.new_password_label.grid()
        self.new_password_entry.grid()
        self.confirm_password_label.grid()
        self.confirm_password_entry.grid()
        self.change_password_button.grid()

    def update_user_password(self):
        new_pass = self.new_password.get()
        confirm_pass = self.confirm_new_password.get()
        email_receiver = self.email.get()
        msg = f"UPDTE|{email_receiver}|{new_pass}|{confirm_pass}"
        if len(msg) <= 60000:  # the size field is two bytes
            self.PROTO.send_one_message(msg.encode())
        else:
            showinfo(title="Information", message="At least ONE fields is too long!!")

    def process_update_user_password(self, data):
        showinfo(title="Information", message=data)

        # Hide password update widgets
        self.new_password_label.grid_remove()
        self.new_password_entry.grid_remove()
        self.confirm_password_label.grid_remove()
        self.confirm_password_entry.grid_remove()
        self.change_password_button.grid_remove()

        self.notebook.set("Login")

    def clear_forgot_password(self):
        """ Resets all fields and hides verification/update widgets """
        self.email.set("")
        self.email_entered_code.set("")
        self.new_password.set("")
        self.confirm_new_password.set("")

        self.verification_code_label.grid_remove()
        self.verification_code_entry.grid_remove()
        self.verify_code_button.grid_remove()

        self.new_password_label.grid_remove()
        self.new_password_entry.grid_remove()
        self.confirm_password_label.grid_remove()
        self.confirm_password_entry.grid_remove()
        self.change_password_button.grid_remove()

        self.email_entry.configure(state="normal")
        self.send_code_button.configure(state="normal")

    def clear(self):
        self.username.set("")
        self.password.set("")
        self.email.set("")
        self.validate_password.set("")

        self.clear_forgot_password()  # reuse reset logic

    def create_thread(self, func_name):
        """ for each function the client side is making a thread """
        func = self.function_dict[func_name]
        t = threading.Thread(target=func, args=())
        t.start()

    def set_window(self):
        """ set the general client interface"""
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.window = ctk.CTk()
        self.window.geometry("600x500")
        self.window.title("Shesh-Besh System")

        self.set_encryption_selection_page()

    def set_encryption_selection_page(self):
        """ page for choosing encryption method """
        self.encryption_selection_frame = ctk.CTkFrame(self.window)
        self.encryption_selection_frame.pack(expand=True)

        # Title label
        title = ctk.CTkLabel(self.encryption_selection_frame, text="Select Encryption Method", font=("Arial", 18))
        title.pack(pady=20)

        # Variable for the encryption method
        self.encryption_method = ctk.StringVar(value="DH")  # Default is Diffie-Hellman

        # Diffie-Hellman radio button
        dh_radio = ctk.CTkRadioButton(
            self.encryption_selection_frame, text="Diffie-Hellman", variable=self.encryption_method, value="DH")
        dh_radio.pack(pady=10)

        # RSA radio button
        rsa_radio = ctk.CTkRadioButton(
            self.encryption_selection_frame, text="RSA", variable=self.encryption_method, value="RSA")
        rsa_radio.pack(pady=10)

        # Continue button; upon click, proceed to the login page
        continue_button = ctk.CTkButton(
            self.encryption_selection_frame,
            text="Continue",
            command=self.encryption_selected
        )
        continue_button.pack(pady=20)

    def encryption_selected(self):
        """ setting the encryption between client and server"""
        prot_to_use = self.encryption_method.get()
        self.PROTO.send_first_proto_message(prot_to_use)
        ans = self.PROTO.recv_one_message(encryption=False)
        try:
            query, value = ans.split(b"|")
            if query == "ERR02":
                showinfo(title="Information", message="Server Doesn't support this method.")
            else:
                threading.Thread(target=self.start_encryption, args=(prot_to_use,), daemon=True).start()

                while not self.is_encrypted:
                    self.window.update()  # Process ALL events including Windows messages
                    time.sleep(0.1)  # Shorter sleep for better responsiveness

                if self.is_encrypted:
                    self.encryption_selection_frame.destroy()
                    self.set_environment()
                    threading.Thread(target=self.recv_loop, daemon=True).start()
        except Exception as e:
            self.Print(f"ERROR with encryption stage!: {e}", 50)

    def start_encryption(self, prot_to_use):
        if prot_to_use == "DH":
            self.contact_with_DH()
        else:
            self.contant_with_RSA()

    def contact_with_DH(self):
        """DH encryption method"""
        self.PROTO.create_DH_keys()
        msg = b"CRTDH|" + self.PROTO.get_dh_parameters()
        self.PROTO.send_one_message(msg, False)
        ans = self.PROTO.recv_one_message(encryption=False)
        query, value = ans.split(b"|")

        if value.decode() == "yes":
            msg = b"GTKEY|" + self.PROTO.get_public_key_dh()
            self.PROTO.send_one_message(msg, False)
            ans = self.PROTO.recv_one_message(encryption=False)
            query, srv_public_key = ans.split(b"|")
            self.PROTO.create_shared_key_dh(srv_public_key)
            self.is_encrypted = True

    def contant_with_RSA(self):
        """RSA encryption method"""
        msg = b"CRTKY"
        self.PROTO.send_one_message(msg, False)
        ans = self.PROTO.recv_one_message(encryption=False)
        query, value = ans.split(b"|")  # query = GETKY
        if query == b"GETKY":
            self.PROTO.set_RSA_public_key(value)
            msg = b"GETKY|" + self.PROTO.encrypt_AES_key_by_RSA_public_key()
            self.PROTO.send_one_message(msg, False)
            bin_data = self.PROTO.recv_one_message()
            self.is_encrypted = True

    

logging_level = 10
UDP_PORT = 57071

udp_cln = UDPClient(UDP_PORT, logging_level)
tcp_ip, tcp_port = udp_cln.run()

# run actual client
cln = Client(tcp_ip, tcp_port, logging_level)

