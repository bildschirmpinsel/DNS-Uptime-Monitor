# DNS-Uptime-Monitor
This script can be used to debug networking issues and monitor reachability of services hosted behind a reverse proxy. 
## Workflow
The script does the following things:
1. Check whether a given DNS can resolve A records for a given list of domains.
2. Check whether these domains can also be resolved when sent to the DNS server advertised via DHCP.
3. Check whether a given reverse proxy hosts these domains and answers positively to an http GET request. 

The results of these checks are stored in an SQLite database for a given amount of days. If any of the three checks yields different results, an email is send from a given GMail address to a given recipient.  

## Configuration
The script is configured entirely by environment variables:
- `UPTIME_URLS`: comma separated list of domains to run checks for (e.g. `www.google.com,www.github.com`).
- `UPTIME_DNS_SERVER_ADDRESS`: IP address of DNS server to query for domains.
- `UPTIME_REVERSE_PROXY_ADDRESS`: IP address of reverse proxy, that should host domains.
- `UPTIME_DATABASE`: File path for database file (e.g. `./database/uptime.db`).
- `UPTIME_RETAIN_TIME_DAYS`: Time in days for how long database should retain information for.
- `UPTIME_LOG_FILE`: File path for log file (e.g. `./uptime.log`).
- `UPTIME_LOG_LEVEL`: Level to log, allowed values are `INFO|WARNING|ERROR|DEBUG` (as per https://docs.python.org/3/library/logging.html#levels). Default is `INFO`.
- `UPTIME_GMAIL_TOKEN`: GMail API token file; Can be generated as `token.json` by following this guide https://developers.google.com/workspace/gmail/api/quickstart/python
- `UPTIME_EMAIL_RECEIVER_ADDRESS`: Address to send emails to.
- `UPTIME_EMAIL_SENDER_ADDRESS`: Address to send emails from.

## Database Scheme
The scheme used in the database is uptime: {[<ins>timestamp</ins>: datetime, <ins>url</ins>: text, dnsdirect: text, dnsrouter: text, reverseproxy: integer]}. The columns `dnsdirect` and `dnsrouter` store the respective DNS answer (IP, `NXDOMAIN`, `TIMEOUT`), while `reverseproxy` stores an http response code (e.g. `200`, `404`). The timestamp of the checks and the checked url together form the primary key.

## Email 
The email is send with the subject 'Uptime Changes' and contains the data in a similar format to the database. If a service is checked for the first time or has not been checked since the last time the database was cleared, an email with the current data will always be send. Otherwise, emails will only be send when the current check yielded different results from the last check in the database. Fields that did not experience any changes will be filled with 'No Change' in the email. 

