import logging
import time

from meshtastic import BROADCAST_NUM

access_logger = logging.getLogger('access')
sync_logger = logging.getLogger('sync')

user_states = {}


def update_user_state(user_id, state):
    user_states[user_id] = state


def get_user_state(user_id):
    return user_states.get(user_id, None)


def send_message(message, destination, interface, category='access'):
    """
    Sends `message` to `destination`, chunked to fit the max payload size.

    `category` controls which persisted log gets the one-liner for this send:
    'access' (default) for replies to users, or 'sync' for BBS-to-BBS sync
    traffic. Errors always also go to the main app/error log.
    """
    logger = sync_logger if category == 'sync' else access_logger

    if destination == BROADCAST_NUM:
        destid = None
        dest_label = "Broadcast"
    else:
        destid = get_node_id_from_num(destination, interface)
        dest_label = get_node_short_name(destid, interface) if destid else None
        dest_label = dest_label or str(destination)

    max_payload_size = 200
    for i in range(0, len(message), max_payload_size):
        chunk = message[i:i + max_payload_size]
        chunk_log = chunk.replace('\n', '\\n')
        try:
            d = interface.sendText(
                text=chunk,
                destinationId=destination,
                wantAck=True,
                wantResponse=False
            )
            logger.info(f"TX to={dest_label}({destid}) dest_num={destination} sendId={d.id} msg=\"{chunk_log}\"")
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"TX RAW RESPONSE: {d!r}")
        except Exception as e:
            logging.error(f"Error sending message to {dest_label}({destid}): {e}")
            logger.info(f"TX ERROR to={dest_label}({destid}) dest_num={destination} msg=\"{chunk_log}\" error={e}")

        time.sleep(2)


def get_node_info(interface, short_name):
    nodes = [{'num': node_id, 'shortName': node['user']['shortName'], 'longName': node['user']['longName']}
             for node_id, node in interface.nodes.items()
             if node['user']['shortName'].lower() == short_name]
    return nodes


def get_node_id_from_num(node_num, interface):
    for node_id, node in interface.nodes.items():
        if node['num'] == node_num:
            return node_id
    return None


def get_node_short_name(node_id, interface):
    node_info = interface.nodes.get(node_id)
    if node_info:
        return node_info['user']['shortName']
    return None


def send_bulletin_to_bbs_nodes(board, sender_short_name, subject, content, unique_id, bbs_nodes, interface):
    message = f"BULLETIN|{board}|{sender_short_name}|{subject}|{content}|{unique_id}"
    for node_id in bbs_nodes:
        send_message(message, node_id, interface, category='sync')


def send_mail_to_bbs_nodes(sender_id, sender_short_name, recipient_id, subject, content, unique_id, bbs_nodes,
                           interface):
    message = f"MAIL|{sender_id}|{sender_short_name}|{recipient_id}|{subject}|{content}|{unique_id}"
    sync_logger.info(f"SERVER SYNC: Syncing new mail message {subject} sent from {sender_short_name} to other BBS systems.")
    for node_id in bbs_nodes:
        send_message(message, node_id, interface, category='sync')


def send_delete_bulletin_to_bbs_nodes(bulletin_id, bbs_nodes, interface):
    message = f"DELETE_BULLETIN|{bulletin_id}"
    for node_id in bbs_nodes:
        send_message(message, node_id, interface, category='sync')


def send_delete_mail_to_bbs_nodes(unique_id, bbs_nodes, interface):
    message = f"DELETE_MAIL|{unique_id}"
    sync_logger.info(f"SERVER SYNC: Sending delete mail sync message with unique_id: {unique_id}")
    for node_id in bbs_nodes:
        send_message(message, node_id, interface, category='sync')


def send_channel_to_bbs_nodes(name, url, bbs_nodes, interface):
    message = f"CHANNEL|{name}|{url}"
    for node_id in bbs_nodes:
        send_message(message, node_id, interface, category='sync')
