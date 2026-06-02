#!/bin/bash
MAP_FILE=/etc/nginx/ssl/subdomain_ports.map
CHECK_FILE=/tmp/nginx_map_md5
NEW_MD5=$(md5sum $MAP_FILE 2>/dev/null | awk '{print $1}')
OLD_MD5=$(cat $CHECK_FILE 2>/dev/null)
if [ "$NEW_MD5" != "$OLD_MD5" ]; then
    nginx -s reload 2>/dev/null
    echo "$(date): nginx reloaded" >> /var/log/nginx-map-reload.log
    echo "$NEW_MD5" > $CHECK_FILE
fi
