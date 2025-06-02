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
Signal calculators for NanoHFT strategy.

This module contains the core signal computation logic including:
- VAMP (Volume-Adjusted Mid Price)
- Edge calculation
- ATR (Average True Range) for volatility
"""

from typing import Optional
import numpy as np
from collections import deque

from nautilus_trader.model.data import QuoteTick, Bar
from nautilus_trader.model.book import OrderBook


class VAMPCalculator:
    """
    Volume-Adjusted Mid Price calculator.
    
    VAMP formula:
    p_t = (A_t × ΔB_t + B_t × ΔA_t) / (ΔB_t + ΔA_t + ε)
    
    Where:
    - A_t = Best ask price
    - B_t = Best bid price  
    - ΔA_t = Ask size
    - ΔB_t = Bid size
    - ε = 0.0001 (epsilon to prevent division by zero)
    """
    
    def __init__(self, epsilon: float = 0.0001):
        """Initialize VAMP calculator."""
        self.epsilon = epsilon
        self._value: Optional[float] = None
        self._ready = False
        
    def update_from_quote(self, quote: QuoteTick) -> None:
        """Update VAMP from quote tick."""
        ask_price = float(quote.ask_price)
        bid_price = float(quote.bid_price)
        ask_size = float(quote.ask_size)
        bid_size = float(quote.bid_size)
        
        self._value = (ask_price * bid_size + bid_price * ask_size) / (
            bid_size + ask_size + self.epsilon
        )
        self._ready = True
        
    def update_from_book(self, book: OrderBook) -> None:
        """Update VAMP from order book."""
        best_bid = book.best_bid_price()
        best_ask = book.best_ask_price()
        bid_size = book.best_bid_size()
        ask_size = book.best_ask_size()
        
        if not all([best_bid, best_ask, bid_size, ask_size]):
            self._ready = False
            return
            
        self._value = (float(best_ask) * float(bid_size) + float(best_bid) * float(ask_size)) / (
            float(bid_size) + float(ask_size) + self.epsilon
        )
        self._ready = True
        
    @property
    def value(self) -> Optional[float]:
        """Get current VAMP value."""
        return self._value
        
    @property
    def ready(self) -> bool:
        """Check if calculator has valid value."""
        return self._ready


class EdgeCalculator:
    """
    Edge calculator in basis points.
    
    Edge formula:
    e_t = 10^4 × (p_t - m_t) / m_t
    
    Where:
    - p_t = VAMP
    - m_t = Mid price
    """
    
    def __init__(self):
        """Initialize edge calculator."""
        self._value: Optional[float] = None
        self._ready = False
        
    def update(self, vamp: float, mid_price: float) -> None:
        """Update edge calculation."""
        if mid_price > 0:
            self._value = 10000 * (vamp - mid_price) / mid_price
            self._ready = True
        else:
            self._ready = False
            
    @property
    def value(self) -> Optional[float]:
        """Get current edge in basis points."""
        return self._value
        
    @property
    def ready(self) -> bool:
        """Check if calculator has valid value."""
        return self._ready


class ATRCalculator:
    """
    Simplified ATR calculator using quote ticks.
    
    Since we're working with quote ticks, we approximate ATR using
    the spread and price movements.
    """
    
    def __init__(self, period: int = 60):
        """Initialize ATR calculator."""
        self.period = period
        self._prices = deque(maxlen=period)
        self._spreads = deque(maxlen=period)
        self._value: Optional[float] = None
        self._ready = False
        
    def update(self, quote: QuoteTick) -> None:
        """Update ATR with new quote."""
        mid_price = (float(quote.ask_price) + float(quote.bid_price)) / 2
        spread = float(quote.ask_price) - float(quote.bid_price)
        
        self._prices.append(mid_price)
        self._spreads.append(spread)
        
        if len(self._prices) >= 2:
            # Calculate price changes
            price_changes = [abs(self._prices[i] - self._prices[i-1]) 
                            for i in range(1, len(self._prices))]
            
            # Combine spread and price volatility
            avg_spread = np.mean(self._spreads)
            avg_change = np.mean(price_changes) if price_changes else 0
            
            # ATR approximation
            self._value = max(avg_spread, avg_change)
            self._ready = len(self._prices) >= min(10, self.period)  # Need at least 10 samples
            
    @property
    def value(self) -> Optional[float]:
        """Get current ATR value."""
        return self._value
        
    @property
    def ready(self) -> bool:
        """Check if calculator has enough data."""
        return self._ready
        
    @property
    def value_bp(self) -> Optional[float]:
        """Get ATR in basis points relative to current price."""
        if self._value and self._prices:
            current_price = self._prices[-1]
            if current_price > 0:
                return 10000 * self._value / current_price
        return None