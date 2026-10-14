"""Timestamp-driven One Euro filter, following Casiez et al. (2012)."""
import math


class ExponentialMovingAverage:
    def __init__(self, alpha=0.5):
        if not 0 < alpha <= 1:
            raise ValueError("alpha must be in (0, 1]")
        self.alpha = alpha
        self.value = None

    def reset(self):
        self.value = None

    def __call__(self, value, alpha=None):
        a = self.alpha if alpha is None else alpha
        if not math.isfinite(value) or not 0 < a <= 1:
            raise ValueError("finite value and alpha in (0, 1] required")
        self.value = value if self.value is None else a * value + (1 - a) * self.value
        return self.value


class OneEuroFilter:
    def __init__(self, min_cutoff=1.5, beta=0.08, derivative_cutoff=1.0):
        if not all(math.isfinite(x) for x in (min_cutoff, beta, derivative_cutoff)):
            raise ValueError("filter parameters must be finite")
        if min_cutoff <= 0 or derivative_cutoff <= 0 or beta < 0:
            raise ValueError("cutoffs must be positive; beta must be nonnegative")
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.derivative_cutoff = derivative_cutoff
        self.signal = ExponentialMovingAverage()
        self.derivative = ExponentialMovingAverage()
        self.timestamp = None
        self.raw = None

    @staticmethod
    def alpha(cutoff, dt):
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return dt / (dt + tau)

    def reset(self):
        self.signal.reset()
        self.derivative.reset()
        self.timestamp = self.raw = None

    def __call__(self, value, timestamp):
        if not math.isfinite(value) or not math.isfinite(timestamp):
            raise ValueError("non-finite filter input")
        if self.timestamp is None:
            self.timestamp, self.raw = timestamp, value
            self.derivative(0.0)
            return self.signal(value)
        dt = timestamp - self.timestamp
        if dt <= 0:
            raise ValueError("timestamps must increase strictly")
        speed = self.derivative((value - self.raw) / dt,
                                self.alpha(self.derivative_cutoff, dt))
        cutoff = self.min_cutoff + self.beta * abs(speed)
        self.timestamp, self.raw = timestamp, value
        return self.signal(value, self.alpha(cutoff, dt))
