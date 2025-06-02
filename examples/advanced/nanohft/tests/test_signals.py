"""Unit tests for NanoHFT signal calculators."""

import unittest
from dataclasses import dataclass

# Add parent directory to path
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from core.signals import VAMPCalculator, EdgeCalculator, ATRCalculator


@dataclass
class MockQuote:
    """Mock quote for testing."""
    bid_price: float
    ask_price: float
    bid_size: float
    ask_size: float


class TestVAMPCalculator(unittest.TestCase):
    """Test VAMP calculator functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.calc = VAMPCalculator(epsilon=0.0001)
        
    def test_initial_state(self):
        """Test calculator starts in correct state."""
        self.assertIsNone(self.calc.value)
        self.assertFalse(self.calc.ready)
        
    def test_vamp_calculation_balanced(self):
        """Test VAMP with balanced order flow."""
        quote = MockQuote(
            bid_price=100.0,
            ask_price=100.1,
            bid_size=10.0,
            ask_size=10.0
        )
        
        self.calc.update_from_quote(quote)
        
        # VAMP should equal mid when sizes are equal
        expected = (100.1 * 10.0 + 100.0 * 10.0) / (20.0 + 0.0001)
        self.assertAlmostEqual(self.calc.value, expected, places=4)
        self.assertTrue(self.calc.ready)
        
    def test_vamp_calculation_imbalanced(self):
        """Test VAMP with imbalanced order flow."""
        quote = MockQuote(
            bid_price=100.0,
            ask_price=100.1,
            bid_size=20.0,  # More bid size
            ask_size=10.0
        )
        
        self.calc.update_from_quote(quote)
        
        # VAMP should be closer to bid due to larger bid size
        expected = (100.1 * 20.0 + 100.0 * 10.0) / (30.0 + 0.0001)
        self.assertAlmostEqual(self.calc.value, expected, places=4)
        self.assertTrue(self.calc.ready)
        
    def test_zero_size_protection(self):
        """Test epsilon prevents division by zero."""
        quote = MockQuote(
            bid_price=100.0,
            ask_price=100.1,
            bid_size=0.0,
            ask_size=0.0
        )
        
        # Should not raise exception
        self.calc.update_from_quote(quote)
        self.assertTrue(self.calc.ready)


class TestEdgeCalculator(unittest.TestCase):
    """Test edge calculator functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.calc = EdgeCalculator()
        
    def test_positive_edge(self):
        """Test positive edge calculation."""
        vamp = 100.05
        mid = 100.00
        
        self.calc.update(vamp, mid)
        
        # Edge = 10000 * (100.05 - 100.00) / 100.00 = 5 bp
        self.assertAlmostEqual(self.calc.value, 5.0, places=2)
        self.assertTrue(self.calc.ready)
        
    def test_negative_edge(self):
        """Test negative edge calculation."""
        vamp = 99.95
        mid = 100.00
        
        self.calc.update(vamp, mid)
        
        # Edge = 10000 * (99.95 - 100.00) / 100.00 = -5 bp
        self.assertAlmostEqual(self.calc.value, -5.0, places=2)
        self.assertTrue(self.calc.ready)
        
    def test_zero_mid_protection(self):
        """Test protection against zero mid price."""
        vamp = 100.0
        mid = 0.0
        
        self.calc.update(vamp, mid)
        self.assertFalse(self.calc.ready)


class TestATRCalculator(unittest.TestCase):
    """Test ATR calculator functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.calc = ATRCalculator(period=5)
        
    def test_initial_state(self):
        """Test calculator starts empty."""
        self.assertIsNone(self.calc.value)
        self.assertFalse(self.calc.ready)
        
    def test_atr_accumulation(self):
        """Test ATR builds up over time."""
        # Add quotes with increasing volatility
        for i in range(10):
            spread = 0.01 + i * 0.001
            quote = MockQuote(
                bid_price=100.0 - spread/2,
                ask_price=100.0 + spread/2,
                bid_size=10.0,
                ask_size=10.0
            )
            self.calc.update(quote)
            
        # After 10 quotes, should be ready
        self.assertTrue(self.calc.ready)
        self.assertIsNotNone(self.calc.value)
        self.assertGreater(self.calc.value, 0)
        
    def test_atr_basis_points(self):
        """Test ATR conversion to basis points."""
        # Add stable quotes
        for i in range(10):
            quote = MockQuote(
                bid_price=99.95,
                ask_price=100.05,
                bid_size=10.0,
                ask_size=10.0
            )
            self.calc.update(quote)
            
        # Check basis points calculation
        atr_bp = self.calc.value_bp
        self.assertIsNotNone(atr_bp)
        self.assertGreater(atr_bp, 0)


if __name__ == "__main__":
    unittest.main()