from dataclasses import dataclass


@dataclass(frozen=True)
class InterfaceInfo:
    index: int
    name: str
    address: str = ""

    @property
    def label(self) -> str:
        suffix = f" ({self.address})" if self.address else ""
        return f"{self.index} - {self.name}{suffix}"


@dataclass(frozen=True)
class Sample:
    timestamp: float
    cpu_percent: float
    rx_bytes_sec: float
    tx_bytes_sec: float
    rx_counter: int
    tx_counter: int