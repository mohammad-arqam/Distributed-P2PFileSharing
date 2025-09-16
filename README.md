TreePeer – P2P File Sharing System

TreePeer is a peer-to-peer file sharing system built in Python. Unlike the centralized file server of TreeDrive and the web-based interface of TreeDrive Web, TreePeer decentralizes file storage and discovery across multiple peers. It uses a gossip protocol for peer discovery, replicates metadata across the network, and supports push, get, delete, and list operations. Each peer maintains a local file store and a synchronized metadata log, while an auto-refreshing HTML page provides live system statistics.

🚀 Features

Decentralized Design – No central server; peers communicate directly over TCP.

Gossip Protocol – Periodically exchanges peer info and metadata to maintain a dynamic, resilient network.

File Operations

push <file> – Upload and share a new file.

get <file_id> – Retrieve a file from available peers.

delete <file_id> – Remove a file you own and propagate deletion to peers.

list – Show all known files, owners, sizes, timestamps, and peers.

Replication – Metadata and file presence replicated across multiple peers.

Auto Fetch – Missing files can be retrieved automatically from peers.

Peer Management – Track live peers, last-seen times, and remove inactive nodes.

Stats Page – Built-in HTTP server serves an HTML dashboard with peer and file tables, auto-refreshing every 2 seconds.

📂 Project Structure

p2pserver.py – Main peer node implementation, gossip, CLI, and HTML stats.

files/ – Local file storage for each peer.

metadata.json – Tracks file IDs, owners, timestamps, and peers.

⚙️ Installation & Usage
1. Clone the repo
git clone https://github.com/yourusername/TreePeer-P2P.git
cd TreePeer-P2P

2. Start a peer
python3 p2pserver.py <peer_id> <host> <p2p_port> <http_port>


Example:

python3 p2pserver.py peer1 127.0.0.1 9000 8080

3. Available Commands

Inside the peer CLI:

list                 # Show known files
peers                # Show connected peers
push <file_path>     # Upload and announce file
get <file_id>        # Download file from peers
delete <file_id>     # Delete your file and propagate
exit                 # Exit the peer

4. View Stats Page

Each peer runs a lightweight HTTP server that provides system stats:

http://<host>:<http_port>/


Example: http://127.0.0.1:8080/
