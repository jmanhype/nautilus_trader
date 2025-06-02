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
Cython-optimized signal calculators for NanoHFT.

This module provides high-performance implementations of the core signal
calculations to achieve sub-microsecond latency.
"""

# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: nonecheck=False
# cython: cdivision=True
# cython: profile=False

cimport cython
from libc.math cimport fabs


cdef class VAMPCalculatorFast:
    """
    Fast VAMP (Volume-Adjusted Mid Price) calculator.
    
    Optimized for minimal latency with pre-calculated constants.
    """
    
    cdef:
        double _epsilon
        double _value
        bint _ready
        
    def __init__(self, double epsilon=0.0001):
        self._epsilon = epsilon
        self._value = 0.0
        self._ready = False
        
    @cython.profile(False)
    @cython.boundscheck(False)
    cdef inline void update_c(self, double bid_price, double ask_price, 
                              double bid_size, double ask_size) nogil:
        """C-level update method for maximum performance."""
        cdef double total_size = bid_size + ask_size + self._epsilon
        self._value = (ask_price * bid_size + bid_price * ask_size) / total_size
        self._ready = True
        
    def update(self, double bid_price, double ask_price, 
               double bid_size, double ask_size):
        """Python-accessible update method."""
        self.update_c(bid_price, ask_price, bid_size, ask_size)
        
    @property
    def value(self) -> double:
        return self._value
        
    @property
    def ready(self) -> bint:
        return self._ready


cdef class EdgeCalculatorFast:
    """
    Fast edge calculator in basis points.
    
    Pre-calculates the basis point multiplier for performance.
    """
    
    cdef:
        double _bp_multiplier
        double _value
        bint _ready
        
    def __init__(self):
        self._bp_multiplier = 10000.0
        self._value = 0.0
        self._ready = False
        
    @cython.profile(False)
    @cython.boundscheck(False)
    cdef inline void update_c(self, double vamp, double mid_price) nogil:
        """C-level update method."""
        if mid_price > 0:
            self._value = self._bp_multiplier * (vamp - mid_price) / mid_price
            self._ready = True
        else:
            self._ready = False
            
    def update(self, double vamp, double mid_price):
        """Python-accessible update method."""
        self.update_c(vamp, mid_price)
        
    @property
    def value(self) -> double:
        return self._value
        
    @property
    def ready(self) -> bint:
        return self._ready


cdef class CombinedSignalCalculator:
    """
    Combined VAMP and Edge calculator for optimal performance.
    
    Calculates both signals in a single pass to minimize latency.
    """
    
    cdef:
        double _epsilon
        double _bp_multiplier
        double _vamp
        double _edge_bp
        bint _ready
        
    def __init__(self, double epsilon=0.0001):
        self._epsilon = epsilon
        self._bp_multiplier = 10000.0
        self._vamp = 0.0
        self._edge_bp = 0.0
        self._ready = False
        
    @cython.profile(False)
    @cython.boundscheck(False)
    cdef inline void update_c(self, double bid_price, double ask_price,
                              double bid_size, double ask_size) nogil:
        """
        Calculate VAMP and edge in single pass.
        
        This is the critical hot path for HFT performance.
        """
        cdef:
            double total_size = bid_size + ask_size + self._epsilon
            double mid_price = (bid_price + ask_price) * 0.5
            
        # Calculate VAMP
        self._vamp = (ask_price * bid_size + bid_price * ask_size) / total_size
        
        # Calculate edge in basis points
        if mid_price > 0:
            self._edge_bp = self._bp_multiplier * (self._vamp - mid_price) / mid_price
            self._ready = True
        else:
            self._ready = False
            
    def update(self, double bid_price, double ask_price,
               double bid_size, double ask_size):
        """Python-accessible update method."""
        self.update_c(bid_price, ask_price, bid_size, ask_size)
        
    @property
    def vamp(self) -> double:
        return self._vamp
        
    @property
    def edge_bp(self) -> double:
        return self._edge_bp
        
    @property
    def ready(self) -> bint:
        return self._ready
        
    cpdef bint should_trade(self, double threshold_bp):
        """Check if edge exceeds threshold (optimized)."""
        return self._ready and fabs(self._edge_bp) > threshold_bp


# Fast guard implementations

cdef class ATRGuardFast:
    """Fast ATR guard with inline checking."""
    
    cdef:
        double _threshold_bp
        bint _triggered
        
    def __init__(self, double threshold_bp=6.0):
        self._threshold_bp = threshold_bp
        self._triggered = False
        
    @cython.profile(False)
    cdef inline bint check_c(self, double atr_bp) nogil:
        """C-level check method."""
        self._triggered = atr_bp > self._threshold_bp
        return self._triggered
        
    def check(self, double atr_bp) -> bint:
        return self.check_c(atr_bp)


cdef class FastHotPath:
    """
    Complete hot path implementation in Cython.
    
    Combines all signal calculations and guard checks for maximum performance.
    """
    
    cdef:
        CombinedSignalCalculator _signals
        ATRGuardFast _atr_guard
        double _edge_threshold_bp
        
    def __init__(self, double edge_threshold_bp=2.0, double atr_threshold_bp=6.0):
        self._signals = CombinedSignalCalculator()
        self._atr_guard = ATRGuardFast(atr_threshold_bp)
        self._edge_threshold_bp = edge_threshold_bp
        
    @cython.profile(False)
    @cython.boundscheck(False)
    cdef inline bint process_quote_c(self, double bid_price, double ask_price,
                                     double bid_size, double ask_size,
                                     double atr_bp) nogil:
        """
        Process quote through entire hot path.
        
        Returns True if trade should be executed.
        """
        # Update signals
        self._signals.update_c(bid_price, ask_price, bid_size, ask_size)
        
        # Check if we should trade
        if not self._signals._ready:
            return False
            
        if fabs(self._signals._edge_bp) <= self._edge_threshold_bp:
            return False
            
        # Check guards
        if self._atr_guard.check_c(atr_bp):
            return False
            
        return True
        
    def process_quote(self, double bid_price, double ask_price,
                      double bid_size, double ask_size,
                      double atr_bp=0.0) -> bint:
        """Python-accessible method."""
        return self.process_quote_c(bid_price, ask_price, bid_size, ask_size, atr_bp)
        
    @property
    def vamp(self) -> double:
        return self._signals._vamp
        
    @property
    def edge_bp(self) -> double:
        return self._signals._edge_bp