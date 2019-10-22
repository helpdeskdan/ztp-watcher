# (Free)ZTP Watcher

Note: This is a fork of ztp-watcher which uses SNMPv3 to properly query the model number of IOS and IOS-XE switches allowing upgrade according to model.  In short, it provides the ability to support different switches, different copy methods (bin or tar) and different protocols (tftp, ftp, scp).  Each switch model has a unique identifier that can be identified via 1.3.6.1.2.1.1.1.0.  (To view yours try: snmpwalk -v 3 -u my_snmp_user -l authPriv -A my_password -a sha -X my_password -x AES 192.0.2.1 1.3.6.1.2.1.1.1.0)  The added python library hnmp is required as it saved me time.  Many thanks the authors of freeztp and to the author of ztp-watcher for giving me the opportunity to work on this fun diversion. 

Watches specified directory for [FreeZTP][freeztp] custom merged-config files which are created after a switch is successfully provisioned. File name is parsed for hostname and host IP address to initiate a TFTP transfer of the specified IOS image.

> _TFTP preferred over SCP due to speed (include `ip tftp blocksize 8192` in the switch template) and because FreeZTP has TFTP built-in so no additional services are required._

_**Use-case**_: Copy IOS image .bin file to C2960S/X/XR switches post FreeZTP provisioning to avoid the auto-install function using a .tar file (lengthy process).

![screenshot-cisco-ref][ss-cisco-ref]

[Source][cisco-doc]

## Considerations

- Ensure that FreeZTP **imagediscoveryfile-option** is set to **disable**.

   ```bash
   ztp set dhcpd INTERFACE-{dhcp_interface} imagediscoveryfile-option disable
   ```

- Custom merged-config file syntax must begin with **{{keystore_id}}_{{ipaddr}}**; e.g.

   `{{keystore_id}}_{{ipaddr}}_{{idarray|join("-")}}_merged.cfg`

   _**Full custom log file config example...**_

   ```bash
   ztp set logging merged-config-to-custom-file '/etc/ztp/logs/merged/{{keystore_id}}_{{ipaddr}}_{{idarray|join("-")}}_merged.cfg'
   ```

   \*_**Suggestion**_: Disable logging merged configs to the main log file via;

    ```bash
     ztp set logging merged-config-to-mainlog disable
    ```

## Installation/Usage

1. Clone repo to desired location.

   ```bash
   sudo git clone {URL} /var/git/ztp-watcher
   sudo pip3 install hnmp
   ```

2. Make a copy of **ztpconfig_sample.yaml** as **ztpconfig.yaml** and edit for environment.

   ```bash
   sudo cp /var/git/ztp-watcher/ztpconfig_sample.yaml /var/git/ztp-watcher/ztpconfig.yaml
   sudo nano /var/git/ztp-watcher/ztpconfig.yaml
   ```

   - _**Edit values accordingly**_
     > **watch_dir** must match path from the `ztp set logging merged-config-to-custom-file` path.

     ```yaml
     logfile: /etc/ztp/logs/ztpwatcher.log
     watch_dir: /etc/ztp/logs/merged/
     ssh_method: ip
     tftpaddr: 172.17.251.251
     imgfile: c2960x-universalk9-mz.152-4.E8.bin
     username: cisco
     password: cisco
     snmp_username: snmp-user
     snmp_authproto: sha 
     snmp_authkey: goykyanBu123
     snmp_privproto: aes128
     snmp_privkey: goykyanBu123
     copy_method: ftp://
     # 2960CG-8TC-L
     1.3.6.1.4.1.9.1.1316: c2960c405ex-universalk9-tar.152-2.E10.tar
     # 2960G-8TC-L
     1.3.6.1.4.1.9.1.799: c2960-lanbasek9-tar.122-55.SE12.tar
     # 2960-24TT-L
     1.3.6.1.4.1.9.1.716: c2960-lanbasek9-tar.122-55.SE12.tar
     # Yada Yada
     ```

3. Edit **ztp-watcher.service** systemd unit file with path.

   ```bash
   sudo nano /var/git/ztp-watcher/ztp-watcher.service
   ```

   - _**Edit `ExecStart` and `WorkingDirectory` paths accordingly**_

     ```bash
     ...
     ExecStart=/bin/bash -c 'cd /var/git/ztp-watcher; python3 ztp-watcher.py'
     WorkingDirectory=/var/git/ztp-watcher/
     ...
     ```

4. Copy **.service** file to **/etc/systemd/system/**, then enable and start it.

   ```bash
   sudo cp /var/git/ztp-watcher/ztp-watcher.service /etc/systemd/system/
   sudo systemctl enable ztp-watcher.service
   sudo systemctl start ztp-watcher.service
   ```

## References

- https://github.com/PackeTsar/freeztp/
- https://github.com/torfsen/python-systemd-tutorial
- https://pynet.twb-tech.com/blog/nornir/intro.html
- https://pynet.twb-tech.com/blog/nornir/os-upgrade-p1.html
- https://www.michaelcho.me/article/using-pythons-watchdog-to-monitor-changes-to-a-directory

[freeztp]: https://github.com/PackeTsar/freeztp/
[cisco-doc]: https://www.cisco.com/c/en/us/td/docs/solutions/Enterprise/Plug-and-Play/release/notes/pnp-release-notes16.html#pgfId-206873
[ss-cisco-ref]: assets/images/cisco-ref.png
