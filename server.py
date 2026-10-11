#!/usr/bin/env python3

"""
TC²-BBS Server for Meshtastic by TheCommsChannel (TC²)
Date: 07/14/2024
Version: 0.1.6

Description:
The system allows for mail message handling, bulletin boards, and a channel
directory. It uses a configuration file for setup details and an SQLite3
database for data storage. Mail messages and bulletins are synced with
other BBS servers listed in the config.ini file.
"""

import logging
import time

from bbs_logging import get_access_logger, get_feature_logger, resolve_debug, resolve_log_dir, setup_logging
from config_init import initialize_config, get_interface, init_cli_parser, merge_config
from db_operations import initialize_database
from js8call_integration import JS8CallClient
from message_processing import on_receive
from pubsub import pub


def display_banner():
    banner = """
████████╗ ██████╗██████╗       ██████╗ ██████╗ ███████╗
╚══██╔══╝██╔════╝╚════██╗      ██╔══██╗██╔══██╗██╔════╝
   ██║   ██║      █████╔╝█████╗██████╔╝██████╔╝███████╗
   ██║   ██║     ██╔═══╝ ╚════╝██╔══██╗██╔══██╗╚════██║
   ██║   ╚██████╗███████╗      ██████╔╝██████╔╝███████║
   ╚═╝    ╚═════╝╚══════╝      ╚═════╝ ╚═════╝ ╚══════╝
Meshtastic Version
"""
    print(banner)

def main():
    display_banner()
    args = init_cli_parser()

    log_dir = resolve_log_dir(args.log_dir)
    debug = resolve_debug(args.debug)
    setup_logging(log_dir, debug)
    logging.info(f"Logging to '{log_dir}' (debug={'on' if debug else 'off'})")

    config_file = None
    if args.config is not None:
        config_file = args.config
    system_config = initialize_config(config_file)

    merge_config(system_config, args)

    # access.log is always on; sync.log only gets its own file when sync is
    # configured (bbs_nodes non-empty), otherwise sync messages fall back to app.log
    get_access_logger(debug)
    get_feature_logger('sync', 'sync.log', enabled=bool(system_config['bbs_nodes']), debug=debug)

    interface = get_interface(system_config)
    interface.bbs_nodes = system_config['bbs_nodes']
    interface.allowed_nodes = system_config['allowed_nodes']

    logging.info(f"TC²-BBS is running on {system_config['interface_type']} interface...")

    initialize_database()

    def receive_packet(packet, interface):
        try:
            on_receive(packet, interface)
        except Exception as e:
            logging.error(f"Caught exception during receive_packet: {e}")

    pub.subscribe(receive_packet, system_config['mqtt_topic'])

    # Initialize and start JS8Call Client if configured. JS8CallClient sets up
    # its own 'js8call' logger (js8call.log when enabled, app.log otherwise).
    js8call_client = JS8CallClient(interface, debug=debug)

    if js8call_client.db_conn:
        js8call_client.connect()

    try:
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        logging.info("Shutting down the server...")
        interface.close()
        if js8call_client.connected:
            js8call_client.close()

if __name__ == "__main__":
    main()
