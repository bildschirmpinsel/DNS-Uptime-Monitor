# DNS-Uptime-Monitor
A python script to monitor reachability of services behind a reverse proxy via directly querying the DNS server and via querying the router. Users are notified by email if reachability changes in the event the DNS is down, the router can't find the DNS, or the reverse proxy cannot forward to the queried service.
