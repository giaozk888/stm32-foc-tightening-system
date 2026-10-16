"""PC/Linux daemon with TCP, UART and USB-serial adapters; no device reset."""
from __future__ import annotations
import argparse
import asyncio
import contextlib
import ipaddress
import json
import time
from functools import partial
from .core import Router
from .wire import Decoder, Frame, DIAGNOSTIC, message
from . import rpc


async def blocking(function, *args):
    """Python 3.8-compatible bounded serial I/O, without asyncio.to_thread."""
    return await asyncio.get_running_loop().run_in_executor(None, partial(function, *args))


class Node:
    def __init__(self, node: int):
        self.router = Router(node)
        self.router.on_response = self._response
        self.router.on_rpc = self._rpc_response
        self.tasks: set[asyncio.Task] = set()
        self.server = None
        self.connections = {}
        self.pending = {}
        self.rpc_pending = {}
        self.next_rpc_call = 1
        self.next_nonce = 1
        self.next_port = 0
        self.closed = False
        self.serial_ports = []

    def _spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def start(self):
        self._spawn(self._maintenance())

    async def _maintenance(self):
        while not self.closed:
            self.router.maintenance()
            await asyncio.sleep(.1)

    async def listen(self, host="127.0.0.1", port=0):
        self.server = await asyncio.start_server(self._accepted, host, port)
        return self.server.sockets[0].getsockname()[1]

    async def _accepted(self, reader, writer):
        await self._attach(reader, writer)

    async def connect(self, host, port):
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), 3)
        return await self._attach(reader, writer)

    async def connect_forever(self, host, port):
        delay = 1
        while not self.closed:
            try:
                name = await self.connect(host, port)
                delay = 1
                while name in self.connections and not self.closed:
                    await asyncio.sleep(.2)
            except (OSError, asyncio.TimeoutError):
                pass
            await asyncio.sleep(delay)
            delay = min(30, delay * 2)

    async def _attach(self, reader, writer):
        if self.closed or len(self.router.ports) >= 8:
            writer.close()
            await writer.wait_closed()
            return None
        self.next_port += 1
        name = f"tcp:{self.next_port}"
        queue = asyncio.Queue(maxsize=32)
        self.connections[name] = writer

        def send(frame):
            if writer.is_closing():
                return False
            try:
                queue.put_nowait(frame.encode())
                return True
            except asyncio.QueueFull:
                writer.close()  # A slow peer cannot accumulate unbounded frames.
                return False

        self.router.add_port(name, send)
        self._spawn(self._reader(name, reader, writer))
        self._spawn(self._writer(name, queue, writer))
        self.router.send(65535, 3, "HELLO")
        return name

    async def _reader(self, name, reader, writer):
        decoder = Decoder()
        window, count, byte_count = time.monotonic(), 0, 0
        try:
            while not self.closed and not writer.is_closing():
                data = await asyncio.wait_for(reader.read(512), 16)
                if not data:
                    break
                if time.monotonic() - window >= 1:
                    window, count, byte_count = time.monotonic(), 0, 0
                frames = decoder.feed(data)
                # Count rejected lines too, so malformed traffic cannot bypass limits.
                count += len(frames) + decoder.rejected
                byte_count += len(data)
                self.router.stats["parse_error"] += decoder.rejected
                decoder.rejected = 0
                if count > 60 or byte_count > 8192:
                    self.router.stats["rate_limit"] += 1
                    break
                for frame in frames:
                    self.router.receive(name, frame)
        except (OSError, asyncio.TimeoutError):
            pass
        finally:
            self.router.remove_port(name)
            self.connections.pop(name, None)
            writer.close()

    async def _writer(self, name, queue, writer):
        try:
            while name in self.connections and not self.closed:
                try:
                    data = await asyncio.wait_for(queue.get(), .5)
                except asyncio.TimeoutError:
                    continue
                writer.write(data)
                await asyncio.wait_for(writer.drain(), 1)
        except (OSError, asyncio.TimeoutError):
            writer.close()
        finally:
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()

    async def attach_serial(self, device, baud=115200, usb=False):
        # Opening real USB adapters can cause electrical line transitions on some
        # drivers. This is not a guarantee against a board-specific auto-reset.
        import serial
        port = serial.Serial(port=None, baudrate=baud, timeout=.1, write_timeout=1)
        port.dtr = False
        port.rts = False
        port.port = device
        port.open()
        name = ("usb-serial:" if usb else "uart:") + device
        queue = asyncio.Queue(maxsize=32)

        def send(frame):
            try:
                queue.put_nowait(frame.encode())
                return True
            except asyncio.QueueFull:
                self.router.stats["serial_queue_full"] += 1
                return False

        try:
            self.router.add_port(name, send)
        except ValueError:
            port.close()
            raise
        self.serial_ports.append(port)

        async def reader():
            decoder = Decoder()
            try:
                while not self.closed:
                    data = await blocking(port.read, 512)
                    for frame in decoder.feed(data):
                        self.router.receive(name, frame)
                    self.router.stats["serial_parse_error"] += decoder.rejected
                    decoder.rejected = 0
            except (OSError, serial.SerialException):
                pass
            finally:
                self.router.remove_port(name)
                port.close()

        async def writer():
            try:
                while name in self.router.ports and not self.closed:
                    try:
                        data = await asyncio.wait_for(queue.get(), .5)
                    except asyncio.TimeoutError:
                        continue
                    sent = await blocking(port.write, data)
                    if sent != len(data):
                        raise serial.SerialException("short Router write")
            except (OSError, serial.SerialException):
                self.router.remove_port(name)
                port.close()

        self._spawn(reader())
        self._spawn(writer())
        self.router.send(65535, 3, "HELLO")

    def _response(self, frame):
        kind, values = message(frame.payload)
        future = self.pending.get((frame.src, values[0], kind))
        if future and not future.done():
            future.set_result(frame)
        else:
            self.router.stats["unsolicited"] += 1

    async def request(self, destination, status=False, timeout=3):
        if len(self.pending) >= 16:
            raise RuntimeError("sixteen in-flight requests maximum")
        kind = "INFO" if status else "PONG"
        nonce = self.next_nonce
        self.next_nonce = self.next_nonce % 65535 + 1
        key = destination, nonce, kind
        future = asyncio.get_running_loop().create_future()
        self.pending[key] = future
        try:
            if not self.router.send(destination, DIAGNOSTIC,
                                    f"{'STATUS' if status else 'PING'} {nonce}"):
                raise ConnectionError(f"no route/transport for node {destination}")
            return await asyncio.wait_for(future, timeout)
        finally:
            self.pending.pop(key, None)

    def _rpc_response(self, frame):
        packet = rpc.decode(frame.payload)
        future = self.rpc_pending.get((frame.src, packet.method, packet.call))
        if packet.type in (1, 5) and future and not future.done():
            future.set_result(packet)
        else:
            self.router.stats["unsolicited_rpc"] += 1

    async def rpc_request(self, method, payload=b"", timeout=5):
        if len(self.rpc_pending) >= 8:
            raise RuntimeError("eight in-flight RPC requests maximum")
        if method not in rpc.METHODS:
            raise ValueError("read-only RPC method only")
        call = self.next_rpc_call
        self.next_rpc_call = call % 0xFFFFFFFF + 1
        key = 1, rpc.METHODS[method], call
        if key in self.rpc_pending:
            raise RuntimeError("RPC call ID still in use")
        text = rpc.request(self.router.node, method, call, payload)
        future = asyncio.get_running_loop().create_future()
        self.rpc_pending[key] = future
        try:
            if not self.router.send(1, rpc.TYPE, text):
                raise ConnectionError("no route/transport to STM32 node 1")
            result = await asyncio.wait_for(future, timeout)
            if result.status:
                raise RuntimeError("RPC returned status " + str(result.status))
            return result.payload
        finally:
            self.rpc_pending.pop(key, None)

    async def wait_route(self, destination, timeout=8):
        deadline = asyncio.get_running_loop().time() + timeout
        while destination not in self.router.routes:
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError(f"node {destination} not discovered")
            await asyncio.sleep(.02)

    async def close(self):
        self.closed = True
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        for writer in tuple(self.connections.values()):
            writer.close()
        for port in self.serial_ports:
            port.close()
        for task in tuple(self.tasks):
            task.cancel()
        await asyncio.gather(*tuple(self.tasks), return_exceptions=True)
        for future in list(self.pending.values()) + list(self.rpc_pending.values()):
            if not future.done():
                future.cancel()
        self.connections.clear()


def endpoint(value):
    host, port = value.rsplit(":", 1)
    address = ipaddress.ip_address(host)  # Explicit IPv4, no remote DNS surprise.
    if address.version != 4 or not 1 <= int(port) <= 65535:
        raise argparse.ArgumentTypeError("use IPv4:port")
    return host, int(port)


async def run(args):
    node = Node(args.node)
    await node.start()
    try:
        if args.listen:
            host, port = args.listen
            address = ipaddress.ip_address(host)
            if not address.is_loopback and (not args.allow_lan or
                    not address.is_private or address.is_unspecified):
                raise ValueError("bind a specific private LAN IP with --allow-lan; no public listener")
            await node.listen(host, port)
        for host, port in args.connect:
            node._spawn(node.connect_forever(host, port))
        for device in args.uart:
            await node.attach_serial(device, args.baud)
        for device in args.usb_serial:
            await node.attach_serial(device, args.baud, usb=True)
        print(f"Router node={args.node}; READ_ONLY; no firmware or motor commands", flush=True)
        if args.ping or args.status:
            for destination, status in [(n, False) for n in args.ping] + [(n, True) for n in args.status]:
                await node.wait_route(destination)
                reply = await node.request(destination, status)
                print(json.dumps({"source": reply.src, "reply": reply.payload}), flush=True)
        else:
            await asyncio.Event().wait()
    finally:
        await node.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", type=int, required=True)
    parser.add_argument("--listen", type=endpoint)
    parser.add_argument("--connect", type=endpoint, action="append", default=[])
    parser.add_argument("--uart", action="append", default=[])
    parser.add_argument("--usb-serial", action="append", default=[])
    parser.add_argument("--baud", type=int, choices=[115200, 2000000], default=115200)
    parser.add_argument("--allow-lan", action="store_true")
    parser.add_argument("--ping", type=int, action="append", default=[])
    parser.add_argument("--status", type=int, action="append", default=[])
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass
    except (ValueError, ConnectionError, TimeoutError) as error:
        parser.exit(2, f"Router error: {error}\n")


if __name__ == "__main__":
    main()
