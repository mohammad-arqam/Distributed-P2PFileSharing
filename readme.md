P2P File Sharing System – README

🔧 How to Start a Peer

To start a peer node, use the following command:

python3 p2pserver.py <peer_id> <host> <p2p_port> <http_port>

Example:

python3 p2pserver.py arqamm crow.cs.umanitoba.ca 8040 8041

<peer_id>: Your unique identifier (e.g., your UMNetID)

<host>: Hostname or IP of your machine

<p2p_port>: TCP port used for P2P communication

<http_port>: Port for the peer’s statistics HTTP server

🕒 Synchronization Behavior

Upon launching, the peer will:

Send a GOSSIP message to a random well-known peer to receive metadata updates.

Automatically run an auto-fetch routine to retrieve 3 missing files from known peers.

Expected Duration: Synchronization typically takes 5–10 seconds depending on network latency. Hence why there is a 10 seconds sleep timer before auto-fetch runs.

What You Will See:

File downloads and save confirmations

Access the web stats page at http://<host>:<http_port>/ to view tracked peers and files

📆 Metadata Handling

File: p2pserver.pyLine: ~292 (def handle_file_data(msg):)

This function processes received file content by decoding it from hex, saving it to disk, and inserting it into the shared metadata dictionary with its associated details (filename, owner, size, timestamp, etc.). It also adds the file ID to the local file set and calls save_metadata() to persist the update.

🧹 Peer Cleanup Logic

File: p2pserver.pyLine: ~217 (def cleanup_tracked_peers():)

This background thread monitors tracked_peers and removes any entry that hasn’t responded in over 60 seconds. It helps ensure your peer list remains fresh and avoids wasting resources on dead peers.

📄 Notes

All files are saved in the files/ directory.

The web interface auto-refreshes every 2 seconds.

The cli loop runs 20 seconds after auto-fetch in order to allow time for the updation of the metadata and handle any gossips. You will see the cli command list once the cli loop runs

Peers without recent GOSSIP updates are removed from the tracked list.

If exit is typed in the CLI, the system saves metadata and cleanly shuts down the CLI loop, however the main (p2pserver) stays alive.