#!/usr/bin/env python3
"""
NanoHFT Modular Architecture Demonstration

This script demonstrates the modular architecture of NanoHFT without
requiring full NautilusTrader setup. It shows how the components interact.
"""

import json
import time
import numpy as np
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

# Import our modular components
import sys
sys.path.append(str(Path(__file__).parent))

from core.signals import VAMPCalculator, EdgeCalculator, ATRCalculator
from core.risk_guards import ATRGuard, CancelClusterGuard, DataStalenessGuard


@dataclass
class MockQuote:
    """Mock quote for demonstration."""
    bid_price: float
    ask_price: float
    bid_size: float
    ask_size: float
    timestamp_ns: int


def generate_mock_quotes(num_quotes: int = 1000):
    """Generate mock market data."""
    quotes = []
    base_price = 2000.0
    base_time_ns = int(time.time() * 1e9)
    
    for i in range(num_quotes):
        # Add some price movement
        if i % 20 == 0:
            base_price += np.random.normal(0, 0.5)
        
        # Create order flow imbalance with more volatility
        imbalance = np.random.normal(0, 1.0)  # Increased volatility
        
        if imbalance > 0:
            # Buying pressure - creates positive edge
            bid_size = 10 + abs(imbalance) * 50  # Larger size imbalances
            ask_size = 10
            spread = 0.05 * (1 - abs(imbalance) * 0.2)  # Tighter spread on bid side
            bid_price = base_price - spread * 0.2
            ask_price = base_price + spread * 0.8
        else:
            # Selling pressure - creates negative edge
            bid_size = 10
            ask_size = 10 + abs(imbalance) * 50
            spread = 0.05 * (1 - abs(imbalance) * 0.2)  # Tighter spread on ask side
            bid_price = base_price - spread * 0.8
            ask_price = base_price + spread * 0.2
        
        quotes.append(MockQuote(
            bid_price=bid_price,
            ask_price=ask_price,
            bid_size=bid_size,
            ask_size=ask_size,
            timestamp_ns=base_time_ns + i * 50_000_000  # 50ms intervals
        ))
    
    return quotes


def main():
    """Demonstrate the modular NanoHFT architecture."""
    print("="*70)
    print("NANOHFT MODULAR ARCHITECTURE DEMONSTRATION")
    print("="*70)
    
    # Load configuration
    config_path = Path(__file__).parent / "config" / "strategy_params_base.json"
    with open(config_path, "r") as f:
        config = json.load(f)
    
    print(f"\n📋 Configuration loaded from: {config_path}")
    print(f"   Edge threshold: {config['edge_threshold_bp']}bp")
    print(f"   ATR gate: {config['atr_gate_bp']}bp")
    print(f"   Cancel cluster: {config['cancel_cluster_count']} in {config['cancel_cluster_window_ms']}ms")
    
    # Initialize components
    print(f"\n🔧 Initializing modular components...")
    
    # Signal calculators
    vamp_calc = VAMPCalculator()
    edge_calc = EdgeCalculator()
    atr_calc = ATRCalculator(period=config['atr_period'])
    
    # Risk guards
    atr_guard = ATRGuard(threshold_bp=config['atr_gate_bp'])
    cancel_guard = CancelClusterGuard(
        count_threshold=config['cancel_cluster_count'],
        window_ms=config['cancel_cluster_window_ms']
    )
    staleness_guard = DataStalenessGuard(
        threshold_us=config['staleness_threshold_us']
    )
    
    print("   ✅ Signal calculators initialized")
    print("   ✅ Risk guards initialized")
    
    # Generate mock data
    print(f"\n📈 Generating mock market data...")
    quotes = generate_mock_quotes(1000)
    print(f"   Generated {len(quotes)} quotes")
    
    # Process quotes
    print(f"\n🚀 Processing quotes through modular pipeline...")
    
    opportunities = 0
    signals_generated = 0
    trades_blocked_by_guards = 0
    trades_executed = 0
    
    for i, quote in enumerate(quotes):
        opportunities += 1
        
        # Update staleness guard
        staleness_guard.update(quote.timestamp_ns)
        
        # Convert to format expected by calculators
        class QuoteAdapter:
            def __init__(self, q):
                self.ask_price = q.ask_price
                self.bid_price = q.bid_price
                self.ask_size = q.ask_size
                self.bid_size = q.bid_size
        
        adapted_quote = QuoteAdapter(quote)
        
        # Update signals
        vamp_calc.update_from_quote(adapted_quote)
        atr_calc.update(adapted_quote)
        
        # Calculate edge if VAMP ready
        if vamp_calc.ready:
            mid_price = (quote.bid_price + quote.ask_price) / 2
            edge_calc.update(vamp_calc.value, mid_price)
            
            if edge_calc.ready:
                # Debug first few edges
                if i < 20:
                    print(f"   Quote {i}: VAMP={vamp_calc.value:.4f}, Mid={mid_price:.4f}, Edge={edge_calc.value:.2f}bp")
                
                if abs(edge_calc.value) > config['edge_threshold_bp']:
                    signals_generated += 1
                
                # Check risk guards
                current_ns = quote.timestamp_ns + 1000  # Simulate processing time
                
                # Check staleness
                should_pull, spread_mult = staleness_guard.check(current_ns)
                if should_pull:
                    trades_blocked_by_guards += 1
                    continue
                
                # Check ATR gate
                if atr_calc.ready and atr_guard.check(atr_calc.value_bp):
                    trades_blocked_by_guards += 1
                    continue
                
                # Check cancel cluster
                if cancel_guard.check(current_ns):
                    trades_blocked_by_guards += 1
                    continue
                
                # If all guards pass, we would execute
                trades_executed += 1
                
                # Occasionally show what's happening
                if trades_executed % 10 == 0:
                    print(f"   Trade {trades_executed}: VAMP={vamp_calc.value:.2f}, "
                          f"Edge={edge_calc.value:.2f}bp, ATR={atr_calc.value_bp:.2f}bp")
    
    # Results
    print(f"\n" + "="*70)
    print("RESULTS")
    print("="*70)
    
    print(f"\n📊 Processing Summary:")
    print(f"   Opportunities analyzed: {opportunities:,}")
    print(f"   Signals generated: {signals_generated:,}")
    print(f"   Trades blocked by guards: {trades_blocked_by_guards:,}")
    print(f"   Trades that would execute: {trades_executed:,}")
    
    if opportunities > 0:
        print(f"\n📈 Rates:")
        print(f"   Signal rate: {signals_generated/opportunities*100:.1f}%")
        print(f"   Execution rate: {trades_executed/opportunities*100:.1f}%")
        if signals_generated > 0:
            print(f"   Guard block rate: {trades_blocked_by_guards/signals_generated*100:.1f}%")
    
    print(f"\n✅ Modular Architecture Benefits Demonstrated:")
    print(f"   1. Clear separation of concerns (signals vs guards)")
    print(f"   2. Easy to test individual components")
    print(f"   3. Configuration-driven behavior")
    print(f"   4. Extensible design (add new signals/guards easily)")
    
    print(f"\n🎯 Next Steps:")
    print(f"   - Run full backtest with NautilusTrader")
    print(f"   - Profile for performance bottlenecks")
    print(f"   - Port hot paths to Rust/Cython")
    
    print(f"\n" + "="*70)


if __name__ == "__main__":
    main()