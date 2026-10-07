"""Pinned-host localhost-only forwarding for the nonpublic Campbell canary."""
import select
import socketserver
from discovery_transport import connect


def main():
    client = connect()
    transport = client.get_transport()
    transport.set_keepalive(20)

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            channel = transport.open_channel('direct-tcpip', ('127.0.0.1', 8792), self.request.getpeername())
            if channel is None:
                return
            try:
                while True:
                    readable, _, _ = select.select([self.request, channel], [], [])
                    if self.request in readable:
                        data = self.request.recv(65536)
                        if not data:
                            break
                        channel.sendall(data)
                    if channel in readable:
                        data = channel.recv(65536)
                        if not data:
                            break
                        self.request.sendall(data)
            finally:
                channel.close()

    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True
        allow_reuse_address = True

    try:
        with Server(('127.0.0.1', 8892), Handler) as server:
            print('Private Campbell canary tunnel on http://127.0.0.1:8892', flush=True)
            server.serve_forever()
    finally:
        client.close()


if __name__ == '__main__':
    main()
