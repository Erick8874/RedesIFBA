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
    rx_bps: float
    tx_bps: float
    rx_counter: int
    tx_counter: int