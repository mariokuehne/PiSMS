#!/usr/bin/python
import serial
import requests
import json
import logging
import argparse
from smspdu.codecs import UCS2


class Modem(object):

    def __init__(self, interface):
        """
        initiates the Modem object
        :param interface: the serial interface where the modem is connected
        """
        self.interface = interface
        self.number = self.get_number()
        self.webhook = self.get_webhook()

    def open(self):
        """opens a connection to the modem and tests it"""
        logging.info('opening connection to {}'.format(self.interface))
        self.ser = serial.Serial(self.interface, 115200, timeout=5)
        self.send_command('AT\r'.encode())					# Modem check
        data = self.read_lines()
        # data should contain and answer like: [b'T\r\r\n', b'OK\r\n']
        # cheking if the answer contained 'OK' if not no compatible modem
        if 'OK' not in data[1].decode():
            self.close()
            raise Exception('No Modem on {}'.format(self.interface))
        self.send_command('AT+CMGF=1\r'.encode()) 			# SMS in test mode
        self.flush_output()

    def get_number(self):
        """
        connects to modem and redeems the Number of the simcard
        :return: the number of the simcard
        """
        logging.info('getting number from {}'.format(self.interface))
        self.open()
        self.send_command('AT+CNUM\r'.encode())
        data = self.read_lines()
        self.close()
        # data should contain and answer like:
        # [b'+CMGF=1\r\r\n', b'OK\r\n', b'AT+CNUM\r\r\n',
        # b'+CNUM: "My Number","+49151XXXXXXX",145,7,4\r\n',
        # b'\r\n', b'OK\r\n']
        # were getting the phone number out of that
        number = data[3].decode().split(',')[1].replace('"', '')
        logging.info('number for {} is {}'.format(self.interface, number))
        return number

    def get_webhook(self):
        """
        cheks the number of the Modem against the Config and returns the
        configured webhook if found
        :return: webhook matching to Number of the Modem
        """
        logging.info('getting webhook for {}'.format(self.number))
        with open('config.json', 'r') as config_file:
            config = json.load(config_file)
            for number in config['numbers']:
                if number['number'] == self.number:
                    return number['webhook']
            raise Exception('no config found for {}'.format(self.number))

    def send_command(self, command):
        """
        executes the command agains the Modem
        :param command: the command to execute
        """
        logging.debug('sending command "{}" to {}'.format(command,
                                                          self.interface))
        self.ser.write(command)

    def read_lines(self):
        """
        gets the results that are currently available from the Modem
        :return: the fetchable output
        """
        logging.debug('getting output from {}'.format(self.interface))
        return self.ser.readlines()

    def flush_output(self):
        """flushes the output stream of the modem"""
        logging.debug('flushing {}'.format(self.interface))
        self.ser.flushOutput()
        self.ser.flushInput()
        self.ser.flush()


    def get_all_sms(self):
        """
        fetches all sms saved on the simcard
        :return: all sms as an array
        """
        logging.info('getting all sms from {} ({})'.format(self.number,
                                                           self.interface))
        self.open()

        self.flush_output()
        command = 'AT+CMGL="ALL"\r\n'.encode()
        self.send_command(command)
        data = self.read_lines()
        self.close()
        if len(data) >= 5:
            # data should contain and answer like:
            # [b'AT+CMGL="ALL"\r\r\n',
            # b'+CMGL: 1,"REC UNREAD","+49172X","","21/03/05,14:20:52+04"\r\n',
            # b'Test msg\r\n', b'\r\n', b'OK\r\n']
            # remove command and ok return msg
            data.pop(0)
            data.pop(len(data) - 1)
            data.pop(len(data) - 1)
            # data should contain:
            # [b'+CMGL: 1,"REC UNREAD","+491725838021","",
            # "21/03/05,14:20:52+04"\r\n', b'Sorry for spamming\r\n']
            # if multiple msg are recived they are split by "b'\r\n'"
            # therefore every three entries are one msg
            # so split data accordingly
            value = [data[x:x+3] for x in range(0, len(data),3)]
            return value
        return []

    def delete_sms(self, sms_index):
        """
        deletes the sms via teh given sms_index
        :param sms_index: the sms to delete
        :return:
        """
        logging.info('deleting sms_no. {} from {} ({})'.format(sms_index,
                                                               self.number,
                                                               self.interface))
        self.open()
        self.send_command('AT+CMGD={}\r'.format(sms_index).encode())
        self.close()


    def close(self):
        """closes an activ serial connection"""
        logging.debug('closing connection to {}'.format(self.interface))
        self.ser.close()

    def send_to_slack(self, sender, message):
        """
        used to send a message to slack via webhook
        :param sender: the sender of the message
        :param message: the contetnt of the message
        """
        logging.info('sending sms from {} to configured slack chanel'.format(
            sender
        ))
        requests.post(self.webhook,
                      json={'text': 'From {}: \n {}'.format(sender, message)})

def decode_msg(msg):
    """
    tryes to decode the msg in different ways
    :param msg: the msg to decode
    :return: decodet msg
    """
    logging.debug('decoding sms')
    try:
        return UCS2.decode(str(ord(c) for c in msg.decode("ISO-8859-1")))
    except:
        return str(msg.decode("ISO-8859-1"))  # use plain text


def parse_args():
    parser = argparse.ArgumentParser(
        description='This is a script to receive sms and post them to any '
                    'webhook api like the one in slack')
    parser.add_argument('--debug', action='store_true')
    parser.add_argument('--verbose', action='store_true')
    return parser.parse_args()


def main():
    args = parse_args()

    format = '[%(asctime)s - %(levelname)s] : %(message)s'
    datefmt = '%d-%b-%y %H:%M:%S'
    filename = 'error.log'
    level = logging.WARNING
    if args.verbose:
        level = logging.INFO
    if args.debug:
        filename = 'debug.log'
        level = logging.DEBUG
    if args.verbose:
        logging.basicConfig(format=format, datefmt=datefmt, level=level)
    else:
        logging.basicConfig(filename=filename, format=format,
                            datefmt=datefmt, level=level)

    logging.info('fetching all available modems')
    with open('config.json', 'r') as config_file:
        config = json.load(config_file)
        modems = []
        for interface in config['modems']:
            try:
                modems.append(Modem(interface))
            except Exception as exp:
                logging.warning('cannot create modem: {}'.format(exp))

    logging.info('fetching all received sms')
    for modem in modems:
        try:
            msg_list = modem.get_all_sms()

            for msg in msg_list:
                # msg should comtain
                # [b'+CMGL: 2,"REC UNREAD","+49172XXXXXXX","",
                # "21/03/05,14:29:39+04"\r\n', b'Testing \r\n']
                # split them into info and msg section and convert info section
                # to a decoded dict
                info = msg[0].decode().split(',')
                # info shozld now contain:
                # ['+CMGL: 2', '"REC UNREAD"', '"+49172XXXXXXX"', '""',
                # '"21/03/05', '14:29:39+04"\r\n']
                # we extract the sms_index and the sender_number
                sms_index = info[0].replace('+CMGL: ', '')
                sender_number = info[2]
                # decode sms as needed for plain text r shortcodes
                sms_msg = decode_msg(msg[1])
                try:
                    modem.send_to_slack(sender_number, sms_msg)
                    #print('{}: {}'.format(sender_number, sms_msg))
                    modem.delete_sms(sms_index)
                except Exception as exp:
                    logging.warning('send Failed: {}'.format(exp))

        except Exception as exp:
            logging.warning('fetching msg failed: {}'.format(exp))


if __name__ == '__main__':
    main()