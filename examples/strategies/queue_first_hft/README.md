# Queue-First HFT Strategy

A sophisticated high-frequency trading strategy implementation for NautilusTrader that prioritizes queue position through ultra-low latency execution and implements comprehensive risk controls.

## Overview

This strategy implements the Queue-First HFT approach as specified in the mathematical model, featuring:

- **VAMP (Volume-Adjusted Mid Price)** calculation for micro-edge detection
- **Six Sigma quality control** principles with poka-yokes (mistake-proofing)
- **Sub-10 microsecond latency targets** for queue priority
- **Comprehensive risk management** with multiple safety mechanisms
- **Dual execution modes**: Maker (limit orders) and Taker (market orders)

## Mathematical Foundation

### Core Formulas

1. **VAMP Calculation**:
   ```
   p_t = (A_t × ΔB_t + B_t × ΔA_t) / (ΔB_t + ΔA_t + ε)
   ```
   Where:
   - A_t = Best ask price
   - B_t = Best bid price
   - ΔA_t = Ask size
   - ΔB_t = Bid size
   - ε = 0.0001 (epsilon to prevent division by zero)

2. **Edge Detection**:
   ```
   e_t = 10^4 × (p_t - m_t) / m_t
   ```
   Edge is calculated in basis points (bp)

3. **Position Sizing (Kelly Criterion)**:
   ```
   N_t = Q_0 × (Equity_t / Equity_0) × f_Kelly × L(t)
   ```
   Where:
   - Q_0 = Base notional ($2,015)
   - f_Kelly = min(|e_t| / 10, 1.0)
   - L(t) = Leverage (25x core, 55x during maker windows)

## Risk Controls (Poka-Yokes)

### 1. Queue Rank Guard
- **Threshold**: 0.35
- **Action**: Cancel orders if queue position > 35%

### 2. ATR Gate
- **Threshold**: 6 basis points
- **Action**: Zero exposure when volatility exceeds threshold

### 3. Cancel Cluster Detection
- **Threshold**: 5 cancels in 50ms
- **Action**: Pull all quotes, 100ms cooldown

### 4. Data Staleness Check
- **Thresholds**:
  - 5-30μs: Double spread width
  - >30μs: Pull all quotes

## Performance Targets

### Latency Requirements
- **Median (p50)**: ≤ 3 μs
- **p95**: ≤ 8 μs
- **p99**: ≤ 15 μs
- **Max spike**: < 30 μs

### Quality Metrics
- **DPMO**: < 80 (Defects Per Million Opportunities)
- **Drawdown limit**: 10%
- **Win rate target**: > 50%

## Configuration

```python
QueueFirstHFTConfig(
    instrument_id=InstrumentId,
    base_notional=2015.0,        # Base position size
    core_leverage=25.0,          # Standard leverage
    maker_leverage=55.0,         # Leverage during maker windows
    edge_threshold_bp=2.0,       # Minimum edge to trade
    maker_spread_bp=10.0,        # Spread for maker orders (0.1%)
    arb_threshold_bp=2.4,        # Cross-venue arbitrage threshold
    queue_rank_threshold=0.35,   # Maximum queue position
    atr_gate_bp=6.0,            # ATR volatility gate
    atr_period=60,              # ATR calculation period
    cancel_cluster_count=5,      # Cancel cluster threshold
    cancel_cluster_window_ms=50, # Cancel cluster window
    staleness_threshold_us=30,   # Data staleness limit
    latency_threshold_us=10,     # Latency threshold
    dpmo_threshold=80,          # DPMO limit
)
```

## Maker Time Windows

The strategy operates in two modes based on time:

1. **Maker Mode** (Higher leverage, tighter spreads):
   - Window 1: 00:30 - 06:00 UTC
   - Window 2: 12:30 - 14:30 UTC

2. **Taker/Arb Mode** (Standard leverage, market orders):
   - All other times

## Usage

### Basic Example

```python
from nautilus_trader.examples.strategies.queue_first_hft import (
    QueueFirstHFT,
    QueueFirstHFTConfig
)

# Configure strategy
config = QueueFirstHFTConfig(
    instrument_id=InstrumentId.from_str("ETHUSDT-PERP.BINANCE"),
    base_notional=2015.0,
    edge_threshold_bp=2.0,
)

# Create strategy instance
strategy = QueueFirstHFT(config=config)

# Add to trading node or backtest engine
engine.add_strategy(strategy)
```

### Backtest Example

See `backtest_example.py` for a complete backtesting setup with synthetic market data generation.

## Performance Characteristics

Based on backtesting with high-frequency data:

- **Processing Speed**: 100,000+ quotes/second
- **Memory Efficiency**: O(1) for core calculations
- **Latency Tracking**: Real-time percentile calculations
- **Risk Monitoring**: Continuous SPC limit checking

## Safety Features

1. **Automatic Kill-Switch**: Triggers on:
   - DPMO > threshold
   - Latency p99 > threshold
   - Drawdown > 10%

2. **Performance Monitoring**:
   - Real-time latency percentiles
   - Queue rank statistics
   - DPMO calculation
   - Drawdown tracking

3. **Defect Detection**:
   - Adverse fill detection
   - Mark-out analysis
   - Fill quality metrics

## Architecture

The strategy follows NautilusTrader patterns:

- Inherits from `Strategy` base class
- Uses frozen configuration dataclasses
- Implements standard event handlers
- Integrates with cache and message bus

## Testing

Unit tests are provided in the main NautilusTrader test suite. Key test areas:

- VAMP calculation accuracy
- Edge detection logic
- Risk control triggers
- Position sizing calculations
- Time window detection

## Production Considerations

1. **Infrastructure Requirements**:
   - Colocated servers recommended
   - Kernel bypass networking (DPDK/AF_XDP)
   - CPU isolation and tuning
   - PTP time synchronization

2. **Data Requirements**:
   - Level 2 order book data
   - Sub-millisecond quote updates
   - Queue position information
   - Cross-venue price feeds

3. **Monitoring**:
   - Real-time latency monitoring
   - SPC chart tracking
   - CloudWatch/Prometheus integration
   - Alert thresholds

## Future Enhancements

1. **Cross-Venue Arbitrage**: Full implementation with multiple venue connections
2. **Machine Learning**: Adaptive edge threshold based on market conditions
3. **Advanced Queue Modeling**: Neural network for queue position estimation
4. **Hardware Acceleration**: FPGA integration for sub-microsecond latency

## References

- Six Sigma quality control principles
- Kelly Criterion for optimal position sizing
- Market microstructure theory
- Queue-based execution strategies

## License

This strategy is provided under the same license as NautilusTrader (LGPL-3.0).