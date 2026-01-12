from dataclasses import dataclass

@dataclass
class Epoch:
    active: bool
    start: float
    end: float
