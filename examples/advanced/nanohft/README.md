# NanoHFT Advanced Example

A modular, educational implementation of a high-frequency trading strategy for NautilusTrader, demonstrating best practices in strategy architecture and risk management.

## Overview

NanoHFT is a **Python prototype** that showcases clean separation of concerns in algorithmic trading strategy development. This implementation prioritizes:

- **Modularity**: Clear separation between signals, risk guards, and execution logic
- **Maintainability**: Easy to understand, test, and modify individual components
- **Educational Value**: Serves as a template for building complex trading strategies
- **Configuration-Driven**: JSON-based configuration for easy parameter tuning

> **Note**: This is an educational example. The latency targets mentioned in the mathematical specifications (sub-10μs) are aspirational and would require Rust/C++ implementations for production use.

## Architecture

```
nanohft/
├── core/
│   ├── __init__.py          # Package initialization
│   ├── strategy.py          # Main strategy orchestrator
│   ├── signals.py           # Signal calculators (VAMP, Edge, ATR)
│   └── risk_guards.py       # Risk management components
├── config/
│   └── strategy_params_base.json  # Configuration parameters
├── data/                    # Sample data directory
├── .context/                # Documentation (CCS/DfLSS)
└── run_backtest.py          # Backtest runner
```

## Key Components

### 1. Signal Calculators (`core/signals.py`)

- **VAMPCalculator**: Volume-Adjusted Mid Price computation
- **EdgeCalculator**: Edge detection in basis points
- **ATRCalculator**: Volatility measurement

### 2. Risk Guards (`core/risk_guards.py`)

- **ATRGuard**: Halts trading during high volatility
- **CancelClusterGuard**: Detects rapid order cancellations
- **DataStalenessGuard**: Ensures data freshness
- **QueueRankGuard**: Monitors queue position

### 3. Strategy Orchestrator (`core/strategy.py`)

- **NanoHFTStrategy**: Main class that coordinates signals and guards
- Implements maker/taker execution logic
- Manages position sizing with Kelly Criterion

## Configuration

The strategy uses JSON configuration (`config/strategy_params_base.json`):

```json
{
  "instrument_id": "ETHUSDT-PERP.BINANCE",
  "base_notional": 2015.0,
  "core_leverage": 25.0,
  "maker_leverage": 55.0,
  "edge_threshold_bp": 2.0,
  "atr_gate_bp": 6.0,
  ...
}
```

## Running the Backtest

```bash
# From the NautilusTrader root directory
python examples/advanced/nanohft/run_backtest.py
```

Expected output:
```
==================================================
NANOHFT ADVANCED EXAMPLE - MODULAR BACKTEST
==================================================

📊 Backtest Setup:
   Platform: NautilusTrader 1.x.x
   Instrument: ETHUSDT-PERP.BINANCE
   
📈 Market Data Generation:
   Generated: 36,000 quotes
   
📋 Configuration loaded from: config/strategy_params_base.json
   
🚀 Running Backtest...

RESULTS
==================================================
📊 Trading Activity:
   Opportunities Analyzed: 36,000
   Trades Executed: XXX
   Hit Rate: XX.X%
```

## Mathematical Foundation

The strategy implements the Queue-First HFT approach with:

1. **VAMP Calculation**:
   ```
   p_t = (A_t × ΔB_t + B_t × ΔA_t) / (ΔB_t + ΔA_t + ε)
   ```

2. **Edge Detection**:
   ```
   e_t = 10^4 × (p_t - m_t) / m_t
   ```

3. **Position Sizing** (Kelly Criterion):
   ```
   N_t = Q_0 × (Equity_t / Equity_0) × f_Kelly × L(t)
   ```

## Development Workflow

### Adding a New Signal

1. Create a new calculator class in `core/signals.py`
2. Implement `update()`, `value`, and `ready` properties
3. Instantiate in `NanoHFTStrategy.__init__()`
4. Update the signal in `on_quote_tick()`

### Adding a New Risk Guard

1. Create a new guard class in `core/risk_guards.py`
2. Implement `check()` method returning bool
3. Instantiate in `NanoHFTStrategy.__init__()`
4. Add check in `_process_trading_logic()`

### Modifying Configuration

1. Edit `config/strategy_params_base.json`
2. Add parameter usage in `NanoHFTStrategy`
3. Document the parameter in this README

## Testing

Unit tests for individual components:

```python
# Example test for VAMP calculator
from nanohft.core.signals import VAMPCalculator

def test_vamp_calculation():
    calc = VAMPCalculator()
    # Create mock quote and test
    ...
```

## Performance Profiling

For optimization (Path B), profile the backtest:

```bash
# Using cProfile
python -m cProfile -o profile.prof examples/advanced/nanohft/run_backtest.py

# Visualize with snakeviz
snakeviz profile.prof
```

## Future Enhancements

1. **Path B - Performance Optimization**:
   - Profile to identify bottlenecks
   - Port critical paths to Rust/Cython
   - Achieve actual HFT latency targets

2. **Additional Features**:
   - Cross-venue arbitrage
   - Machine learning for adaptive thresholds
   - Advanced queue modeling

3. **Production Considerations**:
   - Hardware acceleration (FPGA)
   - Kernel bypass networking
   - Co-location deployment

## Educational Notes

This implementation demonstrates several software engineering best practices:

- **Single Responsibility Principle**: Each class has one clear purpose
- **Dependency Injection**: Strategy receives configuration as parameter
- **Testability**: Small, focused modules are easy to test
- **Documentation**: Clear docstrings and type hints throughout

## License

This example is provided under the same license as NautilusTrader (LGPL-3.0).