"""Unit tests for NanoHFT risk guards."""

import unittest
import time

# Add parent directory to path
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from core.risk_guards import ATRGuard, CancelClusterGuard, DataStalenessGuard, QueueRankGuard


class TestATRGuard(unittest.TestCase):
    """Test ATR guard functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.guard = ATRGuard(threshold_bp=6.0)
        
    def test_below_threshold(self):
        """Test guard passes when ATR below threshold."""
        should_halt = self.guard.check(5.0)
        self.assertFalse(should_halt)
        self.assertFalse(self.guard.triggered)
        
    def test_above_threshold(self):
        """Test guard triggers when ATR above threshold."""
        should_halt = self.guard.check(7.0)
        self.assertTrue(should_halt)
        self.assertTrue(self.guard.triggered)
        
    def test_at_threshold(self):
        """Test guard behavior at exact threshold."""
        should_halt = self.guard.check(6.0)
        self.assertFalse(should_halt)
        
    def test_none_handling(self):
        """Test guard handles None ATR gracefully."""
        should_halt = self.guard.check(None)
        self.assertFalse(should_halt)


class TestCancelClusterGuard(unittest.TestCase):
    """Test cancel cluster guard functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.guard = CancelClusterGuard(count_threshold=3, window_ms=100)
        
    def test_no_cancels(self):
        """Test guard passes with no cancels."""
        current_ns = time.time_ns()
        should_block = self.guard.check(current_ns)
        self.assertFalse(should_block)
        self.assertFalse(self.guard.triggered)
        
    def test_cluster_detection(self):
        """Test guard detects cancel cluster."""
        base_ns = time.time_ns()
        
        # Record 3 cancels within window
        for i in range(3):
            self.guard.record_cancel(base_ns + i * 1_000_000)  # 1ms apart
            
        # Should trigger
        should_block = self.guard.check(base_ns + 50_000_000)  # 50ms later
        self.assertTrue(should_block)
        self.assertTrue(self.guard.triggered)
        
    def test_window_expiry(self):
        """Test old cancels are removed."""
        base_ns = time.time_ns()
        
        # Record old cancels
        for i in range(3):
            self.guard.record_cancel(base_ns + i * 1_000_000)
            
        # Check after window expires
        should_block = self.guard.check(base_ns + 200_000_000)  # 200ms later
        self.assertFalse(should_block)
        self.assertEqual(self.guard.cancel_count, 0)
        
    def test_cooldown_period(self):
        """Test cooldown after cluster detection."""
        base_ns = time.time_ns()
        
        # Trigger cluster
        for i in range(3):
            self.guard.record_cancel(base_ns + i * 1_000_000)
            
        # First check triggers
        self.assertTrue(self.guard.check(base_ns + 10_000_000))
        
        # Still in cooldown
        self.assertTrue(self.guard.check(base_ns + 50_000_000))
        
        # After cooldown
        self.assertFalse(self.guard.check(base_ns + 150_000_000))


class TestDataStalenessGuard(unittest.TestCase):
    """Test data staleness guard functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.guard = DataStalenessGuard(threshold_us=30)
        
    def test_fresh_data(self):
        """Test guard passes with fresh data."""
        current_ns = time.time_ns()
        self.guard.update(current_ns)
        
        # Check immediately
        should_pull, spread_mult = self.guard.check(current_ns + 1000)  # 1μs later
        self.assertFalse(should_pull)
        self.assertEqual(spread_mult, 1.0)
        self.assertFalse(self.guard.is_stale)
        
    def test_warning_level(self):
        """Test warning level doubles spread."""
        current_ns = time.time_ns()
        self.guard.update(current_ns)
        
        # Check at warning level (5-30μs)
        should_pull, spread_mult = self.guard.check(current_ns + 10_000)  # 10μs later
        self.assertFalse(should_pull)
        self.assertEqual(spread_mult, 2.0)
        
    def test_critical_staleness(self):
        """Test critical staleness triggers quote pull."""
        current_ns = time.time_ns()
        self.guard.update(current_ns)
        
        # Check beyond threshold
        should_pull, spread_mult = self.guard.check(current_ns + 40_000)  # 40μs later
        self.assertTrue(should_pull)
        self.assertEqual(spread_mult, 1.0)
        self.assertTrue(self.guard.is_stale)


class TestQueueRankGuard(unittest.TestCase):
    """Test queue rank guard functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.guard = QueueRankGuard(threshold=0.35)
        
    def test_good_rank(self):
        """Test guard passes with good queue position."""
        rank = self.guard.estimate_rank(our_size=10.0, level_size=100.0)
        self.assertEqual(rank, 0.1)
        self.assertFalse(self.guard.should_cancel(rank))
        
    def test_bad_rank(self):
        """Test guard triggers with bad queue position."""
        rank = self.guard.estimate_rank(our_size=50.0, level_size=100.0)
        self.assertEqual(rank, 0.5)
        self.assertTrue(self.guard.should_cancel(rank))
        
    def test_zero_level_size(self):
        """Test handling of zero level size."""
        rank = self.guard.estimate_rank(our_size=10.0, level_size=0.0)
        self.assertEqual(rank, 0.0)
        self.assertFalse(self.guard.should_cancel(rank))


if __name__ == "__main__":
    unittest.main()