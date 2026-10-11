import logging
import re
import time
from typing import NamedTuple, Optional

from meshtastic import BROADCAST_NUM

access_logger = logging.getLogger('access')
sync_logger = logging.getLogger('sync')

# Canonical Meshtastic node ID form: '!' followed by 8 hex digits, e.g. !09d3db18.
NODE_ID_RE = re.compile(r'^![0-9a-fA-F]{8}$')

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
    elif isinstance(destination, str) and destination.startswith('!'):
        # Already a node ID string (e.g. the output of resolve_node_identifier) -
        # meshtastic's sendText can take this directly, no DB lookup needed.
        destid = destination
        dest_label = get_node_short_name(destid, interface)
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


class ResolvedNode(NamedTuple):
    """Result of resolve_node_identifier(). See that function's docstring."""
    node_id: Optional[str]        # canonical '!xxxxxxxx' node ID, or None if unresolved
    node_num: Optional[int]       # decimal node number, if known
    short_name: Optional[str]     # the node's shortName, if known
    long_name: Optional[str]      # the node's longName, if known
    node_info: Optional[dict]     # the raw dict straight out of interface.nodes - the "db row" - if known
    matches: list                 # list of (node_id, node_info) tuples when input was an ambiguous short name
    error: Optional[str]          # human-readable error, or None on a clean resolution


_UNRESOLVED = ResolvedNode(None, None, None, None, None, [], None)


def resolve_node_identifier(user_input, interface) -> ResolvedNode:
    """
    Universal node resolver. Short names are NOT guaranteed to be unique, so
    whenever possible prefer addressing nodes by their Node ID instead.

    Accepts, in order of preference:
      - A node ID in canonical form: '!xxxxxxxx' (8 hex digits). This is
        always considered resolvable syntactically, even for a node we've
        never fully heard from yet (e.g. first contact via an encrypted DM
        before its NodeInfo broadcast arrives) - `node_id` will be set even
        if `node_info` ends up None.
      - A bare decimal node number (e.g. '164879128').
      - A short name (case-insensitive) or public key.

    This is intentionally cheap: ID/num lookups are O(1) dict access, and
    short name/pubkey matching is a single pass over the already in-memory
    `interface.nodes` - no extra DB or network calls.

    Returns a ResolvedNode namedtuple. On success, `node_id` is set and
    `error` is None. On failure, `node_id` is None and `error` describes why;
    `matches` is populated with every candidate when a short name matched
    more than one node, so callers can offer disambiguation (see
    handle_mail_steps step 3/6 in command_handlers.py for an example). Since
    it's a NamedTuple, fields are available either by name:

        resolved = resolve_node_identifier(user_input, interface)
        if resolved.error: ...

    or by position:

        node_id, node_num, short_name, long_name, node_info, matches, error = \\
            resolve_node_identifier(user_input, interface)
    """
    if user_input is None:
        return _UNRESOLVED._replace(error="No identifier provided.")

    token = str(user_input).strip()
    if not token:
        return _UNRESOLVED._replace(error="No identifier provided.")

    nodes = getattr(interface, 'nodes', None) or {}

    # Canonical node ID: '!xxxxxxxx'. Always syntactically resolvable, even
    # if we have no further info about the node yet.
    if token.startswith('!'):
        if not NODE_ID_RE.match(token):
            return _UNRESOLVED._replace(error=(
                f"'{token}' doesn't look like a valid node ID "
                f"(expected '!' + 8 hex digits, e.g. !09d3db18)."
            ))
        node_info = nodes.get(token)
        if node_info is None:
            return ResolvedNode(token, None, None, None, None, [], None)
        user = node_info.get('user') or {}
        return ResolvedNode(
            token, node_info.get('num'), user.get('shortName'), user.get('longName'), node_info, [], None
        )

    # Otherwise, match against node number, short name, and public key in a
    # single pass over the node list.
    node_num_candidate = int(token) if token.isdigit() else None
    token_lower = token.lower()
    matches = []
    for node_id, node_info in nodes.items():
        if node_num_candidate is not None and node_info.get('num') == node_num_candidate:
            matches.append((node_id, node_info))
            continue
        user = node_info.get('user') or {}
        short_name = user.get('shortName')
        pubkey = user.get('publicKey')
        if (short_name and short_name.lower() == token_lower) or (pubkey and str(pubkey) == token):
            matches.append((node_id, node_info))

    if not matches:
        return _UNRESOLVED._replace(error=f"No node found matching '{user_input}'.")
    if len(matches) > 1:
        return _UNRESOLVED._replace(matches=matches, error=f"Multiple nodes match '{user_input}'.")

    node_id, node_info = matches[0]
    user = node_info.get('user') or {}
    return ResolvedNode(node_id, node_info.get('num'), user.get('shortName'), user.get('longName'), node_info, [], None)


def get_node_info(interface, short_name):
    """
    Looks up nodes by short name (case-insensitive). Short names are NOT
    guaranteed to be unique, so this can return more than one match -
    callers are expected to handle 0 or 2+ results.

    Deprecated: prefer resolve_node_identifier(), which also accepts node
    IDs and is the single source of truth for node lookups. Kept as a thin
    compatibility wrapper around it.
    """
    resolved = resolve_node_identifier(short_name, interface)
    candidates = resolved.matches or ([(resolved.node_id, resolved.node_info)] if resolved.node_id else [])
    nodes = []
    for node_id, node_info in candidates:
        user = (node_info or {}).get('user') or {}
        short = user.get('shortName')
        nodes.append({
            'id': node_id,
            'num': (node_info or {}).get('num'),
            'shortName': short,
            'longName': user.get('longName', short),
        })
    return nodes


def get_node_id_from_num(node_num, interface):
    for node_id, node in interface.nodes.items():
        if node.get('num') == node_num:
            return node_id
    return None


def get_node_short_name(node_id, interface):
    """
    Returns the short name for `node_id`, if known. Falls back to `node_id`
    itself (the '!xxxxxxxx' form) when the node is only partially known to
    the local node db (e.g. no 'user'/'shortName' recorded yet), rather than
    raising a KeyError.
    """
    if node_id is None:
        return None
    node_info = interface.nodes.get(node_id)
    if node_info:
        short_name = (node_info.get('user') or {}).get('shortName')
        if short_name:
            return short_name
    return node_id


def send_bulletin_to_bbs_nodes(board, sender_short_name, subject, content, unique_id, bbs_nodes, interface,
                               sender_id=None):
    message = f"BULLETIN|{board}|{sender_short_name}|{subject}|{content}|{unique_id}"
    if sender_id:
        # Appended (rather than inserted) so older peer BBS nodes - whose
        # parsers only read the first 6 fields - keep working unaffected.
        message += f"|{sender_id}"
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
