#!/usr/bin/env python3
"""Simplified performance profiling for NanoHFT hot paths."""

import time
import numpy as np
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).parent))

from core.signals import VAMPCalculator, EdgeCalculator, ATRCalculator
from core.risk_guards import ATRGuard, CancelClusterGuard, DataStalenessGuard


class MockQuote:
    """Mock quote with slots for performance."""
    __slots__ = ['bid_price', 'ask_price', 'bid_size', 'ask_size']
    
    def __init__(self, bid_price, ask_price, bid_size, ask_size):
        self.bid_price = bid_price
        self.ask_price = ask_price
        self.bid_size = bid_size
        self.ask_size = ask_size


def benchmark_hot_path():
    """Benchmark the critical hot path components."""
    
    print("="*70)
    print("NANOHFT HOT PATH BENCHMARKS")
    print("="*70)
    
    # Test parameters
    iterations = 100_000
    
    # 1. VAMP Calculation
    print("\n1. VAMP Calculation Benchmark")
    print("-" * 40)
    
    vamp_calc = VAMPCalculator()
    quote = MockQuote(2000.00, 2000.05, 100.0, 150.0)
    
    start = time.perf_counter()
    for _ in range(iterations):
        vamp_calc.update_from_quote(quote)
    vamp_time = time.perf_counter() - start
    
    print(f"Iterations: {iterations:,}")
    print(f"Total time: {vamp_time:.3f}s")
    print(f"Per iteration: {vamp_time/iterations*1e6:.2f}μs")
    print(f"Throughput: {iterations/vamp_time:,.0f} ops/sec")
    
    # 2. Edge Calculation
    print("\n2. Edge Calculation Benchmark")
    print("-" * 40)
    
    edge_calc = EdgeCalculator()
    vamp = 2000.025
    mid = 2000.025
    
    start = time.perf_counter()
    for _ in range(iterations):
        edge_calc.update(vamp, mid)
    edge_time = time.perf_counter() - start
    
    print(f"Iterations: {iterations:,}")
    print(f"Total time: {edge_time:.3f}s")
    print(f"Per iteration: {edge_time/iterations*1e6:.2f}μs")
    print(f"Throughput: {iterations/edge_time:,.0f} ops/sec")
    
    # 3. Combined Signal Path
    print("\n3. Combined Signal Path (VAMP + Edge)")
    print("-" * 40)
    
    vamp_calc = VAMPCalculator()
    edge_calc = EdgeCalculator()
    
    start = time.perf_counter()
    for _ in range(iterations):
        vamp_calc.update_from_quote(quote)
        if vamp_calc.ready:
            mid = (quote.bid_price + quote.ask_price) / 2
            edge_calc.update(vamp_calc.value, mid)
    combined_time = time.perf_counter() - start
    
    print(f"Iterations: {iterations:,}")
    print(f"Total time: {combined_time:.3f}s")
    print(f"Per iteration: {combined_time/iterations*1e6:.2f}μs")
    print(f"Throughput: {iterations/combined_time:,.0f} ops/sec")
    
    # 4. Risk Guards
    print("\n4. Risk Guard Checks")
    print("-" * 40)
    
    atr_guard = ATRGuard(threshold_bp=6.0)
    staleness_guard = DataStalenessGuard(threshold_us=30)
    
    start = time.perf_counter()
    base_ns = time.time_ns()
    for i in range(iterations):
        atr_guard.check(5.0)
        staleness_guard.update(base_ns + i * 1000)
        staleness_guard.check(base_ns + i * 1000 + 100)
    guard_time = time.perf_counter() - start
    
    print(f"Iterations: {iterations:,}")
    print(f"Total time: {guard_time:.3f}s")
    print(f"Per iteration: {guard_time/iterations*1e6:.2f}μs")
    print(f"Throughput: {iterations/guard_time:,.0f} ops/sec")
    
    # 5. Full Hot Path
    print("\n5. Full Hot Path (Signals + Guards)")
    print("-" * 40)
    
    vamp_calc = VAMPCalculator()
    edge_calc = EdgeCalculator()
    atr_guard = ATRGuard(threshold_bp=6.0)
    staleness_guard = DataStalenessGuard(threshold_us=30)
    
    start = time.perf_counter()
    trades = 0
    for i in range(iterations):
        # Update signals
        vamp_calc.update_from_quote(quote)
        if vamp_calc.ready:
            mid = (quote.bid_price + quote.ask_price) / 2
            edge_calc.update(vamp_calc.value, mid)
            
            # Check guards
            if edge_calc.ready and abs(edge_calc.value) > 0.05:
                if not atr_guard.check(5.0):
                    current_ns = base_ns + i * 1000
                    staleness_guard.update(current_ns)
                    should_pull, _ = staleness_guard.check(current_ns + 100)
                    if not should_pull:
                        trades += 1
    
    full_time = time.perf_counter() - start
    
    print(f"Iterations: {iterations:,}")
    print(f"Total time: {full_time:.3f}s")
    print(f"Per iteration: {full_time/iterations*1e6:.2f}μs")
    print(f"Throughput: {iterations/full_time:,.0f} ops/sec")
    print(f"Trades executed: {trades:,}")
    
    # Summary
    print("\n" + "="*70)
    print("PERFORMANCE SUMMARY")
    print("="*70)
    
    print(f"\nComponent Breakdown:")
    print(f"  VAMP calculation: {vamp_time/iterations*1e6:.2f}μs ({vamp_time/full_time*100:.1f}%)")
    print(f"  Edge calculation: {edge_time/iterations*1e6:.2f}μs ({edge_time/full_time*100:.1f}%)")
    print(f"  Guard checks: {guard_time/iterations*1e6:.2f}μs ({guard_time/full_time*100:.1f}%)")
    
    print(f"\nLatency Targets vs Current:")
    print(f"  Target (p50): ≤ 3μs")
    print(f"  Current: {full_time/iterations*1e6:.2f}μs")
    print(f"  Gap: {full_time/iterations*1e6 - 3:.2f}μs ({(full_time/iterations*1e6/3 - 1)*100:.0f}% over target)")
    
    print(f"\nOptimization Potential:")
    overhead = full_time - (vamp_time + edge_time + guard_time)
    print(f"  Python overhead: {overhead/iterations*1e6:.2f}μs ({overhead/full_time*100:.1f}%)")
    print(f"  Theoretical min (sum of parts): {(vamp_time+edge_time+guard_time)/iterations*1e6:.2f}μs")
    
    return {
        'vamp_us': vamp_time/iterations*1e6,
        'edge_us': edge_time/iterations*1e6,
        'guard_us': guard_time/iterations*1e6,
        'full_us': full_time/iterations*1e6,
    }


if __name__ == "__main__":
    results = benchmark_hot_path()
    
    print("\n" + "="*70)
    print("OPTIMIZATION RECOMMENDATIONS")
    print("="*70)
    
    if results['full_us'] > 10:
        print("\n1. HIGH PRIORITY: Port to Cython/Rust")
        print("   Current latency exceeds 10μs, requiring compiled code")
        print("   Start with VAMP calculation as it's the heaviest component")
        
    print("\n2. Quick wins:")
    print("   - Pre-calculate constants (epsilon, basis point multiplier)")
    print("   - Use numpy arrays for batch processing")
    print("   - Reduce object creation in hot path")
    
    print("\n3. Architecture improvements:")
    print("   - Combine VAMP and Edge into single calculation")
    print("   - Batch guard checks")
    print("   - Use bit flags instead of boolean returns")
    
    print("\n4. Next steps:")
    print("   - Create Cython extension for signals module")
    print("   - Benchmark with production data volumes")
    print("   - Profile memory allocation patterns")
    print("="*70)