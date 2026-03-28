__author__ = 'Nadav'
"""
Has another function - deleting directory.
"""
import os.path
# 2.7  client server Nov 2024

import socket, sys, traceback, os

import tcp_by_size
from tcp_by_size import send_with_size, recv_by_size

# magic numbers
SRV_PORT = 12345
CLNT_PORT = SRV_PORT
MIN_MSG_SIZE = 12
MSG_SIZE_NUMBERS = 5
TOTAL_MSG_SIZE = MSG_SIZE_NUMBERS + 1
QUERY_CODE_LENGTH = 6
START_OF_MSG_CONTENT = 7


def menu():
    """
    show client menu
    return: string with selection
    """
    print('\n  1. ask for PRINT SCREEN: ')
    print('\n  2. ask for FILE in server: ')
    print("\n  3. ask for \"DIR\" at server's folder: ")
    print('\n  4. ask for DELETE FILE/DIRECTORY in server: ')
    print('\n  5. ask for COPY/DIRECTORY: ')
    print('\n  6. ask for RUN PROGRAM: ')
    print('\n  7. ask for EXIT: ')

    return input('Input 1 - 7 > ')


# both for copying proccess
def handle_get_directory():
    dir_url = input(r"Enter the name of the directory. ")
    if not is_no_illegal_chars(dir_url):
        return None

    choice = input("1. The directory is in a local folder, 2. To custom path (include the folder name): ")
    if choice == '1':
        final_path = dir_url
        return final_path

    if choice == '2':
        path = input(r"Enter custom path: (like C:, D:\folder)")
        final_path = path + "\\" + dir_url
        return final_path
    return None


def handle_get_file():
    file_name = input("Enter name for the file including the format (like file.txt): ")
    if not validate_file_name(file_name):
        return None

    choice = input("1. The file is in a local folder, 2. To custom path (include the folder name): ")
    if choice == '1':
        final_path = file_name
        return final_path

    if choice == '2':
        path = input(r"Enter custom path: (like C:, D:\folder)")
        final_path = path + "\\" + file_name
        return final_path
    return None


def is_no_illegal_chars(url):
    is_valid = True
    illegal_chars = ['|', '<', '>', ':', '?', '*', '\"', '\\', '/']
    for illegal in illegal_chars:
        if illegal in url:
            is_valid = False

    return is_valid


def validate_file_name(file_name):
    is_valid = is_no_illegal_chars(file_name) and "." in file_name
    return is_valid


def handle_print_screen_process():
    print("CHOOSED PRINT SCREEN")
    path = handle_get_file()
    if path is None:
        return None
    return fr"SCSHOT|{path}"


def handle_get_file_process_for_menu():
    path = handle_get_file()
    if path is None:
        return None
    return fr"GETFLE|{path}"


def handle_see_dir_process_for_menu():
    dir_url = handle_get_directory()
    if dir_url is None:
        return None
    return fr"SEEDIR|{dir_url}"


def handle_delete_process_for_menu():
    choice = input("1. To delete a file, 2. To delete a folder: ")
    if choice == '1':  # to delete a file
        path = handle_get_file()
        if path is None:
            return None
        return fr"DELFLE|{path}"
    if choice == '2':  # to delete a directory
        path = handle_get_directory()
        if path is None:
            return None
        return fr"DELDIR|{path}"
    else:
        return None


def handle_path_for_copy_process():
    choice = input("1. a file, 2. a directory: ")
    type = None
    if choice == '1' or choice == '2':
        if choice == '1':
            type = "FILE"
            path = handle_get_file()  #returns also a file path
            while path is None:
                path = handle_get_file()
        if choice == '2':
            type = "DIR"
            path = handle_get_directory()  #returns also a dir path
            while path is None:
                path = handle_get_directory()
        return path, type
    else:
        return handle_path_for_copy_process()


def handle_copy_proccess_for_menu():
    #will return CPOYFL|scr|dst
    print("SOURCE: (from where to copy)")
    scr_path_tuple = handle_path_for_copy_process()  #(path,type)
    print("DESTINATION: (where to copy)")
    if scr_path_tuple[1] == "FILE":
        des_path_tuple = handle_path_for_copy_process()
        return fr"COPYFL|{scr_path_tuple[0]}|{des_path_tuple[0]}"

    else:  # directory must be moved to another directory
        des_path_tuple = handle_path_for_copy_process()
        while des_path_tuple[1] != "DIR":
            print("Check your destination and try again.")
            des_path_tuple = handle_path_for_copy_process()
    return fr"COPYDR|{scr_path_tuple[0]}|{des_path_tuple[0]}"


def handle_run_program():
    # this time not using the handle_get_file because of the msgs
    file_name = input("Enter name for the file including the format (like 'file.txt' or 'notepad.exe'): ")

    choice = input("1. The keep the file \"as is\", 2. To custom path (include the folder name): ")
    if choice == '1':
        final_path = file_name
        return fr"RUNFLE|{final_path}"

    if choice == '2':
        path = input(r"Enter custom path: (like C:, D:\folder)")
        final_path = path + "\\" + file_name
        return fr"RUNFLE|{final_path}"
    return None

def print_lst(lst):
    print("CONTENT:")
    for item in lst:
        item = item[:-1]  # dont include the last pipe
        seperated_by_pipe = item.split('|')
        for content in seperated_by_pipe:
            print(content)


def print_custom_error(err):
    splited_by_inverted_commas = err.split('\'')
    return splited_by_inverted_commas[1]  # the msg


def handle_download_file(sock, to_send):
    try:
        tcp_by_size.send_with_size(sock, to_send.encode())
        amount_of_recv = tcp_by_size.recv_by_size(sock).decode()[START_OF_MSG_CONTENT:]
        amount_of_recv = int(amount_of_recv)

        got_part_txt = b'GOTPRT|Got the part'
        print("Copying to file here:")
        new_file_path = handle_get_file_process_for_menu()[START_OF_MSG_CONTENT:]
        byte_data = b''
        with open(new_file_path, 'ab') as file:
            for i in range(amount_of_recv + 1):  # for the finish msg
                tcp_by_size.send_with_size(sock, got_part_txt)
                byte_data = tcp_by_size.recv_by_size(sock)
                to_write = byte_data[START_OF_MSG_CONTENT:]
                if to_write != b'The proccess has ended.':
                    file.write(to_write)
        return byte_data
    except PermissionError as e:
        return "PRMERR|Permisson Error.".encode("utf-8")
    except WindowsError as e:
        return fr"PTHERR|The server was not able to copy the file at:{new_file_path.decode()}. {str(e)}".encode("utf-8")
    except Exception as e:
        return fr"GNRERR|The server was not able to copy the file at:{new_file_path.decode()}. {str(e)}".encode("utf-8")


def handle_see_dir_operation(sock, to_send):
    try:
        tcp_by_size.send_with_size(sock, to_send.encode())
        amount_of_recv = tcp_by_size.recv_by_size(sock).decode()[START_OF_MSG_CONTENT:]
        amount_of_recv = int(amount_of_recv)

        got_part_txt = b'GOTPRT|Got the part'
        byte_data = b''
        dir_lst = []
        item_in_lst = ""

        for i in range(amount_of_recv + 1):  # for the finish msg
            tcp_by_size.send_with_size(sock, got_part_txt)
            byte_data = tcp_by_size.recv_by_size(sock)
            item_in_lst = byte_data[START_OF_MSG_CONTENT:].decode()
            if item_in_lst != 'The proccess has ended.':
                dir_lst.append(item_in_lst)

        return dir_lst, byte_data
    except Exception as e:
        err_msg = "PTHERR|" + str(e)
        return err_msg.encode()


def protocol_build_request(from_user):
    """
    build the request according to user selection and protocol
    return: string - msg code
    """
    if from_user == '1':
        to_return = handle_print_screen_process()
        if to_return is not None:
            return to_return
        else:
            print("Some input is incorrect. try again.")
            return protocol_build_request('1')

    elif from_user == '2':
        print("About the file in server:")
        to_return = handle_get_file_process_for_menu()
        if to_return is not None:
            return to_return
        else:
            print("Some input is incorrect. try again.")
            return protocol_build_request('2')

    elif from_user == '3':
        print("About the file in server:")
        to_return = handle_see_dir_process_for_menu()
        if to_return is not None:
            return to_return
        else:
            print("Some input is incorrect. try again.")
            return protocol_build_request('3')

    elif from_user == '4':
        print("About the file in server:")
        to_return = handle_delete_process_for_menu()
        if to_return is not None:
            return to_return
        else:
            print("Some input is incorrect. try again.")
            return protocol_build_request('4')

    elif from_user == '5':
        to_return = handle_copy_proccess_for_menu()
        return to_return

    elif from_user == '6':
        print("About the file in server:")
        to_return = handle_run_program()
        if to_return is not None:
            return to_return
        else:
            print("Some input is incorrect. try again.")
            return protocol_build_request('6')

    elif from_user == '7':
        return 'EXITCL|Client Want to exit.'

    else:
        return ''


def protocol_parse_reply(reply):
    """
    parse the server reply and prepare it to user
    return: answer from server string
    """

    to_show = 'Invalid reply from server'
    try:

        reply = reply.decode()
        some_data = reply[START_OF_MSG_CONTENT:]

        code = reply[:QUERY_CODE_LENGTH]
        if code == 'PRTSCS':
            to_show = 'The Server was able to save the PRINT SCREEN.'
        elif code == 'ENDFLE':
            to_show = 'Server was able to download the file.'
        elif code == 'SHWDIR':
            to_show = 'Server was able to send the items in the directory.'
        elif code == 'DELSCS':
            to_show = 'Server was able to do the deleting opration.'
        elif code == 'COPIED':
            to_show = 'Server was able to do the copying opration.'
        elif code == 'FLERAN':
            to_show = 'Server was able to run the file.'
        elif code == 'PTHERR':
            to_show = fr"Path error: {some_data}"
        elif code == 'NOTFND':
            to_show = fr"Sever didn't find the path. {some_data}"
        elif code == 'NOTFLE' or code == "NOTDIR":
            to_show = fr"Sever recognized {some_data}"
        elif code == 'GRLERR':
            to_show = fr"There's a general error {some_data}"
        elif code == 'PRMERR':
            to_show = fr"Server has a permission error. {some_data}"
        elif code == 'EXITOK':
            to_show = 'Server acknowledged the exit message'

        return to_show

    except:
        print('Server replay bad format')


def handle_reply(reply):
    """
    get the tcp upcoming message and show reply information
    return: void
    """
    to_show = protocol_parse_reply(reply)
    if to_show is not None:
        print('\n==========================================================')
        print(f'  SERVER Reply: {to_show}   |')
        print('==========================================================')


def main(ip):
    """
    main client - handle socket and main loop
    """
    connected = False
    sock = socket.socket()
    port = CLNT_PORT
    try:
        sock.connect((ip, port))
        print(f'Connect succeeded {ip}:{port}')
        connected = True
    except:
        print(f'Error while trying to connect.  Check ip or port -- {ip}:{port}')

    while connected:
        from_user = menu()
        to_send = protocol_build_request(from_user)
        if to_send == '':
            print("Selection error try again")
            continue
        try:
            if to_send[:TOTAL_MSG_SIZE] == "GETFLE":
                msg = handle_download_file(sock, to_send)
                handle_reply(msg)
            elif to_send[:TOTAL_MSG_SIZE] == "SEEDIR":
                tuple_dir = handle_see_dir_operation(sock, to_send)
                if type(tuple_dir) is tuple:
                    handle_reply(tuple_dir[1])
                    print_lst(tuple_dir[0])
                else:
                    handle_reply(tuple_dir)

            else:
                tcp_by_size.send_with_size(sock, to_send.encode())
                byte_data = tcp_by_size.recv_by_size(sock)  # recive by size
                if byte_data == b'':
                    print('Seems server disconnected abnormal')
                    break
                handle_reply(byte_data)

            if from_user == '7':
                print('Will exit ...')
                connected = False
                break
        except socket.error as err:
            print(f'Got socket error: {err}')
            break
        except Exception as err:
            print(f'General error: {err}')
            print(traceback.format_exc())
            break
    print('Bye')
    sock.close()


if __name__ == '__main__':
    if len(sys.argv) > 1:
        main(sys.argv[1])
    else:
        main('127.0.0.1')
