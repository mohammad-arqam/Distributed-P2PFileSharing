import datetime
import sys
import select
import json
import socket
import time
import random
import uuid
import hashlib
import threading
from urllib.parse import unquote
import os

TIMEOUT = 60

METADATA_FILE = "metadata.json"
FILES_DIR="files"
local_files=set()
lock = threading.Lock()


seen_gossip_ids = set()
tracked_peers={}

GOSSIP_COUNT=3
GOSSIP_INTERVAL = 30
def save_metadata():
    with lock:
        with open(METADATA_FILE, "w") as f:
            json.dump(metadata, f, indent=2)
        print(f"[{UMNETID}] Metadata saved.")

import os

def load_metadata():
    if os.path.exists(METADATA_FILE):
        try:
            with open(METADATA_FILE, "r") as f:
                data = json.load(f)
            print(f"[{UMNETID}] Metadata loaded from file.")
            return data
        except:
            print(f"[{UMNETID}] Failed to load metadata, rebuilding.")
    return rescan_local_files()

def rescan_local_files():
    meta = {}
    if not os.path.exists(FILES_DIR):
        os.makedirs(FILES_DIR)
        return meta

    for fname in os.listdir(FILES_DIR):
        fpath = os.path.join(FILES_DIR, fname)
        if not os.path.isfile(fpath):
            continue
        try:
            with open(fpath, "rb") as f:
                content = f.read()
            stat = os.stat(fpath)
            ts = int(stat.st_mtime)
            fid = hash_file(content, ts)
            size = round(len(content) / (1024 * 1024), 2)
            meta[fid] = {
                "file_name": fname,
                "file_size": size,
                "file_id": fid,
                "file_owner": UMNETID,
                "file_timestamp": ts,
                "peers": [UMNETID]
            }
            local_files.add(fid)
        except:
            continue
    print(f"[{UMNETID}] Reconstructed metadata for {len(meta)} file(s).")
    return meta

def hash_file(content, timestamp):
    h = hashlib.sha256()
    h.update(content)
    h.update(str(timestamp).encode())
    return h.hexdigest()

def send_json(sock, data):
    sock.sendall((json.dumps(data) + "\n").encode())

def recv_json(sock):
    buffer = ""
    while True:
        chunk = sock.recv(4096).decode()
        if not chunk:
            break
        buffer += chunk
        
    try:
        return json.loads(buffer.strip())
    except json.JSONDecodeError:
        print(f"[{UMNETID}] Failed to decode JSON: {buffer}")
        return {}

def gossip(to_host,to_port):
    msg_id= str(uuid.uuid4())
    gossip_msg={
        "type": "GOSSIP",
        "host": HOST,
        "port": PORT,
        "id": msg_id,
        "peerId": UMNETID
    }

    try:
        with socket.create_connection((to_host, to_port), timeout=5) as s:
            send_json(s, gossip_msg)
            seen_gossip_ids.add(msg_id)  # Mark it 
    except Exception as e:
        pass

def handle_gossip(message):
    gossip_identifier = message["id"]
    peer_name = message["peerId"]
    from_host = message["host"]
    from_port = message["port"]

        # Skip already processed gossip messages
    if gossip_identifier in seen_gossip_ids:
        return
    seen_gossip_ids.add(gossip_identifier)

    current_time = time.time()
    with lock:
        if peer_name != UMNETID and peer_name not in tracked_peers:
            tracked_peers[peer_name] = {
            "host": from_host,
            "port": from_port,
            "last_seen": current_time,
            }
        else:
            tracked_peers[peer_name]["last_seen"]=current_time
            
        # Collect metadata of locally stored files only
        local_file_info = [metadata[fid] for fid in local_files if fid in metadata]

        # Prepare GOSSIP_REPLY message with local file info
        response = {
            "type": "GOSSIP_REPLY",
            "host": HOST,
            "port": PORT,
            "peerId": UMNETID,
            "files": local_file_info
        }
        # send reply to the originator
        
        try:
            with socket.create_connection((from_host, from_port), timeout=5) as connection:
                send_json(connection, response)
        except:
            pass
        # Forward the GOSSIP to a random subset of peers, excluding sender and self
        possible_peers=[peer for peer in tracked_peers if peer !=peer_name and peer!=UMNETID]
        if possible_peers:
            to_notify = random.sample(possible_peers, min(GOSSIP_COUNT, len(possible_peers)))  # notify to a minimum of 3 peers
            for peer_id in to_notify:
                h, p, _ = tracked_peers[peer_id]
                try:
                    with socket.create_connection((h, p), timeout=5) as forward_sock:
                        send_json(forward_sock, message)
                except:
                    continue

def handle_gossip_reply(gossip):
    peer_id=gossip["peerId"]
    sender_host,sender_port=gossip["host"], gossip["port"]
    files=gossip.get("files",[])
    
    # update tracked_peers
    with lock:
        if peer_id != UMNETID:
            tracked_peers[peer_id]= {
                "host": sender_host,
                "port": sender_port,
                "last_seen": time.time(),
            }

        for file_entry in files:
            fid= file_entry["file_id"]
            if fid not in metadata:
                metadata[fid]= {
                    **file_entry,
                    "peers": [peer_id],
                }
            else:
                existing=metadata[fid]
                if existing["file_timestamp"] < file_entry["file_timestamp"]:
                    metadata[fid].update(file_entry)

                if peer_id not in metadata[fid]["peers"]:
                    metadata[fid]["peers"].append(peer_id)
        
        save_metadata()

def cleanup_tracked_peers():
    current = time.time()
    stale_peers = []

    with lock:
        def loop():
            while True:
                time.sleep(10) #  check every 10 seconds    
                # Phase 1: Identify stale peers
                for peer_id in list(tracked_peers):
                    last_seen = tracked_peers[peer_id]["last_seen"]
                    if current - last_seen > TIMEOUT:
                        stale_peers.append(peer_id)
                        del tracked_peers[peer_id]

                if not stale_peers:
                    return  # nothing to do

                # Phase 2: Remove stale peers from file metadata
                for fid, meta in metadata.items():
                    if "peers" in meta:
                        original = set(meta["peers"])
                        updated = original - set(stale_peers)
                        if original != updated:
                            meta["peers"] = list(updated)

                save_metadata()
                print(f"[{UMNETID}] Removed inactive peer(s): {', '.join(stale_peers)}")
        t = threading.Thread(target=loop, daemon=True)
        t.start()

def start_gossip_loop():
    def worker():
        while True:
            time.sleep(GOSSIP_INTERVAL)

            # Grab a snapshot of peers we know about
            with lock:
                peer_pool = list(tracked_peers.values())

            if not peer_pool:
                continue  # nothing to chat with

            targets = random.sample(peer_pool,
                                    min(GOSSIP_COUNT, len(peer_pool)))

            for info in targets:
                try:
                    gossip(info["host"], info["port"])
                except Exception:
                    # Ignore network hiccups and keep looping
                    pass

    threading.Thread(target=worker, daemon=True).start()

def handle_get_file(msg, conn):
    fid = msg.get("file_id")
    if fid not in metadata or fid not in local_files:
        response = {"type": "FILE_DATA", "file_id": None, "file_name": None, "data": None}
    else:
        path = os.path.join(FILES_DIR, metadata[fid]["file_name"])
        with open(path, "rb") as f:
            content = f.read()
        response = {
            "type": "FILE_DATA",
            "file_id": fid,
            "file_name": metadata[fid]["file_name"],
            "file_size": metadata[fid]["file_size"],
            "file_owner": metadata[fid]["file_owner"],
            "file_timestamp": metadata[fid]["file_timestamp"],
            "data": content.hex()
        }
    send_json(conn, response)

def handle_file_data(msg):
    fid = msg["file_id"]
    fname = msg["file_name"]
    fpath = os.path.join(FILES_DIR, fname)
    try:
        content = bytes.fromhex(msg["data"])
        with open(fpath, "wb") as f:
            f.write(content)
        metadata[fid] = {
            "file_name": fname,
            "file_size": round(len(content) / (1024 * 1024), 2),
            "file_id": fid,
            "file_owner": msg["file_owner"],
            "file_timestamp": msg["file_timestamp"],
            "peers": [UMNETID]
        }
        local_files.add(fid)
        save_metadata()
        print(f"[{UMNETID}] Successfully stored received file '{fname}' (ID: {fid})")
        announce_file_to_peers(fid)
    except Exception as e:
        print(f"[{UMNETID}] Failed to handle file data for '{fname}': {e}")



def handle_announce(msg):
    fid = msg["file_id"]
    sender = msg["from"]
    with lock:
        if fid not in metadata or metadata[fid]["file_timestamp"] < msg["file_timestamp"]:
            metadata[fid] = {
                "file_name": msg["file_name"],
                "file_size": msg["file_size"],
                "file_id": fid,
                "file_owner": msg["file_owner"],
                "file_timestamp": msg["file_timestamp"],
                "peers": [sender]
            }
        elif sender not in metadata[fid]["peers"]:
            metadata[fid]["peers"].append(sender)
        save_metadata()

def announce_file_to_peers(file_id):
    with lock:
        if file_id not in metadata:
            return

        entry = metadata[file_id]
        announce_msg = {
            "type": "ANNOUNCE",
            "from": UMNETID,
            "file_name": entry["file_name"],
            "file_size": entry["file_size"],
            "file_id": file_id,
            "file_owner": entry["file_owner"],
            "file_timestamp": entry["file_timestamp"]
        }

        for pid, pinfo in tracked_peers.items():
            try:
                with socket.create_connection((pinfo["host"], pinfo["port"]), timeout=5) as sock:
                    send_json(sock, announce_msg)
            except:
                continue

        print(f"[{UMNETID}] Shared new file '{entry['file_name']}' with peers.")

def handle_delete(msg):
    file_id = msg.get("file_id")
    sender = msg.get("from")

    if not file_id or not sender:
        return

    with lock:
        if file_id in metadata:
            if metadata[file_id]["file_owner"] == sender:
                if file_id in metadata:
                    del metadata[file_id]
                if file_id in local_files:
                    local_files.remove(file_id)
                try:
                    os.remove(os.path.join(FILES_DIR, metadata[file_id]["file_name"]))
                except:
                    pass
                save_metadata()
                print(f"[{UMNETID}] Deleted file {file_id} by request from owner {sender}.")



def generate_stats_html():
    html = "<html><head><meta http-equiv='refresh' content='2'></head><body>"
    html += f"<h2>Peer Stats for {UMNETID}</h2>"

    html += "<h3>Tracked Peers</h3>"
    html += "<table border='1'><tr><th>Peer ID</th><th>Host</th><th>Port</th><th>Last Seen</th></tr>"
    for pid, info in tracked_peers.items():
        last_seen = int(time.time() - info["last_seen"])
        html += f"<tr><td>{pid}</td><td>{info['host']}</td><td>{info['port']}</td><td>{last_seen}s ago</td></tr>"
    html += "</table>"

    html += "<h3>Files</h3>"
    html += "<table border='1'><tr><th>ID</th><th>Name</th><th>Owner</th><th>Size (MB)</th><th>Timestamp</th><th>Peers</th></tr>"
    for fid, meta in metadata.items():
        try:
            short_id = fid[:10] + "..."
            readable_ts = datetime.datetime.fromtimestamp(
                float(meta["file_timestamp"])
            ).strftime("%Y-%m-%d %H:%M:%S")
            peers_str = ", ".join(meta.get("peers", []))
            html += (
                f"<tr><td>{short_id}</td><td>{meta['file_name']}</td>"
                f"<td>{meta['file_owner']}</td><td>{meta['file_size']}</td>"
                f"<td>{readable_ts}</td><td>{peers_str}</td></tr>"
            )
        except:
            continue
    html += "</table></body></html>"
    return html

def http_stats_server():
    def serve():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((HOST, HTTP_PORT))
            s.listen(1)
            print(f"[{UMNETID}] HTML stats page available at http://{HOST}:{HTTP_PORT}/")

            while True:
                conn, _ = s.accept()
                with conn:
                    try:
                        req = conn.recv(1024).decode()
                        if req.startswith("GET /"):
                            html = generate_stats_html()
                            headers = "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n"
                            conn.sendall(headers.encode() + html.encode())
                        else:
                            conn.sendall(b"HTTP/1.1 404 Not Found\r\n\r\n")
                    except:
                        continue

    threading.Thread(target=serve, daemon=True).start()

def p2p_server():
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind((HOST, PORT))
    server_sock.listen(5)
    server_sock.setblocking(False)
    print(f"[{UMNETID}] TCP server running on {HOST}:{PORT}")

    inputs = [server_sock]
    buffers = {}

    while True:
        readable, _, _ = select.select(inputs, [], [], 1)

        for sock in readable:
            if sock is server_sock:
                conn, _ = sock.accept()
                conn.setblocking(False)
                inputs.append(conn)
                buffers[conn] = b""
            else:
                try:
                    data = sock.recv(4096)
                    if data:
                        buffers[sock] += data
                        try:
                            msg = json.loads(buffers[sock].decode())
                            handle_peer_connection(sock, msg)
                            buffers[sock] = b""
                        except json.JSONDecodeError:
                            continue
                    else:
                        inputs.remove(sock)
                        buffers.pop(sock, None)
                        sock.close()
                except:
                    inputs.remove(sock)
                    buffers.pop(sock, None)
                    sock.close()

def handle_peer_connection(conn, msg):
    mtype=msg.get("type")
    try:
        print(f"[{UMNETID}] Received message: {msg.get('type', '<no-type>')}")
        # Handle different message types here
        if mtype == "GOSSIP":
            handle_gossip(msg)               #  stores sender in tracked_peers
        elif mtype == "GOSSIP_REPLY":
            handle_gossip_reply(msg)         #  stores sender + file list
        elif mtype == "GET_FILE":
            handle_get_file(msg, conn)       #  returns the file **on the same socket**
        elif mtype == "FILE_DATA":
            handle_file_data(msg)
        elif mtype == "ANNOUNCE":
            handle_announce(msg)
        elif mtype == "DELETE":
            handle_delete(msg)
        else:
            print(f"[{UMNETID}] Unknown msg type {mtype}")

    except Exception as e:
        print(f"[{UMNETID}] Error handling peer message: {e}")


def handle_peer_request(conn):
    try:
        msg = recv_json(conn)
        if msg["type"] == "DELETE":
            handle_delete(msg)
        # Add other handlers here
    except Exception as e:
        print(f"[{UMNETID}] Error handling peer request: {e}")
    finally:
        conn.close()

def cli():
    while True:
        cmd = input("p2p> ").strip()
        if cmd == "list":
            with lock:
                for fid, meta in metadata.items():
                    ts = datetime.datetime.fromtimestamp(meta["file_timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
                    print(f"{fid[:10]} | {meta['file_name']} | {meta['file_size']} MB | Owner: {meta['file_owner']} | Peers: {meta.get('peers', [])} | Timestamp: {ts}")
        elif cmd.startswith("push "):
            path = cmd.split(" ", 1)[1]
            if not os.path.isfile(path):
                print("Invalid file.")
                continue
            with open(path, "rb") as f:
                content = f.read()
            ts = int(time.time())
            fid = hash_file(content, ts)
            name = os.path.basename(path)
            os.makedirs(FILES_DIR, exist_ok=True)
            with open(os.path.join(FILES_DIR, name), "wb") as f:
                f.write(content)
            size = round(len(content) / (1024 * 1024), 2)
            with lock:
                metadata[fid] = {
                    "file_name": name,
                    "file_size": size,
                    "file_id": fid,
                    "file_owner": UMNETID,
                    "file_timestamp": ts,
                    "peers": [UMNETID]
                }
                local_files.add(fid)
                save_metadata()
            announce_file_to_peers(fid)
            push_file_to_random_peer(fid,name,content,size,ts)
            print(f"[{UMNETID}] Pushed file '{name}' with ID {fid[:10]}...")
        elif cmd.startswith("get "):
            fid = cmd.split(" ", 1)[1]
            with lock:
                if fid not in metadata:
                    print("Unknown file ID.")
                    continue
                if fid in local_files:
                    print("You already have this file.")
                    continue
                for pid in metadata[fid].get("peers", []):
                    if pid in tracked_peers:
                        try:
                            with socket.create_connection((tracked_peers[pid]["host"], tracked_peers[pid]["port"]), timeout=5) as sock:
                                send_json(sock, {"type": "GET_FILE", "file_id": fid})
                                print(f"[{UMNETID}] Requested file {fid[:10]} from {pid}")

                                response = recv_json(sock)
                                if response.get("type") == "FILE_DATA" and response.get("file_id"):
                                    handle_file_data(response)
                                else:
                                    print(f"[{UMNETID}] Failed to receive valid FILE_DATA for {fid[:10]}")
                                break
                        except Exception as e:
                            print(f"[{UMNETID}] Error contacting {pid}: {e}")

        elif cmd.startswith("delete "):
            fid = cmd.split(" ", 1)[1]
            with lock:
                if fid not in metadata:
                    print("File not found in metadata.")
                    continue
                if metadata[fid]["file_owner"] != UMNETID:
                    print("You are not the owner of this file.")
                    continue
                try:
                    os.remove(os.path.join(FILES_DIR, metadata[fid]["file_name"]))
                except:
                    pass
                local_files.discard(fid)
                del metadata[fid]
                for pid in tracked_peers:
                    try:
                        with socket.create_connection((tracked_peers[pid]["host"], tracked_peers[pid]["port"]), timeout=5) as sock:
                            send_json(sock, {"type": "DELETE", "file_id": fid, "from": UMNETID})
                    except:
                        continue
                save_metadata()
                print(f"[{UMNETID}] Deleted file {fid[:10]} and broadcast DELETE to peers.")
        elif cmd == "peers":
            with lock:
                for pid, p in tracked_peers.items():
                    age = int(time.time() - p["last_seen"])
                    print(f"{pid} at {p['host']}:{p['port']} (last seen {age}s ago)")
        elif cmd == "exit":
            print("Exiting...")
            save_metadata()
            break
        else:
            print("Commands: list, push <file>, get <file_id>, delete <file_id>, peers, exit")

def push_file_to_random_peer(fid, fname, data, size, ts):
    hex_data = data.hex()
    message = {
        "type": "FILE_DATA",
        "file_id": fid,
        "file_name": fname,
        "file_owner": UMNETID,
        "file_timestamp": ts,
        "file_size": size,
        "data": hex_data,
    }

    with lock:
        potential_targets = [peer for peer in tracked_peers if peer != UMNETID]
        if not potential_targets:
            print(f"[{UMNETID}] No available peers to push '{fname}'.")
            return

        target_peer = random.choice(potential_targets)
        peer_details = tracked_peers[target_peer]

    try:
        with socket.create_connection((peer_details["host"], peer_details["port"]), timeout=5) as conn:
            send_json(conn, message)
        print(f"[{UMNETID}] Sent '{fname}' to peer {target_peer}")
    except Exception as err:
        print(f"[{UMNETID}] Could not send '{fname}' to {target_peer}: {err}")


def auto_fetch_files_on_startup():
    print(f"[{UMNETID}] Starting auto-fetch to retrieve missing files...")
    print(f"[{UMNETID}] Attempting to acquire lock to read metadata...") # debug   
    with lock:
        print(f"[{UMNETID}] Lock acquired. Checking for missing files.") # debug
        candidates = [fid for fid in metadata if fid not in local_files]
    print(f"[{UMNETID}] Candidate files to fetch: {[fid[:10] for fid in candidates]}")

    if not candidates:
        print(f"[{UMNETID}] All known files are already downloaded.")
        return

    files_to_grab = random.sample(candidates, min(3, len(candidates)))
    print(f"[{UMNETID}] Files selected for grab: {[fid[:10] for fid in files_to_grab]}")

    for fid in files_to_grab:
        print(f"[{UMNETID}] Trying to auto-fetch file: {fid[:10]}...")
        with lock:
            peers_with_file = metadata[fid].get("peers", [])
        print(f"[{UMNETID}] Peers with file {fid[:10]}: {peers_with_file}")
        for peer_id in peers_with_file:
            if peer_id in tracked_peers:
                host, port = tracked_peers[peer_id]["host"], tracked_peers[peer_id]["port"]
                print(f"[{UMNETID}] Connecting to peer {peer_id} at {host}:{port}")
                try:
                    with socket.create_connection((host, port), timeout=5) as sock:
                        print(f"[{UMNETID}] Connected. Sending GET_FILE...")
                        send_json(sock, {"type": "GET_FILE", "file_id": fid})
                        print(f"[{UMNETID}] Requested '{fid[:10]}' from {peer_id}")
                        sock.settimeout(5)
                        response = recv_json(sock)
                        print(f"[{UMNETID}] Received response: {response}")
                        if response.get("type") == "FILE_DATA" and response.get("file_id"):
                            handle_file_data(response)
                        else:
                            print(f"[{UMNETID}] Did not receive valid FILE_DATA for {fid[:10]}")
                        break
                except Exception as e:
                    print(f"[{UMNETID}] Failed to reach {peer_id}: {e}")
        time.sleep(1)  # Delay between fetch attempts

    print(f"[{UMNETID}] Auto-fetch routine finished.")



def main():
    global UMNETID, HOST, PORT, HTTP_PORT, metadata
    # take in user input
    if len(sys.argv) != 5:
        print("Usage: python p2p_filesharing.py <peer_id> <host> <p2p_port> <http_port>")
        sys.exit(1)
    UMNETID = sys.argv[1]
    HOST = sys.argv[2]
    PORT = int(sys.argv[3])
    HTTP_PORT = int(sys.argv[4])

    metadata = load_metadata()
    save_metadata()
    WELL_KNOWN_HOSTS = ["silicon.cs.umanitoba.ca", "hawk.cs.umanitoba.ca", "grebe.cs.umanitoba.ca", "eagle.cs.umanitoba.ca"]
    gossip_host=random.choice(WELL_KNOWN_HOSTS)
    gossip_port=8999
    
    # start the TCP connection
    http_stats_server()
    threading.Thread(target=p2p_server, daemon=True).start()

    print(f"[{UMNETID}] Peer started on {HOST}:{PORT} with stats at {HTTP_PORT}")

    gossip(gossip_host,gossip_port)  # send initial gossip
    time.sleep(10)  #  wait until all gossip replies are received
    threading.Thread(target=auto_fetch_files_on_startup, daemon=True).start()

    start_gossip_loop()  # re gossip
    cleanup_tracked_peers()  # clean up tracked peers

    print("Available Commands:")
    print("  list                         → Show all known files")
    print("  peers                        → Display known peers")
    print("  push <file_path>             → Upload and share a file")
    print("  get <file_id> [destination]  → Retrieve a file from peers")
    print("  delete <file_id>             → Remove a file you own")
    print("  exit                         → Exit the peer program")

    cli()



    # Keep the main thread alive
    while True:
        time.sleep(1)

if __name__ == "__main__":
    main()