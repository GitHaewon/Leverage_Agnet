"""
Execution Engine — Signal → Risk Validation → Position Sizing → Order Execution.
"""
from agents.execution.engine import ExecutionEngine, build_emergency_close_ticket, build_entry_ticket, build_sl_ticket, build_tp_ticket
from agents.execution.gateway import PaperGateway
from agents.execution.models import (
    ExecutionRequest,
    ExecutionResult,
    FilledOrder,
    OrderGatewayProtocol,
    OrderTicket,
    RiskValidatorProtocol,
    SafetyDecision,
    SafetyGateProtocol,
)

__all__ = [
    "ExecutionEngine",
    "ExecutionRequest",
    "ExecutionResult",
    "FilledOrder",
    "OrderGatewayProtocol",
    "OrderTicket",
    "PaperGateway",
    "RiskValidatorProtocol",
    "SafetyDecision",
    "SafetyGateProtocol",
    "build_entry_ticket",
    "build_tp_ticket",
    "build_sl_ticket",
    "build_emergency_close_ticket",
]
