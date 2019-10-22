#!/usr/bin/python3
# Author: DS, Synergy Information Solutions, Inc.
# Author: Dan Schmidt, some schmuck who coded in haste


import time
import os
import threading
import logging
import yaml
import socket
import re
from hnmp import SNMP
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from nornir import InitNornir
from nornir.plugins.tasks.networking import netmiko_send_command, netmiko_send_config


# Open the `ztpconfig.yaml` file to parse configuration settings.
with open('./ztpconfig.yaml', 'r') as f:
    config = yaml.safe_load(f)

logfile = config['logfile']
watch_dir = config['watch_dir']
ssh_method = config['ssh_method']
tftpaddr = config['tftpaddr']
# imgfile = config['imgfile'] # no longer used 
username = config['username']
password = config['password']


# `Logger` class to handle logging messages to file.
class Logger:
    def __init__(self, logdata):
        logging.basicConfig(format='%(asctime)s %(message)s',
                            datefmt='%Y/%m/%d %I:%M:%S %p',
                            filename=logfile,
                            level=logging.INFO)
        logging.info(f'-- {logdata}')
        print(f'\n{logdata}')


# `Watcher` class to watch the specified directory for new files.
class Watcher:
    def __init__(self):
        self.observer = Observer()

    def run(self):
        event_handler = Handler()
        self.observer.schedule(event_handler, watch_dir, recursive=False)
        self.observer.start()
        Logger('ZTP Watcher started.')
        try:
            while True:
                time.sleep(5)

        except KeyboardInterrupt:
            self.observer.stop()
            Logger('ZTP Watcher stopped (keyboard interrupt).')

        except:
            self.observer.stop()
            Logger('Error.')


# `Handler` class to validate SSH reachability and initiate .bin file firmware
# update to provisioned switches.
class Handler(FileSystemEventHandler):
    # `on_created` function uses threading to start the update.
    # When a file is created, the filename is parsed for hostname and IP address.
    # These values are passed to the `test_ssh` function to validate SSH reachability.
    def on_created(self, event):

        ignorefiles = ['.swp', '.save']

        if event.is_directory:
            return None
        else:
            newfile = event.src_path.rpartition('/')[2]
            if not any(str in newfile for str in ignorefiles):
                Logger(f'New file detected: {newfile}')
                hostname = newfile.split('_')[0]
                hostaddr = newfile.split('_')[1]
                x = threading.Thread(target=self.test_ssh, args=(
                    hostname, hostaddr))
                x.start()

    # `test_ssh` function validates that the IP address parsed from the `on_created`
    # function will accept SSH connections (auth attempts are not yet made).
    # The hostname and IP address are passed to the `os_upgrade` function to update
    # the provisioned switches.
    def test_ssh(self, hostname, hostaddr, port=22):
        # ToDo: These should be in the Yaml
        initialwait = 15
        retrywait = 3
        attempts = 0
        maxattempts = 20

        conn = hostname if ssh_method == 'dns' else hostaddr

        Logger(
            f'{hostname}: Verifying SSH reachability to {conn} in {initialwait}s.')
        time.sleep(initialwait)

        result = None
        while result is None:
            try:
                attempts += 1
                testconn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                testconn.connect((conn, port))
            except Exception as e:
                if attempts >= maxattempts:
                    result = testconn
                    Logger(
                        f'{hostname}: SSH verification attempts exhausted ({maxattempts}); {e}.')
                else:
                    time.sleep(retrywait)
                    continue
            else:
                result = testconn
                testconn.close()
                Logger(
                    f'{hostname}: SSH reachability verified after {attempts} attempt(s) -> copy image file(?).')
                self.os_upgrade(hostname, hostaddr)

    # `os_upgrade` function copies the .bin image via TFTP, sets the boot variable,
    # and writes the config.
    def os_upgrade(self, hostname, hostaddr):

        def get_output(agg_result):
            for k, multi_result in agg_result.items():
                for result_obj in multi_result:
                    return result_obj.result

        # 'sw_log' function sends syslog messages to the switch.
        def sw_log(logmsg):
            result = nr.run(
                task=netmiko_send_command,
                command_string=f'send log ZTP-Watcher: {logmsg}',
            )
            return(result)

        # 'send_cmd' function sends commands to the host.
        def send_cmd(cmd):
            result = nr.run(
                task=netmiko_send_command,
                command_string=cmd,
                delay_factor=6,
            )
            return(result)

        # 'send_config' function sends configuration commands to the host.
        def send_config(config):
            result = nr.run(
                task=netmiko_send_config,
                config_commands=config
            )
            return(result)
        
        # Instatiate an SNMP instance
        def get_SNMP(ip_addr, config):
            snmp = SNMP(
                ip_addr,
                version=3, 
                username = config['snmp_username'],
                authproto = config['snmp_authproto'],
                authkey = config['snmp_authkey'],
                privproto = config['snmp_privproto'],
                privkey = config['snmp_privkey']
            )   
            return snmp

        # Truncates new_ios & boot_ios to versions
        # That can be accurately compared
        # Readability > Clever
        def truncate_ios(new_ios, boot_ios, ios_xe):
            new_ios_split = new_ios.split('.')
            new_ios_rstrip = '.' + new_ios_split[-1]
            new_ios_lstrip = new_ios_split[0] + '.' 
            new_ios = new_ios.rstrip(new_ios_rstrip)
            new_ios = new_ios.lstrip(new_ios_lstrip)
            if ios_xe:
                new_ios = new_ios.rstrip('.SPA')
                # Would break 03.03, but that is really old
                new_ios = new_ios.replace('0','')
            else:
                new_ios = new_ios[:2] + '.' + new_ios[2:]
                boot_ios = boot_ios.replace('(','-')
                boot_ios = boot_ios.replace(')','.')
            return (boot_ios, new_ios)

        # Parse out 1.3.6.1.2.1.1.1.0 for version information
        # Also, determine if it is a 3850
        # Help needed - do all IOS XE versions have a CAT3K in them?
        # Note: 1.3.6.1.2.1.16.19.6.0 boot file is not reliable for ios xe
        def fetch_ver(snmp):
            ios_xe = False
            sysDescr = str(snmp.get('1.3.6.1.2.1.1.1.0'))
            if 'CAT3K' in sysDescr:
                ios_xe = True
            ver = (sysDescr.split(','))
            if 'Version' in ver[2]:
                ver = ver[2].lstrip(' Version ')
            else:
                ver = ver[3].lstrip(' Version ').split()[0]
            return ver, ios_xe

        # Archive = Run Before  Bin = Run After
        def wr_mem(is_tar = True):
            sw_log('Writing config.')
            writemem = send_cmd('write mem')
            if is_tar:
                Logger(f'{hostname}: Config written, ready to upgrade.')
                sw_log('Config written, ready for upgrade.')
            else:
                Logger(f'{hostname}: Config written, ready to reload/power off.')
                sw_log('Config written, ready to reload/power off.')
            #result = get_output(writemem)
            # Logger(result)                                      # Uncomment for TS

        # Only for .bin
        # This function should properly handle the setting of boot string
        def set_boot_var(new_ios):
            sw_log('Setting boot variable and writing config.')
            bootcmds = f'default boot sys\nboot system flash:{new_ios}'
            bootcmds_list = bootcmds.splitlines()
            bootvar = send_config(bootcmds_list)
            Logger(f'{hostname}: Boot variable set -> write config.')
            #result = get_output(bootvar)
            # Logger(result)                                      # Uncomment for TS

        # IOS XE only - specifically 3850
        # This does a software clean
        def ios_xe_upgrade(copy_method, tftpaddr, new_ios, old_xe = False):
            if old_xe:
                cmd = 'software clean'
            else:
                cmd = 'request platform software package clean switch all'
            #DEBUG
            #Logger(cmd)
            result = nr.run(
                task=netmiko_send_command,
                command_string=cmd,
                delay_factor=6,
                expect_string = "Nothing|proceed"
            )
            for device_name, multi_result in result.items():
                #DEBUG
                #Logger(multi_result[0].result)
                if "proceed" in multi_result[0].result:
                    Logger("Cleaning old software.")
                    result = nr.run(
                        task=netmiko_send_command,
                        command_string='y',
                        delay_factor=6,
                        expect_string=r"\#"
                    )
                else:
                    Logger("No software cleaning required.")
            Logger('Cleaner Done')
            ##result = get_output(result)
            ##Logger(result)                                      # Uncomment for TS
            # FIXME: Figure out why it won't work without sleep
            time.sleep(1)
            cmd = f'copy {copy_method}{tftpaddr}/{new_ios} flash:'
            #DEBUG
            Logger(cmd)
            result = nr.run(
                task=netmiko_send_command,
                command_string=cmd,
                delay_factor=6,
                expect_string=r'Destination filename'
            )
            #DEBUG
            result2 = get_output(result)
            Logger(result2)                                      # Uncomment for TS
            for device_name, multi_result in result.items():
                Logger(multi_result[0].result)
                if "Destination" in multi_result[0].result:
                    result = nr.run(
                        task=netmiko_send_command,
                        command_string=new_ios,
                        delay_factor=6,
                        expect_string=r"\#"
                    )
            result2 = get_output(result)
            Logger(result2)                                      # Uncomment for TS
            if old_xe:
                a = (f'software install file flash:{new_ios} on-reboot new')
                Logger(a)
                installer = send_cmd(a)
            else:
                a = ('request platform software package install switch all file '
                        f'flash:{new_ios} new auto-copy')
                installer = send_cmd(a)
            result = get_output(installer)
            Logger(result)                                      # Uncomment for TS

        nr = InitNornir(
            #logging={"file": "debug.txt", "level": "debug"},
            inventory={
                'options': {
                    'hosts': {
                        hostname: {
                            'hostname': hostaddr,
                            'username': username,
                            'password': password,
                            'platform': 'ios'
                        }
                    }
                }
            }
        )
        Logger(f'{hostname}: Fetching boot variable via SNMP to compare.')

        # I need SNMP anyway, and can fetch this in a fraction of the time
        # it takes to get it via SSH
        snmp = get_SNMP(hostaddr, config)
        try:
            model_oid = str(snmp.get('1.3.6.1.2.1.1.2.0'))
        except:
            # FIXME - Maybe Good-er Exception handling and try again after wait
            Logger(f'{hostname}: Can not SNMP - BAILING!.')
            sw_log('Error: Can not SNMP.')
            nr.close_connections()
            return # Bit Ugly
        if model_oid in config:
            new_ios = config[model_oid]
            is_tar = new_ios.split('.')[-1] == 'tar'
            if is_tar:
                wr_mem()
            boot_ios, ios_xe = fetch_ver(snmp)
            boot_ios_tr, new_ios_tr = truncate_ios(new_ios, boot_ios, ios_xe)
            if boot_ios_tr == new_ios_tr:
                Logger(f'{hostname}: Up to date ({boot_ios_tr}), skipping transfer.')
                sw_log(
                    f'Image file ({boot_ios_tr}) up to date, skipping transfer.')
            else:
                copy_method = config['copy_method']
                Logger(f'{hostname}: Image old, starting {copy_method.split(":")[0]} transfer.')
                sw_log(
                        f'Newer Version ({new_ios_tr}) exists, starting image transfer via {copy_method.split(":")[0]}.')
                copystart = time.time()
                if ios_xe:
                    ios_xe_upgrade(copy_method, tftpaddr, new_ios,
                            old_xe = boot_ios_tr.startswith('03'))
                    copyduration = round(time.time() - copystart)
                    Logger(
                        f'{hostname}: Image transfer completed after {copyduration}s.')
                    if not is_tar: #
                        sw_log('Image transfer complete.')
                else:
                    if is_tar:
                        copyfile = send_cmd(f'archive download-sw /over /rel {copy_method}{tftpaddr}/{new_ios}')
                    else:
                        copyfile = send_cmd(f'copy {copy_method}{tftpaddr}/{boot_file} flash:')
                    copyduration = round(time.time() - copystart)
                    Logger(
                        f'{hostname}: Image transfer completed after {copyduration}s.')
                    if not is_tar: #
                        sw_log('Image transfer complete.')
                #result = get_output(copyfile)
                # Logger(result)                                  # Uncomment for TS
        else:
            Logger(f'{model_oid}: Not found in config - skipping IOS.')
        if not is_tar:
            if not ios_xe:
                set_boot_var(new_ios)
            wr_mem(is_tar)

        Logger(f'Configuration Finished.')
        sw_log('Config finished, ready to use.')
        nr.close_connections()


if __name__ == '__main__':
    w = Watcher()
    w.run()
