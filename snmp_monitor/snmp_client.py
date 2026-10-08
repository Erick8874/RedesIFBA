from __future__ import annotations

import asyncio
import ipaddress
import socket
import time

from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    get_cmd,
    walk_cmd,
)

from snmp_monitor.models import InterfaceInfo, Sample


IF_NAME = "1.3.6.1.2.1.31.1.1.1.1"
IF_DESCR = "1.3.6.1.2.1.2.2.1.2"
IF_HIGH_IN = "1.3.6.1.2.1.31.1.1.1.6"
IF_HIGH_OUT = "1.3.6.1.2.1.31.1.1.1.10"
IF_IN = "1.3.6.1.2.1.2.2.1.10"
IF_OUT = "1.3.6.1.2.1.2.2.1.16"
IP_ADDR = "1.3.6.1.2.1.4.20.1.1"
IP_IF_INDEX = "1.3.6.1.2.1.4.20.1.2"
IP_NETMASK = "1.3.6.1.2.1.4.20.1.3"
HR_CPU_LOAD = "1.3.6.1.2.1.25.3.3.1.2"


def calculate_rate(current: int, previous: int, elapsed: float) -> float:
    if elapsed <= 0:
        return 0.0
    delta = current - previous
    if delta < 0:
        modulus = 2**64 if previous > 2**32 else 2**32
        delta = current + modulus - previous
    return max(0.0, delta / elapsed)


class SnmpClient:
    def __init__(self, host: str, community: str, port: int = 161) -> None:
        self.host = host
        self.community = community
        self.port = port
        self.engine = SnmpEngine()
        self.auth = CommunityData(community, mpModel=1)

    async def _target(self) -> UdpTransportTarget:
        return await UdpTransportTarget.create(
            (self.host, self.port), timeout=2, retries=1
        )

    async def _walk(self, oid: str) -> list[tuple[str, str]]:
        result: list[tuple[str, str]] = []
        async for indication, status, _, var_binds in walk_cmd(
            self.engine,
            self.auth,
            await self._target(),
            ContextData(),
            ObjectType(ObjectIdentity(oid)),
            lexicographicMode=False,
        ):
            if indication:
                raise RuntimeError(str(indication))
            if status:
                raise RuntimeError(f"SNMP: {status.prettyPrint()}")
            result.extend((name.prettyPrint(), value.prettyPrint()) for name, value in var_binds)
        return result

    async def _get_integer(self, oid: str) -> int:
        indication, status, _, var_binds = await get_cmd(
            self.engine,
            self.auth,
            await self._target(),
            ContextData(),
            ObjectType(ObjectIdentity(oid)),
        )
        if indication:
            raise RuntimeError(str(indication))
        if status:
            raise RuntimeError(f"SNMP: {status.prettyPrint()}")
        value = var_binds[0][1]
        rendered = value.prettyPrint()
        if rendered.startswith("No Such"):
            raise RuntimeError(f"O roteador não forneceu o OID {oid}.")
        return int(value)

    async def discover_interfaces(self) -> tuple[list[InterfaceInfo], int | None]:
        try:
            names = await self._walk(IF_NAME)
        except RuntimeError:
            names = await self._walk(IF_DESCR)
        if not names or all(value.startswith("No Such") for _, value in names):
            names = await self._walk(IF_DESCR)
        addresses = await self._walk(IP_ADDR)
        indices = dict(await self._walk(IP_IF_INDEX))
        masks = dict(await self._walk(IP_NETMASK))
        descriptions = {int(oid.rsplit(".", 1)[1]): value for oid, value in names}
        local_ip = self._local_address()
        entries: list[InterfaceInfo] = []
        preferred: int | None = None
        for address_oid, address in addresses:
            index = int(indices.get(address_oid, "0"))
            if not index:
                continue
            name = descriptions.get(index, f"Interface {index}")
            if not any(item.index == index for item in entries):
                entries.append(InterfaceInfo(index, name, address))
            mask = masks.get(address_oid)
            if local_ip and mask:
                try:
                    network = ipaddress.ip_network(f"{address}/{mask}", strict=False)
                    if ipaddress.ip_address(local_ip) in network:
                        preferred = index
                except ValueError:
                    pass
        if not entries:
            entries = [
                InterfaceInfo(int(oid.rsplit(".", 1)[1]), name)
                for oid, name in names
            ]
        return sorted(entries, key=lambda item: item.index), preferred

    def _local_address(self) -> str | None:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
                connection.connect((self.host, self.port))
                return connection.getsockname()[0]
        except OSError:
            return None

    async def sample(
        self,
        interface_index: int,
        cpu_oid: str,
        previous: Sample | None,
    ) -> Sample:
        cpu_values = await self._walk(cpu_oid)
        if not cpu_values:
            raise RuntimeError(
                "Sem dados de CPU. Configure um OID de CPU compatível com o roteador."
            )
        cpu_loads = [float(value) for _, value in cpu_values]
        cpu_percent = sum(cpu_loads) / len(cpu_loads)
        suffix = f".{interface_index}"
        try:
            rx_counter = await self._get_integer(f"{IF_HIGH_IN}{suffix}")
            tx_counter = await self._get_integer(f"{IF_HIGH_OUT}{suffix}")
        except RuntimeError:
            rx_counter = await self._get_integer(f"{IF_IN}{suffix}")
            tx_counter = await self._get_integer(f"{IF_OUT}{suffix}")

        timestamp = time.time()
        elapsed = timestamp - previous.timestamp if previous else 0.0
        return Sample(
            timestamp,
            cpu_percent,
            calculate_rate(rx_counter, previous.rx_counter, elapsed) if previous else 0.0,
            calculate_rate(tx_counter, previous.tx_counter, elapsed) if previous else 0.0,
            rx_counter,
            tx_counter,
        )

    def close(self) -> None:
        self.engine.close_dispatcher()


def run_async(coroutine):
    return asyncio.run(coroutine)