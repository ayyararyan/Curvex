from __future__ import annotations


def estimate_transaction_cost(turnover: float, fee_rate: float, tax_rate: float, brokerage: float, orders: int) -> float:
    return abs(turnover) * (fee_rate + tax_rate) + brokerage * orders


def estimate_round_trip_cost(notional: float, fee_rate: float, tax_rate: float, brokerage: float, orders: int) -> float:
    return abs(notional) * (fee_rate + tax_rate) + brokerage * orders
