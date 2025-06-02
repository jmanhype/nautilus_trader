# -------------------------------------------------------------------------------------------------
#  Copyright (C) 2015-2025 Nautech Systems Pty Ltd. All rights reserved.
#  https://nautechsystems.io
#
#  Licensed under the GNU Lesser General Public License Version 3.0 (the "License");
#  You may not use this file except in compliance with the License.
#  You may obtain a copy of the License at https://www.gnu.org/licenses/lgpl-3.0.en.html
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
# -------------------------------------------------------------------------------------------------

"""
Risk guard components for NanoHFT strategy.

This module contains risk management "poka-yokes" (mistake-proofing mechanisms):
- ATR Gate: Halts trading during high volatility
- Cancel Cluster Guard: Detects rapid order cancellations
- Data Staleness Guard: Ensures data freshness
- Queue Rank Guard: Monitors queue position (simplified)
"""

from typing import Optional, List
from collections import deque
import time


class ATRGuard:
    """
    ATR-based volatility gate.
    
    Halts trading when ATR exceeds threshold to avoid adverse selection
    during volatile periods.
    """
    
    def __init__(self, threshold_bp: float = 6.0):
        """
        Initialize ATR guard.
        
        Parameters
        ----------
        threshold_bp : float
            ATR threshold in basis points
        """
        self.threshold_bp = threshold_bp
        self._triggered = False
        self._last_atr_bp: Optional[float] = None
        
    def check(self, atr_bp: Optional[float]) -> bool:
        """
        Check if trading should be halted.
        
        Parameters
        ----------
        atr_bp : Optional[float]
            Current ATR in basis points
            
        Returns
        -------
        bool
            True if trading should be halted
        """
        if atr_bp is None:
            return False
            
        self._last_atr_bp = atr_bp
        self._triggered = atr_bp > self.threshold_bp
        return self._triggered
        
    @property
    def triggered(self) -> bool:
        """Check if guard is currently triggered."""
        return self._triggered
        
    @property
    def last_atr_bp(self) -> Optional[float]:
        """Get last ATR value in basis points."""
        return self._last_atr_bp


class CancelClusterGuard:
    """
    Cancel cluster detection guard.
    
    Detects when too many order cancellations occur in a short time window,
    which may indicate adverse market conditions or technical issues.
    """
    
    def __init__(self, count_threshold: int = 5, window_ms: int = 50):
        """
        Initialize cancel cluster guard.
        
        Parameters
        ----------
        count_threshold : int
            Number of cancels to trigger guard
        window_ms : int
            Time window in milliseconds
        """
        self.count_threshold = count_threshold
        self.window_ns = window_ms * 1_000_000  # Convert to nanoseconds
        self._cancel_times: deque = deque()
        self._triggered = False
        self._cooldown_until_ns: int = 0
        
    def record_cancel(self, timestamp_ns: int) -> None:
        """Record a cancel event."""
        self._cancel_times.append(timestamp_ns)
        
    def check(self, current_ns: int) -> bool:
        """
        Check if cancel cluster detected.
        
        Parameters
        ----------
        current_ns : int
            Current timestamp in nanoseconds
            
        Returns
        -------
        bool
            True if cluster detected and in cooldown
        """
        # Remove old cancel times outside window
        while self._cancel_times and current_ns - self._cancel_times[0] > self.window_ns:
            self._cancel_times.popleft()
            
        # Check if in cooldown
        if current_ns < self._cooldown_until_ns:
            return True
            
        # Check if cluster detected
        if len(self._cancel_times) >= self.count_threshold:
            self._triggered = True
            self._cooldown_until_ns = current_ns + 100_000_000  # 100ms cooldown
            return True
            
        self._triggered = False
        return False
        
    @property
    def triggered(self) -> bool:
        """Check if guard is currently triggered."""
        return self._triggered
        
    @property
    def cancel_count(self) -> int:
        """Get current cancel count in window."""
        return len(self._cancel_times)


class DataStalenessGuard:
    """
    Data staleness detection guard.
    
    Implements graduated response based on data age:
    - 5-30μs: Double spread width
    - >30μs: Pull all quotes
    """
    
    def __init__(self, threshold_us: int = 30):
        """
        Initialize staleness guard.
        
        Parameters
        ----------
        threshold_us : int
            Maximum staleness threshold in microseconds
        """
        self.threshold_us = threshold_us
        self.warning_threshold_us = 5  # Warning level
        self._last_update_ns: Optional[int] = None
        self._staleness_us: float = 0.0
        
    def update(self, timestamp_ns: int) -> None:
        """Update with latest data timestamp."""
        self._last_update_ns = timestamp_ns
        
    def check(self, current_ns: int) -> tuple[bool, float]:
        """
        Check data staleness.
        
        Parameters
        ----------
        current_ns : int
            Current timestamp in nanoseconds
            
        Returns
        -------
        tuple[bool, float]
            (should_pull_quotes, spread_multiplier)
        """
        if self._last_update_ns is None:
            return False, 1.0
            
        self._staleness_us = (current_ns - self._last_update_ns) / 1000
        
        if self._staleness_us > self.threshold_us:
            # Critical staleness - pull all quotes
            return True, 1.0
        elif self._staleness_us > self.warning_threshold_us:
            # Warning level - double spread
            return False, 2.0
        else:
            # Fresh data
            return False, 1.0
            
    @property
    def staleness_us(self) -> float:
        """Get current staleness in microseconds."""
        return self._staleness_us
        
    @property
    def is_stale(self) -> bool:
        """Check if data exceeds staleness threshold."""
        return self._staleness_us > self.threshold_us


class QueueRankGuard:
    """
    Simplified queue rank guard.
    
    In production, this would track actual order acknowledgments and
    estimate queue position. This simplified version uses conservative
    assumptions.
    """
    
    def __init__(self, threshold: float = 0.35):
        """
        Initialize queue rank guard.
        
        Parameters
        ----------
        threshold : float
            Maximum acceptable queue rank (0.0-1.0)
        """
        self.threshold = threshold
        self._last_rank: float = 0.0
        
    def estimate_rank(self, our_size: float, level_size: float) -> float:
        """
        Estimate queue rank (simplified).
        
        Parameters
        ----------
        our_size : float
            Our order size
        level_size : float
            Total size at price level
            
        Returns
        -------
        float
            Estimated rank (0.0 = front, 1.0 = back)
        """
        if level_size <= 0:
            return 0.0
            
        # Conservative: assume we're at the back
        self._last_rank = min(1.0, our_size / level_size)
        return self._last_rank
        
    def should_cancel(self, rank: float) -> bool:
        """
        Check if order should be cancelled based on rank.
        
        Parameters
        ----------
        rank : float
            Current queue rank estimate
            
        Returns
        -------
        bool
            True if order should be cancelled
        """
        return rank > self.threshold
        
    @property
    def last_rank(self) -> float:
        """Get last calculated rank."""
        return self._last_rank