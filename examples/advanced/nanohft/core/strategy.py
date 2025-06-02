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
NanoHFT Strategy - Modular implementation.

This is the main strategy class that orchestrates signal calculators and risk guards
to implement the Queue-First HFT strategy in a clean, modular fashion.
"""

from typing import Optional, Dict, Any
import datetime
import pandas as pd

from nautilus_trader.core.data import Data
from nautilus_trader.model.data import QuoteTick, OrderBookDeltas
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.events import OrderFilled, PositionChanged
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.trading.strategy import Strategy

from .signals import VAMPCalculator, EdgeCalculator, ATRCalculator
from .risk_guards import ATRGuard, CancelClusterGuard, DataStalenessGuard, QueueRankGuard


class NanoHFTStrategy(Strategy):
    """
    NanoHFT Strategy - Modular Queue-First HFT implementation.
    
    This strategy demonstrates clean separation of concerns:
    - Signal calculation (VAMP, Edge, ATR)
    - Risk management (Guards)
    - Execution logic
    """
    
    def __init__(self, config: Dict[str, Any]) -> None:
        """
        Initialize strategy with configuration dictionary.
        
        Parameters
        ----------
        config : Dict[str, Any]
            Configuration loaded from JSON
        """
        super().__init__()
        
        # Store configuration
        self.config = config
        self.instrument_id = InstrumentId.from_str(config["instrument_id"])
        
        # Initialize signal calculators
        self.vamp_calc = VAMPCalculator()
        self.edge_calc = EdgeCalculator()
        self.atr_calc = ATRCalculator(period=config["atr_period"])
        
        # Initialize risk guards
        self.atr_guard = ATRGuard(threshold_bp=config["atr_gate_bp"])
        self.cancel_guard = CancelClusterGuard(
            count_threshold=config["cancel_cluster_count"],
            window_ms=config["cancel_cluster_window_ms"]
        )
        self.staleness_guard = DataStalenessGuard(
            threshold_us=config["staleness_threshold_us"]
        )
        self.queue_guard = QueueRankGuard(
            threshold=config["queue_rank_threshold"]
        )
        
        # Parse maker windows
        self.maker_windows = self._parse_maker_windows()
        
        # State tracking
        self.instrument: Optional[Instrument] = None
        self.initial_equity: float = 0.0
        self.opportunity_count: int = 0
        self.trade_count: int = 0
        
    def _parse_maker_windows(self) -> list[tuple[datetime.time, datetime.time]]:
        """Parse maker time windows from config."""
        windows = []
        
        # Window 1
        start1 = datetime.datetime.strptime(self.config["maker_start_utc"], "%H:%M").time()
        end1 = datetime.datetime.strptime(self.config["maker_end_utc"], "%H:%M").time()
        windows.append((start1, end1))
        
        # Window 2
        start2 = datetime.datetime.strptime(self.config["maker2_start_utc"], "%H:%M").time()
        end2 = datetime.datetime.strptime(self.config["maker2_end_utc"], "%H:%M").time()
        windows.append((start2, end2))
        
        return windows
        
    def on_start(self) -> None:
        """Actions to be performed on strategy start."""
        # Get instrument
        self.instrument = self.cache.instrument(self.instrument_id)
        if self.instrument is None:
            self.log.error(f"Could not find instrument for {self.instrument_id}")
            self.stop()
            return
            
        # Subscribe to market data
        self.subscribe_quote_ticks(instrument_id=self.instrument_id)
        
        # Record initial equity
        account = self.portfolio.account(self.instrument.venue)
        if account:
            self.initial_equity = float(account.balance_total(account.base_currency))
            
        self.log.info(f"NanoHFT Strategy started with initial equity: {self.initial_equity}")
        
    def on_stop(self) -> None:
        """Actions to be performed on strategy stop."""
        # Cancel all pending orders
        self.cancel_all_orders(self.instrument_id)
        
        # Log final statistics
        self.log.info(
            f"NanoHFT Strategy stopped - "
            f"Opportunities: {self.opportunity_count}, "
            f"Trades: {self.trade_count}, "
            f"Hit Rate: {self.trade_count/max(self.opportunity_count, 1)*100:.1f}%"
        )
        
    def on_quote_tick(self, tick: QuoteTick) -> None:
        """
        Handle quote tick updates.
        
        This is the main entry point for market data processing.
        """
        # Update signal calculators
        self.vamp_calc.update_from_quote(tick)
        self.atr_calc.update(tick)
        
        # Update staleness guard
        self.staleness_guard.update(tick.ts_event)
        
        # Calculate edge if VAMP is ready
        if self.vamp_calc.ready:
            mid_price = (float(tick.ask_price) + float(tick.bid_price)) / 2
            self.edge_calc.update(self.vamp_calc.value, mid_price)
            
        # Process trading logic
        self._process_trading_logic(tick)
        
    def _process_trading_logic(self, tick: QuoteTick) -> None:
        """Main trading logic processing."""
        self.opportunity_count += 1
        
        # Check data staleness
        current_ns = self.clock.timestamp_ns()
        should_pull, spread_mult = self.staleness_guard.check(current_ns)
        
        if should_pull:
            self.log.warning(f"Data staleness detected: {self.staleness_guard.staleness_us:.1f}μs")
            self._pull_all_quotes()
            return
            
        # Check ATR gate
        if self.atr_calc.ready and self.atr_guard.check(self.atr_calc.value_bp):
            self.log.info(f"ATR gate triggered: {self.atr_calc.value_bp:.2f}bp")
            self._pull_all_quotes()
            return
            
        # Check cancel cluster
        if self.cancel_guard.check(current_ns):
            self.log.warning("Cancel cluster detected, entering cooldown")
            return
            
        # Check if edge meets threshold
        if not self.edge_calc.ready:
            return
            
        edge_bp = self.edge_calc.value
        if abs(edge_bp) < self.config["edge_threshold_bp"]:
            return
            
        # Determine execution mode
        if self._is_maker_window():
            self._execute_maker_logic(tick, edge_bp, spread_mult)
        else:
            self._execute_taker_logic(tick, edge_bp)
            
    def _is_maker_window(self) -> bool:
        """Check if current time is within maker windows."""
        current_time = pd.Timestamp.now(tz="UTC").time()
        
        for start, end in self.maker_windows:
            if start <= current_time < end:
                return True
                
        return False
        
    def _execute_maker_logic(self, tick: QuoteTick, edge_bp: float, spread_mult: float) -> None:
        """Execute maker (limit order) strategy."""
        if self.config["dry_run"]:
            self.log.info(f"[DRY RUN] Maker signal: edge={edge_bp:.2f}bp")
            return
            
        # Determine side based on edge
        side = OrderSide.BUY if edge_bp > 0 else OrderSide.SELL
        
        # Calculate order price with spread adjustment
        mid_price = (float(tick.ask_price) + float(tick.bid_price)) / 2
        spread_bp = self.config["maker_spread_bp"] * spread_mult
        
        if side == OrderSide.BUY:
            price_mult = 1 - (spread_bp / 10000)
        else:
            price_mult = 1 + (spread_bp / 10000)
            
        order_price = self.instrument.make_price(mid_price * price_mult)
        
        # Calculate position size
        quantity = self._calculate_position_size(edge_bp)
        if quantity == Quantity.zero():
            return
            
        # Submit order
        order = self.order_factory.limit(
            instrument_id=self.instrument_id,
            order_side=side,
            price=order_price,
            quantity=quantity,
            time_in_force=TimeInForce.GTC,
            post_only=True,
        )
        
        self.submit_order(order)
        self.trade_count += 1
        
    def _execute_taker_logic(self, tick: QuoteTick, edge_bp: float) -> None:
        """Execute taker (market order) strategy."""
        # Check if edge meets arbitrage threshold
        if abs(edge_bp) < self.config["arb_threshold_bp"]:
            return
            
        if self.config["dry_run"]:
            self.log.info(f"[DRY RUN] Taker signal: edge={edge_bp:.2f}bp")
            return
            
        # Determine side based on edge
        side = OrderSide.BUY if edge_bp > 0 else OrderSide.SELL
        
        # Calculate position size
        quantity = self._calculate_position_size(edge_bp)
        if quantity == Quantity.zero():
            return
            
        # Submit market order
        order = self.order_factory.market(
            instrument_id=self.instrument_id,
            order_side=side,
            quantity=quantity,
            time_in_force=TimeInForce.IOC,
        )
        
        self.submit_order(order)
        self.trade_count += 1
        
    def _calculate_position_size(self, edge_bp: float) -> Quantity:
        """
        Calculate position size using Kelly criterion.
        
        N_t = Q_0 × (Equity_t / Equity_0) × f_Kelly × L(t)
        """
        if not self.instrument:
            return Quantity.zero()
            
        # Get current equity
        account = self.portfolio.account(self.instrument.venue)
        if not account:
            return Quantity.zero()
            
        current_equity = float(account.balance_total(account.base_currency))
        equity_ratio = current_equity / self.initial_equity if self.initial_equity > 0 else 1.0
        
        # Kelly fraction (simplified)
        kelly_fraction = min(abs(edge_bp) / 10.0, 1.0)
        
        # Determine leverage
        leverage = self.config["maker_leverage"] if self._is_maker_window() else self.config["core_leverage"]
        
        # Calculate notional
        notional = self.config["base_notional"] * equity_ratio * kelly_fraction * leverage
        
        # Convert to quantity
        mid_price = self.cache.quote_tick(self.instrument_id)
        if mid_price:
            price = (float(mid_price.ask_price) + float(mid_price.bid_price)) / 2
            quantity = notional / price
            return self.instrument.make_qty(quantity)
            
        return Quantity.zero()
        
    def _pull_all_quotes(self) -> None:
        """Cancel all resting orders."""
        self.cancel_all_orders(self.instrument_id)
        self.cancel_guard.record_cancel(self.clock.timestamp_ns())
        
    def on_order_filled(self, event: OrderFilled) -> None:
        """Handle order fill events."""
        self.log.info(
            f"Order filled: {event.order_side} {event.last_qty} @ {event.avg_px}"
        )
        
    def on_event(self, event: Data) -> None:
        """Handle generic events."""
        if isinstance(event, PositionChanged):
            # Monitor position changes
            pass