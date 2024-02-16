from __future__ import annotations
import time
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import aiohttp.web_exceptions


class CircuitBreakerState(Enum):
    CLOSED = 'CLOSED'
    HALF_OPENED = 'HALF_OPENED'
    OPENED = 'OPENED'


@dataclass
class _CBGuard:
    cb: CircuitBreaker
    service_name: str

    def __enter__(self):
        state = self.cb.get_state(self.service_name)
        print(f'[CB/G] state of {self.service_name} is {state.name}')
        if state == CircuitBreakerState.OPENED:
            raise aiohttp.web_exceptions.HTTPInternalServerError(
                text=f'Service {self.service_name} temporarly unavailable')
        self.t = time.time()

    def __exit__(self, exc_type, exc_val, exc_tb):
        t = int(time.time() - self.t)
        successed = exc_val is None
        self.cb.observe(self.service_name, t, successed)


class CircuitBreaker:
    req_success: dict[str, list[bool]]
    req_times: dict[str, list[int]]
    store_limit: int = 100
    error_rate: int = 75
    time_threshold_sec: float = 3.2
    half_open_threshold_sec: int = 10
    closed_at_sec: dict[str, Optional[int]]

    def guard(self, service_name: str) -> _CBGuard:
        return _CBGuard(self, service_name)

    def __init__(self, store_limit=100, error_rate=75, time_threshold_sec=3.2, half_open_threshold_sec=10):
        self.req_success = defaultdict(list)
        self.req_times = defaultdict(list)
        self.closed_at_sec = defaultdict(lambda: None)
        self.store_limit = store_limit
        self.error_rate = error_rate
        self.time_threshold_sec = time_threshold_sec
        self.half_open_threshold_sec = half_open_threshold_sec

    def get_combo_state(self, service_names: list[str]) -> CircuitBreakerState:
        ret = CircuitBreakerState.CLOSED
        for name in service_names:
            state = self.get_state(name)
            if state == CircuitBreakerState.HALF_OPENED:
                ret = state
            elif state == CircuitBreakerState.OPENED:
                return state
        return ret

    def get_state(self, service_name: str) -> CircuitBreakerState:
        if self.closed_at_sec[service_name] is not None:
            if time.time() - self.closed_at_sec[service_name] >= self.half_open_threshold_sec:
                print('[CB] trying to close')
                self.closed_at_sec[service_name] = int((time.time() + self.closed_at_sec[service_name]) / 2)
                return CircuitBreakerState.HALF_OPENED
            else:
                return CircuitBreakerState.OPENED
        if len(self.req_success) >= self.store_limit:
            self.req_success[service_name] = self.req_success[service_name][-self.store_limit:]
            self.req_times[service_name] = self.req_times[service_name][-self.store_limit:]

        if (not self.check_req_time_closed(service_name)
                or not self.check_req_success_closed(service_name)):
            print(f'[CB] opening service {service_name}')
            self.closed_at_sec[service_name] = int(time.time())
            return CircuitBreakerState.OPENED
        return CircuitBreakerState.CLOSED

    def check_req_success_closed(self, service_name: str) -> bool:
        if len(self.req_success[service_name]) == 0:
            return True
        return (len(list(filter(lambda x: x, self.req_success[service_name]))) /
                len(self.req_success[service_name]) > self.error_rate / 100)

    def check_req_time_closed(self, service_name: str) -> bool:
        if len(self.req_times[service_name]) == 0:
            return True
        return sum(self.req_times[service_name]) / len(self.req_times[service_name]) < self.time_threshold_sec

    def observe(self, service_name: str, req_time_sec: int, was_success: bool):
        self.req_times[service_name].append(req_time_sec)
        self.req_success[service_name].append(was_success)


@dataclass
class ServiceError(Exception):
    service_name: str
