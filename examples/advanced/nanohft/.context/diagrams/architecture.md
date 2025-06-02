# NanoHFT Architecture Diagram

## System Architecture

```mermaid
graph TB
    subgraph "Market Data"
        QT[Quote Tick]
        OB[Order Book]
    end
    
    subgraph "Signal Layer"
        VAMP[VAMP Calculator]
        EDGE[Edge Calculator]
        ATR[ATR Calculator]
    end
    
    subgraph "Risk Guards"
        ATR_G[ATR Guard]
        CC_G[Cancel Cluster Guard]
        DS_G[Data Staleness Guard]
        QR_G[Queue Rank Guard]
    end
    
    subgraph "Strategy Orchestrator"
        STRAT[NanoHFTStrategy]
        EXEC[Execution Logic]
    end
    
    subgraph "Configuration"
        JSON[strategy_params_base.json]
    end
    
    subgraph "Output"
        ORDERS[Orders]
        LOGS[Logs/Metrics]
    end
    
    QT --> VAMP
    QT --> ATR
    OB --> VAMP
    
    VAMP --> EDGE
    
    VAMP --> STRAT
    EDGE --> STRAT
    ATR --> STRAT
    
    JSON --> STRAT
    
    STRAT --> ATR_G
    STRAT --> CC_G
    STRAT --> DS_G
    STRAT --> QR_G
    
    ATR_G --> EXEC
    CC_G --> EXEC
    DS_G --> EXEC
    QR_G --> EXEC
    
    EXEC --> ORDERS
    EXEC --> LOGS
```

## Data Flow Sequence

```mermaid
sequenceDiagram
    participant Market
    participant Signals
    participant Guards
    participant Strategy
    participant Execution
    
    Market->>Signals: Quote Tick
    Signals->>Signals: Calculate VAMP
    Signals->>Signals: Calculate Edge
    Signals->>Strategy: Signal Values
    
    Strategy->>Guards: Check ATR Gate
    Guards-->>Strategy: Pass/Fail
    
    Strategy->>Guards: Check Staleness
    Guards-->>Strategy: Pass/Fail
    
    Strategy->>Guards: Check Cancel Cluster
    Guards-->>Strategy: Pass/Fail
    
    alt All Guards Pass
        Strategy->>Execution: Submit Order
        Execution->>Market: Order
    else Any Guard Fails
        Strategy->>Strategy: Skip Trade
    end
```

## Component Responsibilities

### Signal Calculators
- **Input**: Market data (quotes, order book)
- **Processing**: Mathematical calculations
- **Output**: Signal values (VAMP, edge, volatility)

### Risk Guards
- **Input**: Signal values, market conditions
- **Processing**: Risk rule evaluation
- **Output**: Binary decision (allow/block)

### Strategy Orchestrator
- **Input**: Signals, configuration
- **Processing**: Coordinate components, timing
- **Output**: Trading decisions

## Performance Optimization Points

The modular architecture identifies clear optimization targets:

1. **Hot Path** (highest frequency):
   - VAMP calculation
   - Edge calculation
   - Basic guard checks

2. **Warm Path** (medium frequency):
   - ATR updates
   - Queue rank estimation

3. **Cold Path** (low frequency):
   - Configuration loading
   - Logging/metrics