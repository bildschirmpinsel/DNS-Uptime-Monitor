from datetime import datetime, timedelta
from os import environ, path

# uptime
import dns.resolver
import requests

# database
import sqlite3

# logging
import logging
from logging.handlers import RotatingFileHandler

# email imports
import base64
from email.message import EmailMessage

# google libraries necessary for email service
import google.auth
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# uptime variables
URLS_ENVIRONMENT_VARIABLE = "UPTIME_URLS"
DNS_ENVIRONMENT_VARIABLE = "UPTIME_DNS_SERVER_ADDRESS"
REVERSE_PROXY_ENVIRONMENT_VARIABLE = "UPTIME_REVERSE_PROXY_ADDRESS"

# database variables
DATABASE_FILE_ENVIRONMENT_VARIABLE = "UPTIME_DATABASE"
DATABSE_RETAIN_TIME_ENVIRONMENT_VARIABLE = "UPTIME_RETAIN_TIME_DAYS"

# logging
LOG_FILE_ENVIRONMENT_VARIABLE = "UPTIME_LOG_FILE"
LOG_LEVEL_ENVIRONMENT_VARIABLE = "UPTIME_LOG_LEVEL"

# email service variables
GMAIL_API_TOKEN_ENVIRONMENT_VARIABLE = "UPTIME_GMAIL_TOKEN"
EMAIL_RECEIVER_ADDRESS_ENVIRONMENT_VARIABLE = "UPTIME_EMAIL_RECEIVER_ADDRESS"
EMAIL_SENDER_ADDRESS_ENVIRONMENT_VARIABLE = "UPTIME_EMAIL_SENDER_ADDRESS"

# constants
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
URL_LIST_DELIMITER = ","

if __name__ == "__main__":
    timestamp = datetime.now()

    #################################
    # Extract environment variables #
    #################################
    def extract_environment_variable(variable, variable_descriptor, optional=False):
        extracted_value = environ.get(key=variable, default=None)
        if not extracted_value and not optional:
            raise ValueError(
                f"No {variable_descriptor} found in environment variable {variable}"
            )
        return extracted_value

    urls = extract_environment_variable(
        variable=URLS_ENVIRONMENT_VARIABLE, variable_descriptor="URLs"
    )
    dns_address = extract_environment_variable(
        variable=DNS_ENVIRONMENT_VARIABLE, variable_descriptor="DNS server address"
    )
    reverse_proxy_address = extract_environment_variable(
        variable=REVERSE_PROXY_ENVIRONMENT_VARIABLE,
        variable_descriptor="reverse proxy address",
    )
    database_file = extract_environment_variable(
        variable=DATABASE_FILE_ENVIRONMENT_VARIABLE,
        variable_descriptor="database file path",
    )
    database_retain_time_days = int(
        extract_environment_variable(
            variable=DATABSE_RETAIN_TIME_ENVIRONMENT_VARIABLE,
            variable_descriptor="database retain time (in days)",
        )
    )
    log_file = extract_environment_variable(
        variable=LOG_FILE_ENVIRONMENT_VARIABLE, variable_descriptor="log file path"
    )
    log_level = environ.get(LOG_LEVEL_ENVIRONMENT_VARIABLE, "INFO").upper()
    api_token_file = extract_environment_variable(
        variable=GMAIL_API_TOKEN_ENVIRONMENT_VARIABLE,
        variable_descriptor="gmail api token file path",
        optional=True,
    )
    if api_token_file:
        if not path.exists(api_token_file):
            raise ValueError(f"No api token file found under path {api_token_file}")
        email_receiver_address = extract_environment_variable(
            variable=EMAIL_RECEIVER_ADDRESS_ENVIRONMENT_VARIABLE,
            variable_descriptor="email receiver address",
        )
        email_sender_address = extract_environment_variable(
            variable=EMAIL_SENDER_ADDRESS_ENVIRONMENT_VARIABLE,
            variable_descriptor="email sender address",
        )

    ######################
    # Setup of variables #
    ######################
    # set http scheme
    reverse_proxy_address = "http://" + reverse_proxy_address
    # split urls
    urls = urls.split(sep=URL_LIST_DELIMITER)
    # set up log formatter and file handler
    log_formatter = logging.Formatter(
        "%(asctime)s %(levelname)s (%(lineno)d) %(message)s"
    )
    file_handler = RotatingFileHandler(
        log_file,
        mode="a",
        maxBytes=5 * 1024 * 1024,
        backupCount=2,
        encoding=None,
        delay=0,
    )
    file_handler.setFormatter(log_formatter)
    file_handler.setLevel(log_level)
    # set up logger
    logger = logging.getLogger(__name__)
    logger.setLevel(log_level)
    logger.addHandler(file_handler)

    ############################
    # Start DNS lookup of URLs #
    ############################
    logger.info("Start DNS Lookup of URLs")

    def dns_lookup(dns_resolver, result_set, url_list):
        for url in url_list:
            try:
                result = dns_resolver.resolve(url, "A")
                # extract (first) ip from result
                result_set[url] = result[0]
            except dns.resolver.NXDOMAIN:
                result_set[url] = "NXDOMAIN"
                logger.warning(f"NXDOMAIN for {url}")
            except dns.resolver.LifetimeTimeout:
                result_set[url] = "TIMEOUT"
                logger.error(f"TIMEOUT for {url}")
            logger.debug(f"\t\t{url}: {result_set[url]}")

    # dicts holding either the successful response or NXDOMAIN
    dns_direct_lookup_results = {}
    dns_router_lookup_results = {}

    # instantiate resolver with dns server address set
    resolver = dns.resolver.Resolver()
    resolver.nameservers = [dns_address]

    logger.info("\tDirect to DNS")
    dns_lookup(
        dns_resolver=resolver, result_set=dns_direct_lookup_results, url_list=urls
    )

    # instantiate resolver without dns address set (go via router advertised dns)
    resolver = dns.resolver.Resolver()
    logger.info("\tRouter to DNS")
    dns_lookup(
        dns_resolver=resolver, result_set=dns_router_lookup_results, url_list=urls
    )

    ######################
    # Check reverse proxy #
    ######################
    logger.info("Start Reverse Proxy Lookup of URLs")

    reverse_proxy_lookup_results = {}

    for url in urls:
        request_answer = requests.get(reverse_proxy_address, headers={"Host": url})
        reverse_proxy_lookup_results[url] = request_answer.status_code
        logger.debug(f"\t{url}: {request_answer.reason}")

    logger.info("Finished Checking Uptimes...")

    #######################
    # Database management #
    #######################
    logger.info("Begin Database Management...")
    connection = sqlite3.connect(database=database_file)
    cursor = connection.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS uptime (
            timestamp DATETIME NOT NULL,
            url TEXT NOT NULL,
            dnsdirect TEXT NOT NULL,
            dnsrouter TEXT NOT NULL,
            reverseproxy INTEGER NOT NULL,
            PRIMARY KEY (timestamp, url)
        );
    """
    )

    # check for empty database
    previous_data_available = (
        cursor.execute("SELECT 1 FROM uptime LIMIT 1").fetchone() is not None
    )
    notify_user = True

    def insert_values_into_database():
        data = []
        for url in urls:
            row_data = {
                "timestamp": timestamp,
                "url": url,
                "dnsdirect": str(dns_direct_lookup_results[url]),
                "dnsrouter": str(dns_router_lookup_results[url]),
                "reverseproxy": reverse_proxy_lookup_results[url],
            }
            data.append(row_data)
        cursor.executemany(
            "INSERT INTO uptime VALUES(:timestamp, :url, :dnsdirect, :dnsrouter, :reverseproxy)",
            data,
        )

    changed_urls = {}

    if previous_data_available:
        previous_timestamp = cursor.execute(
            "SELECT MAX(timestamp) FROM uptime"
        ).fetchone()[0]
        previous_timestamp = timestamp.strptime(
            previous_timestamp, "%Y-%m-%d %H:%M:%S.%f"
        )
        logger.info(
            f'\tPrevious Uptime Data Available at {previous_timestamp.strftime("%H:%M:%S")}, Checking For Changes...'
        )
        previous_data = cursor.execute(
            "SELECT * FROM uptime WHERE timestamp = ?", (previous_timestamp,)
        ).fetchall()
        # drop time stamp from data
        previous_data = [row[1:] for row in previous_data]
        # restructure data into dict with urls as key and the tuple (:dnsdirect, :dnsrouter, :reverseproxy) as value
        previous_data = {row[0]: row[1:] for row in previous_data}

        ###################################
        # Check previous data for changes #
        ###################################
        for url in urls:
            # new services are always changed
            if url not in previous_data.keys():
                changed_urls[url] = (
                    str(dns_direct_lookup_results[url]),
                    str(dns_router_lookup_results[url]),
                    reverse_proxy_lookup_results[url],
                )
            else:
                previous_dns_direct, previous_dns_router, previous_reverse_proxy = (
                    previous_data[url]
                )
                current_dns_direct = str(dns_direct_lookup_results[url])
                current_dns_router = str(dns_router_lookup_results[url])
                current_reverse_proxy = reverse_proxy_lookup_results[url]

                changed_values = ["No Change", "No Change", "No Change"]
                value_changed = False
                if previous_dns_direct != current_dns_direct:
                    value_changed = True
                    changed_values[0] = current_dns_direct
                if previous_dns_router != current_dns_router:
                    value_changed = True
                    changed_values[1] = current_dns_router
                if previous_reverse_proxy != current_reverse_proxy:
                    value_changed = True
                    changed_values[2] = current_reverse_proxy
                if value_changed:
                    changed_urls[url] = tuple(changed_values)

        if changed_urls:
            notify_user = True
            logger.info("\t\tFound Changes!")
        else:
            notify_user = False
            logger.info("\t\tFound No Changes...")

        insert_values_into_database()
        logger.info("\tInserted New Data Into Database!")

        ###############################
        # Delete old data in database #
        ###############################
        logger.info("\tDatabase Housekeeping")
        database_retain_time_delta = timedelta(days=database_retain_time_days)
        oldest_allowed_timestamp = timestamp - database_retain_time_delta

        number_rows_before = cursor.execute("SELECT COUNT(*) FROM uptime").fetchone()[0]
        logger.debug(f"\t\tDatabase Had {number_rows_before} Rows Before Cleaning")
        cursor.execute(
            "DELETE FROM uptime WHERE timestamp < ?", (oldest_allowed_timestamp,)
        )
        number_rows_after = cursor.execute("SELECT COUNT(*) FROM uptime").fetchone()[0]
        logger.debug(f"\t\tDatabase Has {number_rows_after} Rows After Cleaning")
    else:
        logger.info("\tNew Database Created, Inserting Data...")
        for url in urls:
            changed_urls[url] = (
                str(dns_direct_lookup_results[url]),
                str(dns_router_lookup_results[url]),
                reverse_proxy_lookup_results[url],
            )
        notify_user = True
        insert_values_into_database()
        logger.info("\tInserted New Data Into Database!")

    if not api_token_file:
        logger.info("No API Token Supplied, Not Sending Email!")
    if notify_user and api_token_file:
        logger.info("Sending Email...")
        creds = Credentials.from_authorized_user_file(api_token_file, SCOPES)

        # construct message
        message_content = (
            f'Uptime data from {timestamp.strftime("%Y-%m-%d %H:%M:%S")}:\n\n'
        )
        message_content += "\n".join(
            [f"{url}: \n\t{changed_urls[url]}" for url in changed_urls.keys()]
        )
        message_content += "\n\nData format: DNS direct resolution, DNS via router, reverse proxy status"

        try:
            service = build("gmail", "v1", credentials=creds)
            message = EmailMessage()

            message.set_content(message_content)

            message["To"] = email_receiver_address
            message["From"] = email_sender_address
            message["Subject"] = "Uptime Changes"

            # encoded message
            encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

            create_message = {"raw": encoded_message}
            # pylint: disable=E1101
            send_message = (
                service.users()
                .messages()
                .send(userId="me", body=create_message)
                .execute()
            )
            logger.debug(f'\tMessage ID: {send_message["id"]}')
        except HttpError as error:
            logger.error(f"\tAn Error Occurred: {error}")

    cursor.close()
    connection.commit()
    connection.close()
    logger.info("Script Finished!")
