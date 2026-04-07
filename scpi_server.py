import socket
import threading
import logging
import os
import pyvisa

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# TCPIP0::10.1.1.138::5025::SOCKET

VISA_ADDR = os.getenv("VISA_ADDRESS", "USB0::4916::520::999991006::0::INSTR")
SERVER_PORT = int(os.getenv("BRIDGE_PORT", "5025"))

def handle_client(conn, addr, rm):
    instr = None
    try:
        instr = rm.open_resource(VISA_ADDR)
        instr.timeout = 5000
        instr.read_termination = '\r\n'
        instr.write_termination = '\r\n'
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        logging.info(f"Client connected: {addr}")
        buffer = ""
        with conn:
            while True:
                data = conn.recv(1024)
                if not data:
                    break
                buffer += data.decode()
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    if "?" in line:
                        try:
                            resp = instr.query(line)
                            conn.sendall((resp + "\n").encode())
                        except pyvisa.VisaIOError as e:
                            conn.sendall(f"ERROR: {e}\n".encode())
                    else:
                        instr.write(line)
    except Exception as e:
        logging.error(f"Error with {addr}: {e}")
    finally:
        if instr:
            instr.close()
        logging.info(f"Client disconnected: {addr}")

def main():
    rm = pyvisa.ResourceManager('@py')
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(('0.0.0.0', SERVER_PORT))
            s.listen()
            logging.info(f"Bridge listening on port {SERVER_PORT}, VISA: {VISA_ADDR}")
            while True:
                conn, addr = s.accept()
                threading.Thread(target=handle_client, args=(conn, addr, rm), daemon=True).start()
    except KeyboardInterrupt:
        logging.info("Shutting down.")
    finally:
        rm.close()

if __name__ == "__main__":
    main()
