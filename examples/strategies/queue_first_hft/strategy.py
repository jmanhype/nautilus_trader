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
Queue-First HFT Strategy

A high-frequency trading strategy that prioritizes queue position through ultra-low latency
and implements multiple risk controls (poka-yokes) to maintain stable profits.

Key features:
- VAMP (Volume-Adjusted Mid Price) for micro-edge detection
- Queue rank estimation and cancellation logic
- ATR-based volatility gating
- Cancel cluster detection
- Kelly criterion position sizing
- Maker/taker execution modes based on time windows
"""

from decimal import Decimal
from typing import Optional
import datetime
import pandas as pd
import numpy as np

from nautilus_trader.config import PositiveFloat, PositiveInt, NonNegativeFloat, StrategyConfig
from nautilus_trader.core.data import Data
from nautilus_trader.indicators.atr import AverageTrueRange
from nautilus_trader.model.book import OrderBook
from nautilus_trader.model.data import OrderBookDeltas, QuoteTick, Bar
from nautilus_trader.model.enums import OrderSide, TimeInForce, BookType, OrderType
from nautilus_trader.model.events import OrderFilled, PositionChanged, PositionClosed, PositionOpened
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.model.orders import Order
from nautilus_trader.trading.strategy import Strategy


class QueueFirstHFTConfig(StrategyConfig, frozen=True):
    """
    Configuration for the Queue-First HFT Strategy.
    
    Parameters
    ----------
    instrument_id : InstrumentId
        The instrument ID to trade
    base_notional : PositiveFloat, default 2015.0
        Base notional amount in USD (Q0 in the mathematical spec)
    core_leverage : PositiveFloat, default 25.0
        Core leverage multiplier
    maker_leverage : PositiveFloat, default 55.0
        Leverage during maker time windows
    edge_threshold_bp : PositiveFloat, default 2.0
        Minimum edge in basis points to trigger orders
    maker_spread_bp : PositiveFloat, default 10.0
        Spread for maker orders in basis points (0.1%)
    arb_threshold_bp : PositiveFloat, default 2.4
        Cross-venue arbitrage threshold in basis points
    queue_rank_threshold : PositiveFloat, default 0.35
        Maximum queue rank before cancelling orders
    atr_gate_bp : PositiveFloat, default 6.0
        ATR threshold in basis points above which trading stops
    atr_period : PositiveInt, default 60
        Period for ATR calculation (ticks)
    cancel_cluster_count : PositiveInt, default 5
        Number of cancels to trigger cluster guard
    cancel_cluster_window_ms : PositiveInt, default 50
        Time window for cancel cluster detection
    staleness_threshold_us : PositiveInt, default 30
        Maximum data staleness in microseconds
    latency_threshold_us : PositiveInt, default 10
        Maximum tolerable latency in microseconds
    dpmo_threshold : PositiveInt, default 80
        Defects per million opportunities threshold
    maker_start_utc : str, default "00:30"
        Start time for maker window 1 (UTC)
    maker_end_utc : str, default "06:00" 
        End time for maker window 1 (UTC)
    maker2_start_utc : str, default "12:30"
        Start time for maker window 2 (UTC)
    maker2_end_utc : str, default "14:30"
        End time for maker window 2 (UTC)
    manage_inventory : bool, default True
        Whether to use the cache-managed order book
    dry_run : bool, default False
        Whether to run in dry mode (no actual orders)
    """

    instrument_id: InstrumentId
    base_notional: PositiveFloat = 2015.0
    core_leverage: PositiveFloat = 25.0
    maker_leverage: PositiveFloat = 55.0
    edge_threshold_bp: PositiveFloat = 2.0
    maker_spread_bp: PositiveFloat = 10.0  # 0.1% = 10 bp
    arb_threshold_bp: PositiveFloat = 2.4
    queue_rank_threshold: PositiveFloat = 0.35
    atr_gate_bp: PositiveFloat = 6.0
    atr_period: PositiveInt = 60
    cancel_cluster_count: PositiveInt = 5
    cancel_cluster_window_ms: PositiveInt = 50
    staleness_threshold_us: PositiveInt = 30
    latency_threshold_us: PositiveInt = 10
    dpmo_threshold: PositiveInt = 80
    maker_start_utc: str = "00:30"
    maker_end_utc: str = "06:00"
    maker2_start_utc: str = "12:30"
    maker2_end_utc: str = "14:30"
    manage_inventory: bool = True
    dry_run: bool = False


class QueueFirstHFT(Strategy):
    """
    Queue-First HFT Strategy implementation.
    
    This strategy implements a high-frequency trading approach that prioritizes
    queue position through ultra-low latency and sophisticated risk controls.
    """

    def __init__(self, config: QueueFirstHFTConfig) -> None:
        """Initialize the strategy."""
        super().__init__(config)
        
        # Configuration
        self.instrument_id = config.instrument_id
        self.base_notional = config.base_notional
        self.core_leverage = config.core_leverage
        self.maker_leverage = config.maker_leverage
        self.edge_threshold_bp = config.edge_threshold_bp
        self.maker_spread_bp = config.maker_spread_bp
        self.arb_threshold_bp = config.arb_threshold_bp
        self.queue_rank_threshold = config.queue_rank_threshold
        self.atr_gate_bp = config.atr_gate_bp
        self.atr_period = config.atr_period
        self.cancel_cluster_count = config.cancel_cluster_count
        self.cancel_cluster_window_ms = config.cancel_cluster_window_ms
        self.staleness_threshold_us = config.staleness_threshold_us
        self.latency_threshold_us = config.latency_threshold_us
        self.dpmo_threshold = config.dpmo_threshold
        self.manage_inventory = config.manage_inventory
        self.dry_run = config.dry_run
        
        # Parse maker windows
        self.maker_windows = self._parse_maker_windows(config)
        
        # State
        self.instrument: Optional[Instrument] = None
        self.order_book: Optional[OrderBook] = None
        self._atr: Optional[AverageTrueRange] = None
        
        # Tracking
        self.last_tick_time_ns: int = 0
        self.cancel_times: list[int] = []
        self.initial_equity: float = 0.0
        self.defect_count: int = 0
        self.opportunity_count: int = 0
        
        # Performance monitoring
        self.latencies: list[float] = []
        self.queue_ranks: list[float] = []
        self.drawdowns: list[float] = []
        self.max_drawdown: float = 0.0
        self.last_spc_check_ns: int = 0
        self.spc_check_interval_ns: int = 1_000_000_000  # 1 second
        self.cancel_cluster_cooldown_ns: int = 0
        self.staleness_spread_multiplier: float = 1.0
        
    def _parse_maker_windows(self, config: QueueFirstHFTConfig) -> list[tuple[datetime.time, datetime.time]]:
        """Parse maker time windows from config."""
        windows = []
        
        # Window 1
        start1 = datetime.datetime.strptime(config.maker_start_utc, "%H:%M").time()
        end1 = datetime.datetime.strptime(config.maker_end_utc, "%H:%M").time()
        windows.append((start1, end1))
        
        # Window 2
        start2 = datetime.datetime.strptime(config.maker2_start_utc, "%H:%M").time()
        end2 = datetime.datetime.strptime(config.maker2_end_utc, "%H:%M").time()
        windows.append((start2, end2))
        
        return windows
        
    def on_start(self) -> None:
        """Actions to be performed on strategy start."""
        self.instrument = self.cache.instrument(self.instrument_id)
        if self.instrument is None:
            self.log.error(f"Could not find instrument for {self.instrument_id}")
            self.stop()
            return
            
        # Initialize ATR indicator
        self._atr = AverageTrueRange(self.atr_period)
        
        # Create order book if not using managed
        if not self.manage_inventory:
            self.order_book = OrderBook(
                instrument_id=self.instrument_id,
                book_type=BookType.L2_MBP,
            )
            
        # Subscribe to order book deltas
        self.subscribe_order_book_deltas(
            instrument_id=self.instrument_id,
            book_type=BookType.L2_MBP,
        )
        
        # Subscribe to quote ticks for ATR
        self.subscribe_quote_ticks(instrument_id=self.instrument_id)
        
        # Record initial equity
        account = self.portfolio.account(self.instrument.venue)
        if account:
            self.initial_equity = float(account.balance_total(account.base_currency))
            
        self.log.info(f"Strategy started with initial equity: {self.initial_equity}")
        
    def on_stop(self) -> None:
        """Actions to be performed on strategy stop."""
        # Cancel all pending orders
        self.cancel_all_orders(self.instrument_id)
        
        # Close all positions
        self.close_all_positions(self.instrument_id)
        
        # Log final statistics
        self._log_performance_stats()
        
    def on_order_book_deltas(self, deltas: OrderBookDeltas) -> None:
        """Handle order book delta updates."""
        # Update latency tracking
        now_ns = self.clock.timestamp_ns()
        latency_us = (now_ns - deltas.ts_event) / 1000  # ns to us
        self.latencies.append(latency_us)
        
        # Check latency threshold
        if latency_us > self.latency_threshold_us:
            self.log.warning(f"Latency {latency_us:.1f}us exceeds threshold")
            return
            
        # Update order book if not managed
        if not self.manage_inventory and self.order_book:
            self.order_book.apply_deltas(deltas)
            
        # Check data staleness and apply graduated response
        staleness_us = (now_ns - self.last_tick_time_ns) / 1000
        if staleness_us > self.staleness_threshold_us:
            self.log.warning(f"Data staleness {staleness_us:.1f}us exceeds threshold, pulling quotes")
            self._pull_all_quotes()
            return
        elif staleness_us > 5:  # Between 5-30 microseconds
            # Double the spread for stale data
            self.staleness_spread_multiplier = 2.0
        else:
            self.staleness_spread_multiplier = 1.0
            
        self.last_tick_time_ns = now_ns
        
        # Process trading logic
        self._process_trading_logic()
        
        # Check SPC limits periodically
        self._check_spc_limits()
        
    def on_quote_tick(self, tick: QuoteTick) -> None:
        """Handle quote tick updates."""
        # Update ATR with quote
        if self._atr:
            # Simple ATR approximation from spread
            spread = float(tick.ask_price) - float(tick.bid_price)
            # ATR needs bars, but we can approximate with spread
            
        # Process trading logic with quote data
        self._process_quote_trading_logic(tick)
    
    def _process_quote_trading_logic(self, tick: QuoteTick) -> None:
        """Process trading logic from quote tick."""
        # Calculate VAMP from quote
        best_bid = float(tick.bid_price)
        best_ask = float(tick.ask_price)
        bid_size = float(tick.bid_size)
        ask_size = float(tick.ask_size)
        
        epsilon = 0.0001
        vamp = (best_ask * bid_size + best_bid * ask_size) / (bid_size + ask_size + epsilon)
        
        # Calculate edge
        mid = (best_bid + best_ask) / 2
        edge_bp = 10000 * (vamp - mid) / mid if mid > 0 else 0
        
        self.opportunity_count += 1
        
        # Check edge threshold
        if abs(edge_bp) < self.edge_threshold_bp:
            return
            
        # For backtesting, submit a simple market order
        if not self.dry_run:
            side = OrderSide.BUY if edge_bp > 0 else OrderSide.SELL
            quantity = self.instrument.make_qty(0.1)  # Simple fixed size
            
            order = self.order_factory.market(
                instrument_id=self.instrument_id,
                order_side=side,
                quantity=quantity,
                time_in_force=TimeInForce.IOC,
            )
            
            self.submit_order(order)
            
    def on_event(self, event: Data) -> None:
        """Handle generic events."""
        if isinstance(event, (PositionOpened, PositionChanged, PositionClosed)):
            self._check_drawdown()
            
        if isinstance(event, OrderFilled):
            self._on_order_filled(event)
            
    def _process_trading_logic(self) -> None:
        """Main trading logic processing."""
        # Get current order book
        book = self._get_order_book()
        if not book or book.count == 0:
            return
            
        # Calculate VAMP and edge
        vamp = self._calculate_vamp(book)
        mid_price = book.midpoint()
        if not mid_price:
            return
        mid = float(mid_price)
        edge_bp = 10000 * (vamp - mid) / mid if mid > 0 else 0
        
        # Check ATR gate
        if self._atr and self._atr.initialized:
            atr_bp = 10000 * float(self._atr.value) / mid if mid > 0 else 0
            if atr_bp > self.atr_gate_bp:
                self.log.info(f"ATR gate triggered: {atr_bp:.2f} bp > {self.atr_gate_bp} bp")
                self._cancel_all_and_wait()
                return
        else:
            atr_bp = 0
            
        # Check edge threshold
        if abs(edge_bp) < self.edge_threshold_bp:
            return
            
        # Check cancel cluster
        if self._check_cancel_cluster():
            self.log.warning("Cancel cluster detected, pulling quotes for 100ms")
            self._pull_all_quotes()
            self.cancel_cluster_cooldown_ns = now_ns + 100_000_000  # 100ms cooldown
            return
            
        # Check if we're in cooldown
        if self.cancel_cluster_cooldown_ns > now_ns:
            return
            
        # Determine execution mode
        if self._is_maker_window():
            self._execute_maker_logic(book, edge_bp, atr_bp)
        else:
            self._execute_arb_logic(book, edge_bp)
            
    def _calculate_vamp(self, book: OrderBook) -> float:
        """Calculate Volume-Adjusted Mid Price (VAMP)."""
        best_bid = book.best_bid_price()
        best_ask = book.best_ask_price()
        bid_size = book.best_bid_size()
        ask_size = book.best_ask_size()
        
        if not all([best_bid, best_ask, bid_size, ask_size]):
            return 0.0
            
        epsilon = 0.0001  # Small value to prevent division by zero
        vamp = (float(best_ask) * float(bid_size) + float(best_bid) * float(ask_size)) / (
            float(bid_size) + float(ask_size) + epsilon
        )
        
        return vamp
        
    def _estimate_queue_rank(self, side: OrderSide, price: Price) -> float:
        """Estimate our queue position rank."""
        # This is a simplified estimation
        # In production, would track actual order acknowledgments
        book = self._get_order_book()
        if not book:
            return 1.0
            
        if side == OrderSide.BUY:
            level_size = book.bid_size(price)
        else:
            level_size = book.ask_size(price)
            
        if not level_size:
            return 0.0
            
        # Assume we're at the end of the queue (conservative)
        # In reality, would use order ack timestamps to estimate position
        our_position = float(level_size)
        total_size = float(level_size)
        
        return our_position / (total_size + 0.0001)
        
    def _is_maker_window(self) -> bool:
        """Check if current time is within maker windows."""
        current_time = pd.Timestamp.now(tz="UTC").time()
        
        for start, end in self.maker_windows:
            if start <= current_time < end:
                return True
                
        return False
        
    def _calculate_position_size(self, edge_bp: float, atr_bp: float) -> Quantity:
        """Calculate position size using Kelly criterion."""
        # Get current equity
        if not self.instrument:
            return Quantity.zero()
        account = self.portfolio.account(self.instrument.venue)
        if not account:
            return Quantity.zero()
            
        current_equity = float(account.balance_total(account.base_currency))
        equity_ratio = current_equity / self.initial_equity if self.initial_equity > 0 else 1.0
        
        # Kelly fraction
        kelly_fraction = min(abs(edge_bp) / 10.0, 1.0) if atr_bp > 0 else 1.0
        
        # Determine leverage
        leverage = self.maker_leverage if self._is_maker_window() else self.core_leverage
        
        # Calculate notional
        notional = self.base_notional * equity_ratio * kelly_fraction * leverage
        
        # Convert to quantity
        book = self._get_order_book()
        if not book:
            return Quantity.zero()
        mid_price = book.midpoint()
        if not mid_price:
            return Quantity.zero()
            
        quantity = notional / float(mid_price)
        
        if self.instrument:
            return self.instrument.make_qty(quantity)
        return Quantity.zero()
        
    def _execute_maker_logic(self, book: OrderBook, edge_bp: float, atr_bp: float) -> None:
        """Execute maker (limit order) strategy."""
        if self.dry_run:
            self.log.info(f"[DRY RUN] Would place maker order, edge={edge_bp:.2f}bp")
            return
            
        # Calculate order parameters
        side = OrderSide.BUY if edge_bp > 0 else OrderSide.SELL
        mid_price = float(book.midpoint())
        
        # Calculate price with spread (apply staleness multiplier)
        effective_spread_bp = self.maker_spread_bp * self.staleness_spread_multiplier
        spread_mult = 1 - (effective_spread_bp / 10000) if side == OrderSide.BUY else 1 + (effective_spread_bp / 10000)
        if not self.instrument:
            return
        order_price = self.instrument.make_price(mid_price * spread_mult)
        
        # Check queue rank
        queue_rank = self._estimate_queue_rank(side, order_price)
        self.queue_ranks.append(queue_rank)
        
        if queue_rank > self.queue_rank_threshold:
            self.log.info(f"Queue rank {queue_rank:.3f} exceeds threshold, cancelling")
            self._cancel_order_at_price(side, order_price)
            return
            
        # Calculate size
        quantity = self._calculate_position_size(edge_bp, atr_bp)
        if quantity == Quantity.zero():
            return
            
        # Create and submit order
        order = self.order_factory.limit(
            instrument_id=self.instrument_id,
            order_side=side,
            price=order_price,
            quantity=quantity,
            time_in_force=TimeInForce.GTC,
            post_only=True,  # Maker only
        )
        
        self.submit_order(order)
        self.opportunity_count += 1
        
    def _execute_arb_logic(self, book: OrderBook, edge_bp: float) -> None:
        """Execute arbitrage (taker) strategy."""
        # This is simplified - in production would check cross-venue prices
        if abs(edge_bp) < self.arb_threshold_bp:
            return
            
        if self.dry_run:
            self.log.info(f"[DRY RUN] Would execute arb trade, edge={edge_bp:.2f}bp")
            return
            
        # Calculate size
        quantity = self._calculate_position_size(edge_bp, 0)
        if quantity == Quantity.zero():
            return
            
        # Submit market orders
        side = OrderSide.BUY if edge_bp > 0 else OrderSide.SELL
        
        order = self.order_factory.market(
            instrument_id=self.instrument_id,
            order_side=side,
            quantity=quantity,
            time_in_force=TimeInForce.IOC,
        )
        
        self.submit_order(order)
        self.opportunity_count += 1
        
    def _check_cancel_cluster(self) -> bool:
        """Check for cancel cluster condition."""
        now_ns = self.clock.timestamp_ns()
        window_ns = self.cancel_cluster_window_ms * 1_000_000
        
        # Remove old cancel times
        self.cancel_times = [t for t in self.cancel_times if now_ns - t < window_ns]
        
        # Check if we have too many recent cancels
        return len(self.cancel_times) >= self.cancel_cluster_count
        
    def _cancel_order_at_price(self, side: OrderSide, price: Price) -> None:
        """Cancel orders at specific price level."""
        for order in self.cache.orders_open(instrument_id=self.instrument_id):
            if order.side == side and order.price == price:
                self.cancel_order(order)
                self.cancel_times.append(self.clock.timestamp_ns())
                
    def _pull_all_quotes(self) -> None:
        """Cancel all resting orders."""
        self.cancel_all_orders(self.instrument_id)
        self.cancel_times.append(self.clock.timestamp_ns())
        
    def _cancel_all_and_wait(self) -> None:
        """Cancel all orders and wait."""
        self._pull_all_quotes()
        # In production, would implement actual wait logic
        
    def _check_drawdown(self) -> None:
        """Check current drawdown and update tracking."""
        if not self.instrument:
            return
        account = self.portfolio.account(self.instrument.venue)
        if not account or self.initial_equity == 0:
            return
            
        current_equity = float(account.balance_total(account.base_currency))
        drawdown = (self.initial_equity - current_equity) / self.initial_equity
        self.drawdowns.append(drawdown)
        
        # Check if we need to halt
        if drawdown > 0.10:  # 10% drawdown limit
            self.log.error(f"Drawdown {drawdown:.1%} exceeds limit, stopping strategy")
            self.stop()
            
    def _on_order_filled(self, event: OrderFilled) -> None:
        """Handle order fill events."""
        # Track fill quality and detect defects
        if event.order_side == OrderSide.BUY:
            # Check if we got adversely filled (price moved against us)
            book = self._get_order_book()
            if book:
                current_mid = book.midpoint()
                if current_mid and float(current_mid) < float(event.avg_px):
                    # Adverse fill - we bought higher than current mid
                    self.defect_count += 1
                    self.log.warning(f"Adverse fill detected: bought at {event.avg_px}, mid now {current_mid}")
        else:
            # Sell side
            book = self._get_order_book()
            if book:
                current_mid = book.midpoint()
                if current_mid and float(current_mid) > float(event.avg_px):
                    # Adverse fill - we sold lower than current mid
                    self.defect_count += 1
                    self.log.warning(f"Adverse fill detected: sold at {event.avg_px}, mid now {current_mid}")
        
    def _get_order_book(self) -> Optional[OrderBook]:
        """Get the current order book."""
        if self.manage_inventory:
            return self.cache.order_book(self.instrument_id)
        else:
            return self.order_book
            
    def _check_spc_limits(self) -> None:
        """Check Statistical Process Control limits and trigger kill-switch if needed."""
        now_ns = self.clock.timestamp_ns()
        
        # Only check periodically
        if now_ns - self.last_spc_check_ns < self.spc_check_interval_ns:
            return
            
        self.last_spc_check_ns = now_ns
        
        # Calculate current DPMO
        if self.opportunity_count > 0:
            current_dpmo = (self.defect_count / self.opportunity_count) * 1_000_000
            if current_dpmo > self.dpmo_threshold:
                self.log.error(f"DPMO {current_dpmo:.0f} exceeds threshold {self.dpmo_threshold}, halting strategy")
                self.stop()
                return
                
        # Check latency p99
        if len(self.latencies) >= 100:
            latency_p99 = np.percentile(self.latencies[-1000:], 99)  # Last 1000 samples
            if latency_p99 > self.latency_threshold_us:
                self.log.error(f"Latency p99 {latency_p99:.1f}us exceeds threshold, halting strategy")
                self.stop()
                return
                
        # Check drawdown
        if self.drawdowns and max(self.drawdowns) > 0.10:
            self.log.error(f"Max drawdown {max(self.drawdowns):.1%} exceeds 10%, halting strategy")
            self.stop()
            return
            
    def _log_performance_stats(self) -> None:
        """Log performance statistics."""
        if not self.latencies:
            return
            
        # Calculate DPMO
        dpmo = (self.defect_count / max(self.opportunity_count, 1)) * 1_000_000
        
        # Calculate statistics
        latency_p50 = np.percentile(self.latencies, 50)
        latency_p95 = np.percentile(self.latencies, 95)
        latency_p99 = np.percentile(self.latencies, 99)
        
        queue_rank_mean = np.mean(self.queue_ranks) if self.queue_ranks else 0
        max_drawdown = max(self.drawdowns) if self.drawdowns else 0
        
        self.log.info(
            f"Performance Stats - "
            f"DPMO: {dpmo:.0f}, "
            f"Latency p50/p95/p99: {latency_p50:.1f}/{latency_p95:.1f}/{latency_p99:.1f}us, "
            f"Avg Queue Rank: {queue_rank_mean:.3f}, "
            f"Max Drawdown: {max_drawdown:.1%}"
        )
        
        # Check SPC limits
        if dpmo > self.dpmo_threshold:
            self.log.error(f"DPMO {dpmo:.0f} exceeds threshold {self.dpmo_threshold}")
        if latency_p99 > self.latency_threshold_us:
            self.log.error(f"Latency p99 {latency_p99:.1f}us exceeds threshold")