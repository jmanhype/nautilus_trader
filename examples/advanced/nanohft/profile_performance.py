#!/usr/bin/env python3
"""
Performance profiling script for NanoHFT.

This script profiles the hot paths to identify optimization targets for Path B.
"""

import cProfile
import pstats
import io
import time
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).parent))

from demo_backtest import generate_mock_quotes, MockQuote
from core.signals import VAMPCalculator, EdgeCalculator, ATRCalculator
from core.risk_guards import ATRGuard, CancelClusterGuard, DataStalenessGuard


def profile_hot_path(num_quotes: int = 10000):
    """Profile the hot path of quote processing."""
    
    # Initialize components
    vamp_calc = VAMPCalculator()
    edge_calc = EdgeCalculator()
    atr_calc = ATRCalculator(period=60)
    
    atr_guard = ATRGuard(threshold_bp=6.0)
    cancel_guard = CancelClusterGuard(count_threshold=5, window_ms=50)
    staleness_guard = DataStalenessGuard(threshold_us=30)
    
    # Generate test data
    quotes = generate_mock_quotes(num_quotes)
    
    # Profile the hot path
    profiler = cProfile.Profile()
    profiler.enable()
    
    # Hot path simulation
    signals_generated = 0
    trades_executed = 0
    
    for quote in quotes:
        # Convert to expected format
        class QuoteAdapter:
            def __init__(self, q):
                self.ask_price = q.ask_price
                self.bid_price = q.bid_price
                self.ask_size = q.ask_size
                self.bid_size = q.bid_size
        
        adapted_quote = QuoteAdapter(quote)
        
        # Hot path: Signal calculation
        vamp_calc.update_from_quote(adapted_quote)
        
        if vamp_calc.ready:
            mid_price = (quote.bid_price + quote.ask_price) / 2
            edge_calc.update(vamp_calc.value, mid_price)
            
            if edge_calc.ready and abs(edge_calc.value) > 0.05:
                signals_generated += 1
                
                # Risk checks
                current_ns = quote.timestamp_ns
                staleness_guard.update(quote.timestamp_ns)
                should_pull, spread_mult = staleness_guard.check(current_ns + 1000)
                
                if not should_pull:
                    trades_executed += 1
    
    profiler.disable()
    
    # Print results
    print(f"\nProcessed {num_quotes:,} quotes")
    print(f"Signals generated: {signals_generated:,}")
    print(f"Trades executed: {trades_executed:,}")
    
    return profiler


def analyze_profile(profiler):
    """Analyze and display profiling results."""
    
    # Create string buffer for stats
    s = io.StringIO()
    ps = pstats.Stats(profiler, stream=s)
    
    print("\n" + "="*70)
    print("TOP 20 FUNCTIONS BY CUMULATIVE TIME")
    print("="*70)
    ps.sort_stats('cumulative')
    ps.print_stats(20)
    
    print("\n" + "="*70)
    print("TOP 20 FUNCTIONS BY TOTAL TIME")
    print("="*70)
    ps.sort_stats('tottime')
    ps.print_stats(20)
    
    # Extract hot spots
    print("\n" + "="*70)
    print("HOT PATH ANALYSIS")
    print("="*70)
    
    stats = ps.stats
    total_time = ps.total_tt
    
    hot_functions = []
    for func, (cc, nc, tt, ct, callers) in stats.items():
        if tt > 0.01:  # Functions taking >10ms
            hot_functions.append((func, tt, tt/total_time*100))
    
    hot_functions.sort(key=lambda x: x[1], reverse=True)
    
    print(f"\nFunctions consuming >1% of total time:")
    for func, time_sec, percent in hot_functions[:10]:
        filename, line, name = func
        print(f"  {percent:5.1f}% - {name} ({Path(filename).name}:{line})")
    
    return hot_functions


def benchmark_components():
    """Benchmark individual components."""
    
    print("\n" + "="*70)
    print("COMPONENT BENCHMARKS")
    print("="*70)
    
    # Benchmark VAMP calculation
    vamp_calc = VAMPCalculator()
    quote = MockQuote(100.0, 100.1, 10.0, 20.0, time.time_ns())
    adapted = type('Q', (), {'ask_price': quote.ask_price, 'bid_price': quote.bid_price,
                            'ask_size': quote.ask_size, 'bid_size': quote.bid_size})()
    
    start = time.perf_counter()
    for _ in range(100000):
        vamp_calc.update_from_quote(adapted)
    vamp_time = time.perf_counter() - start
    
    print(f"\nVAMP Calculation:")
    print(f"  100k updates: {vamp_time:.3f}s")
    print(f"  Per update: {vamp_time/100000*1e6:.2f}μs")
    print(f"  Throughput: {100000/vamp_time:,.0f} updates/sec")
    
    # Benchmark Edge calculation
    edge_calc = EdgeCalculator()
    start = time.perf_counter()
    for _ in range(100000):
        edge_calc.update(100.05, 100.0)
    edge_time = time.perf_counter() - start
    
    print(f"\nEdge Calculation:")
    print(f"  100k updates: {edge_time:.3f}s")
    print(f"  Per update: {edge_time/100000*1e6:.2f}μs")
    print(f"  Throughput: {100000/edge_time:,.0f} updates/sec")
    
    # Benchmark Risk Guards
    atr_guard = ATRGuard()
    start = time.perf_counter()
    for i in range(100000):
        atr_guard.check(5.0 + (i % 3))
    guard_time = time.perf_counter() - start
    
    print(f"\nATR Guard Check:")
    print(f"  100k checks: {guard_time:.3f}s")
    print(f"  Per check: {guard_time/100000*1e6:.2f}μs")
    print(f"  Throughput: {100000/guard_time:,.0f} checks/sec")


def suggest_optimizations(hot_functions):
    """Suggest optimization strategies based on profiling."""
    
    print("\n" + "="*70)
    print("OPTIMIZATION RECOMMENDATIONS")
    print("="*70)
    
    print("\nBased on profiling results, consider optimizing:")
    
    # Check for specific hot spots
    for func, time_sec, percent in hot_functions[:5]:
        filename, line, name = func
        
        if "update_from_quote" in name:
            print(f"\n1. VAMP Calculation ({percent:.1f}% of time)")
            print("   - Port to Cython with typed memoryviews")
            print("   - Pre-calculate reciprocals")
            print("   - Use SIMD instructions for parallel computation")
            
        elif "update" in name and "edge" in filename.lower():
            print(f"\n2. Edge Calculation ({percent:.1f}% of time)")
            print("   - Combine with VAMP in single Cython function")
            print("   - Eliminate intermediate Python objects")
            print("   - Use integer arithmetic for basis points")
            
        elif "check" in name and "guard" in filename.lower():
            print(f"\n3. Risk Guard Checks ({percent:.1f}% of time)")
            print("   - Batch multiple guards in single pass")
            print("   - Use bit flags for guard states")
            print("   - Early exit on first failure")
    
    print("\nGeneral optimization strategies:")
    print("- Create Cython extension for entire hot path")
    print("- Use numpy arrays for batch processing")
    print("- Implement zero-copy data structures")
    print("- Consider Rust for ultra-low latency")


def main():
    """Run complete performance analysis."""
    
    print("="*70)
    print("NANOHFT PERFORMANCE PROFILING - PATH B")
    print("="*70)
    
    # Run profiling
    print("\nProfiling hot path with 10,000 quotes...")
    profiler = profile_hot_path(10000)
    
    # Analyze results
    hot_functions = analyze_profile(profiler)
    
    # Benchmark components
    benchmark_components()
    
    # Suggest optimizations
    suggest_optimizations(hot_functions)
    
    print("\n" + "="*70)
    print("Next steps for Path B:")
    print("1. Create Cython versions of hot functions")
    print("2. Benchmark Cython vs Python implementations")
    print("3. Profile with production data volumes")
    print("4. Consider Rust for sub-microsecond targets")
    print("="*70)


if __name__ == "__main__":
    main()