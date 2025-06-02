#!/usr/bin/env python3
"""
Benchmark comparison between Python and Cython implementations.

This demonstrates the performance gains from Path B optimization.
"""

import time
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))

# Import Python versions
from core.signals import VAMPCalculator, EdgeCalculator, CombinedSignalCalculator
from profile_simple import MockQuote


def build_cython_extension():
    """Build the Cython extension if needed."""
    import subprocess
    import os
    
    cython_dir = Path(__file__).parent / "cython_ext"
    os.chdir(cython_dir)
    
    print("Building Cython extension...")
    result = subprocess.run([
        sys.executable, "setup.py", "build_ext", "--inplace"
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print("Build failed:")
        print(result.stderr)
        return False
        
    os.chdir(Path(__file__).parent)
    return True


def benchmark_implementations():
    """Compare Python vs Cython performance."""
    
    print("="*70)
    print("PYTHON VS CYTHON PERFORMANCE COMPARISON")
    print("="*70)
    
    iterations = 1_000_000
    
    # Test data
    bid_price = 2000.00
    ask_price = 2000.05
    bid_size = 100.0
    ask_size = 150.0
    
    # 1. Python VAMP
    print("\n1. VAMP Calculation")
    print("-" * 40)
    
    vamp_py = VAMPCalculator()
    quote = MockQuote(bid_price, ask_price, bid_size, ask_size)
    
    start = time.perf_counter()
    for _ in range(iterations):
        vamp_py.update_from_quote(quote)
    py_time = time.perf_counter() - start
    
    print(f"Python implementation:")
    print(f"  Time: {py_time:.3f}s")
    print(f"  Per iteration: {py_time/iterations*1e9:.0f}ns")
    print(f"  Throughput: {iterations/py_time:,.0f} ops/sec")
    
    # Try to import and benchmark Cython version
    try:
        # Add cython_ext to path
        sys.path.insert(0, str(Path(__file__).parent / "cython_ext"))
        from signals_fast import VAMPCalculatorFast
        
        vamp_cy = VAMPCalculatorFast()
        
        start = time.perf_counter()
        for _ in range(iterations):
            vamp_cy.update(bid_price, ask_price, bid_size, ask_size)
        cy_time = time.perf_counter() - start
        
        print(f"\nCython implementation:")
        print(f"  Time: {cy_time:.3f}s")
        print(f"  Per iteration: {cy_time/iterations*1e9:.0f}ns")
        print(f"  Throughput: {iterations/cy_time:,.0f} ops/sec")
        print(f"  Speedup: {py_time/cy_time:.1f}x")
        
    except ImportError:
        print("\nCython extension not available. Build with:")
        print("  cd cython_ext && python setup.py build_ext --inplace")
        cy_time = None
    
    # 2. Combined Signal Path
    print("\n2. Combined Signal Path (VAMP + Edge)")
    print("-" * 40)
    
    # Python version
    vamp_py = VAMPCalculator()
    edge_py = EdgeCalculator()
    
    start = time.perf_counter()
    for _ in range(iterations):
        vamp_py.update_from_quote(quote)
        if vamp_py.ready:
            mid = (quote.bid_price + quote.ask_price) / 2
            edge_py.update(vamp_py.value, mid)
    py_combined_time = time.perf_counter() - start
    
    print(f"Python implementation:")
    print(f"  Time: {py_combined_time:.3f}s")
    print(f"  Per iteration: {py_combined_time/iterations*1e9:.0f}ns")
    
    try:
        from signals_fast import CombinedSignalCalculator
        
        combined_cy = CombinedSignalCalculator()
        
        start = time.perf_counter()
        for _ in range(iterations):
            combined_cy.update(bid_price, ask_price, bid_size, ask_size)
        cy_combined_time = time.perf_counter() - start
        
        print(f"\nCython implementation:")
        print(f"  Time: {cy_combined_time:.3f}s")
        print(f"  Per iteration: {cy_combined_time/iterations*1e9:.0f}ns")
        print(f"  Speedup: {py_combined_time/cy_combined_time:.1f}x")
        
    except ImportError:
        cy_combined_time = None
    
    # Summary
    print("\n" + "="*70)
    print("OPTIMIZATION RESULTS")
    print("="*70)
    
    if cy_time:
        print(f"\nVAMP Calculation:")
        print(f"  Python: {py_time/iterations*1e9:.0f}ns")
        print(f"  Cython: {cy_time/iterations*1e9:.0f}ns")
        print(f"  Improvement: {(1 - cy_time/py_time)*100:.1f}%")
        
    if cy_combined_time:
        print(f"\nCombined Signal Path:")
        print(f"  Python: {py_combined_time/iterations*1e9:.0f}ns")
        print(f"  Cython: {cy_combined_time/iterations*1e9:.0f}ns")
        print(f"  Improvement: {(1 - cy_combined_time/py_combined_time)*100:.1f}%")
        
        # Check against targets
        print(f"\nLatency vs Targets:")
        print(f"  Target (p50): ≤ 3,000ns")
        print(f"  Achieved: {cy_combined_time/iterations*1e9:.0f}ns")
        
        if cy_combined_time/iterations*1e9 < 1000:
            print(f"  ✅ Sub-microsecond achieved!")
        elif cy_combined_time/iterations*1e9 < 3000:
            print(f"  ✅ Within 3μs target!")
        else:
            print(f"  ⚠️  Further optimization needed")
    
    # Next steps
    print("\n" + "="*70)
    print("NEXT STEPS FOR PATH B")
    print("="*70)
    
    print("\n1. Memory optimization:")
    print("   - Use memory pools for quote objects")
    print("   - Implement zero-copy data structures")
    print("   - Align data for cache efficiency")
    
    print("\n2. Further performance gains:")
    print("   - SIMD instructions for parallel computation")
    print("   - Rust implementation for critical paths")
    print("   - Hardware acceleration (FPGA)")
    
    print("\n3. Production deployment:")
    print("   - CPU pinning and isolation")
    print("   - Kernel bypass networking")
    print("   - Real-time scheduling")


def demonstrate_hot_path():
    """Demonstrate the complete optimized hot path."""
    
    print("\n" + "="*70)
    print("HOT PATH DEMONSTRATION")
    print("="*70)
    
    try:
        from signals_fast import FastHotPath
        
        hot_path = FastHotPath(edge_threshold_bp=0.05, atr_threshold_bp=6.0)
        
        # Simulate market data
        trades = 0
        iterations = 100_000
        
        start = time.perf_counter()
        for i in range(iterations):
            # Vary the data slightly
            bid = 2000.0 + (i % 100) * 0.01
            ask = bid + 0.05
            bid_size = 100.0 + (i % 50)
            ask_size = 150.0 - (i % 50)
            
            if hot_path.process_quote(bid, ask, bid_size, ask_size, 5.0):
                trades += 1
                
        elapsed = time.perf_counter() - start
        
        print(f"\nProcessed {iterations:,} quotes in {elapsed:.3f}s")
        print(f"Latency per quote: {elapsed/iterations*1e9:.0f}ns")
        print(f"Throughput: {iterations/elapsed:,.0f} quotes/sec")
        print(f"Trades executed: {trades:,}")
        
        if elapsed/iterations*1e9 < 100:
            print("\n✅ ACHIEVED SUB-100ns HOT PATH!")
            
    except ImportError:
        print("\nCython hot path not available.")


if __name__ == "__main__":
    # Try to build Cython extension
    if "--build" in sys.argv:
        if build_cython_extension():
            print("Build successful!\n")
        else:
            print("Build failed. Continuing with Python-only benchmarks.\n")
    
    # Run benchmarks
    benchmark_implementations()
    
    # Demonstrate hot path
    demonstrate_hot_path()