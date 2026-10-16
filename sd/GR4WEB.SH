#!/bin/sh
# GR4-WebCam launcher. Starts the Wi-Fi network and web page when enabled.
# You can edit this file on the SD card.
SD=/media/storage1

# wait for the Wi-Fi interface, up to ~30s
i=0; while [ $i -lt 30 ] && [ ! -e /sys/class/net/uap0 ]; do i=$((i+1)); sleep 1; done

cat > /tmp/hostapd.conf <<CFG
interface=uap0
driver=nl80211
ssid=GR4-WEB
hw_mode=g
channel=6
auth_algs=1
wpa=2
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
wpa_passphrase=gr4camera
ignore_broadcast_ssid=0
CFG
cat > /tmp/udhcpd.conf <<CFG
start 192.168.0.100
end 192.168.0.150
interface uap0
option subnet 255.255.255.0
option router 192.168.0.1
option lease 86400
CFG
: > /tmp/udhcpd.leases

ip addr flush dev uap0 2>/dev/null
ip addr add 192.168.0.1/24 dev uap0
ip link set uap0 up
hostapd -B /tmp/hostapd.conf
busybox udhcpd -S /tmp/udhcpd.conf

mkdir -p /tmp/webui
# place the web page (retry on early boot)
i=0; while [ $i -lt 20 ] && [ ! -s /tmp/webui/index.html ]; do
  i=$((i+1)); cp "$SD"/GR4WEB.HTM /tmp/webui/index.html 2>/dev/null; sleep 1
done
printf 'P:/v1/:http://127.0.0.1:80/v1/\n' > /tmp/webui/httpd.conf
busybox httpd -p 8080 -h /tmp/webui -c /tmp/webui/httpd.conf

# auto-stop: tear down ~2 min after the last device disconnects
( seen=0; idle=0
  while :; do
    if iw dev uap0 station dump 2>/dev/null | grep -q Station; then seen=1; idle=0; else idle=$((idle+1)); fi
    if [ $seen -eq 1 ] && [ $idle -ge 12 ]; then
      killall httpd udhcpd hostapd 2>/dev/null
      ip link set uap0 down 2>/dev/null; ip addr flush dev uap0 2>/dev/null
      break
    fi
    sleep 10
  done ) &
